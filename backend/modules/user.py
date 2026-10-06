"""user.py - CRUD ของผู้ใช้ (User) และข้อมูลโปรไฟล์ศิลปิน"""
from backend import config
from backend.modules import logger, permissions, references, security, storage, validation
from backend.modules.errors import (AppError, conflict_error, forbidden_error, not_found,
                                    unauthorized_error, validation_error)
from backend.modules.utils import now_iso, paginate


def public_user(record):
    """ตัด password_hash ออก - ต้องใช้ทุกครั้งที่ส่งข้อมูล user ออกไปนอก backend"""
    return {key: value for key, value in record.items() if key != "password_hash"}


def public_profile(record):
    """ข้อมูลโปรไฟล์ที่คนทั่วไปดูได้ (ไม่มีอีเมล/สถานะบัญชี)"""
    fields = ("id", "name", "role", "headline", "bio", "rating", "followers", "accepts_commissions")
    return {field: record.get(field) for field in fields}


def get_user_record(user_id):
    """ดึง record ของ user (มี password_hash - ใช้ภายใน backend เท่านั้น) ถ้าไม่พบ raise 404"""
    record = storage.get_record("users", user_id)
    if record is None:
        raise not_found("ผู้ใช้")
    return record


def create_user(data, allowed_roles, actor=None, require_confirm=False):
    """สร้างผู้ใช้ใหม่ (ใช้ทั้งตอนสมัครเอง และ admin สร้างให้)

    พารามิเตอร์: data (dict), allowed_roles (tuple ของ role ที่กำหนดได้), actor (คนสร้าง หรือ None = สมัครเอง),
                require_confirm (True = ต้องส่ง confirm_password ที่ตรงกัน - ใช้ตอนสมัครเอง)
    คืนค่า: dict ของ user (ไม่มี password_hash)
    """
    clean, errors = validation.validate_user_data(data, allowed_roles, require_confirm)
    if errors:
        raise validation_error(errors)
    password_hash = security.hash_password(clean["password"])    # คำนวณก่อนล็อก (ใช้เวลานาน)
    with storage.transaction():                                   # เช็คอีเมลซ้ำ + บันทึก ต้องเสร็จในจังหวะเดียว
        if storage.find_one("users", "email", clean["email"]) is not None:
            raise AppError("EMAIL_EXISTS", "อีเมลนี้ถูกใช้งานแล้ว", 409, {"email": "อีเมลนี้ถูกใช้งานแล้ว"})
        record = _new_user_record(clean, password_hash)
        storage.create_record("users", record, "u")
    actor_id = actor["id"] if actor else record["id"]
    logger.create_audit_log(actor_id, "USER_CREATED", "user", record["id"], {"role": record["role"]})
    return public_user(record)


def _new_user_record(clean, password_hash):
    """สร้าง dict ของ user ใหม่ (ยังไม่บันทึกลงไฟล์)"""
    now = now_iso()
    return {
        "name": clean["name"],
        "email": clean["email"],
        "password_hash": password_hash,
        "role": clean["role"],
        "status": "ACTIVE",
        "headline": "New artist" if clean["role"] == "ARTIST" else "",
        "bio": "",
        "rating": 0.0,
        "followers": 0,
        "accepts_commissions": False,
        "password_changed_at": None,                  # ใช้คำนวณ cooldown การเปลี่ยนรหัสผ่าน
        "created_at": now,
        "updated_at": now,
    }


def get_user(user_id, actor):
    """ดูข้อมูล user: ดูของตัวเอง หรือ admin ดูของใครก็ได้"""
    if actor is None:
        raise unauthorized_error()
    if not (permissions.is_owner(actor, user_id) or permissions.has_permission(actor, "user.manage")):
        raise forbidden_error()
    return public_user(get_user_record(user_id))


def list_users(query, actor):
    """รายชื่อผู้ใช้ทั้งหมด (admin เท่านั้น) รองรับ q, role, status, page, page_size"""
    permissions.check_permission(actor, "user.manage")
    page, page_size, errors = validation.validate_page_params(query)
    role = str(query.get("role", "")).strip().upper()
    status = str(query.get("status", "")).strip().upper()
    if role and role not in config.ROLES:
        errors["role"] = "role ไม่ถูกต้อง"
    if status and status not in config.USER_STATUSES:
        errors["status"] = "status ไม่ถูกต้อง"
    if errors:
        raise validation_error(errors)

    text = str(query.get("q", "")).strip().lower()
    matched = []
    for record in storage.get_all("users"):
        if role and record["role"] != role:
            continue
        if status and record["status"] != status:
            continue
        if text and text not in record["name"].lower() and text not in record["email"].lower():
            continue
        matched.append(public_user(record))
    return paginate(matched, page, page_size)


