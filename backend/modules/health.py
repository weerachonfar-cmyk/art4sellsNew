"""health.py - สถานะระบบสำหรับ GET /api/health

บอกเฉพาะข้อมูลที่ปลอดภัย: ชื่อระบบ โหมด provider ของ storage ว่าพร้อมหรือไม่ โหมดอีเมล เวอร์ชัน
ห้ามมี: token, password, session, secret, URL ของ Redis, path ในเครื่อง, ข้อความ error ดิบ
deployment_ready = พร้อมใช้งานตามสถาปัตยกรรมที่ตั้งใจไว้หรือยัง (บน Vercel ต้องใช้ Redis ที่ต่อได้ / ในเครื่องต้องเขียน JSON ได้)
"""
from backend import config
from backend.modules import storage
from backend.modules.errors import StorageError

SAFE_ERRORS = {                                        # รหัสที่อนุญาตให้แสดง (allowlist) - ที่เหลือแสดงเป็น STORAGE_ERROR
    "REDIS_NOT_CONFIGURED", "REDIS_URL_INVALID", "REDIS_UNREACHABLE", "REDIS_UNEXPECTED_RESPONSE",
    "JSON_STORAGE_NOT_ALLOWED_ON_VERCEL", "STORAGE_PROVIDER_UNSUPPORTED", "DATA_DIR_NOT_WRITABLE",
}


def build_health():
    """คืน tuple (status_code, dict)  200 = พร้อม / 503 = storage ใช้ไม่ได้"""
    try:
        state = storage.health()
    except StorageError:
        state = {"provider": config.STORAGE_PROVIDER, "available": False, "error": "STORAGE_ERROR"}
    available = state["available"] is True
    error = state["error"]
    if error is not None and error not in SAFE_ERRORS:
        error = "STORAGE_ERROR"
    email_mode = config.EMAIL_MODE if config.EMAIL_MODE in config.EMAIL_MODES else "invalid"
    ready = available and (state["provider"] == "redis" if config.RUNNING_ON_VERCEL else True) and email_mode != "invalid"
    payload = {
        "ok": available,
        "application": config.APP_NAME,
        "mode": config.MODE,
        "storage": state["provider"],
        "storage_available": available,
        "deployment_ready": ready,
        "email_mode": email_mode,
        "version": config.APP_VERSION,
    }
    if config.DEMO_EPHEMERAL:                           # โหมด DEMO: ใช้งานได้ แต่ข้อมูลชั่วคราว (ยังไม่ถือว่า deployment_ready จนกว่าจะต่อ Redis)
        payload["demo_mode"] = True
        payload["persistent"] = False
    if error:
        payload["storage_error"] = error
    return (200 if available else 503), payload
