"""utils.py - ฟังก์ชันเล็ก ๆ ที่หลาย module ใช้ร่วมกัน (เวลา, id, pagination)"""
import math
import uuid
from datetime import datetime, timedelta, timezone


def now_utc():
    """เวลาปัจจุบัน (UTC) เป็น datetime"""
    return datetime.now(timezone.utc)


def now_iso():
    """เวลาปัจจุบันเป็นข้อความ ISO 8601 เช่น 2026-10-01T09:30:00+00:00"""
    return now_utc().isoformat(timespec="seconds")


def minutes_from_now_iso(minutes):
    """เวลาในอนาคต (หน่วยนาที) เป็นข้อความ ISO"""
    return (now_utc() + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def parse_iso(text):
    """แปลงข้อความ ISO เป็น datetime (ถ้าไม่มี timezone ถือว่าเป็น UTC)"""
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def is_expired(iso_text):
    """True ถ้าเวลาที่ให้มาผ่านไปแล้ว (ถ้าอ่านเวลาไม่ได้ ถือว่าหมดอายุเพื่อความปลอดภัย)"""
    try:
        return parse_iso(iso_text) < now_utc()
    except (TypeError, ValueError):
        return True


def new_id(prefix=""):
    """สร้าง id ใหม่ เช่น w3fa91c2e"""
    return prefix + uuid.uuid4().hex[:8]


def calculate_pagination(total, page, page_size):
    """คำนวณข้อมูลแบ่งหน้า
    พารามิเตอร์: total (จำนวนรายการทั้งหมด), page (หน้าที่ขอ), page_size (จำนวนต่อหน้า)
    คืนค่า: tuple (page, total_pages, start_index)  - page ถูกปรับให้อยู่ในช่วง 1..total_pages
    """
    total_pages = max(1, math.ceil(total / page_size))
    page = min(max(1, page), total_pages)
    start_index = (page - 1) * page_size
    return page, total_pages, start_index


def paginate(items, page, page_size):
    """ตัดรายการเป็นหน้า แล้วคืน dict ตามรูปแบบ API
    {"items": [...], "page": 1, "page_size": 12, "total": 100, "total_pages": 9}
    """
    total = len(items)
    page, total_pages, start = calculate_pagination(total, page, page_size)
    return {
        "items": items[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }
