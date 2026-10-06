"""payment.py - payment foundation: method/status/slip metadata/verification.
No real payment gateway or OCR; amounts are always recalculated from the order.
"""
import hashlib

from backend import config
from backend.modules import artwork_files, file_storage, logger, order, permissions, storage, uploads, validation
from backend.modules.errors import conflict_error, forbidden_error, not_found, unauthorized_error, validation_error
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

<<<<<<< HEAD
def _clean_slip(slip, method):
    """จำลองการแนบสลิป: ผู้ซื้อพิมพ์คำว่า slip (ตัวพิมพ์เล็ก/ใหญ่ก็ได้) แทนการอัปโหลดไฟล์
    QR_PAYMENT / BANK_TRANSFER ต้องพิมพ์ให้ถูก  COD ไม่ต้องมีสลิป"""
    text = slip.strip() if isinstance(slip, str) else ""
    if method == "COD":
        return None
    if text.lower() != "slip":
        raise validation_error({"slip": 'กรุณาพิมพ์คำว่า "slip" เพื่อจำลองการแนบสลิป'})
    return {"text": "slip", "simulated": True}
=======
SLIP_SKIP_WORD = "slip"        # คำสั่งลับ: พิมพ์ slip (ตัวพิมพ์เล็ก/ใหญ่ก็ได้) เพื่อข้ามการอัปโหลดรูป -> บันทึกเป็นสลิปจำลอง (simulated)


def _slip_files(order_id):
    return [f for f in storage.get_all("files") if f.get("role") == "slip" and f.get("order_id") == order_id]


def _slip_summary(record):
    """ข้อมูลสลิปที่บันทึกใน payment (ไม่มี blob_path ภายใน)"""
    return {"file_id": record["id"], "content_type": record["content_type"], "size": record["size"], "simulated": False}


def _clean_slip(slip, method, order_id):
    """สลิปของการชำระเงิน
    - COD: ไม่ต้องมีสลิป
    - QR_PAYMENT / BANK_TRANSFER: ต้องมี "รูปสลิปที่อัปโหลดไว้แล้ว" ของออเดอร์นี้ (POST /orders/:id/payment/slip)
      หรือพิมพ์คำลับ slip เพื่อข้าม (เก็บเป็นสลิปจำลอง ให้แอดมินเห็นว่าไม่มีรูป)"""
    if method == "COD":
        return None
    typed = slip.strip().lower() if isinstance(slip, str) else ""
    if typed == SLIP_SKIP_WORD:
        return {"text": SLIP_SKIP_WORD, "simulated": True}
    files = _slip_files(order_id)
    if not files:
        raise validation_error({"slip": "กรุณาอัปโหลดรูปสลิปการโอนเงิน"})
    return _slip_summary(max(files, key=lambda f: f.get("created_at", "")))


