"""follow.py - ติดตามศิลปิน  ผูกกับ user_id และกัน record ซ้ำ (user_id, artist_id)"""
from backend.modules import permissions, storage, validation
from backend.modules.errors import conflict_error, not_found, validation_error
from backend.modules.utils import now_iso

ADD_FIELDS = ("artist_id",)


def list_follows(actor):
    """GET /api/follows : ศิลปินที่ฉันติดตาม"""
    permissions.check_permission(actor, "follow.use")
    names = {u["id"]: u["name"] for u in storage.get_all("users")}
    items = [{"id": f["id"], "artist_id": f["artist_id"], "artist_name": names.get(f["artist_id"], ""),
              "created_at": f["created_at"]}
             for f in storage.get_all("follows") if f["user_id"] == actor["id"]]
    return {"items": items}


def follow_artist(data, actor):
    """POST /api/follows  body: {"artist_id"}  คืน {"item", "created"}"""
    permissions.check_permission(actor, "follow.use")
    body = validation.pick_fields(data, ADD_FIELDS)
    problem = validation.validate_id(body.get("artist_id"), "artist_id")
    if problem:
        raise validation_error({"artist_id": problem})
    with storage.transaction():
        artist = storage.get_record("users", body["artist_id"])
        if artist is None or artist["role"] != "ARTIST" or artist["status"] != "ACTIVE":
            raise not_found("ศิลปิน")
        if artist["id"] == actor["id"]:
            raise conflict_error("OWN_PROFILE", "ติดตามตัวเองไม่ได้")
        for entry in storage.get_all("follows"):
            if entry["user_id"] == actor["id"] and entry["artist_id"] == artist["id"]:
                return {"item": entry, "created": False}
        entry = {"user_id": actor["id"], "artist_id": artist["id"], "created_at": now_iso()}
        return {"item": storage.create_record("follows", entry, "fl"), "created": True}


def unfollow(item_id, actor):
    """DELETE /api/follows/:id (เฉพาะของตัวเอง)"""
    permissions.check_permission(actor, "follow.use")
    entry = permissions.get_owned_record("follows", item_id, actor, "รายการติดตาม")
    storage.delete_record("follows", entry["id"])
    return {"deleted": True, "id": entry["id"]}
