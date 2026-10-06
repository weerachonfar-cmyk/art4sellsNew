"""password.py - เปลี่ยนรหัสผ่าน (Change Password) และกู้รหัสผ่านด้วย OTP (Forgot Password)

ใช้ hash ตัวเดิมของระบบ (security.hash_password / verify_password)  ไม่แก้ไขรหัสผ่านใด ๆ (ไม่ strip / ไม่ลบอักขระ)

Change Password : ต้อง login + รหัสผ่านเดิมถูก + นโยบายรหัสผ่าน + ห่างจากการเปลี่ยนครั้งก่อน >= 30 วัน
Forgot Password : ไม่ติด cooldown  ขั้นตอนและสถานะ
    forgot/resend  -> OTP_PENDING   (OTP 5 หลัก เก็บเฉพาะ hash, อายุ 10 นาที, ผิดได้ 5 ครั้ง, ใช้ครั้งเดียว)
    verify         -> OTP_VERIFIED  แล้วออก reset authorization (token ใช้ครั้งเดียว อายุ 15 นาที) = RESET_AUTHORIZED
    reset          -> PASSWORD_RESET  (ต้องมี reset token เท่านั้น เรียกตรงข้าม OTP ไม่ได้)
ทุกคำตอบของขั้นตอน "ขอรหัส" เป็นข้อความกลางเหมือนกัน ไม่บอกว่ามีอีเมลนี้ในระบบหรือไม่
"""
import hashlib
from datetime import timedelta

from backend import config
from backend.modules import email_service, logger, security, storage, user, validation
from backend.modules.errors import AppError, unauthorized_error, validation_error
from backend.modules.utils import is_expired, minutes_from_now_iso, now_iso, now_utc, parse_iso

GENERIC_REQUEST_MESSAGE = "หากอีเมลนี้ลงทะเบียนไว้ ระบบจะส่งรหัสยืนยันให้"
INVALID_CODE_MESSAGE = "รหัสไม่ถูกต้อง หมดอายุ หรือถูกใช้ไปแล้ว กรุณาตรวจสอบหรือขอรหัสใหม่"
INVALID_RESET_MESSAGE = "สิทธิ์ในการตั้งรหัสผ่านไม่ถูกต้องหรือหมดอายุ กรุณาเริ่มขั้นตอนใหม่"
RATE_LIMIT_MESSAGE = "ขอรหัสบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่"


def _email_hash(email):
    """hash ของอีเมล (ใช้นับจำนวนครั้งที่ขอ โดยไม่เก็บอีเมลที่อาจไม่มีในระบบ)"""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def _other_sessions_removed(user_id, keep_token_hash=None):
    """ลบ session ของ user ยกเว้น session ที่ระบุ"""
    for session in storage.find_records("sessions", "user_id", user_id):
        if session["token_hash"] != keep_token_hash:
            storage.delete_record("sessions", session["id"])


def _format_date(moment):
    """วันที่แบบอ่านง่าย เช่น 30 October 2026 (UTC)"""
    return str(moment.day) + " " + moment.strftime("%B") + " " + str(moment.year)


# ---------------------------------------------------------------------------
# Change Password
# ---------------------------------------------------------------------------
def next_change_allowed_at(user_record):
    """คำนวณเวลาที่เปลี่ยนรหัสผ่านได้อีกครั้ง จาก password_changed_at จริง  คืน datetime หรือ None (เปลี่ยนได้เลย)"""
    changed_at = user_record.get("password_changed_at")
    if not changed_at:
        return None
    try:
        allowed_at = parse_iso(changed_at) + timedelta(days=config.PASSWORD_CHANGE_COOLDOWN_DAYS)
    except (TypeError, ValueError):
        return None
    return allowed_at if allowed_at > now_utc() else None


