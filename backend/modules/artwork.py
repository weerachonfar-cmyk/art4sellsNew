"""artwork.py - Artwork CRUD + workflow อนุมัติ + Search / Filter / Sort / Pagination

Workflow สถานะ (ดูตารางใน config.ARTWORK_TRANSITIONS):
    DRAFT -> PENDING_APPROVAL -> APPROVED -> SOLD
                  |
                  +-> REJECTED -> (ศิลปินแก้) -> PENDING_APPROVAL
"""
import random

from backend import config
from backend.modules import category, logger, notification, permissions, references, storage, validation
from backend.modules.errors import (conflict_error, forbidden_error, not_found,
                                    unauthorized_error, validation_error)
from backend.modules.utils import now_iso, paginate

EDITABLE_FIELDS = ("title", "description", "category", "price", "sale_type", "tags")


# ---------------------------------------------------------------------------
# ฟังก์ชันช่วย
# ---------------------------------------------------------------------------
def _artist_names():
    """dict {user_id: ชื่อ} ไว้แสดงชื่อศิลปินและค้นหาตามชื่อศิลปิน"""
    return {u["id"]: u["name"] for u in storage.get_all("users")}


def _category_names():
    """dict {category_id: ชื่อหมวดหมู่}"""
    return {c["id"]: c["name"] for c in storage.get_all("categories")}


def can_view_artwork(actor, art):
    """ใครมองเห็นงานนี้ได้บ้าง
    - งานที่ APPROVED/SOLD: ทุกคน   - สถานะอื่น: เจ้าของงาน หรือ admin เท่านั้น
    """
    if art["status"] in config.PUBLIC_ARTWORK_STATUSES:
        return True
    if actor is None:
        return False
    if permissions.has_permission(actor, "artwork.manage_any"):
        return True
    return permissions.is_owner(actor, art["artist_id"])


def compute_availability(art, locked_ids):
    """สถานะการซื้อ: SOLD / PROCESSING (มีคนรอจ่ายเงินงาน LIMITED) / AVAILABLE / NOT_FOR_SALE"""
    if art["status"] == "SOLD":
        return "SOLD"
    if art["status"] not in ("APPROVED", "AVAILABLE"):
        return "NOT_FOR_SALE"
    if art["sale_type"] == "LIMITED" and art["id"] in locked_ids:
        return "PROCESSING"
    return "AVAILABLE"


def build_artwork_view(art, artist_names, category_names, locked_ids):
    """สร้างข้อมูลที่ส่งให้ client = ข้อมูลงาน + ชื่อศิลปิน + ชื่อหมวด + availability"""
    view = dict(art)
    view["artist_name"] = artist_names.get(art["artist_id"], "")
    view["category_name"] = category_names.get(art["category"], art["category"])
    view["availability"] = compute_availability(art, locked_ids or set())
    try:
        from backend.modules import promotion
        current_price, promo = promotion.get_price(art["price"], art["id"])
        view["current_price"] = current_price
        view["promotion"] = ({"id": promo["id"], "title": promo["title"], "type": promo["type"], "value": promo["value"]} if promo else None)
    except Exception:
        view["current_price"] = art["price"]
        view["promotion"] = None
    return view


def _get_record_or_404(artwork_id):
    art = storage.get_record("artworks", artwork_id)
    if art is None:
        raise not_found("Artwork")
    return art


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def get_artwork(artwork_id, actor=None, locked_ids=None):
    """ดูงานชิ้นเดียว  งานที่ยังไม่เผยแพร่ + ผู้ขอไม่มีสิทธิ์ -> ตอบ 404 (ไม่เผยว่ามีงานนี้อยู่)"""
    art = storage.get_record("artworks", artwork_id)
    if art is None or not can_view_artwork(actor, art):
        raise not_found("Artwork")
    return build_artwork_view(art, _artist_names(), _category_names(), locked_ids)


