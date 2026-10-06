"""review.py - รีวิวงานศิลป์ (Review foundation)

กติกา: รีวิวได้เฉพาะคนที่ซื้องานนั้นและออเดอร์ COMPLETED แล้ว, รีวิวงานละ 1 ครั้ง, รีวิวงานตัวเองไม่ได้
(ระบบกันรีวิวปลอมขั้นสูงจะทำใน Phase ถัดไป)
"""
from backend import config
from backend.modules import logger, order, permissions, storage, validation
from backend.modules.errors import (AppError, forbidden_error, not_found,
                                    unauthorized_error, validation_error)
from backend.modules.utils import now_iso, paginate


def calculate_average_rating(reviews, field="rating"):
    """ค่าเฉลี่ยคะแนน (ปัด 1 ตำแหน่ง) โดยรองรับ rating เดิมย้อนหลังได้"""
    if not reviews:
        return 0.0
    total = 0
    count = 0
    for review in reviews:
        value = review.get(field, review.get("rating"))
        if isinstance(value, (int, float)):
            total += value
            count += 1
    return round(total / count, 1) if count else 0.0


def refresh_ratings(artwork_id):
    """คำนวณคะแนนเฉลี่ยของงานและของศิลปินใหม่ จากรีวิวที่ PUBLISHED แล้วเก็บกลับลงข้อมูล"""
    art = storage.get_record("artworks", artwork_id)
    if art is None:
        return
    published = [r for r in storage.get_all("reviews") if r["status"] == "PUBLISHED"]
    artwork_reviews = [r for r in published if r["artwork_id"] == artwork_id]
    artist_reviews = [r for r in published if r["artist_id"] == art["artist_id"]]
    storage.update_record("artworks", artwork_id, {"rating": calculate_average_rating(artwork_reviews, "artwork_rating")})
    storage.update_record("users", art["artist_id"], {"rating": calculate_average_rating(artist_reviews, "artist_rating")})


def check_review_eligibility(actor, artwork_id):
    """ตรวจว่า actor รีวิวงานนี้ได้หรือไม่
    คืนค่า: tuple (eligible, reason, order_id)  - order_id คือออเดอร์ที่ใช้เป็นหลักฐานการซื้อ
    """
    if actor is None:
        return False, "กรุณาเข้าสู่ระบบ", None
    if not permissions.has_permission(actor, "review.create"):
        return False, "บทบาทนี้เขียนรีวิวไม่ได้", None
    art = storage.get_record("artworks", artwork_id)
    if art is None:
        return False, "ไม่พบ Artwork", None
    if art["artist_id"] == actor["id"]:
        return False, "รีวิวงานของตัวเองไม่ได้", None
    done_order = order.find_completed_order(actor["id"], artwork_id)
    if done_order is None:
        return False, "ต้องซื้องานนี้และคำสั่งซื้อเสร็จสมบูรณ์ก่อนจึงรีวิวได้", None
    for review in storage.get_all("reviews"):
        if review["user_id"] == actor["id"] and review["artwork_id"] == artwork_id:
            return False, "คุณรีวิวงานนี้ไปแล้ว", None
    return True, "", done_order["id"]


def create_review(data, actor):
    """สร้างรีวิว body: {"artwork_id", "rating" (1-5), "comment"}"""
    permissions.check_permission(actor, "review.create")
    clean, errors = validation.validate_review(data)
    artwork_id = str(data.get("artwork_id") or "").strip()
    if not artwork_id:
        errors["artwork_id"] = "กรุณาระบุ artwork_id"
    if errors:
        raise validation_error(errors)

    art = storage.get_record("artworks", artwork_id)
    if art is None:
        raise not_found("Artwork")
    with storage.transaction():                        # ตรวจสิทธิ์ + บันทึก ต้องเสร็จในจังหวะเดียว (กันรีวิวซ้ำพร้อมกัน)
        eligible, reason, order_id = check_review_eligibility(actor, artwork_id)
        if not eligible:
            raise AppError("REVIEW_NOT_ALLOWED", reason, 403)
        record = _save_review(clean, art, actor, order_id)
    refresh_ratings(artwork_id)
    logger.create_audit_log(actor["id"], "REVIEW_CREATED", "review", record["id"],
                            {"artwork_id": artwork_id, "rating": record["rating"]})
    return record