def change_password(data, actor, token):
    """POST /api/auth/change-password  body: {"current_password", "new_password", "confirm_password"}"""
    if actor is None:
        raise unauthorized_error()
    body = validation.pick_fields(data, ("current_password", "new_password", "confirm_password"))
    record = user.get_user_record(actor["id"])

    # 1) cooldown (ไม่ขึ้นกับความลับ จึงตรวจก่อน และกัน session ที่ถูกขโมยมาลองเดารหัสเดิม)
    allowed_at = next_change_allowed_at(record)
    if allowed_at is not None:
        logger.create_audit_log(actor["id"], "PASSWORD_CHANGE_REJECTED_COOLDOWN", "user", actor["id"],
                                {"available_at": allowed_at.isoformat(timespec="seconds")}, result="REJECTED")
        raise AppError("PASSWORD_CHANGE_COOLDOWN",
                       "สามารถเปลี่ยนรหัสผ่านได้อีกครั้ง: " + _format_date(allowed_at), 429,
                       details={"available_at": allowed_at.isoformat(timespec="seconds")})

    # 2) ชนิดข้อมูล + นโยบาย + ยืนยันรหัส
    errors = {}
    for field in ("current_password", "new_password", "confirm_password"):
        if not isinstance(body.get(field), str) or not body.get(field):
            errors[field] = "กรุณากรอกข้อมูล"
    if not errors:
        problem = validation.validate_password(body["new_password"])
        if problem:
            errors["new_password"] = problem
        elif body["new_password"] != body["confirm_password"]:
            errors["confirm_password"] = "รหัสผ่านใหม่ไม่ตรงกัน"
    if errors:
        raise validation_error(errors)

    # 3) รหัสผ่านเดิมต้องถูก และรหัสใหม่ต้องไม่เหมือนเดิม
    if not security.verify_password(body["current_password"], record["password_hash"]):
        logger.create_audit_log(actor["id"], "PASSWORD_CHANGE_FAILED", "user", actor["id"],
                                {"reason": "wrong_current_password"}, result="FAILURE")
        raise AppError("WRONG_CURRENT_PASSWORD", "รหัสผ่านปัจจุบันไม่ถูกต้อง", 403,
                       {"current_password": "รหัสผ่านปัจจุบันไม่ถูกต้อง"})
    if security.verify_password(body["new_password"], record["password_hash"]):
        raise validation_error({"new_password": "รหัสผ่านใหม่ต้องไม่เหมือนรหัสผ่านเดิม"})

    now = now_iso()
    storage.update_record("users", record["id"], {"password_hash": security.hash_password(body["new_password"]),
                                                  "password_changed_at": now, "updated_at": now})
    _other_sessions_removed(record["id"], keep_token_hash=security.hash_token(token) if token else None)
    logger.create_audit_log(actor["id"], "PASSWORD_CHANGE_SUCCESS", "user", actor["id"], {})
    return {"changed": True, "next_change_allowed_at": (parse_iso(now) + timedelta(
        days=config.PASSWORD_CHANGE_COOLDOWN_DAYS)).isoformat(timespec="seconds")}


# ---------------------------------------------------------------------------
# Forgot Password: ขอรหัส (ใช้ร่วมกับ resend)
# ---------------------------------------------------------------------------
def _check_request_rate(email_hash):
    """ตรวจจำนวนครั้งที่ขอรหัสต่ออีเมล (นับเหมือนกันทั้งอีเมลที่มีและไม่มีในระบบ) คืน True ถ้าถูกจำกัด"""
    now = now_utc()
    recent_hour, newest = 0, None
    for entry in storage.get_all("reset_requests"):
        if entry["email_hash"] != email_hash:
            continue
        requested_at = parse_iso(entry["requested_at"])
        if now - requested_at < timedelta(hours=1):
            recent_hour += 1
        if newest is None or requested_at > newest:
            newest = requested_at
    too_soon = newest is not None and (now - newest).total_seconds() < config.OTP_RESEND_COOLDOWN_SECONDS
    return too_soon or recent_hour >= config.OTP_MAX_REQUESTS_PER_HOUR


def _purge_old_requests():
    """ลบบันทึกการขอรหัสที่เก่ากว่า 1 วัน (กันไฟล์โตไม่จำกัด)"""
    for entry in storage.get_all("reset_requests"):
        if now_utc() - parse_iso(entry["requested_at"]) > timedelta(days=1):
            storage.delete_record("reset_requests", entry["id"])


