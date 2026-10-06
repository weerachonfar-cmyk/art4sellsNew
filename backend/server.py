"""server.py - เว็บเซิร์ฟเวอร์ (Python Standard Library: http.server)

หน้าที่ของไฟล์นี้มีแค่ "ส่งต่อ HTTP" - ไม่มี business logic
    /api/...        -> modules/api.py  (handle_request)
    /public, /src   -> ส่งไฟล์ static ให้ browser (frontend เดิม)

รัน:   python backend/server.py        แล้วเปิด http://127.0.0.1:8000
"""
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

if __package__ in (None, ""):                          # อนุญาตให้รัน "python backend/server.py" ตรง ๆ
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, seed
from backend.modules import adapter, api, http_headers, logger, session_cookie, storage

# Security Headers อยู่ที่ http_headers.py (ใช้ร่วมกับ api/index.py ของ Vercel)  คงชื่อเดิมไว้ให้โค้ด/เทสต์ที่อ้างถึง
build_csp = http_headers.build_csp
SECURITY_HEADERS = http_headers.BASE_HEADERS
HTTP_ERROR_MESSAGES = {                                # ข้อความ error กลาง ๆ (ไม่แสดงรายละเอียดภายใน/ข้อความดิบของ Python)
    400: "คำขอไม่ถูกต้อง", 404: "ไม่พบหน้าที่ต้องการ", 405: "ไม่รองรับวิธีเรียกนี้",
    408: "หมดเวลารอคำขอ", 414: "ที่อยู่ที่ส่งมายาวเกินไป", 431: "ส่วนหัวของคำขอใหญ่เกินไป", 501: "ไม่รองรับวิธีเรียกนี้",
}


def resolve_static_path(url_path):
    """แปลง URL เป็น path ของไฟล์ที่ "อนุญาตให้เปิด" เท่านั้น (กัน path traversal เช่น /public/../backend/data/users.json)
    คืนค่า Path ถ้าปลอดภัยและไฟล์มีจริง ไม่งั้นคืน None
    """
    if url_path in ("", "/"):
        url_path = "/public/index.html"
    pieces = [p for p in unquote(url_path).split("/") if p]
    if not pieces:
        return None
    if any(p in ("..", ".") or "\\" in p or "\x00" in p for p in pieces):
        return None
    if pieces[0] not in config.STATIC_ROOTS:
        pieces = ["public"] + pieces                   # เหมือนบน Vercel: ไฟล์ใน public/ อยู่ที่รากเว็บ (/style.css, /login.html) - หน้า HTML อ้างถึงแบบนี้
    root = config.STATIC_ROOTS[pieces[0]].resolve()
    candidate = root.joinpath(*pieces[1:]).resolve()
    try:
        candidate.relative_to(root)                    # ต้องอยู่ใต้โฟลเดอร์ที่อนุญาตจริง ๆ
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "Art4Sells"
    sys_version = ""                                   # ไม่เปิดเผยเวอร์ชัน Python

    # ---------- ตัวช่วยส่ง response ----------
    def _is_https(self):
        return session_cookie.is_https(dict(getattr(self, "headers", None) or {}))

    def _send(self, status, body_bytes, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        for name, value in http_headers.security_headers(self._is_https()).items():
            self.send_header(name, value)
        items = extra_headers.items() if isinstance(extra_headers, dict) else (extra_headers or [])
        for name, value in items:                      # รับทั้ง dict และ list ของ (ชื่อ, ค่า) - Set-Cookie ซ้ำได้
            self.send_header(name, value)
        self.end_headers()
        if getattr(self, "command", None) != "HEAD":
            self.wfile.write(body_bytes)

    def _cors_headers(self):
        headers = getattr(self, "headers", None)           # คำขอที่ผิดรูปแบบจะยังไม่มี headers
        return adapter.cors_headers(dict(headers) if headers else {})

    def _send_json(self, status, payload, extra_headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = [("Cache-Control", "no-store")] + list(self._cors_headers()) + list(extra_headers or [])
        self._send(status, data, "application/json; charset=utf-8", headers)

    # ---------- แต่ละ HTTP method ----------
    def _handle_api(self, parts):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > api.body_limit_for(self.command, parts.path):
            self._send_json(413, api.error_payload("PAYLOAD_TOO_LARGE", "ข้อมูลที่ส่งมามีขนาดใหญ่เกินไป"))
            return
        raw_body = self.rfile.read(length) if length else b""
        status, body, headers = adapter.handle_api(self.command, self.path, dict(self.headers), raw_body,
                                                   self.client_address[0])
        self.send_response(status)                         # adapter ใส่ security header / Content-Type / Content-Length ให้ครบแล้ว
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle_static(self, parts):
        path = resolve_static_path(parts.path)
        if path is None:
            self._send(404, "ไม่พบหน้าที่ต้องการ".encode("utf-8"), "text/plain; charset=utf-8")
            return
        try:
            content = path.read_bytes()
        except OSError as err:
            logger.log_exception("static read failed: " + str(path), err)
            self._send(500, "เกิดข้อผิดพลาดภายในระบบ".encode("utf-8"), "text/plain; charset=utf-8")
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self._send(200, content, content_type, {"Cache-Control": "no-cache"})

    def _dispatch(self):
        parts = urlsplit(self.path)
        if self.command == "OPTIONS":
            self._send(204, b"", "text/plain", list(self._cors_headers()))
        elif parts.path.startswith("/api/") or parts.path == "/api":
            self._handle_api(parts)
        elif self.command in ("GET", "HEAD"):
            self._handle_static(parts)
        else:
            self._send_json(405, api.error_payload("METHOD_NOT_ALLOWED", "ไม่รองรับวิธีเรียกนี้"))

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_HEAD = _dispatch

    def send_error(self, code, message=None, explain=None):
        """แทนหน้า error HTML ดั้งเดิมของ http.server (ที่โชว์ข้อความดิบ) ด้วย JSON ข้อความกลาง ๆ"""
        text = HTTP_ERROR_MESSAGES.get(code, "เกิดข้อผิดพลาด")
        self.close_connection = True
        self._send_json(code, api.error_payload("HTTP_ERROR", text))

    def log_message(self, format, *args):              # ใช้ dev logger แทนการพิมพ์ดิบ ๆ
        logger.log_info(self.address_string() + " " + (format % args))


def create_server(host=None, port=None):
    """สร้าง server (ยังไม่เริ่มรับ request) - แยกไว้เพื่อให้เทสต์เรียกได้"""
    return ThreadingHTTPServer((host or config.HOST, config.PORT if port is None else port), Handler)


def main():
    logger.setup_dev_logging()
    created = seed.seed_if_empty()
    if created:
        logger.log_info("สร้างข้อมูลตัวอย่างครั้งแรกที่ " + str(config.DATA_DIR))
    state = storage.health()
    logger.log_info("storage=" + str(state["provider"]) + " available=" + str(state["available"]))
    httpd = create_server()
    logger.log_info("Art 4 Sells พร้อมใช้งานที่ http://" + config.HOST + ":" + str(httpd.server_address[1])
                    + "  (กด Ctrl+C เพื่อหยุด)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.log_info("หยุด server แล้ว")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