def _save_review(clean, art, actor, order_id):
    """สร้าง record รีวิวและบันทึกลงไฟล์ คืน record"""
    now = now_iso()
    record = {
        "order_id": order_id,
        "artwork_id": art["id"],
        "artist_id": art["artist_id"],
        "user_id": actor["id"],
        "rating": clean["rating"],
        "artwork_rating": clean.get("artwork_rating", clean["rating"]),
        "artist_rating": clean.get("artist_rating", clean["rating"]),
        "comment": clean["comment"],
        "status": "PUBLISHED",
        "created_at": now,
        "updated_at": now,
    }
    return storage.create_record("reviews", record, "r")


def list_reviews(query, actor=None):
    """GET /api/reviews  กรองด้วย artwork_id / artist_id / user_id  (คนทั่วไปเห็นเฉพาะที่ PUBLISHED)"""
    page, page_size, errors = validation.validate_page_params(query)
    if errors:
        raise validation_error(errors)
    can_moderate = permissions.has_permission(actor, "review.moderate")
    matched = []
    for review in storage.get_all("reviews"):
        if review["status"] != "PUBLISHED" and not can_moderate:
            continue
        if query.get("artwork_id") and review["artwork_id"] != query["artwork_id"]:
            continue
        if query.get("artist_id") and review["artist_id"] != query["artist_id"]:
            continue
        if query.get("user_id") and review["user_id"] != query["user_id"]:
            continue
        matched.append(review)
    matched.reverse()
    result = paginate(matched, page, page_size)
    names = {u["id"]: u["name"] for u in storage.get_all("users")}
    result["items"] = [dict(r, user_name=names.get(r["user_id"], "")) for r in result["items"]]
    return result


def update_review(review_id, data, actor):
    """แก้รีวิว: เจ้าของแก้ rating/comment ได้ / admin ซ่อน-แสดงรีวิวได้ด้วย field status"""
    if actor is None:
        raise unauthorized_error()
    record = storage.get_record("reviews", review_id)
    if record is None:
        raise not_found("รีวิว")
    is_owner = permissions.is_owner(actor, record["user_id"])
    is_mod = permissions.has_permission(actor, "review.moderate")
    if not (is_owner or is_mod):
        raise forbidden_error()

    changes = {}
    text_fields = {k: data[k] for k in ("rating", "artwork_rating", "artist_rating", "comment") if k in data}
    if text_fields:
        if not is_owner:
            raise forbidden_error()                    # admin ไม่แก้ถ้อยคำของลูกค้า
        clean, errors = validation.validate_review(text_fields, partial=True)
        if errors:
            raise validation_error(errors)
        changes.update(clean)
    if "status" in data:
        if not is_mod:
            raise forbidden_error()
        status = str(data["status"]).strip().upper()
        if status not in config.REVIEW_STATUSES:
            raise validation_error({"status": "status ต้องเป็น PUBLISHED หรือ HIDDEN"})
        changes["status"] = status
    if not changes:
        raise validation_error({"_": "ไม่มีข้อมูลที่ต้องแก้ไข"})

    changes["updated_at"] = now_iso()
    updated = storage.update_record("reviews", review_id, changes)
    refresh_ratings(record["artwork_id"])
    logger.create_audit_log(actor["id"], "REVIEW_UPDATED", "review", review_id,
                            {"fields": sorted(k for k in changes if k != "updated_at")})
    return updated


def delete_review(review_id, actor):
    """ลบรีวิว: เจ้าของหรือ admin"""
    if actor is None:
        raise unauthorized_error()
    record = storage.get_record("reviews", review_id)
    if record is None:
        raise not_found("รีวิว")
    if not (permissions.is_owner(actor, record["user_id"]) or permissions.has_permission(actor, "review.moderate")):
        raise forbidden_error()
    storage.delete_record("reviews", review_id)
    refresh_ratings(record["artwork_id"])
    logger.create_audit_log(actor["id"], "REVIEW_DELETED", "review", review_id, {})
    return {"deleted": True, "id": review_id}
