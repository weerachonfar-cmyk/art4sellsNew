"""category.py - CRUD ของหมวดหมู่งานศิลป์ (อ่านได้ทุกคน / เพิ่ม-แก้-ลบ เฉพาะ admin)"""
import re

from backend.modules import logger, permissions, storage, validation
from backend.modules.errors import AppError, conflict_error, not_found, validation_error
from backend.modules.utils import new_id, now_iso


def slugify(name):
    """แปลงชื่อเป็น id แบบอ่านง่าย เช่น "Digital Painting" -> "digital-painting" (ชื่อภาษาไทยจะได้ค่าว่าง)"""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def list_categories():
    """รายการหมวดหมู่ทั้งหมด"""
    return {"items": storage.get_all("categories")}


def get_category_ids():
    """set ของ id หมวดหมู่ที่มีอยู่จริง (ใช้ตรวจ artwork.category)"""
    return {c["id"] for c in storage.get_all("categories")}


def _name_taken(name, ignore_id=None):
    """True ถ้ามีหมวดหมู่อื่นใช้ชื่อนี้แล้ว (ไม่สนตัวพิมพ์เล็ก/ใหญ่)"""
    for category in storage.get_all("categories"):
        if category["id"] != ignore_id and category["name"].lower() == name.lower():
            return True
    return False


def create_category(data, actor):
    permissions.check_permission(actor, "category.manage")
    clean, errors = validation.validate_category(data)
    if errors:
        raise validation_error(errors)
    if _name_taken(clean["name"]):
        raise AppError("CATEGORY_EXISTS", "มีหมวดหมู่ชื่อนี้อยู่แล้ว", 409, {"name": "ชื่อนี้ถูกใช้แล้ว"})
    now = now_iso()
    record = {"id": slugify(clean["name"]) or new_id("cat_"), "name": clean["name"],
              "description": clean["description"], "created_at": now, "updated_at": now}
    if storage.get_record("categories", record["id"]) is not None:
        record["id"] = new_id("cat_")
    storage.create_record("categories", record)
    logger.create_audit_log(actor["id"], "CATEGORY_CREATED", "category", record["id"], {"name": record["name"]})
    return record


def update_category(category_id, data, actor):
    permissions.check_permission(actor, "category.manage")
    if storage.get_record("categories", category_id) is None:
        raise not_found("หมวดหมู่")
    clean, errors = validation.validate_category(data, partial=True)
    if errors:
        raise validation_error(errors)
    if not clean:
        raise validation_error({"_": "ไม่มีข้อมูลที่ต้องแก้ไข"})
    if "name" in clean and _name_taken(clean["name"], ignore_id=category_id):
        raise AppError("CATEGORY_EXISTS", "มีหมวดหมู่ชื่อนี้อยู่แล้ว", 409, {"name": "ชื่อนี้ถูกใช้แล้ว"})
    clean["updated_at"] = now_iso()
    updated = storage.update_record("categories", category_id, clean)
    logger.create_audit_log(actor["id"], "CATEGORY_UPDATED", "category", category_id, {})
    return updated


def delete_category(category_id, actor):
    """ลบหมวดหมู่ - ลบไม่ได้ถ้ายังมีงาน (artwork) ใช้หมวดนี้อยู่"""
    permissions.check_permission(actor, "category.manage")
    if storage.get_record("categories", category_id) is None:
        raise not_found("หมวดหมู่")
    if storage.find_records("artworks", "category", category_id):
        raise conflict_error("CATEGORY_IN_USE", "ลบไม่ได้ เพราะยังมีงานใช้หมวดหมู่นี้อยู่")
    storage.delete_record("categories", category_id)
    logger.create_audit_log(actor["id"], "CATEGORY_DELETED", "category", category_id, {})
    return {"deleted": True, "id": category_id}
