"""session_cookie.py - Cookie ของ session (HttpOnly) และตัวช่วยอ่าน header ที่เกี่ยวกับ HTTPS / IP

Cookie ที่ตั้ง:  a4s_session=<token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=<วินาที>; (Secure เมื่อเป็น HTTPS)
    HttpOnly  : JavaScript อ่านไม่ได้ -> ถ้ามีช่องโหว่ XSS ก็ขโมย token ไปไม่ได้ง่าย ๆ
    SameSite  : Lax = ไม่ส่ง cookie ไปกับคำขอ POST ข้ามเว็บ (ชั้นป้องกัน CSRF เสริม ควบคู่กับการตรวจ Origin)
    Secure    : ส่งเฉพาะทาง HTTPS (บน Vercel เป็น HTTPS เสมอ / ในเครื่อง http://127.0.0.1 ไม่ตั้ง เพราะเบราว์เซอร์จะไม่เก็บ)
"""
from http.cookies import CookieError, SimpleCookie

from backend import config


def header_value(headers, name):
    """อ่านค่า header แบบไม่สนตัวพิมพ์เล็ก/ใหญ่ (ไม่มี -> "")"""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value if isinstance(value, str) else ""
    return ""


def is_https(headers):
    """คำขอนี้มาทาง HTTPS หรือไม่ (เชื่อ X-Forwarded-Proto เฉพาะเมื่ออยู่หลัง proxy ที่เชื่อถือได้)"""
    mode = config.COOKIE_SECURE_MODE
    if mode == "always":
        return True
    if mode == "never":
        return False
    if config.TRUST_PROXY:
        return header_value(headers, "X-Forwarded-Proto").split(",")[0].strip().lower() == "https"
    return False


def client_ip(headers, peer_ip):
    """IP ของผู้เรียก: ถ้าอยู่หลัง proxy ที่เชื่อถือได้ใช้ตัวแรกของ X-Forwarded-For  ไม่งั้นใช้ IP ที่ต่อเข้ามาจริง"""
    if config.TRUST_PROXY:
        forwarded = header_value(headers, "X-Forwarded-For").split(",")[0].strip()
        if forwarded and len(forwarded) <= 64:
            return forwarded
    return (peer_ip or "unknown")[:64]


def build_session_cookie(token, max_age_seconds, secure):
    parts = [config.SESSION_COOKIE_NAME + "=" + token, "HttpOnly", "SameSite=Lax", "Path=/",
             "Max-Age=" + str(int(max_age_seconds))]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def build_clear_cookie(secure):
    """สั่งเบราว์เซอร์ลบ cookie (Max-Age=0)  ใช้ attribute ชุดเดียวกับตอนตั้ง เพื่อให้ลบถูกตัว"""
    return build_session_cookie("", 0, secure)


def read_session_token(headers):
    """ดึง token จาก Cookie header (ไม่มี / รูปแบบผิด -> None)"""
    raw = header_value(headers, "Cookie")
    if not raw or len(raw) > 4096:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(config.SESSION_COOKIE_NAME)
    value = morsel.value if morsel else ""
    return value if 20 <= len(value) <= 200 else None