def search_artworks(artworks, text, search_in, artist_names):
    """ค้นหา: คืนเฉพาะงานที่ข้อความ text ตรงกับ title / ชื่อศิลปิน / tag (ตาม search_in)"""
    text = text.strip().lower()
    if not text:
        return artworks
    results = []
    for art in artworks:                               # for: วนดูทีละงาน
        title_hit = text in art["title"].lower()
        artist_hit = text in artist_names.get(art["artist_id"], "").lower()
        tag_hit = any(text in tag for tag in art["tags"])
        if search_in == "title":
            keep = title_hit
        elif search_in == "artist":
            keep = artist_hit
        elif search_in == "tag":
            keep = tag_hit
        else:                                          # "all"
            keep = title_hit or artist_hit or tag_hit or text in art["description"].lower()
        if keep:
            results.append(art)
    return results


def filter_artworks(artworks, filters, locked_ids):
    """กรองตามหมวด/ราคา/คะแนน/ประเภทขาย/ศิลปิน/ซื้อได้เลยหรือไม่"""
    results = []
    for art in artworks:
        if filters.get("category") and art["category"] != filters["category"]:
            continue
        if filters.get("artist_id") and art["artist_id"] != filters["artist_id"]:
            continue
        if filters.get("sale_type") and art["sale_type"] != filters["sale_type"]:
            continue
        if "min_price" in filters and art["price"] < filters["min_price"]:
            continue
        if "max_price" in filters and art["price"] > filters["max_price"]:
            continue
        if "min_rating" in filters and art["rating"] < filters["min_rating"]:
            continue
        if filters.get("available") and compute_availability(art, locked_ids) != "AVAILABLE":
            continue
        results.append(art)
    return results


def sort_artworks(artworks, sort_key):
    """เรียงลำดับตามชื่อ sort ใน config.SORT_OPTIONS (เสมอกันให้เรียงตาม id เพื่อให้ผลคงที่)"""
    field, descending = config.SORT_OPTIONS[sort_key]  # แกะ tuple
    return sorted(artworks, key=lambda a: (a[field], a["id"]), reverse=descending)


def _select_visible(filters, actor):
    """เลือกชุดงานที่ผู้เรียกมีสิทธิ์เห็น ตามพารามิเตอร์ status / mine / submitted"""
    artworks = storage.get_all("artworks")
    is_admin = permissions.has_permission(actor, "artwork.manage_any")

    if filters.get("mine"):
        if actor is None:
            raise unauthorized_error()
        return [a for a in artworks if a["artist_id"] == actor["id"]]

    if filters.get("submitted"):
        permissions.check_permission(actor, "artwork.approve")
        return [a for a in artworks if a.get("submitted_at")]

    wanted_status = filters.get("status")
    if wanted_status:
        if wanted_status not in config.PUBLIC_ARTWORK_STATUSES and not is_admin:
            raise forbidden_error()
        return [a for a in artworks if a["status"] == wanted_status]

    return [a for a in artworks if a["status"] in config.PUBLIC_ARTWORK_STATUSES]


def list_artworks(query, actor=None, locked_ids=None):
    """GET /api/artworks : ค้นหา + กรอง + เรียง + แบ่งหน้า (ทำงานฝั่ง backend)

    query = dict จาก query string เช่น {"q": "fox", "category": "3d-art", "sort": "price_asc", "page": "2"}
    คืนค่า: {"items": [...], "page": 1, "page_size": 12, "total": 100, "total_pages": 9}
    """
    filters, errors = validation.validate_artwork_filters(query)
    page, page_size, page_errors = validation.validate_page_params(query)
    errors.update(page_errors)
    if errors:
        raise validation_error(errors)

    locked_ids = locked_ids or set()
    artist_names = _artist_names()
    category_names = _category_names()

    items = _select_visible(filters, actor)
    items = search_artworks(items, filters["q"], filters["search_in"], artist_names)
    items = filter_artworks(items, filters, locked_ids)
    items = sort_artworks(items, filters["sort"])
    result = paginate(items, page, page_size)
    result["items"] = [build_artwork_view(a, artist_names, category_names, locked_ids) for a in result["items"]]
    return result


# ---------------------------------------------------------------------------
# Create / Update / Delete
# ---------------------------------------------------------------------------
def ensure_artist_exists(artist_id):
    """ตรวจว่าศิลปินมีอยู่จริง, เป็น role ARTIST และบัญชียังใช้งานได้ (ไม่งั้น raise)"""
    record = storage.get_record("users", artist_id)
    if record is None or record["role"] != "ARTIST" or record["status"] != "ACTIVE":
        raise validation_error({"artist_id": "ไม่พบศิลปินที่ใช้งานได้"})
    return record


