"""permissions.py - RBAC (Role-Based Access Control)

สำคัญ: frontend ซ่อนปุ่มได้ แต่ "ความปลอดภัยจริง" อยู่ที่ไฟล์นี้ - ทุก action ฝั่ง backend ต้องเรียกตรวจสิทธิ์ซ้ำ
"""
from backend.modules import storage, validation
from backend.modules.errors import forbidden_error, not_found, unauthorized_error, validation_error

# สิทธิ์พื้นฐานของผู้ซื้อ (set = ไม่มีค่าซ้ำ และตรวจสอบสมาชิกได้เร็ว)
# สิทธิ์ของ "บัญชีที่ login แล้ว" ทุก role (ข้อมูลส่วนตัวของตัวเอง)
ACCOUNT_PERMISSIONS = {
    "wishlist.use",
    "follow.use",
    "notification.view_own",
}

USER_PERMISSIONS = ACCOUNT_PERMISSIONS | {
    "cart.use",           # ใช้ตะกร้าสินค้า (admin ไม่ซื้อของ จึงไม่มีสิทธิ์นี้)
    "order.create",       # สร้างคำสั่งซื้อ
    "order.view_own",     # ดูคำสั่งซื้อของตัวเอง
    "review.create",      # เขียนรีวิว
    "commission.request",
    "payment.submit",
}

# ศิลปินทำได้ทุกอย่างที่ผู้ซื้อทำได้ + จัดการงานของตัวเอง
ARTIST_PERMISSIONS = USER_PERMISSIONS | {
    "artwork.create",
    "artwork.edit_own",
    "artwork.delete_own",
    "artwork.submit",     # ส่งงานขออนุมัติ
    "order.view_sales",   # ดูยอดขายของตัวเอง
    "commission.manage",
    "promotion.manage",
}

ADMIN_PERMISSIONS = ACCOUNT_PERMISSIONS | {
    "data.manage",        # ล้างข้อมูล / รีเซ็ตข้อมูลตัวอย่าง
    "artwork.approve",    # อนุมัติ/ปฏิเสธงาน
    "artwork.manage_any", # แก้/ลบงานของใครก็ได้
    "order.view_all",
    "order.manage",       # เปลี่ยนสถานะ/ลบ order ได้
    "review.moderate",    # ซ่อน/ลบรีวิวของคนอื่น
    "user.manage",        # ดู/สร้าง/แก้/ลบ user
    "user.ban",
    "category.manage",
    "audit.view",
    "dashboard.view",
    "devtools.use",       # Developer OTP Mailbox
    "payment.verify",
    "commission.manage_any",
    "review.moderate",
    "admin.blacklist",
    "admin.ip_block",
    "promotion.manage",
}

ROLE_PERMISSIONS = {
    "USER": USER_PERMISSIONS,
    "ARTIST": ARTIST_PERMISSIONS,
    "ADMIN": ADMIN_PERMISSIONS,
}


def get_permissions(role):
    """คืน set ของสิทธิ์ของ role นั้น (role ที่ไม่รู้จัก -> set ว่าง)"""
    return set(ROLE_PERMISSIONS.get(role, set()))


def has_permission(user, permission):
    """True/False: user คนนี้มีสิทธิ์ permission หรือไม่ (user เป็น None = ยังไม่ login = ไม่มีสิทธิ์)"""
    if user is None:
        return False
    return permission in ROLE_PERMISSIONS.get(user.get("role"), set())


def check_permission(user, permission):
    """ตรวจสิทธิ์แบบ "ผ่านหรือ raise"
    - ยังไม่ login           -> 401
    - login แล้วแต่ไม่มีสิทธิ์ -> 403
    """
    if user is None:
        raise unauthorized_error()
    if not has_permission(user, permission):
        raise forbidden_error()


def is_owner(user, owner_id):
    """True ถ้า user เป็นเจ้าของ (id ตรงกับ owner_id)"""
    return user is not None and user.get("id") == owner_id


def get_owned_record(collection, record_id, actor, label):
    """ดึง record ส่วนตัว (ตะกร้า/wishlist/follow/notification) ที่ต้องเป็นของ actor เท่านั้น
    - ยังไม่ login        -> 401
    - id รูปแบบผิด        -> 400
    - ไม่มี record นี้      -> 404
    - เป็นของคนอื่น        -> 403  (เจ้าของถูกตัดสินจาก session ฝั่ง server ไม่ใช่ user_id ที่ client ส่งมา)
    """
    if actor is None:
        raise unauthorized_error()
    problem = validation.validate_id(record_id, "id")
    if problem:
        raise validation_error({"id": problem})
    record = storage.get_record(collection, record_id)
    if record is None:
        raise not_found(label)
    if record.get("user_id") != actor["id"]:
        raise forbidden_error()
    return record
