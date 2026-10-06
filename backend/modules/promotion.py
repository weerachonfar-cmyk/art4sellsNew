"""promotion.py - artist promotions and price history foundation."""
from backend import config
from backend.modules import logger, notification, permissions, storage, validation
from backend.modules.errors import conflict_error, not_found, validation_error
from backend.modules.utils import now_iso

TYPES = ("PERCENTAGE", "FIXED_AMOUNT")

def _validate_target(body):
    fields = ("artwork_id", "category_id", "store_id")
    targets = {k: body.get(k) for k in fields if body.get(k)}
    if not targets:
        return None, {"target": "ต้องเลือก artwork, category หรือ store อย่างน้อย 1 อย่าง"}
    for key in targets:
        if validation.validate_id(targets[key], key):
            return None, {key: key + " ไม่ถูกต้อง"}
    if "artwork_id" in targets:
        art = storage.get_record("artworks", targets["artwork_id"])
        if art is None:
            return None, {"artwork_id": "ไม่พบ artwork"}
    if "category_id" in targets and storage.get_record("categories", targets["category_id"]) is None:
        return None, {"category_id": "ไม่พบ category"}
    return targets, {}

def create_promotion(data, actor):
    permissions.check_permission(actor, "promotion.manage")
    body = validation.pick_fields(data, ("title", "type", "value", "start_at", "end_at", "artwork_id", "category_id", "store_id"))
    errors = {}
    problem = validation.validate_string(body.get("title"), "ชื่อโปรโมชั่น", 2, 80)
    if problem: errors["title"] = problem
    if body.get("type") not in TYPES: errors["type"] = "type ต้องเป็น PERCENTAGE หรือ FIXED_AMOUNT"
    val, problem = validation.validate_price(body.get("value"))
    if problem: errors["value"] = problem
    if body.get("type") == "PERCENTAGE" and val is not None and val > 100: errors["value"] = "เปอร์เซ็นต์ส่วนลดต้องไม่เกิน 100"
    if not isinstance(body.get("start_at"), str) or not isinstance(body.get("end_at"), str):
        errors["date"] = "ต้องมี start_at และ end_at"
    try:
        from datetime import datetime
        start = datetime.fromisoformat(body.get("start_at", "").replace("Z", "+00:00"))
        end = datetime.fromisoformat(body.get("end_at", "").replace("Z", "+00:00"))
        if start >= end: errors["date"] = "start_at ต้องก่อน end_at"
    except ValueError:
        errors["date"] = "รูปแบบวันเวลาไม่ถูกต้อง"
    targets, target_errors = _validate_target(body)
    errors.update(target_errors)
    if errors: raise validation_error(errors)
    if targets.get("artwork_id"):
        art = storage.get_record("artworks", targets["artwork_id"])
        if art["artist_id"] != actor["id"]: raise conflict_error("NOT_OWNER", "โปรโมชั่นต้องใช้ artwork ของตัวเอง")
    rec = {"title": validation.clean_text(body["title"]), "type": body["type"], "value": val,
           "start_at": body["start_at"], "end_at": body["end_at"], **targets, "artist_id": actor["id"],
           "status": "SCHEDULED", "created_at": now_iso(), "updated_at": now_iso()}
    record = storage.create_record("promotions", rec, "pr")
    logger.create_audit_log(actor["id"], "PROMOTION_CREATED", "promotion", record["id"], {"title": record["title"]})
    return record

def list_promotions(actor=None, artist_id=None):
    rows = storage.get_all("promotions")
    if artist_id:
        rows = [p for p in rows if p.get("artist_id") == artist_id]
    rows.reverse()
    return {"items": rows}

def get_price(price, artwork_id):
    active = [p for p in storage.get_all("promotions") if p.get("status") not in ("CANCELLED", "ENDED")
              and p.get("artwork_id") == artwork_id]
    if not active: return round(price, 2), None
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    best = (price, None)
    for p in active:
        try:
            start = datetime.datetime.fromisoformat(p["start_at"].replace("Z", "+00:00")); end = datetime.datetime.fromisoformat(p["end_at"].replace("Z", "+00:00"))
        except ValueError: continue
        if not (start <= now <= end): continue
        discounted = price * (1 - p["value"] / 100) if p["type"] == "PERCENTAGE" else max(0, price - p["value"])
        if discounted < best[0]: best = (round(discounted, 2), p)
    return best

def record_price_change(artwork_id, old_price, new_price, actor_id):
    if old_price == new_price: return None
    return storage.create_record("price_history", {"artwork_id": artwork_id, "old_price": old_price, "new_price": new_price,
                                                    "changed_at": now_iso(), "changed_by": actor_id}, "ph")

def history(artwork_id):
    return {"items": list(reversed([x for x in storage.get_all("price_history") if x["artwork_id"] == artwork_id]))}
