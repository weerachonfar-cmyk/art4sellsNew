"""payment.py - payment foundation: method/status/slip metadata/verification.
No real payment gateway or OCR; amounts are always recalculated from the order.
"""
from backend import config
from backend.modules import logger, order, permissions, storage, validation
from backend.modules.errors import conflict_error, forbidden_error, not_found, validation_error
from backend.modules.utils import now_iso

METHODS = ("COD", "QR_PAYMENT", "BANK_TRANSFER")
STATUSES = config.PAYMENT_STATUSES

def _get(order_id):
    return next((p for p in storage.get_all("payments") if p["order_id"] == order_id), None)

def ensure_for_order(order_record):
    existing = _get(order_record["id"])
    if existing:
        return existing
    return storage.create_record("payments", {
        "order_id": order_record["id"],
        "user_id": order_record["user_id"],
        "method": None,
        "expected_amount": float(order_record["total"]),
        "submitted_amount": None,
        "verified_amount": None,
        "status": "UNPAID",
        "slip": None,
        "submitted_at": None,
        "verified_at": None,
        "verified_by": None,
        "rejection_reason": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }, "pay")

def get_payment(order_id, actor):
    record = order.get_order(order_id, actor)
    payment = _get(order_id) or ensure_for_order(storage.get_record("orders", order_id))
    return dict(payment, order_status=record["status"])

def submit_payment(data, actor):
    body = validation.pick_fields(data, ("order_id", "method", "submitted_amount", "slip"))
    problem = validation.validate_id(body.get("order_id"), "order_id")
    if problem:
        raise validation_error({"order_id": problem})
    method = body.get("method")
    if method not in METHODS:
        raise validation_error({"method": "วิธีชำระเงินต้องเป็น COD, QR_PAYMENT หรือ BANK_TRANSFER"})
    amount, problem = validation.validate_price(body.get("submitted_amount"))
    if problem:
        raise validation_error({"submitted_amount": problem})
    with storage.transaction():
        o = storage.get_record("orders", body["order_id"])
        if o is None or o["user_id"] != actor["id"]:
            raise not_found("คำสั่งซื้อ")
        if o["status"] not in ("PENDING_PAYMENT", "PAYMENT_SUBMITTED"):
            raise conflict_error("PAYMENT_NOT_ALLOWED", "คำสั่งซื้อนี้ไม่อยู่ในขั้นตอนรอชำระเงิน")
        payment = _get(o["id"]) or ensure_for_order(o)
        if amount < 0:
            raise validation_error({"submitted_amount": "ยอดต้องไม่ติดลบ"})
        slip = body.get("slip")
        if slip is not None and not isinstance(slip, dict):
            raise validation_error({"slip": "ข้อมูลสลิปไม่ถูกต้อง"})
        clean_slip = None
        if slip:
            clean_slip = {k: slip[k] for k in ("filename", "content_type", "size", "storage_key") if k in slip}
            if "filename" in clean_slip and (not isinstance(clean_slip["filename"], str) or len(clean_slip["filename"]) > 200):
                raise validation_error({"slip": "ชื่อไฟล์สลิปไม่ถูกต้อง"})
        updated = storage.update_record("payments", payment["id"], {
            "method": method, "submitted_amount": amount, "status": "PENDING_VERIFICATION",
            "slip": clean_slip, "submitted_at": now_iso(), "updated_at": now_iso(), "rejection_reason": None,
        })
        order._apply_status(o, "PAYMENT_SUBMITTED", actor["id"])
        logger.create_audit_log(actor["id"], "PAYMENT_SUBMITTED", "payment", updated["id"],
                                {"order_id": o["id"], "method": method, "submitted_amount": amount})
        return updated

def verify_payment(order_id, data, actor):
    permissions.check_permission(actor, "payment.verify")
    body = validation.pick_fields(data or {}, ("verified_amount", "approved", "reason"))
    o = storage.get_record("orders", order_id)
    if o is None:
        raise not_found("คำสั่งซื้อ")
    payment = _get(order_id) or ensure_for_order(o)
    approved, problem = validation.validate_boolean(body.get("approved"), "approved")
    if problem:
        raise validation_error({"approved": problem})
    verified_amount, problem = validation.validate_price(body.get("verified_amount", payment.get("submitted_amount")))
    if problem:
        raise validation_error({"verified_amount": problem})
    if approved and verified_amount < payment["expected_amount"]:
        raise validation_error({"verified_amount": "ยอดที่ยืนยันต่ำกว่ายอดที่ต้องชำระ"})
    reason = body.get("reason", "") or ""
    if not isinstance(reason, str) or len(reason) > 300:
        raise validation_error({"reason": "เหตุผลต้องเป็นข้อความไม่เกิน 300 ตัวอักษร"})
    with storage.transaction():
        status = "PAID" if approved else "REJECTED"
        updated = storage.update_record("payments", payment["id"], {
            "verified_amount": verified_amount if approved else None,
            "status": status,
            "verified_at": now_iso(), "verified_by": actor["id"],
            "rejection_reason": None if approved else (reason.strip() or "Payment rejected"),
            "updated_at": now_iso(),
        })
        if approved:
            if o["status"] == "PENDING_PAYMENT":
                order._apply_status(o, "PAYMENT_VERIFIED", actor["id"])
            elif o["status"] == "PAYMENT_SUBMITTED":
                order._apply_status(o, "PAYMENT_VERIFIED", actor["id"])
        else:
            logger.create_audit_log(actor["id"], "PAYMENT_REJECTED", "payment", payment["id"],
                                    {"order_id": o["id"], "reason": updated["rejection_reason"]})
        return updated

def reject_payment(order_id, reason, actor):
    return verify_payment(order_id, {"approved": False, "reason": reason or "Payment rejected"}, actor)
