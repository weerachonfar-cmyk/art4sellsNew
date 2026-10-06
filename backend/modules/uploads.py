"""uploads.py - รากฐานการรับไฟล์อัปโหลด (Phase 3.5 foundation: ยังไม่มี endpoint อัปโหลดจริง)

หลักการ: ไม่เชื่อชื่อไฟล์/ชนิดไฟล์ที่ client ส่งมา
  - ตรวจ extension + Content-Type + ขนาด จาก allowlist ใน config
  - ชื่อไฟล์ที่เก็บจริงสร้างเองที่ server (สุ่ม) ไม่ใช้ชื่อจาก client
  - การรวม path ใช้ safe_join() ซึ่งปฏิเสธ ../  path เต็ม และการหลุดออกนอกโฟลเดอร์ปลายทาง
"""
import uuid
from pathlib import Path

from backend import config
from backend.modules import validation


def validate_upload_metadata(filename, content_type, size):
    """ตรวจ metadata ของไฟล์ที่ client บอกมา  คืน tuple (clean, errors)
    clean = {"extension", "content_type", "size"}   errors = dict {ชื่อช่อง: ข้อความ}
    """
    errors, clean = {}, {}
    if not isinstance(filename, str) or not filename or len(filename) > 255 or validation.has_control_chars(filename) \
            or "/" in filename or "\\" in filename or ".." in filename:
        errors["filename"] = "ชื่อไฟล์ไม่ถูกต้อง"
    else:
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in config.ALLOWED_UPLOAD_EXTENSIONS:
            errors["filename"] = "รองรับเฉพาะไฟล์ " + ", ".join(sorted(config.ALLOWED_UPLOAD_EXTENSIONS))
        else:
            clean["extension"] = extension
    if not isinstance(content_type, str) or "extension" not in clean \
            or content_type.lower() != config.ALLOWED_UPLOAD_EXTENSIONS[clean["extension"]]:
        errors["content_type"] = "ชนิดไฟล์ไม่ตรงกับนามสกุล"
    else:
        clean["content_type"] = content_type.lower()
    if isinstance(size, bool) or not isinstance(size, int) or not (0 < size <= config.MAX_UPLOAD_BYTES):
        errors["size"] = "ขนาดไฟล์ต้องมากกว่า 0 และไม่เกิน " + str(config.MAX_UPLOAD_BYTES) + " ไบต์"
    else:
        clean["size"] = size
    return clean, errors


def safe_server_filename(extension):
    """ชื่อไฟล์ที่เก็บจริง: uuid สุ่ม + นามสกุลที่ผ่านการตรวจแล้ว"""
    return uuid.uuid4().hex + "." + extension


def safe_join(base_dir, name):
    """รวมโฟลเดอร์ + ชื่อไฟล์เดี่ยว ๆ อย่างปลอดภัย คืน Path ที่อยู่ภายใน base_dir จริง ๆ หรือ None ถ้าพยายามหลุดออกนอก"""
    if not isinstance(name, str) or not name or "\x00" in name or "/" in name or "\\" in name or name in (".", ".."):
        return None                                    # รับเฉพาะ "ชื่อไฟล์เดี่ยว ๆ" (ไม่ว่าระบบปฏิบัติการจะใช้ / หรือ \ คั่น path)
    base = Path(base_dir).resolve()
    candidate = (base / name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate != base else None


# ---------------------------------------------------------------------------
# ตรวจ "เนื้อไฟล์จริง" (ไม่เชื่อแค่ชื่อไฟล์/Content-Type ที่ client บอก) และเก็บไฟล์อย่างปลอดภัย
# ---------------------------------------------------------------------------
# เครื่องหมายที่บอกว่าไฟล์อาจเป็นโค้ดซ่อนในรูป (polyglot) - ตรวจแบบพื้นฐานระดับ prototype ไม่ใช่การสแกนมัลแวร์จริง
SUSPICIOUS_MARKERS = (b"<?php", b"<script", b"<%", b"#!/", b"<!doctype html", b"<html", b"<svg", b"javascript:")


def sniff_image_type(data):
    """ดูจาก "ไบต์แรกของไฟล์" ว่าเป็นรูปชนิดใด  คืน "png" / "jpg" / "webp" หรือ None ถ้าไม่ใช่รูปที่รองรับ"""
    if not isinstance(data, (bytes, bytearray)):
        return None
    head = bytes(data[:12])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def validate_upload(filename, content_type, data):
    """ตรวจไฟล์อัปโหลดทั้งก้อน: metadata (นามสกุล/Content-Type/ขนาด) + ไบต์จริงต้องตรงกับนามสกุล + ไม่มีโค้ดแฝง
    คืน tuple (clean, errors)   ยังเป็นการตรวจระดับพื้นฐาน (ไม่ใช่ malware scanning)
    """
    if not isinstance(data, (bytes, bytearray)):
        return {}, {"file": "ข้อมูลไฟล์ไม่ถูกต้อง"}
    clean, errors = validate_upload_metadata(filename, content_type, len(data))
    if errors:
        return {}, errors
    real_type = sniff_image_type(data)
    family = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp"}[clean["extension"]]
    if real_type != family:
        errors["file"] = "เนื้อไฟล์ไม่ตรงกับนามสกุลที่ระบุ"
    else:
        lowered = bytes(data).lower()
        if any(marker in lowered for marker in SUSPICIOUS_MARKERS):
            errors["file"] = "ไฟล์มีเนื้อหาที่ไม่อนุญาต"
    clean["detected_type"] = real_type
    return (clean, errors) if not errors else ({}, errors)


def save_upload(base_dir, data, extension):
    """เก็บไฟล์ที่ผ่านการตรวจแล้วลงโฟลเดอร์ที่กำหนด ด้วยชื่อที่ server สร้างเอง  คืนชื่อไฟล์ที่เก็บ (ไม่ใช่ path)
    - เปิดแบบ "x" (สร้างใหม่เท่านั้น ไม่เขียนทับไฟล์เดิม)  - ปิดสิทธิ์ execute (0o644)  - ไม่ใช้ path จาก client เลย
    """
    if extension not in config.ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError("extension not allowed")
    folder = Path(base_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_server_filename(extension)
    target = safe_join(folder, name)
    if target is None:
        raise ValueError("unsafe path")
    with open(target, "xb") as f:
        f.write(data)
    target.chmod(0o644)
    return name
