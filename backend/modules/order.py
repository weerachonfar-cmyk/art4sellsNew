"""order.py - คำสั่งซื้อ (Order) + state machine ของสถานะ

ยังไม่มีการจ่ายเงินจริง (Phase ถัดไป) - ที่นี่ทำฐานให้พร้อม:
    CREATED -> PENDING_PAYMENT -> PAYMENT_VERIFIED -> PAID -> COMPLETED
                    |-> CANCELLED / EXPIRED
ตารางกติกาอยู่ใน config.ORDER_TRANSITIONS  เช่น COMPLETED -> PENDING_PAYMENT ถูกปฏิเสธเสมอ
"""
from backend import config
from backend.modules import artwork, logger, notification, permissions, storage, validation
from backend.modules.errors import (conflict_error, forbidden_error, not_found,
                                    unauthorized_error, validation_error)
from backend.modules.utils import is_expired, minutes_from_now_iso, now_iso, paginate


# ---------------------------------------------------------------------------
# กติกาและฟังก์ชันช่วย
# ---------------------------------------------------------------------------
def is_order_paid(order):
    """True ถ้าออเดอร์ "จ่ายเงินแล้ว" (สถานะ PAID หรือ COMPLETED)"""
    return order["status"] in config.PAID_ORDER_STATES


def expire_stale_orders():
    """เปลี่ยนออเดอร์ที่รอจ่ายเงินเกินเวลา (expires_at ผ่านไปแล้ว) เป็น EXPIRED  คืนจำนวนที่หมดอายุ"""
    count = 0
    for order in storage.get_all("orders"):
        waiting = order["status"] in ("CREATED", "PENDING_PAYMENT")
        if waiting and is_expired(order["expires_at"]):
            _apply_status(order, "EXPIRED", None)
            count += 1
    return count


def get_locked_artwork_ids():
    """set ของ id งาน LIMITED ที่ถูกล็อกอยู่ เพราะมีออเดอร์ที่ยังดำเนินอยู่ (คนอื่นซื้อซ้ำไม่ได้)"""
    expire_stale_orders()
    locked = set()
    for order in storage.get_all("orders"):
        if order["status"] in config.ACTIVE_ORDER_STATES:
            for item in order["items"]:
                if item["sale_type"] == "LIMITED":
                    locked.add(item["artwork_id"])
    return locked


def find_completed_order(user_id, artwork_id):
    """หาออเดอร์ COMPLETED ของ user ที่มีงานชิ้นนี้ (ใช้ตรวจสิทธิ์รีวิว) ไม่พบ -> None"""
    for order in storage.get_all("orders"):
        if order["user_id"] == user_id and order["status"] == "COMPLETED":
            for item in order["items"]:
                if item["artwork_id"] == artwork_id:
                    return order
    return None


def _apply_status(order, new_status, actor_id):
    """เปลี่ยนสถานะตามตารางกติกา (ตรวจ transition ที่นี่ที่เดียว) แล้วบันทึก + audit
    ถ้าเปลี่ยนไม่ได้ raise 409
    """
    old_status = order["status"]
    if not validation.can_transition(old_status, new_status, config.ORDER_TRANSITIONS):
        raise conflict_error("INVALID_TRANSITION",
                             "เปลี่ยนสถานะจาก " + old_status + " เป็น " + new_status + " ไม่ได้")
    changes = {"status": new_status, "updated_at": now_iso()}
    if new_status == "PAID":
        changes["paid_at"] = now_iso()
        for item in order["items"]:
            artwork.mark_artwork_sold(item["artwork_id"], actor_id)
    if new_status == "PAYMENT_VERIFIED":
        changes["payment_verified_at"] = now_iso()
    updated = storage.update_record("orders", order["id"], changes)
    logger.create_audit_log(actor_id, "ORDER_UPDATED", "order", order["id"],
                            {"from": old_status, "to": new_status})
    notification.notify(order["user_id"], "ORDER_UPDATED", "คำสั่งซื้อ " + order["id"] + " เปลี่ยนสถานะเป็น " + new_status)
    return updated


def _build_view(order, user_names):
    view = dict(order)
    view["user_name"] = user_names.get(order["user_id"], "")
    return view


