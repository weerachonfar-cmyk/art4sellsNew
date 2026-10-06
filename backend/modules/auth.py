"""auth.py - สมัครสมาชิก / เข้าสู่ระบบ / ออกจากระบบ / ตรวจว่าใครกำลังเรียก API

Session: login สำเร็จ -> server สร้าง token สุ่ม (secrets) แล้ว api.py ส่งให้เบราว์เซอร์เป็น HttpOnly cookie
(ไม่ส่ง token กลับใน JSON และ frontend ไม่เก็บ token ใน localStorage)
ใน collection "sessions" เก็บเฉพาะ hash ของ token + user_id + created_at + expires_at (หมดอายุ 12 ชั่วโมง)
ฟังก์ชันในไฟล์นี้ยังคืน token ให้ชั้น api.py เท่านั้น (เพื่อตั้ง cookie) - ไม่ถูกส่งต่อให้ client เป็น JSON
"""
from backend import config
from backend.modules import logger, rate_limit, security, storage, user, validation
from backend.modules.errors import AppError, validation_error
from backend.modules.utils import is_expired, minutes_from_now_iso, now_iso


def _create_session(user_id):
    """สร้าง session ใหม่ คืน tuple (token จริง, เวลาหมดอายุ)"""
    token = security.new_session_token()
    expires_at = minutes_from_now_iso(config.SESSION_TTL_HOURS * 60)
    storage.create_record("sessions", {
        "token_hash": security.hash_token(token),
        "user_id": user_id,
        "created_at": now_iso(),
        "expires_at": expires_at,
    }, "s")
    return token, expires_at


def purge_expired_sessions():
    """ลบ session ที่หมดอายุแล้วออกจากไฟล์ คืนจำนวนที่ลบ"""
    removed = 0
    for session in storage.get_all("sessions"):
        if is_expired(session.get("expires_at")):
            storage.delete_record("sessions", session["id"])
            removed += 1
    return removed


def register_user(data):
    """สมัครสมาชิก: ตรวจข้อมูล (รวมนโยบายรหัสผ่าน + confirm_password), เช็คอีเมลซ้ำ, hash รหัสผ่าน, กำหนด role (USER/ARTIST เท่านั้น) แล้ว login ให้เลย"""
    new_user = user.create_user(data, config.SELF_REGISTER_ROLES, actor=None, require_confirm=True)
    token, expires_at = _create_session(new_user["id"])
    return {"user": new_user, "token": token, "expires_at": expires_at}


def login(data, client_ip=None):
    """เข้าสู่ระบบ คืน {"user", "token", "expires_at"}  (api.py เอา token ไปตั้ง cookie แล้วตัดออกจาก JSON)

    ลำดับ: ตรวจรูปแบบข้อมูล -> ตรวจ rate limit (IP + อีเมล) -> ตรวจรหัสผ่านจริงด้วย hash เดียวกับ user ทั่วไป -> สร้าง session
    ทุกบัญชี (รวมบัญชี demo) ต้องผ่านการ verify รหัสผ่านจริง  ไม่มี bypass ด้วยอีเมลหรือรหัสผ่านใดเป็นพิเศษ
    ไม่บอกว่า "อีเมลไม่มี" หรือ "รหัสผ่านผิด" - ตอบข้อความเดียวกัน เพื่อไม่เผยว่าอีเมลไหนมีในระบบ
    """
    clean, errors = validation.validate_login(data)
    if errors:
        raise validation_error(errors)
    ip = client_ip or "unknown"
    rate_limit.check_login_allowed(ip, clean["email"])         # ถูกล็อกอยู่ -> 429 โดยยังไม่ตรวจรหัสผ่านเลย

    record = storage.find_one("users", "email", clean["email"])
    stored_hash = record["password_hash"] if record else security.get_dummy_hash()
    password_ok = security.verify_password(clean["password"], stored_hash)

    if record is None or not password_ok:
        logger.create_audit_log(record["id"] if record else None, "USER_LOGIN_FAILED", "user",
                                record["id"] if record else None, {})
        rate_limit.record_failed_login(ip, clean["email"], record["id"] if record else None)
        raise AppError("INVALID_CREDENTIALS", "อีเมลหรือรหัสผ่านไม่ถูกต้อง", 401)
    if record["status"] != "ACTIVE":
        raise AppError("ACCOUNT_BANNED", "บัญชีนี้ถูกระงับการใช้งาน", 403)

    rate_limit.clear_failures_for_pair(ip, clean["email"])
    purge_expired_sessions()
    token, expires_at = _create_session(record["id"])
    logger.create_audit_log(record["id"], "USER_LOGIN", "user", record["id"], {})
    return {"user": user.public_user(record), "token": token, "expires_at": expires_at}


def logout(token, actor):
    """ออกจากระบบ: ลบ session ของ token นี้ (ใช้ซ้ำไม่ได้อีก)"""
    if actor is None or not token:
        raise AppError("UNAUTHORIZED", "กรุณาเข้าสู่ระบบ", 401)
    session = storage.find_one("sessions", "token_hash", security.hash_token(token))
    if session is not None:
        storage.delete_record("sessions", session["id"])
    logger.create_audit_log(actor["id"], "USER_LOGOUT", "user", actor["id"], {})
    return {"logged_out": True}


def authenticate(token):
    """หาว่า token นี้เป็นของใคร
    คืนค่า: dict ของ user (ไม่มี password_hash) หรือ None ถ้า token ไม่ถูกต้อง/หมดอายุ/บัญชีถูกระงับ
    """
    if not token:
        return None
    session = storage.find_one("sessions", "token_hash", security.hash_token(token))
    if session is None:
        return None
    if is_expired(session["expires_at"]):
        storage.delete_record("sessions", session["id"])
        return None
    record = storage.get_record("users", session["user_id"])
    if record is None or record.get("status") != "ACTIVE":
        return None
    return user.public_user(record)