def upload_slip(order_id, data, actor):
    """POST /api/orders/:order_id/payment/slip  body {filename, content_type, data_base64}
    เจ้าของออเดอร์อัปโหลดรูปสลิป (PNG/JPG/WebP) ขณะออเดอร์ยังรอชำระ  ตรวจนามสกุล + Content-Type + ขนาด + magic bytes + ถอดรหัสด้วย Pillow
    เก็บแบบ private (ไม่มี public URL)  อัปโหลดใหม่ = แทนที่รูปเดิม"""
    if actor is None:
        raise unauthorized_error()
    permissions.check_permission(actor, "payment.submit")
    problem = validation.validate_id(order_id, "order_id")
    if problem:
        raise validation_error({"order_id": problem})
    filename, content_type, raw = artwork_files.decode_upload_body(data)
    clean, errors = uploads.validate_upload(filename, content_type, raw)
    if errors:
        raise validation_error(errors)
    image_type = clean["detected_type"]
    artwork_files.decode_image(raw, image_type)
    extension = artwork_files.EXTENSION_FOR_TYPE[image_type]
    mime = artwork_files.CONTENT_TYPE[image_type]
    o = storage.get_record("orders", order_id)
    if o is None or o["user_id"] != actor["id"]:
        raise not_found("คำสั่งซื้อ")
    if o["status"] not in ("PENDING_PAYMENT", "PAYMENT_SUBMITTED"):
        raise conflict_error("PAYMENT_NOT_ALLOWED", "คำสั่งซื้อนี้ไม่อยู่ในขั้นตอนรอชำระเงิน")
    store = file_storage.get_store()
    path = store.put("slip", raw, extension, mime)
    try:
        with storage.transaction():
            old = _slip_files(order_id)
            record = storage.create_record("files", {
                "order_id": order_id, "owner_id": actor["id"], "role": "slip", "storage_provider": store.name,
                "blob_path": path, "content_type": mime, "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "created_at": now_iso()}, "f")
            for item in old:
                storage.delete_record("files", item["id"])
    except Exception:
        store.delete(path)                              # ล้มกลางทาง: ไม่ทิ้งไฟล์กำพร้า
        raise
    for item in old:
        artwork_files._delete_stored(item)
    logger.create_audit_log(actor["id"], "PAYMENT_SLIP_UPLOADED", "order", order_id, {"size": len(raw), "type": image_type})
    return {"order_id": order_id, "slip": _slip_summary(record)}


def get_slip(order_id, actor):
    """GET /api/orders/:order_id/payment/slip - รูปสลิป: เจ้าของออเดอร์หรือผู้ที่ตรวจสอบการชำระเงินได้ (admin) เท่านั้น  ไม่มี public URL"""
    if actor is None:
        raise unauthorized_error()
    problem = validation.validate_id(order_id, "order_id")
    if problem:
        raise validation_error({"order_id": problem})
    o = storage.get_record("orders", order_id)
    allowed = o is not None and (o["user_id"] == actor["id"] or permissions.has_permission(actor, "payment.verify"))
    if not allowed:
        raise not_found("คำสั่งซื้อ")                      # คนอื่นไม่รู้ว่ามีออเดอร์/สลิปนี้อยู่จริง
    payment = _get(order_id)
    files = _slip_files(order_id)
    wanted = (payment or {}).get("slip") or {}
    record = next((f for f in files if f["id"] == wanted.get("file_id")), None) or (
        max(files, key=lambda f: f.get("created_at", "")) if files else None)
    if record is None:
        raise not_found("รูปสลิป")
    response = artwork_files._serve(record, None)
    response.private = True
    return response


def delete_slips_of_orders(order_ids):
    """ลบรูปสลิปของออเดอร์ที่ถูกล้างข้อมูล (ไม่ให้เหลือไฟล์กำพร้า)"""
    doomed = [f for f in storage.get_all("files") if f.get("role") == "slip" and f.get("order_id") in order_ids]
    for item in doomed:
        artwork_files._delete_stored(item)
        storage.delete_record("files", item["id"])
    return len(doomed)
>>>>>>> 4bb6b93 (Block emoji in email, simulate slip by typing 'slip', fix payment/commission/admin forms)


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
<<<<<<< HEAD
        clean_slip = _clean_slip(body.get("slip"), method)
=======
        clean_slip = _clean_slip(body.get("slip"), method, o["id"])
>>>>>>> 4bb6b93 (Block emoji in email, simulate slip by typing 'slip', fix payment/commission/admin forms)
        updated = storage.update_record("payments", payment["id"], {
            "method": method, "submitted_amount": amount, "status": "PENDING_VERIFICATION",
            "slip": clean_slip, "submitted_at": now_iso(), "updated_at": now_iso(), "rejection_reason": None,
        })
        if o["status"] == "PENDING_PAYMENT":            # ส่งซ้ำ (เปลี่ยนสลิป / ถูกปฏิเสธแล้วส่งใหม่) ตอนสถานะเป็น PAYMENT_SUBMITTED อยู่แล้ว: ไม่ต้องเปลี่ยนสถานะอีก
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