def _user_names():
    return {u["id"]: u["name"] for u in storage.get_all("users")}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create_order(data, actor):
    """สร้างคำสั่งซื้อ (ทำทีละคำขอ เพื่อไม่ให้ 2 คนซื้องาน LIMITED ชิ้นเดียวกันพร้อมกันได้)"""
    permissions.check_permission(actor, "order.create")
    with storage.transaction():
        return _create_order_locked(data, actor)


def _create_order_locked(data, actor):
    """สร้างคำสั่งซื้อจากรายการ [{"artwork_id": ..., "quantity": ...}]

    ตรวจต่อรายการ: งานต้องมีอยู่และ APPROVED, ไม่ใช่งานของตัวเอง, งาน LIMITED ซื้อได้ชิ้นเดียวและต้องไม่ถูกล็อก
    คำนวณราคารวมจากราคาในฐานข้อมูล (ไม่เชื่อราคาที่ client ส่งมา)
    """
    items_in, errors = validation.validate_order_items(data.get("items"))
    if errors:
        raise validation_error(errors)

    locked_ids = get_locked_artwork_ids()
    order_items = []
    total = 0.0
    list_total = 0.0
    for entry in items_in:
        art = storage.get_record("artworks", entry["artwork_id"])
        if art is None or art["status"] not in config.PUBLIC_ARTWORK_STATUSES:
            raise not_found("Artwork")
        if art["status"] == "SOLD":
            raise conflict_error("ARTWORK_SOLD", "งาน \"" + art["title"] + "\" ขายไปแล้ว")
        if permissions.is_owner(actor, art["artist_id"]):
            raise conflict_error("OWN_ARTWORK", "ซื้องานของตัวเองไม่ได้")
        if art["sale_type"] == "LIMITED":
            if entry["quantity"] != 1:
                raise validation_error({"items": "งาน LIMITED ซื้อได้ครั้งละ 1 ชิ้น"})
            if art["id"] in locked_ids:
                raise conflict_error("ARTWORK_LOCKED", "งาน \"" + art["title"] + "\" มีผู้ซื้ออื่นกำลังชำระเงินอยู่")
        from backend.modules import promotion
        current_price, promo = promotion.get_price(art["price"], art["id"])
        order_items.append({
            "artwork_id": art["id"],
            "title": art["title"],
            "artist_id": art["artist_id"],
            "sale_type": art["sale_type"],
            "quantity": entry["quantity"],
            "unit_price": current_price,
            "list_price": art["price"],
            "promotion_id": promo["id"] if promo else None,
        })
        total += current_price * entry["quantity"]
        list_total += art["price"] * entry["quantity"]

    now = now_iso()
    order = {
        "user_id": actor["id"],
        "items": order_items,
        "total": round(total, 2),
        "original_total": round(list_total, 2),
        "status": "CREATED",
        "created_at": now,
        "updated_at": now,
        "expires_at": minutes_from_now_iso(config.ORDER_TTL_MINUTES),
        "paid_at": None,
        "payment_verified_at": None,
        "payment_status": "UNPAID",
        "payment_method": None,
    }
    storage.create_record("orders", order, "o")
    from backend.modules import payment
    payment.ensure_for_order(order)
    logger.create_audit_log(actor["id"], "ORDER_CREATED", "order", order["id"],
                            {"total": order["total"], "items": len(order_items)})
    return _apply_status(order, "PENDING_PAYMENT", actor["id"])   # รอจ่ายเงินทันที (เหมือน Phase 2)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def get_order(order_id, actor):
    """ดูออเดอร์เดียว: เจ้าของออเดอร์ หรือ admin  (คนอื่น -> 404 ไม่เผยว่ามีออเดอร์นี้)"""
    if actor is None:
        raise unauthorized_error()
    expire_stale_orders()
    order = storage.get_record("orders", order_id)
    allowed = order is not None and (order["user_id"] == actor["id"]
                                     or permissions.has_permission(actor, "order.view_all"))
    if not allowed:
        raise not_found("คำสั่งซื้อ")
    return _build_view(order, _user_names())


