"""artwork_files.py - ไฟล์ของงานศิลปะ: อัปโหลด / ลายน้ำ / ดูตัวอย่าง / ดาวน์โหลดหลังชำระเงิน

ไฟล์ 3 แบบต่องาน 1 ชิ้น (เก็บเป็น 3 object แยกกัน):
    original   ไฟล์ต้นฉบับ "ไม่ถูกแก้ไขแม้แต่ไบต์เดียว"   เห็นได้เฉพาะเจ้าของงาน/admin
    preview    สำเนาที่ใส่ลายน้ำ (ย่อให้เล็กลง)            ใครก็เห็นได้เมื่องานถูกเผยแพร่ (APPROVED/SOLD)
    delivery   ไฟล์ที่ส่งมอบให้ผู้ซื้อ (สำเนาของ original)     ดาวน์โหลดได้เมื่อ "ล็อกอิน + เป็นเจ้าของออเดอร์ + ชำระเงินยืนยันแล้ว + งานอยู่ในออเดอร์นั้น" เท่านั้น
ลายน้ำใช้กับ preview เท่านั้น  (ใช้ Pillow - ถ้าไม่มี Pillow ระบบ "ไม่ยอมรับอัปโหลด" แทนที่จะเอา original ไปเป็น preview)
Metadata (collection "files"): storage_provider, blob_path (ภายใน ไม่ส่งให้ client), content_type, size, owner_id, created_at
"""
import base64
import binascii
import hashlib
import io
import warnings

from backend import config
from backend.modules import file_storage, logger, permissions, storage, uploads, validation
from backend.modules.artwork import can_view_artwork
from backend.modules.errors import (AppError, conflict_error, forbidden_error, not_found, unauthorized_error,
                                    validation_error)
from backend.modules.utils import now_iso

PREVIEW_MAX_SIDE = 900                                 # preview ย่อให้ด้านยาวสุดไม่เกินนี้ (ไม่ส่งภาพความละเอียดเต็มให้คนทั่วไป)
MAX_IMAGE_PIXELS = 40_000_000                          # กัน "decompression bomb" (ไฟล์เล็กแต่ภาพใหญ่มหาศาล)
WATERMARK_TEXT = "ART 4 SELLS - PREVIEW"
UPLOAD_FIELDS = ("filename", "content_type", "data_base64")
EXTENSION_FOR_TYPE = {"png": "png", "jpg": "jpg", "webp": "webp"}
PIL_FORMAT = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}
CONTENT_TYPE = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


class FileResponse:
    """ผลลัพธ์แบบไฟล์ (binary) ที่ handler คืนแทน dict - ชั้น transport ส่งเป็นไบต์ตรง ๆ"""

    def __init__(self, content, content_type, filename=None, private=True):
        self.content = content
        self.content_type = content_type
        self.filename = filename
        self.private = private                         # private=True -> ห้ามให้ cache / proxy เก็บ


def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont     # noqa: F401
    except ImportError:
        raise AppError("WATERMARK_UNAVAILABLE", "ระบบสร้างลายน้ำยังไม่พร้อมใช้งาน จึงยังรับอัปโหลดไม่ได้", 503)
    import PIL.Image
    PIL.Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    return PIL