def create_artwork(data, actor):
    """สร้างงานใหม่ (สถานะเริ่มต้น DRAFT) - เฉพาะ ARTIST และงานเป็นของคนที่ login อยู่เสมอ"""
    permissions.check_permission(actor, "artwork.create")
    ensure_artist_exists(actor["id"])
    clean, errors = validation.validate_artwork(data, category.get_category_ids())
    if errors:
        raise validation_error(errors)

    now = now_iso()
    record = dict(clean)
    record.update({
        "artist_id": actor["id"],
        "rating": 0.0,
        "status": "DRAFT",
        "preview_seed": random.randrange(8),
        "created_at": now,
        "updated_at": now,
        "submitted_at": None,
        "reviewed_by": None,
        "reject_reason": None,
    })
    storage.create_record("artworks", record, "w")
    logger.create_audit_log(actor["id"], "ARTWORK_CREATED", "artwork", record["id"], {"title": record["title"]})
    return record


def update_artwork(artwork_id, data, actor):
    """แก้ไขงาน (รับเฉพาะ field ใน EDITABLE_FIELDS - ส่ง status/artist_id มาจะถูกเมินเพื่อกันการแอบแก้)
    - ศิลปิน: แก้ได้เฉพาะงานตัวเองที่เป็น DRAFT หรือ REJECTED
    - admin : แก้ได้ทุกงานที่ยังไม่ SOLD
    """
    if actor is None:
        raise unauthorized_error()
    art = _get_record_or_404(artwork_id)
    is_admin = permissions.has_permission(actor, "artwork.manage_any")
    is_own = permissions.has_permission(actor, "artwork.edit_own") and permissions.is_owner(actor, art["artist_id"])
    if not (is_admin or is_own):
        raise forbidden_error()

    if is_admin:
        locked = art["status"] == "SOLD"
    else:
        locked = art["status"] not in config.ARTIST_EDITABLE_STATUSES
    if locked:
        raise conflict_error("ARTWORK_LOCKED", "แก้ไขงานในสถานะ " + art["status"] + " ไม่ได้")

    incoming = {field: data[field] for field in EDITABLE_FIELDS if field in data}
    if not incoming:
        raise validation_error({"_": "ไม่มีข้อมูลที่ต้องแก้ไข"})
    clean, errors = validation.validate_artwork(incoming, category.get_category_ids(), partial=True)
    if errors:
        raise validation_error(errors)

    clean["updated_at"] = now_iso()
    old_price = art.get("price")
    updated = storage.update_record("artworks", artwork_id, clean)
    if "price" in clean:
        from backend.modules import promotion
        history = promotion.record_price_change(artwork_id, old_price, clean["price"], actor["id"])
        if history and clean["price"] < old_price:
            for wish in storage.get_all("wishlists"):
                if wish.get("artwork_id") == artwork_id:
                    notification.notify(wish.get("user_id"), "PRICE_DROP", "ราคา \"" + art["title"] + "\" ลดจาก " + str(old_price) + " เป็น " + str(clean["price"]))
    logger.create_audit_log(actor["id"], "ARTWORK_UPDATED", "artwork", artwork_id,
                            {"fields": sorted(k for k in clean if k != "updated_at")})
    return updated


def delete_artwork(artwork_id, actor):
    """ลบงาน: เจ้าของหรือ admin - ลบไม่ได้ถ้ามีคำสั่งซื้อเกี่ยวข้อง (เพื่อรักษาประวัติการซื้อขาย)"""
    if actor is None:
        raise unauthorized_error()
    art = _get_record_or_404(artwork_id)
    is_admin = permissions.has_permission(actor, "artwork.manage_any")
    is_own = permissions.has_permission(actor, "artwork.delete_own") and permissions.is_owner(actor, art["artist_id"])
    if not (is_admin or is_own):
        raise forbidden_error()

    for order in storage.get_all("orders"):
        for item in order["items"]:
            if item["artwork_id"] == artwork_id:
                raise conflict_error("ARTWORK_IN_USE", "ลบไม่ได้ เพราะมีคำสั่งซื้อที่เกี่ยวข้อง")

    storage.delete_record("artworks", artwork_id)
    references.purge_artwork_references(artwork_id)
    references.purge_artwork_files(artwork_id)         # ลบไฟล์ภาพ (original/preview/delivery) ที่ผูกกับงานนี้ด้วย    # ล้างตะกร้า/wishlist ที่ชี้ไปยังงานนี้ ไม่ให้เหลือ reference ลอย
    logger.create_audit_log(actor["id"], "ARTWORK_DELETED", "artwork", artwork_id, {"title": art["title"]})
    return {"deleted": True, "id": artwork_id}


