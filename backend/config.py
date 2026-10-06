"""config.py - ค่าตั้งต้นของระบบ Art 4 Sells

- ไม่มี secret / รหัสผ่านจริงอยู่ในไฟล์นี้
- ค่าที่ปรับได้ตอนรัน ใช้ environment variable เช่น
      A4S_PORT=9000 python backend/server.py
"""
import os
from pathlib import Path


def _env_int(name, default):
    """อ่านเลขจำนวนเต็มจาก environment variable
    พารามิเตอร์: name (ชื่อ env), default (ค่าที่ใช้ถ้าไม่มี/ผิดรูปแบบ)
    คืนค่า: int  (ตัวอย่างของ type conversion + try/except)
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name, default=False):
    """อ่านค่า true/false จาก environment variable (รับเฉพาะ true/1/yes เป็นจริง ที่เหลือเป็นเท็จ)
    พารามิเตอร์: name (ชื่อ env), default (ค่าเมื่อไม่ได้ตั้ง)  คืนค่า: bool
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":                 # ไม่ตั้ง หรือเว้นว่าง (เช่น คัดลอก .env.example มาแล้วไม่กรอก) = ใช้ค่าเริ่มต้น
        return default
    return raw.strip().lower() in ("true", "1", "yes")


APP_NAME = "Art 4 Sells"
APP_VERSION = "finale-prototype"
# Vercel ตั้งตัวแปร VERCEL=1 ให้เองตอนรันจริง  ใช้บอกว่ากำลังรันแบบ "vercel" หรือ "local"
RUNNING_ON_VERCEL = bool(os.environ.get("VERCEL"))
MODE = "vercel" if RUNNING_ON_VERCEL else "local"

# ---------- ที่อยู่ไฟล์ ----------
BASE_DIR = Path(__file__).resolve().parent          # .../backend
PROJECT_DIR = BASE_DIR.parent                       # .../art4sells