def decode_image(data, image_type):
    """เปิดไฟล์ด้วย Pillow จริง ๆ เพื่อตรวจว่าเป็นรูปที่ถอดรหัสได้ (ไม่เชื่อแค่ magic bytes)  คืน Image หรือ raise validation_error
    ตรวจ "จำนวนพิกเซล" จาก header ก่อนถอดรหัส (ไฟล์เล็กแต่ภาพใหญ่มหาศาล = decompression bomb จะกินหน่วยความจำของ Function)"""
    PIL = _pillow()
    too_large = validation_error({"file": "ภาพมีขนาดพิกเซลใหญ่เกินกำหนด"})
    broken = validation_error({"file": "ไฟล์ภาพเสียหายหรือไม่สามารถเปิดได้"})
    try:
        warnings.simplefilter("ignore", PIL.Image.DecompressionBombWarning)   # เราตรวจจำนวนพิกเซลเองด้านล่าง ไม่ต้องให้ Pillow พิมพ์คำเตือน
        with PIL.Image.open(io.BytesIO(data)) as probe:    # ขั้น 1: อ่านเฉพาะ header (ยังไม่ถอดรหัสพิกเซล)
            if probe.width * probe.height > MAX_IMAGE_PIXELS:
                raise too_large
            probe.verify()                                 # โครงสร้างไฟล์ถูกต้อง
        image = PIL.Image.open(io.BytesIO(data))
        image.load()                                       # ขั้น 2: ถอดรหัสพิกเซลจริง
    except AppError:
        raise
    except (OSError, ValueError, SyntaxError, PIL.Image.DecompressionBombError):
        raise broken
    if image.width < 1 or image.height < 1 or image.format != PIL_FORMAT[image_type]:
        raise validation_error({"file": "เนื้อไฟล์ไม่ตรงกับนามสกุลที่ระบุ"})
    return image


