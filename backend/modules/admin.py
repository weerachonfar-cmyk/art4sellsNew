"""admin.py - ฟังก์ชันสำหรับผู้ดูแลระบบ: Dashboard, ดู Audit Log, ระงับ/ปลดระงับบัญชี"""
from backend import config
from backend.modules import logger, order, permissions, storage, validation
from backend.modules.errors import conflict_error, not_found, validation_error
from backend.modules.utils import now_iso


def count_by_field(records, field):
    """นับจำนวน record แยกตามค่าของ field  เช่น {"APPROVED": 12, "DRAFT": 1}  (ใช้ dict เป็นตัวนับ)"""
    counts = {}
    for record in records:
        key = record[field]
        counts[key] = counts.get(key, 0) + 1
    return counts


def get_dashboard_summary(actor):
    """สรุปภาพรวมระบบ - คำนวณจากข้อมูลจริงในไฟล์ทุกครั้งที่เรียก (ไม่มีตัวเลข hardcode)"""
    permissions.check_permission(actor, "dashboard.view")
    users = storage.get_all("users")
    artworks = storage.get_all("artworks")
    orders = storage.get_all("orders")
    reviews = storage.get_all("reviews")
    payments = storage.get_all("payments")
    commissions = storage.get_all("commissions")
    promotions = storage.get_all("promotions")
    blacklist = storage.get_all("blacklist")
    blocked_ips = storage.get_all("blocked_ips")

    total_artists = 0
    for u in users:
        if u["role"] == "ARTIST":
            total_artists += 1

    total_sales = 0.0
    for o in orders:                                   # ยอดขายรวม = ผลรวมออเดอร์ที่จ่ายเงินแล้ว
        if order.is_order_paid(o):
            total_sales += o["total"]

    pending = [a for a in artworks if a["status"] == "PENDING_APPROVAL"]
    return {
        "total_users": len(users),
        "total_artists": total_artists,
        "total_artworks": len(artworks),
        "pending_artworks": len(pending),
        "total_orders": len(orders),
        "total_sales": round(total_sales, 2),
        "total_reviews": len(reviews),
        "users_by_role": count_by_field(users, "role"),
        "artworks_by_status": count_by_field(artworks, "status"),
        "orders_by_status": count_by_field(orders, "status"),
        "payments_pending": len([p for p in payments if p.get("status") == "PENDING_VERIFICATION"]),
        "payments_paid": len([p for p in payments if p.get("status") == "PAID"]),
        "commissions": len(commissions),
        "commissions_by_state": count_by_field(commissions, "state") if commissions else {},
        "promotions": len(promotions),
        "blacklisted_users": len(blacklist),
        "blocked_ips": len(blocked_ips),
    }


def get_audit_logs(query, actor):
    """GET /api/logs (admin) - กรองด้วย action, actor_id, target_type, target_id + แบ่งหน้า"""
    permissions.check_permission(actor, "audit.view")
    page, page_size, errors = validation.validate_page_params(query)
    action = str(query.get("action", "")).strip().upper()
    if action and action not in logger.AUDIT_ACTIONS:
        errors["action"] = "ไม่รู้จัก action นี้"
    if errors:
        raise validation_error(errors)
    filters = {
        "action": action,
        "actor_id": query.get("actor_id"),
        "target_type": query.get("target_type"),
        "target_id": query.get("target_id"),
    }
    return logger.list_audit_logs(filters, page, page_size)


def _drop_sessions(user_id):
    """ลบ session ทั้งหมดของ user (บังคับให้ออกจากระบบทันที)"""
    for session in storage.find_records("sessions", "user_id", user_id):
        storage.delete_record("sessions", session["id"])


def ban_user(user_id, actor):
    """ระงับบัญชี: ห้ามระงับตัวเอง/ผู้ดูแลระบบอื่น และตัด session ที่ login อยู่ทันที"""
    permissions.check_permission(actor, "user.ban")
    target = storage.get_record("users", user_id)
    if target is None:
        raise not_found("ผู้ใช้")
    if target["id"] == actor["id"] or target["role"] == "ADMIN":
        raise conflict_error("CANNOT_BAN", "ไม่สามารถระงับบัญชีของตัวเองหรือผู้ดูแลระบบได้")
    if target["status"] == "BANNED":
        raise conflict_error("ALREADY_BANNED", "บัญชีนี้ถูกระงับอยู่แล้ว")
    storage.update_record("users", user_id, {"status": "BANNED", "updated_at": now_iso()})
    _drop_sessions(user_id)
    logger.create_audit_log(actor["id"], "USER_BANNED", "user", user_id, {})
    return {"id": user_id, "status": "BANNED"}


def unban_user(user_id, actor):
    """ปลดระงับบัญชี"""
    permissions.check_permission(actor, "user.ban")
    target = storage.get_record("users", user_id)
    if target is None:
        raise not_found("ผู้ใช้")
    if target["status"] != "BANNED":
        raise conflict_error("NOT_BANNED", "บัญชีนี้ไม่ได้ถูกระงับ")
    storage.update_record("users", user_id, {"status": "ACTIVE", "updated_at": now_iso()})
    logger.create_audit_log(actor["id"], "USER_UNBANNED", "user", user_id, {})
    return {"id": user_id, "status": "ACTIVE"}
