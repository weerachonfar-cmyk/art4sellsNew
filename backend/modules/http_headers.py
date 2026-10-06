"""http_headers.py - Security Headers ที่ใช้ร่วมกันทั้ง server.py (Local) และ api/index.py (Vercel)

ตั้งให้พอดี ไม่เข้มจนเว็บพัง:  script ต้องมาจากเว็บเราเอง (ไม่มี inline script / eval), style อนุญาต inline + Google Fonts,
รูปจากเว็บเราเองและ data: เท่านั้น (รูปงานศิลปะส่งผ่าน API ของเรา ไม่ลิงก์ตรงไปที่เก็บไฟล์ภายนอก)
"""
from backend import config


def build_csp():
    """Content-Security-Policy: ให้เบราว์เซอร์รันเฉพาะ script ของเว็บเราเอง (ชั้นป้องกัน XSS อีกชั้น เผื่อมีช่องโหว่หลุด)"""
    connect = " ".join(("'self'",) + tuple(config.ALLOWED_ORIGINS))
    return ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src " + connect + "; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": build_csp(),
}
HSTS = "max-age=31536000"                              # ส่งเฉพาะเมื่อคำขอมาทาง HTTPS (ไม่ใส่ includeSubDomains/preload เพราะเป็น prototype)


def security_headers(https=False):
    """dict ของ security header ที่ต้องแนบกับทุก response  (HSTS เฉพาะ HTTPS)"""
    headers = dict(BASE_HEADERS)
    if https:
        headers["Strict-Transport-Security"] = HSTS
    return headers
