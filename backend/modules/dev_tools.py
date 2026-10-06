"""dev_tools.py - เครื่องมือสำหรับ developer (Developer OTP Mailbox)

เปิดได้เฉพาะเมื่อ  A4S_EMAIL_MODE=development  และ  A4S_DEV_TOOLS=true  พร้อมกัน  (ค่าเริ่มต้น = ปิด)
ปิดอยู่ -> ตอบ 404 เหมือนไม่มี endpoint นี้ (ไม่บอกว่ามีฟีเจอร์นี้)   เปิดอยู่ -> เฉพาะ ADMIN เท่านั้น (ไม่ login 401 / role อื่น 403)
นี่คือ "ทางลัดสำหรับทดสอบ Prototype" ไม่ใช่ฟีเจอร์ production - ห้ามเปิดในระบบจริงที่มีผู้ใช้จริง
"""
from backend import config
from backend.modules import logger, permissions, storage
from backend.modules.errors import not_found
from backend.modules.utils import is_expired


def _require_enabled_admin(actor):
    if not config.dev_mailbox_enabled():
        raise not_found("ปลายทาง API")
    permissions.check_permission(actor, "devtools.use")


def list_mailbox(actor):
    """GET /api/dev/mailbox - อีเมลจำลองล่าสุด (ใหม่สุดก่อน) พร้อม OTP  คืน {"items": [...], "warning": ...}"""
    _require_enabled_admin(actor)
    items = []
    for entry in reversed(storage.get_all("dev_mailbox")):
        items.append({"id": entry["id"], "recipient": entry["recipient"], "created_at": entry["created_at"],
                      "expires_at": entry["expires_at"], "otp": entry["otp"], "purpose": entry["purpose"],
                      "expired": is_expired(entry["expires_at"])})
    logger.create_audit_log(actor["id"], "DEV_MAILBOX_VIEWED", "dev_mailbox", None, {"count": len(items)})   # ไม่ใส่ OTP ใน log
    return {"items": items, "warning": "DEVELOPMENT ONLY: แสดง OTP จริงเพื่อทดสอบ ห้ามเปิดใน production"}


def clear_mailbox(actor):
    """DELETE /api/dev/mailbox - ล้างอีเมลจำลองทั้งหมด"""
    _require_enabled_admin(actor)
    with storage.transaction():
        removed = storage.count_records("dev_mailbox")
        storage.save_json("dev_mailbox", [])
    logger.create_audit_log(actor["id"], "DEV_MAILBOX_CLEARED", "dev_mailbox", None, {"removed": removed})
    return {"removed": removed}
