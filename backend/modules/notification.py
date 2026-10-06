"""notification.py - การแจ้งเตือนส่วนตัวของ user (Phase 3.5 foundation)

- ทุก record มี user_id เจ้าของ  ผู้ใช้ดูได้เฉพาะของตัวเอง (ตัดสินจาก session ฝั่ง server)
- ข้อความเป็น plain text ที่ระบบสร้างเอง  หน้าเว็บต้องแสดงด้วยการ escape (ห้ามตีความเป็น HTML)
"""
from backend.modules import logger, permissions, storage, validation
from backend.modules.errors import StorageError, validation_error
from backend.modules.utils import now_iso, paginate

KINDS = {"ARTWORK_APPROVED", "ARTWORK_REJECTED", "ORDER_UPDATED", "PAYMENT_UPDATE", "NEW_ARTWORK", "PRICE_DROP", "PROMOTION", "COMMISSION_UPDATE"}


def notify(user_id, kind, message):
    """สร้างการแจ้งเตือนให้ user  ล้มเหลวก็ไม่ทำให้ action หลักล้ม (แค่เขียน dev log)  คืน record หรือ None"""
    if kind not in KINDS or not user_id:
        return None
    record = {"user_id": user_id, "type": kind, "message": message[:200], "read": False, "created_at": now_iso()}
    try:
        return storage.create_record("notifications", record, "n")
    except StorageError as err:
        logger.log_exception("notification write failed", err)
        return None


def list_notifications(query, actor):
    """GET /api/me/notifications : ของฉันเท่านั้น (ใหม่สุดก่อน) + unread_count"""
    permissions.check_permission(actor, "notification.view_own")
    errors = validation.check_allowed_params(query, {"unread", "page", "page_size"})
    page, page_size, page_errors = validation.validate_page_params(query)
    errors.update(page_errors)
    only_unread = False
    if "unread" in query:
        only_unread, problem = validation.validate_boolean(query["unread"], "unread", from_query=True)
        if problem:
            errors["unread"] = problem
    if errors:
        raise validation_error(errors)
    mine = [n for n in storage.get_all("notifications") if n["user_id"] == actor["id"]]
    unread_count = len([n for n in mine if not n["read"]])
    items = [n for n in mine if not (only_unread and n["read"])]
    items.reverse()
    result = paginate(items, page, page_size)
    result["unread_count"] = unread_count
    return result


def mark_read(notification_id, actor):
    """PUT /api/me/notifications/:id : ทำเครื่องหมายว่าอ่านแล้ว (เจ้าของเท่านั้น)"""
    permissions.check_permission(actor, "notification.view_own")
    record = permissions.get_owned_record("notifications", notification_id, actor, "การแจ้งเตือน")
    return storage.update_record("notifications", record["id"], {"read": True})


def mark_all_read(actor):
    permissions.check_permission(actor, "notification.view_own")
    changed = 0
    for record in storage.get_all("notifications"):
        if record["user_id"] == actor["id"] and not record["read"]:
            storage.update_record("notifications", record["id"], {"read": True})
            changed += 1
    return {"updated": changed}
