"""cart.py - ตะกร้าสินค้าของ user (Backend เป็น source of truth)

- ทุกรายการมี user_id เจ้าของ  ตัดสินจาก session ฝั่ง server เสมอ (user_id ที่ client ส่งมาถูกทิ้ง)
- ยังไม่ login = ทำอะไรกับตะกร้าไม่ได้ (401)  ไม่มีตะกร้าของคนไม่ล็อกอิน และไม่มีการ merge
- ก่อนเพิ่มของ ตรวจว่างานมีอยู่จริง/อนุมัติแล้ว/ยังซื้อได้/ไม่ใช่งานของตัวเอง
"""
from backend import config
from backend.modules import artwork, order, permissions, storage, validation
from backend.modules.errors import conflict_error, not_found, unauthorized_error, validation_error
from backend.modules.utils import now_iso

ADD_FIELDS = ("artwork_id", "quantity")        # allowlist: field อื่น (user_id, price ฯลฯ) ถูกทิ้ง
UPDATE_FIELDS = ("quantity",)


def _my_lines(actor):
    return [line for line in storage.get_all("carts") if line["user_id"] == actor["id"]]


def _require_login(actor):
    if actor is None:
        raise unauthorized_error()


def _quantity_from(data, default=1):
    """อ่าน quantity จาก body  คืน int 1..MAX_ORDER_QUANTITY หรือ raise 400"""
    quantity, problem = validation.validate_quantity(data.get("quantity", default))
    if problem:
        raise validation_error({"quantity": problem})
    return quantity


def build_cart_view(actor):
    """ข้อมูลตะกร้าของ actor: รายการ (พร้อมข้อมูลงานล่าสุดจาก server) + ยอดรวมที่ server คำนวณเอง"""
    _require_login(actor)
    locked_ids = order.get_locked_artwork_ids()
    artists = {u["id"]: u["name"] for u in storage.get_all("users")}
    cats = {c["id"]: c["name"] for c in storage.get_all("categories")}
    items, total, count = [], 0.0, 0
    for line in _my_lines(actor):
        art = storage.get_record("artworks", line["artwork_id"])
        if art is None:
            continue                                   # งานหายไปแล้ว (ปกติถูกล้างพร้อมการลบงาน)
        view = artwork.build_artwork_view(art, artists, cats, locked_ids)
        purchasable = view["availability"] == "AVAILABLE"
        line_total = round(art["price"] * line["quantity"], 2)
        items.append({"id": line["id"], "artwork_id": art["id"], "quantity": line["quantity"],
                      "created_at": line["created_at"], "updated_at": line["updated_at"],
                      "artwork": view, "line_total": line_total, "purchasable": purchasable})
        count += line["quantity"]
        if purchasable:
            total += line_total
    return {"items": items, "count": count, "total": round(total, 2)}


def _check_can_add(art, actor):
    """ตรวจว่า actor เพิ่มงานนี้ลงตะกร้าได้หรือไม่ (ไม่ได้ -> raise)"""
    if art is None or art["status"] not in config.PUBLIC_ARTWORK_STATUSES:
        raise not_found("Artwork")                     # ไม่มีจริง หรือยังไม่เผยแพร่/ไม่ผ่านอนุมัติ
    if art["status"] == "SOLD":
        raise conflict_error("ARTWORK_SOLD", "งานนี้ขายไปแล้ว")
    if permissions.is_owner(actor, art["artist_id"]):
        raise conflict_error("OWN_ARTWORK", "ซื้องานของตัวเองไม่ได้")
    if art["sale_type"] == "LIMITED" and art["id"] in order.get_locked_artwork_ids():
        raise conflict_error("ARTWORK_LOCKED", "งานนี้มีผู้ซื้ออื่นกำลังชำระเงินอยู่")