def _invalidate_codes(user_id):
    """ทำให้ OTP / reset authorization เดิมของ user ใช้ไม่ได้ทั้งหมด"""
    for entry in storage.find_records("password_resets", "user_id", user_id):
        if not entry["used"]:
            storage.update_record("password_resets", entry["id"], {"used": True})


def request_password_reset(data):
    """POST /api/auth/forgot-password และ /api/auth/resend-reset-code  body: {"email"}
    ตอบข้อความกลางเสมอ (ยกเว้นรูปแบบอีเมลผิด / ขอบ่อยเกินไป ซึ่งตอบเหมือนกันไม่ว่ามีบัญชีหรือไม่)
    """
    body = validation.pick_fields(data, ("email",))
    problem = validation.validate_email(body.get("email"))
    if problem:
        raise validation_error({"email": problem})
    email = body["email"].strip().lower()
    digest = _email_hash(email)
    record = storage.find_one("users", "email", email)
    known_id = record["id"] if record else None

    with storage.transaction():
        if _check_request_rate(digest):
            logger.create_audit_log(None, "OTP_RATE_LIMITED", "user", known_id, {"step": "request"}, result="REJECTED")
            raise AppError("RATE_LIMITED", RATE_LIMIT_MESSAGE, 429)
        storage.create_record("reset_requests", {"email_hash": digest, "requested_at": now_iso()}, "rq")
        _purge_old_requests()

        if record is None or record["status"] != "ACTIVE":
            security.hash_otp("00000")                       # ใช้เวลาใกล้เคียงกรณีมีอีเมล (ลด timing ที่บอกว่ามีบัญชี)
            logger.create_audit_log(None, "PASSWORD_RESET_REQUESTED", "user", known_id, {}, result="NO_ACTION")
            return {"message": GENERIC_REQUEST_MESSAGE}

        _invalidate_codes(record["id"])
        code = security.new_otp_code()
        storage.create_record("password_resets", {
            "kind": "OTP", "state": "OTP_PENDING", "user_id": record["id"], "otp_hash": security.hash_otp(code),
            "expires_at": minutes_from_now_iso(config.OTP_LIFETIME_MINUTES), "attempts": 0,
            "max_attempts": config.MAX_OTP_ATTEMPTS, "used": False, "created_at": now_iso(),
        }, "pr")
        sent = email_service.send_password_reset_code(record["email"], code, config.OTP_LIFETIME_MINUTES)
        logger.create_audit_log(None, "PASSWORD_RESET_REQUESTED", "user", record["id"], {"email_sent": sent})
    return {"message": GENERIC_REQUEST_MESSAGE}


# ---------------------------------------------------------------------------
# Forgot Password: ยืนยัน OTP -> ได้ reset authorization
# ---------------------------------------------------------------------------
def _invalid_code():
    return AppError("INVALID_CODE", INVALID_CODE_MESSAGE, 400)


def _active_otp(user_id):
    """OTP ล่าสุดของ user ที่ยังไม่ถูกใช้ (ไม่มี -> None)"""
    candidates = [e for e in storage.find_records("password_resets", "user_id", user_id)
                  if e["kind"] == "OTP" and not e["used"]]
    return candidates[-1] if candidates else None


