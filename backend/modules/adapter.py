"""adapter.py - ตัวแปลง HTTP ที่ใช้ร่วมกันระหว่าง server.py (Local) และ api/index.py (Vercel)

    Transport (http.server / Vercel Function)  ->  adapter.handle_api()  ->  api.dispatch()  ->  Business Logic

หน้าที่: ตรวจขนาด body -> แยก query -> เตรียมระบบเก็บข้อมูล (seed ครั้งแรกบน Redis) -> เรียก dispatch -> แปลงผลเป็นไบต์ + header
ไม่มี business logic ที่นี่ - ทั้งสอง transport จึงทำงานเหมือนกันทุกประการ
"""
import json
import re
import threading
from urllib.parse import parse_qsl, urlsplit

from backend import config, seed
from backend.modules import api, artwork_files, http_headers, logger, session_cookie, storage
from backend.modules.errors import StorageError

_ready_lock = threading.Lock()
_ready_for = None                                      # provider ที่เตรียมข้อมูลเสร็จแล้ว (กันตรวจ/seed ซ้ำทุก request ใน instance เดียว)
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def ensure_ready():
    """เตรียมระบบเก็บข้อมูลก่อนใช้งานครั้งแรกของ instance นี้  คืน None (ผิดพลาดจะ raise StorageError ให้ dispatch แปลงเป็น 503)
    - Redis : seed ข้อมูลตัวอย่าง "ครั้งแรกที่ฐานข้อมูลว่าง" เท่านั้น (ดู storage.ensure_initialized) - ไม่ seed ทุก request/ทุก cold start
    - JSON  : server.py เตรียมตอนเริ่มโปรแกรมแล้ว ไม่ต้องทำที่นี่
    - JSON ในโหมด DEMO บน Vercel (config.DEMO_EPHEMERAL): ไม่มี server.py ให้เตรียม จึง seed ที่นี่ครั้งแรกของ instance (ข้อมูลอยู่ใน /tmp ชั่วคราว)
    """
    global _ready_for
    provider = storage.get_provider()
    if _ready_for is provider or (provider.name != "redis" and not (provider.name == "json" and config.DEMO_EPHEMERAL)):
        return
    with _ready_lock:
        if _ready_for is provider:
            return
        if seed.seed_if_empty():
            logger.log_info("seeded demo data into empty " + provider.name + " storage (first run)")
        _ready_for = provider                          # ตั้งหลังสำเร็จเท่านั้น: ถ้า Redis ล่ม request หน้าจะลองใหม่


def reset_ready():
    """ให้ตรวจ/เตรียมใหม่ในคำขอถัดไป (ใช้ในเทสต์)"""
    global _ready_for
    _ready_for = None


def cors_headers(request_headers):
    """CORS: ตอบเฉพาะ Origin ที่อยู่ใน A4S_CORS_ORIGINS (ไม่มี = ไม่เปิดข้าม origin เลย, ไม่เคยใช้ Access-Control-Allow-Origin: *)"""
    origin = session_cookie.header_value(request_headers or {}, "Origin")
    if origin and origin in config.ALLOWED_ORIGINS:
        return [("Access-Control-Allow-Origin", origin),
                ("Access-Control-Allow-Headers", "Content-Type, Authorization"),
                ("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS"),
                ("Access-Control-Allow-Credentials", "true"),
                ("Vary", "Origin")]
    return []


def _content_disposition(filename):
    """ไม่มีชื่อไฟล์ = แสดงในหน้า (preview) / มีชื่อไฟล์ = ให้ดาวน์โหลด (ชื่อผ่านตัวกรองเหลือเฉพาะอักษรปลอดภัย)"""
    if not filename:
        return "inline"
    return 'attachment; filename="' + _SAFE_FILENAME.sub("_", filename)[:80] + '"'


def encode(result, request_headers):
    """แปลง api.Response เป็น (status, body bytes, header list) พร้อม header ความปลอดภัย / cookie / CORS"""
    https = session_cookie.is_https(request_headers or {})
    headers = list(http_headers.security_headers(https).items())
    payload = result.payload
    if isinstance(payload, artwork_files.FileResponse):
        body = payload.content
        headers.append(("Content-Type", payload.content_type))
        headers.append(("Cache-Control", "private, no-store" if payload.private else "public, max-age=60"))
        headers.append(("Content-Disposition", _content_disposition(payload.filename)))
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers.append(("Content-Type", "application/json; charset=utf-8"))
        headers.append(("Cache-Control", "no-store"))
    headers.extend(cors_headers(request_headers))
    headers.extend(result.headers)                     # Set-Cookie ฯลฯ จาก handler
    return result.status, body, headers


def _error(status, code, message, request_headers):
    return encode(api.Response(status, api.error_payload(code, message), []), request_headers)


def handle_api(method, raw_path, request_headers, raw_body, peer_ip=None):
    """รับ request ของ /api/... หนึ่งครั้ง คืน (status, body bytes, header list)  ไม่ raise ออกไปข้างนอก"""
    parts = urlsplit(raw_path)
    query = dict(parse_qsl(parts.query, keep_blank_values=False))
    if len(raw_body) > api.body_limit_for(method, parts.path):
        return _error(413, "PAYLOAD_TOO_LARGE", "ข้อมูลที่ส่งมามีขนาดใหญ่เกินไป", request_headers)
    try:
        ensure_ready()
    except StorageError as err:                        # Redis ล่ม/ไม่ได้ตั้งค่า: ตอบ 503 ที่ปลอดภัย (เก็บรายละเอียดไว้ใน log) - /api/health ยังตอบสถานะได้
        if parts.path.rstrip("/") != "/api/health":
            logger.log_exception("storage not ready: " + err.code + ": " + err.detail, err)
            return encode(api.Response(err.status, err.to_dict(), []), request_headers)
    result = api.dispatch(method, parts.path, query, request_headers, raw_body, peer_ip)
    return encode(result, request_headers)
