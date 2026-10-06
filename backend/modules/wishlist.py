"""wishlist.py - งานโปรดของ user  ผูกกับ user_id และกัน record ซ้ำ (user_id, artwork_id)"""
from backend import config
from backend.modules import artwork, order, permissions, storage, validation
from backend.modules.errors import conflict_error, not_found, validation_error
from backend.modules.utils import now_iso

ADD_FIELDS = ("artwork_id",)


def list_wishlist(actor):
    """GET /api/wishlist : ของฉันเท่านั้น  คืน {"items": [{"id", "artwork_id", "created_at", "artwork"}]}"""
    permissions.check_permission(actor, "wishlist.use")
    locked_ids = order.get_locked_artwork_ids()
    artists = {u["id"]: u["name"] for u in storage.get_all("users")}
    cats = {c["id"]: c["name"] for c in storage.get_all("categories")}
    items = []
    for entry in storage.get_all("wishlists"):
        if entry["user_id"] != actor["id"]:
            continue
        art = storage.get_record("artworks", entry["artwork_id"])
        if art is not None:
            items.append({"id": entry["id"], "artwork_id": art["id"], "created_at": entry["created_at"],
                          "artwork": artwork.build_artwork_view(art, artists, cats, locked_ids)})
    items.reverse()
    return {"items": items}


def add_to_wishlist(data, actor):
    """POST /api/wishlist  body: {"artwork_id"}  คืน {"item", "created"}  (เพิ่มซ้ำ = ไม่สร้าง record ใหม่)"""
    permissions.check_permission(actor, "wishlist.use")
    body = validation.pick_fields(data, ADD_FIELDS)
    problem = validation.validate_id(body.get("artwork_id"), "artwork_id")
    if problem:
        raise validation_error({"artwork_id": problem})
    with storage.transaction():
        art = storage.get_record("artworks", body["artwork_id"])
        if art is None or art["status"] not in config.PUBLIC_ARTWORK_STATUSES:
            raise not_found("Artwork")
        if art["status"] == "SOLD":
            raise conflict_error("ARTWORK_SOLD", "งานนี้ขายไปแล้ว")
        mine = [w for w in storage.get_all("wishlists") if w["user_id"] == actor["id"]]
        for entry in mine:
            if entry["artwork_id"] == art["id"]:
                return {"item": entry, "created": False}
        if len(mine) >= config.MAX_WISHLIST_ITEMS:
            raise conflict_error("WISHLIST_FULL", "รายการโปรดเต็ม")
        entry = {"user_id": actor["id"], "artwork_id": art["id"], "created_at": now_iso()}
        return {"item": storage.create_record("wishlists", entry, "f"), "created": True}


def remove_from_wishlist(item_id, actor):
    """DELETE /api/wishlist/:id (เฉพาะของตัวเอง)"""
    permissions.check_permission(actor, "wishlist.use")
    entry = permissions.get_owned_record("wishlists", item_id, actor, "รายการโปรด")
    storage.delete_record("wishlists", entry["id"])
    return {"deleted": True, "id": entry["id"]}