def verify_reset_code(data):
    """POST /api/auth/verify-reset-code  body: {"email", "code"}  สำเร็จได้ {"reset_token"} (ใช้ได้ครั้งเดียว)"""
    body = validation.pick_fields(data, ("email", "code"))
    problem = validation.validate_email(body.get("email"))
    code = body.get("code")
    if problem or not isinstance(code, str) or len(code) != config.OTP_LENGTH or not code.isascii() or not code.isdigit():
        raise _invalid_code()                                  # รูปแบบผิด: ตอบเหมือนรหัสผิดทุกกรณี
    record = storage.find_one("users", "email", body["email"].strip().lower())

    with storage.transaction():                                # ผู้ใช้หลายคนกดพร้อมกันต้องไม่ข้ามจำนวนครั้งที่ผิดได้
        otp = _active_otp(record["id"]) if record else None
        if otp is None:
            security.verify_otp(code, security.get_dummy_hash())
            raise _invalid_code()
        if is_expired(otp["expires_at"]):
            storage.update_record("password_resets", otp["id"], {"used": True})
            logger.create_audit_log(None, "OTP_EXPIRED", "user", record["id"], {}, result="FAILURE")
            raise _invalid_code()

        if not security.verify_otp(code, otp["otp_hash"]):
            attempts = otp["attempts"] + 1
            changes = {"attempts": attempts}
            logger.create_audit_log(None, "OTP_INVALID", "user", record["id"], {"attempts": attempts}, result="FAILURE")
            if attempts >= otp["max_attempts"]:                # ผิดครบ -> ยกเลิกรหัสนี้ ต้องขอใหม่
                changes["used"] = True
                logger.create_audit_log(None, "OTP_RATE_LIMITED", "user", record["id"], {"step": "verify"}, result="REJECTED")
            storage.update_record("password_resets", otp["id"], changes)
            raise _invalid_code()

        storage.update_record("password_resets", otp["id"], {"used": True, "state": "OTP_VERIFIED"})   # ใช้แล้วหมดทันที
        token = security.new_secret_token()
        storage.create_record("password_resets", {
            "kind": "AUTH", "state": "RESET_AUTHORIZED", "user_id": record["id"],
            "token_hash": security.hash_token(token),
            "expires_at": minutes_from_now_iso(config.RESET_AUTH_LIFETIME_MINUTES),
            "used": False, "created_at": now_iso(),
        }, "pr")
        logger.create_audit_log(None, "PASSWORD_RESET_OTP_VERIFIED", "user", record["id"], {})
    return {"reset_token": token, "expires_in_minutes": config.RESET_AUTH_LIFETIME_MINUTES}


# ---------------------------------------------------------------------------
# Forgot Password: ตั้งรหัสผ่านใหม่ (ต้องมี reset token)
# ---------------------------------------------------------------------------
def reset_password(data):
    """POST /api/auth/reset-password  body: {"reset_token", "new_password", "confirm_password"}"""
    body = validation.pick_fields(data, ("reset_token", "new_password", "confirm_password"))
    token = body.get("reset_token")
    if not isinstance(token, str) or not (20 <= len(token) <= 100):
        raise AppError("INVALID_RESET", INVALID_RESET_MESSAGE, 400)

    with storage.transaction():
        auth = storage.find_one("password_resets", "token_hash", security.hash_token(token))
        if auth is None or auth["kind"] != "AUTH" or auth["used"]:
            raise AppError("INVALID_RESET", INVALID_RESET_MESSAGE, 400)
        if is_expired(auth["expires_at"]):
            storage.update_record("password_resets", auth["id"], {"used": True})
            logger.create_audit_log(None, "PASSWORD_RESET_FAILED", "user", auth["user_id"], {"reason": "expired"}, result="FAILURE")
            raise AppError("INVALID_RESET", INVALID_RESET_MESSAGE, 400)

        errors = {}
        problem = validation.validate_password(body.get("new_password"))
        if problem:
            errors["new_password"] = problem
        elif body["new_password"] != body.get("confirm_password"):
            errors["confirm_password"] = "รหัสผ่านใหม่ไม่ตรงกัน"
        if errors:
            raise validation_error(errors)                     # รหัสไม่ผ่านนโยบาย: ยังไม่ใช้ token ให้แก้ไขได้

        now = now_iso()
        storage.update_record("users", auth["user_id"], {"password_hash": security.hash_password(body["new_password"]),
                                                         "password_reset_at": now, "updated_at": now})
        _invalidate_codes(auth["user_id"])
        storage.update_record("password_resets", auth["id"], {"used": True, "state": "PASSWORD_RESET"})
        _other_sessions_removed(auth["user_id"])               # ทุกอุปกรณ์ต้อง login ใหม่
        logger.create_audit_log(None, "PASSWORD_RESET_SUCCESS", "user", auth["user_id"], {})
    return {"reset": True, "message": "ตั้งรหัสผ่านใหม่สำเร็จ กรุณาเข้าสู่ระบบอีกครั้ง"}
