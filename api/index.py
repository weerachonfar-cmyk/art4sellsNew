"""api/index.py - Vercel Python Function (API Adapter เท่านั้น ไม่มี business logic)

    Vercel Request -> handler (ไฟล์นี้) -> backend/modules/adapter.py -> api.dispatch() -> Business Logic เดิมใน backend/modules/ -> Response

- vercel.json rewrite ทุก /api/* มาที่ฟังก์ชันนี้ (ฟังก์ชันเห็น path เดิม เช่น /api/artworks)
- ไม่ import backend/server.py (ตัวนั้นสำหรับ Local Development เท่านั้น)
- ที่เก็บข้อมูล: A4S_STORAGE=redis (Upstash)  ที่เก็บไฟล์: Vercel Blob  - ไม่เขียน filesystem ของ Function เป็นที่เก็บถาวร
- รูปแบบ handler(BaseHTTPRequestHandler) เป็นรูปแบบที่เอกสาร Vercel Python Runtime รองรับ
  ยังไม่ได้ทดสอบ deploy บน Vercel จริง - ดู VERCEL_DEPLOYMENT.md
"""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ให้ import "backend" ได้ตอนอยู่ใน Function

from backend import config                                  # noqa: E402
from backend.modules import adapter, api                    # noqa: E402


class handler(BaseHTTPRequestHandler):
    server_version = "Art4Sells"
    sys_version = ""

    def _run(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > api.body_limit_for(self.command, self.path.split("?", 1)[0]):
            status, body, headers = adapter._error(413, "PAYLOAD_TOO_LARGE", "ข้อมูลที่ส่งมามีขนาดใหญ่เกินไป",
                                                   dict(self.headers))
        else:
            raw_body = self.rfile.read(length) if length else b""
            status, body, headers = adapter.handle_api(self.command, self.path, dict(self.headers), raw_body,
                                                       self.client_address[0])
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        for name, value in adapter.cors_headers(dict(self.headers)):
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _run

    def log_message(self, format, *args):                    # ไม่พิมพ์ header/ข้อมูลผู้ใช้ลง log ของ Function
        pass