def update_user(user_id, data, actor):
    """แก้ข้อมูล user: เจ้าของแก้โปรไฟล์ตัวเองได้ / admin แก้ได้ทุกคน และเปลี่ยน role ได้
    รับเฉพาะ field ที่อนุญาต (name, headline, bio, accepts_commissions และ role สำหรับ admin)
    """
    if actor is None:
        raise unauthorized_error()
    is_admin = permissions.has_permission(actor, "user.manage")
    if not (is_admin or permissions.is_owner(actor, user_id)):
        raise forbidden_error()
    record = get_user_record(user_id)

    changes, errors = {}, {}
    if "name" in data:
        problem = validation.validate_username(data["name"])
        if problem:
            errors["name"] = problem
        else:
            changes["name"] = str(data["name"]).strip()
    if "headline" in data:
        problem = validation.validate_string(data["headline"], "headline", max_len=80)
        if problem:
            errors["headline"] = problem
        else:
            changes["headline"] = str(data["headline"] or "").strip()
    if "bio" in data:
        problem = validation.validate_string(data["bio"], "bio", max_len=500, single_line=False)
        if problem:
            errors["bio"] = problem
        else:
            changes["bio"] = str(data["bio"] or "").strip()
    if "accepts_commissions" in data:
        value, problem = validation.validate_boolean(data["accepts_commissions"], "accepts_commissions")
        if problem:
            errors["accepts_commissions"] = problem
        else:
            changes["accepts_commissions"] = value
    if "role" in data:
        if not is_admin:
            raise forbidden_error()                    # คนทั่วไปเปลี่ยน role ตัวเองไม่ได้
        role = str(data["role"]).strip().upper()
        if role not in config.ROLES:
            errors["role"] = "role ไม่ถูกต้อง"
        elif permissions.is_owner(actor, user_id) and role != record["role"]:
            raise conflict_error("CANNOT_CHANGE_OWN_ROLE", "เปลี่ยน role ของตัวเองไม่ได้")
        else:
            changes["role"] = role

    if errors:
        raise validation_error(errors)
    if not changes:
        raise validation_error({"_": "ไม่มีข้อมูลที่ต้องแก้ไข"})
    changes["updated_at"] = now_iso()
    updated = storage.update_record("users", user_id, changes)
    logger.create_audit_log(actor["id"], "USER_UPDATED", "user", user_id,
                            {"fields": sorted(k for k in changes if k != "updated_at")})
    return public_user(updated)


def delete_user(user_id, actor):
    """ลบ user (admin เท่านั้น) - ลบตัวเองไม่ได้ และลบไม่ได้ถ้ามีงาน/คำสั่งซื้อ/รีวิวที่เกี่ยวข้อง (ให้ใช้ Ban แทน)"""
    permissions.check_permission(actor, "user.manage")
    get_user_record(user_id)
    if actor["id"] == user_id:
        raise conflict_error("CANNOT_DELETE_SELF", "ลบบัญชีของตัวเองไม่ได้")
    in_use = (storage.find_records("artworks", "artist_id", user_id)
              or storage.find_records("orders", "user_id", user_id)
              or storage.find_records("reviews", "user_id", user_id))
    if in_use:
        raise conflict_error("USER_IN_USE", "ลบไม่ได้ เพราะผู้ใช้นี้มีข้อมูลที่เกี่ยวข้อง (ใช้การระงับบัญชีแทน)")
    references.purge_user_references(user_id)          # ตะกร้า/wishlist/follow/แจ้งเตือน/session/รหัส OTP ของ user นี้
    storage.delete_record("users", user_id)
    logger.create_audit_log(actor["id"], "USER_DELETED", "user", user_id)
    return {"deleted": True, "id": user_id}


def list_artists():
    """รายชื่อศิลปินที่ใช้งานอยู่ (public) - ใช้ for วนกรอง"""
    artists = []
    for record in storage.get_all("users"):
        if record["role"] == "ARTIST" and record["status"] == "ACTIVE":
            artists.append(public_profile(record))
    return {"items": artists}


def get_artist(user_id):
    """โปรไฟล์ศิลปิน (public) ถ้าไม่ใช่ศิลปินหรือถูกระงับ -> 404"""
    record = storage.get_record("users", user_id)
    if record is None or record["role"] != "ARTIST" or record["status"] != "ACTIVE":
        raise not_found("ศิลปิน")
    return public_profile(record)