def add_to_cart(data, actor):
    """POST /api/cart  body: {"artwork_id", "quantity"?}
    คืน dict {"item": ..., "created": True/False}  (งาน LIMITED ที่อยู่ในตะกร้าแล้ว = ไม่เพิ่มซ้ำ)
    """
    permissions.check_permission(actor, "cart.use")
    body = validation.pick_fields(data, ADD_FIELDS)
    problem = validation.validate_id(body.get("artwork_id"), "artwork_id")
    if problem:
        raise validation_error({"artwork_id": problem})
    quantity = _quantity_from(body)

    with storage.transaction():                        # ตรวจ + เขียน ต้องเสร็จทีละคำขอ (กัน record ซ้ำ)
        art = storage.get_record("artworks", body["artwork_id"])
        _check_can_add(art, actor)
        lines = _my_lines(actor)
        existing = next((l for l in lines if l["artwork_id"] == art["id"]), None)
        now = now_iso()
        if existing is not None:
            if art["sale_type"] == "LIMITED":
                return {"item": existing, "created": False}
            new_quantity = existing["quantity"] + quantity
            if new_quantity > config.MAX_ORDER_QUANTITY:
                raise validation_error({"quantity": "จำนวนรวมต้องไม่เกิน " + str(config.MAX_ORDER_QUANTITY)})
            return {"item": storage.update_record("carts", existing["id"],
                                                 {"quantity": new_quantity, "updated_at": now}), "created": False}
        if len(lines) >= config.MAX_CART_LINES:
            raise conflict_error("CART_FULL", "ตะกร้าเต็ม (สูงสุด " + str(config.MAX_CART_LINES) + " รายการ)")
        if art["sale_type"] == "LIMITED":
            quantity = 1
        line = {"user_id": actor["id"], "artwork_id": art["id"], "quantity": quantity,
                "created_at": now, "updated_at": now}
        return {"item": storage.create_record("carts", line, "c"), "created": True}


def update_item(item_id, data, actor):
    """PUT /api/cart/:id  body: {"quantity"}  (เฉพาะรายการของตัวเอง)"""
    permissions.check_permission(actor, "cart.use")
    line = permissions.get_owned_record("carts", item_id, actor, "รายการในตะกร้า")
    body = validation.pick_fields(data, UPDATE_FIELDS)
    quantity = _quantity_from(body, default=None)
    art = storage.get_record("artworks", line["artwork_id"])
    if art is None:
        raise not_found("Artwork")
    if art["sale_type"] == "LIMITED" and quantity != 1:
        raise validation_error({"quantity": "งาน LIMITED ซื้อได้ครั้งละ 1 ชิ้น"})
    return storage.update_record("carts", line["id"], {"quantity": quantity, "updated_at": now_iso()})


def remove_item(item_id, actor):
    """DELETE /api/cart/:id"""
    permissions.check_permission(actor, "cart.use")
    line = permissions.get_owned_record("carts", item_id, actor, "รายการในตะกร้า")
    storage.delete_record("carts", line["id"])
    return {"deleted": True, "id": line["id"]}


def clear_cart(actor):
    """DELETE /api/cart : ล้างตะกร้าของตัวเอง"""
    permissions.check_permission(actor, "cart.use")
    removed = storage.delete_where("carts", "user_id", actor["id"])
    return {"deleted": removed}


def checkout(actor):
    """POST /api/cart/checkout : สร้างคำสั่งซื้อจากตะกร้าของตัวเอง (ราคา/ความพร้อมตรวจที่ order.create_order) แล้วล้างตะกร้า"""
    permissions.check_permission(actor, "cart.use")
    with storage.transaction():
        lines = _my_lines(actor)
        if not lines:
            raise validation_error({"cart": "ตะกร้าว่าง"}, "ตะกร้าว่าง")
        items = [{"artwork_id": l["artwork_id"], "quantity": l["quantity"]} for l in lines]
        created = order.create_order({"items": items}, actor)     # ล้มเหลว (เช่น งานถูกล็อก) = ตะกร้าคงเดิม
        storage.delete_where("carts", "user_id", actor["id"])
    return created