# ---------------------------------------------------------------------------
# Workflow อนุมัติ
# ---------------------------------------------------------------------------
def _change_status(art, new_status, changes):
    """เปลี่ยนสถานะตามตารางกติกา ถ้าไปไม่ได้ raise 409  คืน record ใหม่"""
    if not validation.can_transition(art["status"], new_status, config.ARTWORK_TRANSITIONS):
        raise conflict_error("INVALID_TRANSITION",
                             "เปลี่ยนสถานะจาก " + art["status"] + " เป็น " + new_status + " ไม่ได้")
    changes = dict(changes)
    changes["status"] = new_status
    changes["updated_at"] = now_iso()
    return storage.update_record("artworks", art["id"], changes)


def submit_artwork(artwork_id, actor):
    """ศิลปินส่งงานของตัวเองขออนุมัติ: DRAFT/REJECTED -> PENDING_APPROVAL"""
    permissions.check_permission(actor, "artwork.submit")
    art = _get_record_or_404(artwork_id)
    if not permissions.is_owner(actor, art["artist_id"]):
        raise forbidden_error()
    updated = _change_status(art, "PENDING_APPROVAL",
                             {"submitted_at": now_iso(), "reject_reason": None})
    logger.create_audit_log(actor["id"], "ARTWORK_SUBMITTED", "artwork", artwork_id, {})
    return updated


def approve_artwork(artwork_id, actor):
    """admin อนุมัติ: PENDING_APPROVAL -> APPROVED"""
    permissions.check_permission(actor, "artwork.approve")
    art = _get_record_or_404(artwork_id)
    updated = _change_status(art, "APPROVED", {"reviewed_by": actor["id"], "reject_reason": None})
    logger.create_audit_log(actor["id"], "ARTWORK_APPROVED", "artwork", artwork_id, {})
    notification.notify(art["artist_id"], "ARTWORK_APPROVED", "งาน \"" + art["title"] + "\" ได้รับการอนุมัติแล้ว")
    for follow in storage.get_all("follows"):
        if follow.get("artist_id") == art["artist_id"]:
            notification.notify(follow.get("user_id"), "NEW_ARTWORK", "ศิลปินที่คุณติดตามเผยแพร่ \"" + art["title"] + "\"")
    return updated


def reject_artwork(artwork_id, actor, data=None):
    """admin ปฏิเสธ: PENDING_APPROVAL -> REJECTED (ใส่เหตุผลได้ ไม่เกิน 300 ตัวอักษร)"""
    permissions.check_permission(actor, "artwork.approve")
    art = _get_record_or_404(artwork_id)
    reason = str((data or {}).get("reason") or "").strip()
    if len(reason) > 300:
        raise validation_error({"reason": "เหตุผลยาวเกินไป (ไม่เกิน 300 ตัวอักษร)"})
    updated = _change_status(art, "REJECTED", {"reviewed_by": actor["id"], "reject_reason": reason or None})
    logger.create_audit_log(actor["id"], "ARTWORK_REJECTED", "artwork", artwork_id, {"reason": reason})
    notification.notify(art["artist_id"], "ARTWORK_REJECTED", "งาน \"" + art["title"] + "\" ไม่ผ่านการอนุมัติ")
    return updated


def mark_artwork_sold(artwork_id, actor_id):
    """(ใช้ภายใน) order.py เรียกเมื่อออเดอร์ถูกจ่ายเงินแล้ว: APPROVED -> SOLD (เฉพาะงาน LIMITED)"""
    art = storage.get_record("artworks", artwork_id)
    if art is None or art["sale_type"] != "LIMITED" or art["status"] not in ("APPROVED", "AVAILABLE"):
        return None
    updated = _change_status(art, "SOLD", {})
    logger.create_audit_log(actor_id, "ARTWORK_SOLD", "artwork", artwork_id, {})
    return updated