# Vercel Marketplace (Upstash) อาจตั้งชื่อ KV_REST_API_* ให้แทน - รองรับเป็นทางเลือกสำรอง
REDIS_REST_URL = (os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL") or "").strip()
REDIS_REST_TOKEN = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN") or "").strip()

# ---------- โหมด DEMO บน Vercel (deploy แล้วใช้ได้เลยโดยไม่ต้องตั้งค่าอะไร) ----------
# เปิดอัตโนมัติเมื่อ "ทั้งหมด" เป็นจริง:  รันบน Vercel + ไม่ได้ตั้ง A4S_STORAGE เอง + ยังไม่ได้ต่อ Redis (Upstash)
#   -> เก็บข้อมูลเป็น JSON ใน /tmp (ชั่วคราว: หายเมื่อ Function ถูกรีสตาร์ท/สลับ instance แล้ว seed ข้อมูลตัวอย่างใหม่)
# ปิดเองทันทีเมื่อต่อ Redis หรือกำหนด A4S_STORAGE ชัด ๆ  (ถ้ากำหนดเองแล้วตั้งค่าไม่ครบ = ยังตอบ 503 เหมือนเดิม ไม่ fallback แบบเงียบ ๆ)
_STORAGE_CHOICE = (os.environ.get("A4S_STORAGE") or "").strip().lower()
DEMO_EPHEMERAL = RUNNING_ON_VERCEL and not _STORAGE_CHOICE and not (REDIS_REST_URL and REDIS_REST_TOKEN)
DEMO_TMP_DIR = Path(os.environ.get("A4S_DEMO_TMP_DIR", "/tmp/art4sells"))

DATA_DIR = Path(os.environ.get("A4S_DATA_DIR") or (str(DEMO_TMP_DIR / "data") if DEMO_EPHEMERAL else str(BASE_DIR / "data")))
LOG_DIR = BASE_DIR / "logs"

# โฟลเดอร์ที่ server ยอมให้เปิดเป็นไฟล์ static (dict) - backend/ ไม่อยู่ในรายการนี้ ข้อมูลจึงไม่หลุด
STATIC_ROOTS = {
    "public": PROJECT_DIR / "public",
    "src": PROJECT_DIR / "src",
}

# ---------- Server ----------
HOST = os.environ.get("A4S_HOST", "127.0.0.1")      # 127.0.0.1 = เครื่องนี้เท่านั้น
PORT = _env_int("A4S_PORT", 8000)
MAX_BODY_BYTES = 1024 * 1024                         # request body ใหญ่สุด 1 MB
# ถ้า frontend อยู่คนละ origin ให้ใส่ เช่น A4S_CORS_ORIGINS=http://localhost:5500
ALLOWED_ORIGINS = tuple(
    o.strip() for o in os.environ.get("A4S_CORS_ORIGINS", "").split(",") if o.strip()
)

# ---------- Storage ----------
# "json"  = เก็บเป็นไฟล์ backend/data/*.json (Local Development / งานวิชา File Handling)
# "redis" = Upstash Redis ผ่าน REST (Vercel Prototype)  Business Logic ไม่รู้ว่าใช้ตัวไหน (ดู storage.py)
# บน Vercel: ไม่ตั้ง A4S_STORAGE -> ใช้ redis ถ้าต่อ Upstash แล้ว  ถ้ายังไม่ต่อ = โหมด DEMO (json ใน /tmp, ดู DEMO_EPHEMERAL ด้านบน)
STORAGE_PROVIDER = _STORAGE_CHOICE or ("redis" if RUNNING_ON_VERCEL and not DEMO_EPHEMERAL else "json")
STORAGE_PROVIDERS = ("json", "redis")
REDIS_KEY_PREFIX = os.environ.get("A4S_REDIS_PREFIX", "a4s:v1").strip() or "a4s:v1"   # เทสต์ใช้ prefix อื่น จึงไม่แตะข้อมูลจริง
REDIS_TIMEOUT_SECONDS = 8
REDIS_LOCK_SECONDS = 15                              # lock หมดอายุเองเผื่อ function ตายกลางทาง
REDIS_LOCK_WAIT_SECONDS = 10                         # รอ lock ได้นานสุด

# ไฟล์ภาพ: "local" = โฟลเดอร์ uploads/ (เฉพาะ Local)  "blob" = Vercel Blob   (ว่าง = เลือกให้ตามโหมด)
FILE_STORAGE_PROVIDER = os.environ.get("A4S_FILE_STORAGE", "").strip().lower()
BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
UPLOAD_DIR = (DEMO_TMP_DIR / "uploads") if DEMO_EPHEMERAL else (PROJECT_DIR / "uploads")   # โหมด DEMO: เก็บไฟล์ภาพใน /tmp (ชั่วคราว)

# ---------- Security ----------
SESSION_TTL_HOURS = 12
SESSION_COOKIE_NAME = "a4s_session"                  # HttpOnly cookie (JavaScript อ่านไม่ได้) - ไม่เก็บ token ใน localStorage
# Secure cookie: "auto" = ตั้งเมื่อคำขอมาทาง HTTPS (ดู X-Forwarded-Proto ตอนอยู่หลัง proxy)  "always"/"never" บังคับได้
COOKIE_SECURE_MODE = os.environ.get("A4S_COOKIE_SECURE", "auto").strip().lower()
# เชื่อ header X-Forwarded-For / X-Forwarded-Proto เฉพาะเมื่ออยู่หลัง proxy ที่เชื่อถือได้ (Vercel) - ไม่งั้นปลอมได้ง่าย
TRUST_PROXY = _env_bool("A4S_TRUST_PROXY", RUNNING_ON_VERCEL)
PASSWORD_ITERATIONS = _env_int("A4S_PBKDF2_ITERATIONS", 600_000)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# ---------- Login rate limit (ดู rate_limit.py) ----------
# ไม่ใช้ IP อย่างเดียวเป็นตัวตน: นับ "IP + อีเมล" (กันคนเดาบัญชีเดียว), "อีเมล" (กันเดาจากหลาย IP), "IP" (กันไล่เดาหลายบัญชี)
LOGIN_WINDOW_MINUTES = 10
LOGIN_MAX_FAILS_PER_PAIR = 5                         # IP + อีเมลเดียวกัน ผิดได้ 5 ครั้ง / 10 นาที
LOGIN_MAX_FAILS_PER_ACCOUNT = 15                     # อีเมลเดียวกัน (ทุก IP) - กันเดาแบบกระจาย แต่ไม่ล็อกเจ้าของบัญชีง่ายเกินไป
LOGIN_MAX_FAILS_PER_IP = 30                          # IP เดียวไล่เดาหลายอีเมล
LOGIN_COOLDOWN_MINUTES = 10                          # ถูกล็อกแล้วต้องรอจนกว่าความพยายามผิดเก่าสุดหลุดหน้าต่างเวลา

# ---------- Roles (tuple = ค่าคงที่ที่แก้ไม่ได้) ----------
ROLES = ("USER", "ARTIST", "ADMIN")
SELF_REGISTER_ROLES = ("USER", "ARTIST")             # สมัครเองเป็น ADMIN ไม่ได้
USER_STATUSES = ("ACTIVE", "BANNED")

# ---------- Artwork ----------
SALE_TYPES = ("LIMITED", "UNLIMITED")
PUBLIC_ARTWORK_STATUSES = ("APPROVED", "AVAILABLE", "SOLD")       # สถานะที่คนทั่วไปมองเห็น
PRICE_MAX = 1_000_000
MAX_TAGS = 10

# สถานะ -> สถานะถัดไปที่ "ไปได้"  (state machine ของ Artwork)
ARTWORK_TRANSITIONS = {
    "DRAFT": ("PENDING_APPROVAL",),
    "PENDING_APPROVAL": ("APPROVED", "REJECTED"),
    "REJECTED": ("PENDING_APPROVAL",),               # ศิลปินแก้แล้วส่งใหม่
    "APPROVED": ("AVAILABLE", "SOLD"),
    "AVAILABLE": ("SOLD",),
    "SOLD": (),
}
ARTWORK_STATUSES = tuple(ARTWORK_TRANSITIONS)
ARTIST_EDITABLE_STATUSES = ("DRAFT", "REJECTED")     # ศิลปินแก้งานได้เฉพาะสถานะนี้

# ---------- Order ----------
ORDER_TRANSITIONS = {
    "CREATED": ("PENDING_PAYMENT", "CANCELLED"),
    "PENDING_PAYMENT": ("PAYMENT_SUBMITTED", "PAYMENT_VERIFIED", "CANCELLED", "EXPIRED"),
    "PAYMENT_SUBMITTED": ("PAYMENT_VERIFIED", "CANCELLED", "EXPIRED"),
    "PAYMENT_VERIFIED": ("PAID",),
    "PAID": ("PROCESSING", "COMPLETED"),
    "PROCESSING": ("COMPLETED",),
    "COMPLETED": (),
    "CANCELLED": (),
    "EXPIRED": (),
    "REFUNDED": (),
}
ORDER_STATES = tuple(ORDER_TRANSITIONS)
ACTIVE_ORDER_STATES = ("CREATED", "PENDING_PAYMENT", "PAYMENT_SUBMITTED", "PAYMENT_VERIFIED", "PAID", "PROCESSING")  # ล็อกงาน LIMITED
PAID_ORDER_STATES = ("PAID", "PROCESSING", "COMPLETED")            # ถือว่า "จ่ายเงินแล้ว"
BUYER_ORDER_ACTIONS = ("CANCELLED", "COMPLETED")     # สถานะที่ผู้ซื้อเปลี่ยนเองได้
ORDER_TTL_MINUTES = 30
MAX_ORDER_QUANTITY = 99


# ---------- Payment ----------
PAYMENT_METHODS = ("COD", "QR_PAYMENT", "BANK_TRANSFER")
PAYMENT_STATUSES = ("UNPAID", "PENDING_VERIFICATION", "PAID", "REJECTED", "EXPIRED", "REFUNDED")
OVERPAYMENT_REFUND_POLICY = "NO_REFUND_UNLESS_SYSTEM_ERROR"

# ---------- Promotions / price history ----------
PROMOTION_TYPES = ("PERCENTAGE", "FIXED_AMOUNT")

# ---------- Commission ----------
COMMISSION_STATES = ("LISTING", "BRIEF", "PAYMENT", "PAYMENT_VERIFIED", "ACCEPTED", "REJECTED", "IN_PROGRESS", "DELIVERED", "COMPLETED", "CANCELLED", "REFUND_ELIGIBLE")
COMMISSION_TRANSITIONS = {
    "LISTING": ("BRIEF",),
    "BRIEF": ("PAYMENT", "CANCELLED"),
    "PAYMENT": ("PAYMENT_VERIFIED", "CANCELLED", "REFUND_ELIGIBLE"),
    "PAYMENT_VERIFIED": ("ACCEPTED", "REJECTED"),
    "ACCEPTED": ("IN_PROGRESS",),
    "REJECTED": ("REFUND_ELIGIBLE", "CANCELLED"),
    "IN_PROGRESS": ("DELIVERED", "REFUND_ELIGIBLE"),
    "DELIVERED": ("COMPLETED", "REFUND_ELIGIBLE"),
    "COMPLETED": (),
    "CANCELLED": (),
    "REFUND_ELIGIBLE": ("CANCELLED",),
}
MAX_COMMISSION_DAYS = 365

# ---------- Review ----------
REVIEW_STATUSES = ("PUBLISHED", "HIDDEN")

# ---------- Cart / Wishlist ----------
MAX_CART_LINES = 50                                  # จำนวนรายการสูงสุดในตะกร้า 1 คน
MAX_WISHLIST_ITEMS = 500
MAX_NOTIFICATIONS_LIST = 50

# ---------- Password management (Phase 3.5) ----------
PASSWORD_CHANGE_COOLDOWN_DAYS = 30                   # เปลี่ยนรหัสผ่านได้อีกครั้งหลังผ่านไป 30 วัน (ไม่นับการ "ลืมรหัสผ่าน")
OTP_LENGTH = 5
OTP_LIFETIME_MINUTES = 10
MAX_OTP_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60                     # ขอรหัสใหม่ได้ทุก 60 วินาที
OTP_MAX_REQUESTS_PER_HOUR = 5                        # ขอรหัสได้ไม่เกิน 5 ครั้ง/ชั่วโมง ต่ออีเมล
RESET_AUTH_LIFETIME_MINUTES = 15                     # หลังยืนยัน OTP ต้องตั้งรหัสใหม่ให้เสร็จใน 15 นาที

# ---------- Email (ยังไม่มีผู้ให้บริการจริง) ----------
# "development" = พิมพ์อีเมลลงหน้าจอ server เท่านั้น (DEV ONLY)  ห้ามใส่ SMTP password/API key ในไฟล์นี้
EMAIL_MODE = os.environ.get("A4S_EMAIL_MODE", "development").strip().lower()
EMAIL_MODES = ("development", "production")
# Developer OTP Mailbox (เฉพาะ ADMIN) เปิดได้ก็ต่อเมื่อ EMAIL_MODE=development และ A4S_DEV_TOOLS=true เท่านั้น (ค่าเริ่มต้น = ปิด)
DEV_TOOLS = _env_bool("A4S_DEV_TOOLS", False)
DEV_MAILBOX_MAX_ITEMS = 50


def dev_mailbox_enabled():
    """True เมื่อเปิด Developer Mailbox ได้ (อ่านค่าตอนเรียก เพื่อให้เทสต์สลับค่าได้)"""
    return EMAIL_MODE == "development" and DEV_TOOLS is True

# ---------- Admin data management ----------
CONFIRM_TOKEN_MINUTES = 5                            # ขั้นยืนยันที่ 2 ต้องทำภายใน 5 นาที
CLEAR_CONFIRM_TEXT = "CLEAR"
RESET_CONFIRM_TEXT = "RESET"
CLEAR_AUDIT_CONFIRM_TEXT = "CLEAR AUDIT LOGS"

# ---------- Input limits (ข้อมูลจาก client = untrusted) ----------
ID_MAX_LENGTH = 64
SEARCH_MAX_LENGTH = 100
DISPLAY_NAME_RANGE = (2, 50)
ALLOWED_UPLOAD_EXTENSIONS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
UPLOAD_BODY_BYTES = 8 * 1024 * 1024                  # ขนาด JSON (base64) ของ endpoint อัปโหลดเท่านั้น  (Vercel จำกัด request ~4.5 MB เอง)
FILE_ROLES = ("original", "preview", "delivery")     # ไฟล์ของงานศิลปะ 3 แบบ
DELIVERY_ORDER_STATES = ("PAYMENT_VERIFIED", "PAID", "COMPLETED")   # ดาวน์โหลดไฟล์จริงได้เมื่อยืนยันการชำระเงินแล้วเท่านั้น

# ---------- Search / Pagination ----------
PAGE_SIZE_DEFAULT = 12
PAGE_SIZE_RANGE = (1, 50)                            # tuple (ต่ำสุด, สูงสุด)
SEARCH_FIELDS = ("all", "title", "artist", "tag")
# ชื่อ sort -> (ชื่อ field, เรียงจากมากไปน้อยหรือไม่)
SORT_OPTIONS = {
    "newest": ("created_at", True),
    "oldest": ("created_at", False),
    "price_asc": ("price", False),
    "price_desc": ("price", True),
    "rating": ("rating", True),
}