def list_orders(query, actor):
    """รายการออเดอร์  scope=mine (ของฉัน) | sales (ยอดขายของศิลปิน) | all (admin)  + status, page, page_size"""
    if actor is None:
        raise unauthorized_error()
    default_scope = "all" if permissions.has_permission(actor, "order.view_all") else "mine"
    scope = query.get("scope", default_scope)
    needed = {"mine": "order.view_own", "sales": "order.view_sales", "all": "order.view_all"}
    if scope not in needed:
        raise validation_error({"scope": "scope ต้องเป็น mine, sales หรือ all"})
    permissions.check_permission(actor, needed[scope])

    page, page_size, errors = validation.validate_page_params(query)
    status = str(query.get("status", "")).strip().upper()
    if status and status not in config.ORDER_STATES:
        errors["status"] = "status ไม่ถูกต้อง"
    if errors:
        raise validation_error(errors)

    expire_stale_orders()
    names = _user_names()
    matched = []
    for order in storage.get_all("orders"):
        if status and order["status"] != status:
            continue
        if scope == "mine" and order["user_id"] != actor["id"]:
            continue
        if scope == "sales":
            own_items = [i for i in order["items"] if i["artist_id"] == actor["id"]]
            if not own_items or not is_order_paid(order):
                continue
            view = _build_view(order, names)
            view["items"] = own_items                  # ศิลปินเห็นเฉพาะงานของตัวเอง
            view["sales_total"] = round(sum(i["unit_price"] * i["quantity"] for i in own_items), 2)
            matched.append(view)
            continue
        matched.append(_build_view(order, names))
    matched.reverse()                                  # ใหม่สุดก่อน
    return paginate(matched, page, page_size)


# ---------------------------------------------------------------------------
# Update (เปลี่ยนสถานะ) / Delete
# ---------------------------------------------------------------------------
def update_order_status(order_id, data, actor):
    """เปลี่ยนสถานะออเดอร์  body: {"status": "CANCELLED"}
    - ผู้ซื้อ: ยกเลิก (CANCELLED) หรือยืนยันรับงาน (COMPLETED) ออเดอร์ของตัวเองเท่านั้น
    - admin : เปลี่ยนได้ทุกสถานะที่ตารางกติกาอนุญาต (ใช้จำลองการยืนยันชำระเงินใน Phase นี้)
    """
    if actor is None:
        raise unauthorized_error()
    new_status = str(data.get("status") or "").strip().upper()
    if new_status not in config.ORDER_STATES:
        raise validation_error({"status": "สถานะไม่ถูกต้อง"})
    expire_stale_orders()
    order = storage.get_record("orders", order_id)
    is_admin = permissions.has_permission(actor, "order.manage")
    is_buyer = order is not None and order["user_id"] == actor["id"]
    if order is None or not (is_admin or is_buyer):
        raise not_found("คำสั่งซื้อ")
    if not is_admin and new_status not in config.BUYER_ORDER_ACTIONS:
        raise forbidden_error()                        # ผู้ซื้อห้ามข้ามไป PAID เอง
    if new_status == "PAYMENT_VERIFIED" and is_admin:
        from backend.modules import payment
        return payment.verify_payment(order_id, {"approved": True, "verified_amount": order["total"]}, actor)
    updated = _apply_status(order, new_status, actor["id"])
    return _build_view(updated, _user_names())


def delete_order(order_id, actor):
    """ลบออเดอร์ (admin เท่านั้น) - ลบได้เฉพาะ CANCELLED / EXPIRED เพื่อไม่ให้ประวัติการเงินหาย"""
    permissions.check_permission(actor, "order.manage")
    order = storage.get_record("orders", order_id)
    if order is None:
        raise not_found("คำสั่งซื้อ")
    if order["status"] not in ("CANCELLED", "EXPIRED"):
        raise conflict_error("ORDER_NOT_DELETABLE", "ลบได้เฉพาะออเดอร์ที่ถูกยกเลิกหรือหมดอายุ")
    storage.delete_record("orders", order_id)
    logger.create_audit_log(actor["id"], "ORDER_DELETED", "order", order_id, {})
    return {"deleted": True, "id": order_id}