def make_watermarked_preview(image, image_type):
    """สร้าง preview: ย่อขนาด + พิมพ์ลายน้ำข้อความซ้ำทแยงมุมทั่วภาพ  ไม่แตะ original  คืน bytes"""
    PIL = _pillow()
    from PIL import ImageDraw, ImageFont
    base = image.convert("RGBA")
    base.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
    layer = PIL.Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.load_default(size=max(14, base.width // 18))
    text_width = int(font.getlength(WATERMARK_TEXT))
    step_x = text_width + max(30, text_width // 3)       # เว้นช่องไฟตามความกว้างข้อความจริง ไม่ให้ข้อความซ้อนทับกัน
    step_y = max(40, base.height // 5)
    for row, y in enumerate(range(-step_y, base.height + step_y, step_y)):
        offset = (row % 2) * (step_x // 2)
        for x in range(-base.width, base.width * 2, step_x):
            draw.text((x + offset, y), WATERMARK_TEXT, fill=(255, 255, 255, 120), font=font,
                      stroke_width=1, stroke_fill=(0, 0, 0, 90))
    marked = PIL.Image.alpha_composite(base, layer.rotate(25, resample=PIL.Image.BICUBIC))
    out = io.BytesIO()
    if image_type == "jpg":
        marked.convert("RGB").save(out, "JPEG", quality=80)
    elif image_type == "webp":
        marked.save(out, "WEBP", quality=80)
    else:
        marked.save(out, "PNG")
    return out.getvalue()


def _public_file(record):
    """ข้อมูลไฟล์ที่ส่งให้ client ได้ (ไม่มี blob_path / storage_provider ภายใน)"""
    return {"id": record["id"], "artwork_id": record["artwork_id"], "role": record["role"],
            "content_type": record["content_type"], "size": record["size"], "created_at": record["created_at"]}


def _get_artwork_or_404(artwork_id):
    problem = validation.validate_id(artwork_id, "id")
    if problem:
        raise validation_error({"id": problem})
    art = storage.get_record("artworks", artwork_id)
    if art is None:
        raise not_found("Artwork")
    return art


def _can_manage(actor, art):
    return permissions.has_permission(actor, "artwork.manage_any") or (
        permissions.has_permission(actor, "artwork.edit_own") and permissions.is_owner(actor, art["artist_id"]))


def _files_of(artwork_id):
    return storage.find_records("files", "artwork_id", artwork_id)


def _file_of(artwork_id, role):
    for record in _files_of(artwork_id):
        if record["role"] == role:
            return record
    return None


def decode_upload_body(data):
    """ตรวจ body ของคำขออัปโหลด คืน (filename, content_type, bytes)  base64 ต้องถูกต้องเคร่งครัด (validate=True) และขนาดไม่เกิน"""
    body = validation.pick_fields(data, UPLOAD_FIELDS)
    encoded = body.get("data_base64")
    if not isinstance(encoded, str) or not encoded:
        raise validation_error({"data_base64": "ไม่พบข้อมูลไฟล์"})
    if len(encoded) > (config.MAX_UPLOAD_BYTES * 4) // 3 + 8:          # เช็คขนาดก่อนถอดรหัส ไม่ให้เปลืองหน่วยความจำ
        raise AppError("PAYLOAD_TOO_LARGE", "ไฟล์มีขนาดใหญ่เกินกำหนด", 413)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise validation_error({"data_base64": "ข้อมูลไฟล์ไม่ถูกต้อง"})
    return body.get("filename"), body.get("content_type"), raw


def upload_artwork_file(artwork_id, data, actor):
    """POST /api/artworks/:id/file  - เจ้าของงาน (ศิลปิน) หรือ admin อัปโหลดไฟล์ภาพของงาน
    ขั้นตอน: ตรวจสิทธิ์ -> ตรวจ metadata + magic bytes + โค้ดแฝง -> ถอดรหัสด้วย Pillow -> สร้าง preview ลายน้ำ -> เก็บ 3 ไฟล์ -> บันทึก metadata
    ศิลปินอัปโหลดแทนที่ได้เฉพาะงานสถานะ DRAFT/REJECTED (เหมือนการแก้ข้อมูลงาน)  ไฟล์เก่าถูกลบเมื่อบันทึกไฟล์ใหม่สำเร็จ
    """
    if actor is None:
        raise unauthorized_error()
    art = _get_artwork_or_404(artwork_id)
    if not _can_manage(actor, art):
        raise forbidden_error()
    is_admin = permissions.has_permission(actor, "artwork.manage_any")
    if art["status"] == "SOLD" or (not is_admin and art["status"] not in config.ARTIST_EDITABLE_STATUSES):
        raise conflict_error("ARTWORK_LOCKED", "ไม่สามารถเปลี่ยนไฟล์ของงานในสถานะนี้ได้")

    filename, content_type, raw = decode_upload_body(data)
    clean, errors = uploads.validate_upload(filename, content_type, raw)
    if errors:
        raise validation_error(errors)
    image_type = clean["detected_type"]
    image = decode_image(raw, image_type)
    preview_bytes = make_watermarked_preview(image, image_type)
    extension = EXTENSION_FOR_TYPE[image_type]
    mime = CONTENT_TYPE[image_type]
    owner_id = art["artist_id"]

    store = file_storage.get_store()
    created_paths = []
    try:
        new_records = []
        for role, content in (("original", raw), ("preview", preview_bytes), ("delivery", raw)):
            path = store.put(role, content, extension, mime)
            created_paths.append(path)
            new_records.append({"artwork_id": art["id"], "owner_id": owner_id, "role": role,
                                "storage_provider": store.name, "blob_path": path, "content_type": mime,
                                "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                                "created_at": now_iso()})
        with storage.transaction():
            old = _files_of(art["id"])
            for record in new_records:
                storage.create_record("files", record, "f")
            for record in old:
                storage.delete_record("files", record["id"])
    except Exception:
        for path in created_paths:                      # ล้มกลางทาง: เก็บกวาดไฟล์ที่เพิ่งเขียน ไม่ให้เหลือไฟล์กำพร้า
            store.delete(path)
        raise
    for record in old:
        _delete_stored(record)
    logger.create_audit_log(actor["id"], "ARTWORK_FILE_UPLOADED", "artwork", art["id"],
                            {"size": len(raw), "type": image_type})
    return {"artwork_id": art["id"], "files": [_public_file(r) for r in new_records]}


def _delete_stored(record):
    try:
        file_storage.get_store().delete(record["blob_path"])
    except Exception:
        pass


def delete_files_of_artwork(artwork_id):
    """ลบไฟล์ทั้งหมดของงาน (ใช้ตอนลบงาน) คืนจำนวน record ที่ลบ"""
    records = _files_of(artwork_id)
    for record in records:
        _delete_stored(record)
    return storage.delete_where("files", "artwork_id", artwork_id)


def purge_all_files():
    """ลบไฟล์ภาพทั้งหมด (ใช้ตอน Reset Demo Data) คืนจำนวนที่ลบ"""
    records = storage.get_all("files")
    for record in records:
        _delete_stored(record)
    return len(records)


def list_artwork_files(artwork_id, actor):
    """GET /api/artworks/:id/files - รายการไฟล์ (เฉพาะเจ้าของงาน/admin) ไม่มี blob_path"""
    if actor is None:
        raise unauthorized_error()
    art = _get_artwork_or_404(artwork_id)
    if not _can_manage(actor, art):
        raise forbidden_error()
    return {"items": [_public_file(r) for r in _files_of(art["id"])]}


def _serve(record, filename_hint):
    content = file_storage.get_store().get(record["blob_path"])
    return FileResponse(content, record["content_type"], filename_hint, private=True)


def get_preview(artwork_id, actor):
    """GET /api/artworks/:id/preview - ไฟล์ตัวอย่างที่ใส่ลายน้ำแล้ว  เปิดได้เมื่อเห็นงานนี้ได้ (งานเผยแพร่แล้ว หรือเป็นเจ้าของ/admin)
    ไม่มีทางเอา original ออกมาทาง endpoint นี้ - ไม่พบ preview = 404"""
    art = _get_artwork_or_404(artwork_id)
    if not can_view_artwork(actor, art):
        raise not_found("Artwork")                      # งานที่ยังไม่เผยแพร่ ไม่เผยว่ามีอยู่จริง
    record = _file_of(art["id"], "preview")
    if record is None:
        raise not_found("ไฟล์ตัวอย่าง")
    response = _serve(record, None)
    response.private = art["status"] not in config.PUBLIC_ARTWORK_STATUSES
    return response


def get_original(artwork_id, actor):
    """GET /api/artworks/:id/original - ไฟล์ต้นฉบับ: เจ้าของงานหรือ admin เท่านั้น (ไม่ใช่ public URL)"""
    if actor is None:
        raise unauthorized_error()
    art = _get_artwork_or_404(artwork_id)
    if not _can_manage(actor, art):
        raise forbidden_error()
    record = _file_of(art["id"], "original")
    if record is None:
        raise not_found("ไฟล์ต้นฉบับ")
    return _serve(record, "original-" + art["id"] + "." + record["content_type"].split("/")[1].replace("jpeg", "jpg"))


def download_delivery(order_id, artwork_id, actor):
    """GET /api/orders/:order_id/artworks/:artwork_id/download - ดาวน์โหลดไฟล์ส่งมอบ
    ต้องผ่านทุกข้อ: ล็อกอิน + เป็นเจ้าของออเดอร์ + ออเดอร์ชำระเงินยืนยันแล้ว (PAYMENT_VERIFIED/PAID/COMPLETED) + งานอยู่ในออเดอร์นี้
    ไม่ผ่าน -> 403 (ไม่ล็อกอิน -> 401) และบันทึก audit  ไม่ส่ง original ให้ผู้ซื้อ - ส่งไฟล์ delivery เท่านั้น"""
    if actor is None:
        raise unauthorized_error()
    for label, value in (("order_id", order_id), ("artwork_id", artwork_id)):
        problem = validation.validate_id(value, label)
        if problem:
            raise validation_error({label: problem})

    def deny(reason):
        logger.create_audit_log(actor["id"], "ARTWORK_FILE_DOWNLOAD_DENIED", "artwork", artwork_id,
                                {"order_id": order_id, "reason": reason}, result="REJECTED")
        raise forbidden_error("ไม่มีสิทธิ์ดาวน์โหลดไฟล์นี้")

    order = storage.get_record("orders", order_id)
    if order is None or order.get("user_id") != actor["id"]:
        deny("not_order_owner")
    if order["status"] not in config.DELIVERY_ORDER_STATES:
        deny("payment_not_verified")
    if not any(item["artwork_id"] == artwork_id for item in order["items"]):
        deny("artwork_not_in_order")
    record = _file_of(artwork_id, "delivery")
    if record is None:
        raise not_found("ไฟล์งาน")
    response = _serve(record, "artwork-" + artwork_id + "." + record["content_type"].split("/")[1].replace("jpeg", "jpg"))
    logger.create_audit_log(actor["id"], "ARTWORK_FILE_DOWNLOADED", "artwork", artwork_id, {"order_id": order_id})
    return response
