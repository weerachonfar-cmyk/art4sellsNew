"""storage.py - ชั้นเก็บข้อมูลกลาง (Storage Abstraction)

กติกาของโปรเจกต์: module อื่นห้ามเรียก open("xxx.json") หรือยิง Redis เอง ต้องผ่านไฟล์นี้เท่านั้น

    Business Logic -> storage.py -> provider ที่เลือกตาม A4S_STORAGE (ดู storage_providers.py)
                                      json  : backend/data/*.json   (Local / งานวิชา File Handling)
                                      redis : Upstash Redis         (Vercel Prototype)
    เปลี่ยน provider แล้ว business logic ไม่ต้องแก้แม้แต่บรรทัดเดียว

ข้อมูลทุก collection เป็น "list ของ dict" (ไฟล์ <collection>.json หรือ key ใน Redis)
ฟังก์ชันระดับ record (get_all, get_record, find_records, find_one, count_records, create_record,
update_record, delete_record, delete_where, transaction) เป็น API เดียวกันทุก provider
"""
from pathlib import Path
import threading

from backend import config
from backend.modules import storage_providers
from backend.modules.errors import StorageError
from backend.modules.utils import new_id

# ชื่อ collection ที่อนุญาต (set) - กัน path / key แปลก ๆ เช่น "../../etc/passwd"
COLLECTIONS = {
    "users", "artworks", "categories", "orders", "reviews", "logs", "sessions",
    "carts", "wishlists", "follows", "notifications",          # ข้อมูลส่วนตัวของ user (ทุก record มี user_id)
    "password_resets", "reset_requests", "confirmations",      # OTP / ขอรหัส / ขั้นยืนยันของ admin
    "login_attempts",                                          # ความพยายาม login ที่ผิด (ใช้ทำ rate limit)
    "dev_mailbox",                                             # อีเมลจำลองของโหมด development (เฉพาะ DEV TOOLS)
    "files", "payments", "promotions", "price_history", "commission_listings", "commissions", "commission_messages", "blacklist", "blocked_ips",  # PART 2
}

# Redis เก็บ collection ละ 1 ค่า (จำกัดขนาด) จึงเก็บเฉพาะรายการล่าสุดของ collection ที่โตเรื่อย ๆ  (JSON ในเครื่องไม่ตัด)
REDIS_COLLECTION_CAPS = {"logs": 2000, "login_attempts": 2000, "reset_requests": 2000, "dev_mailbox": config.DEV_MAILBOX_MAX_ITEMS}

_data_dir = Path(config.DATA_DIR)
_provider = None
_provider_guard = threading.Lock()


# ---------------------------------------------------------------------------
# เลือก / ตั้งค่า provider
# ---------------------------------------------------------------------------
def get_provider():
    """คืน provider ที่ใช้อยู่ (สร้างครั้งแรกตาม config)"""
    global _provider
    if _provider is None:
        with _provider_guard:
            if _provider is None:
                _provider = storage_providers.build_provider(_data_dir)
    return _provider


def use_provider(provider):
    """กำหนด provider เอง (ใช้ในเทสต์ เช่น ชี้ไปที่ Redis emulator)"""
    global _provider
    _provider = provider


def reset_provider():
    """ลืม provider ที่สร้างไว้ แล้วสร้างใหม่ตาม config ในครั้งถัดไป"""
    global _provider
    _provider = None


def configure(data_dir):
    """เปลี่ยนโฟลเดอร์เก็บข้อมูลของ JSON provider (ใช้ตอนเทสต์ให้ไม่ไปแตะข้อมูลจริง)"""
    global _data_dir
    _data_dir = Path(data_dir)
    if isinstance(_provider, storage_providers.JSONStorage):
        _provider.data_dir = _data_dir
    elif _provider is not None and _provider.name == "unavailable":
        reset_provider()


def get_data_dir():
    """คืนค่าโฟลเดอร์เก็บข้อมูลของ JSON provider ที่ใช้อยู่ตอนนี้"""
    return _data_dir


def provider_name():
    return get_provider().name


def health():
    """สถานะระบบเก็บข้อมูล: {"provider", "available", "error"}  (ไม่มี token / URL / path)"""
    provider = get_provider()
    result = provider.health()
    return {"provider": provider.name if provider.name != "unavailable" else config.STORAGE_PROVIDER,
            "available": bool(result["available"]), "error": result["error"]}


def begin_request():
    get_provider().begin_request()


def end_request():
    get_provider().end_request()


def prefetch(collections):
    """อ่านล่วงหน้าหลาย collection ในรอบเดียว (มีผลเฉพาะ Redis - ลดจำนวนรอบ network ต่อ request)"""
    for name in collections:
        _check_collection(name)
    get_provider().prefetch(collections)


def ensure_initialized(seed_function):
    """seed ข้อมูลตัวอย่างครั้งแรกเท่านั้น: ยังไม่เคย initialize -> ล็อก -> เช็คอีกรอบ -> seed -> ทำเครื่องหมาย
    คืน True ถ้าเพิ่ง seed  ไม่ seed ซ้ำทุก request / ทุก cold start (และไม่ทับข้อมูลจริง)
    """
    provider = get_provider()
    if provider.is_initialized():
        return False
    with provider.lock():
        if provider.is_initialized():                  # อีก instance อาจ seed เสร็จระหว่างที่เรารอ lock
            return False
        seed_function()
        provider.mark_initialized()
    return True


def transaction():
    """ตัวล็อกสำหรับงาน "ตรวจแล้วค่อยเขียน" ให้เสร็จทีละคน เช่น ตรวจว่างานยังว่างแล้วสร้างออเดอร์
    ใช้แบบ:  with storage.transaction():  ...  (กัน 2 request ผ่านการตรวจพร้อมกัน - JSON ใช้ lock ในโปรเซส, Redis ใช้ lock กลาง)
    """
    return get_provider().lock()


def _check_collection(collection):
    if collection not in COLLECTIONS:
        raise StorageError("UNKNOWN_COLLECTION", "ไม่พบแหล่งข้อมูลที่ต้องการ", detail=str(collection))


# ---------------------------------------------------------------------------
# ระดับ collection: load_json / save_json (ชื่อเดิมคงไว้ เพื่อไม่ต้องแก้ผู้เรียกเดิม)
# ---------------------------------------------------------------------------
def load_json(collection, default=None):
    """อ่านทั้ง collection จาก provider ที่ใช้อยู่
    พารามิเตอร์: collection (ชื่อ เช่น "artworks"), default (ค่าที่คืนถ้าไม่มีข้อมูลเลย)
    คืนค่า: list ของ dict    ข้อมูลเสีย/รูปแบบผิด -> raise StorageError (ไม่ลบหรือเขียนทับของเดิม)
    """
    _check_collection(collection)
    data = get_provider().read(collection)
    if not data and default is not None:
        return default
    return data


def save_json(collection, data):
    """เขียนทั้ง collection ผ่าน provider (JSON: ไฟล์ชั่วคราว + os.replace / Redis: SET ภายใต้ lock)"""
    _check_collection(collection)
    get_provider().write(collection, data)


# ---------------------------------------------------------------------------
# ระดับ record: ที่ module อื่นเรียกใช้
# ---------------------------------------------------------------------------
def get_all(collection):
    """คืนรายการทั้งหมดใน collection (list ของ dict)"""
    return load_json(collection)


def get_record(collection, record_id):
    """คืน record ที่ id ตรงกัน หรือ None ถ้าไม่พบ"""
    for record in get_all(collection):
        if record.get("id") == record_id:
            return record
    return None


def find_records(collection, field, value):
    """คืนรายการ record ทั้งหมดที่ record[field] == value"""
    return [r for r in get_all(collection) if r.get(field) == value]


def find_one(collection, field, value):
    """คืน record แรกที่ record[field] == value หรือ None"""
    matches = find_records(collection, field, value)
    return matches[0] if matches else None


def count_records(collection):
    """จำนวน record ใน collection"""
    return len(get_all(collection))


def create_record(collection, record, id_prefix=""):
    """เพิ่ม record ใหม่ (สร้าง id ให้ถ้ายังไม่มี) แล้วคืน record นั้น"""
    with transaction():
        records = get_all(collection)
        if not record.get("id"):
            used_ids = {r.get("id") for r in records}      # set ของ id ที่ใช้แล้ว
            candidate = new_id(id_prefix)
            while candidate in used_ids:                   # กัน id ซ้ำ (แทบไม่เกิด แต่เช็คไว้)
                candidate = new_id(id_prefix)
            record["id"] = candidate
        records.append(record)
        cap = REDIS_COLLECTION_CAPS.get(collection)
        if cap and get_provider().name == "redis" and len(records) > cap:
            records = records[-cap:]                       # เก็บเฉพาะรายการล่าสุด (Redis จำกัดขนาดต่อ collection)
        save_json(collection, records)
    return record


def update_record(collection, record_id, changes):
    """แก้ record ตาม dict changes แล้วคืน record ที่แก้แล้ว (ไม่พบ -> None)"""
    with transaction():
        records = get_all(collection)
        for record in records:
            if record.get("id") == record_id:
                record.update(changes)
                save_json(collection, records)
                return record
    return None


def delete_record(collection, record_id):
    """ลบ record ที่ id ตรงกัน คืน True ถ้าลบได้ / False ถ้าไม่พบ"""
    with transaction():
        records = get_all(collection)
        remaining = [r for r in records if r.get("id") != record_id]
        if len(remaining) == len(records):
            return False
        save_json(collection, remaining)
        return True


def delete_where(collection, field, value):
    """ลบ record ทั้งหมดที่ record[field] == value คืนจำนวนที่ลบ (ใช้ล้างข้อมูลที่อ้างถึง record ที่ถูกลบ)"""
    with transaction():
        records = get_all(collection)
        remaining = [r for r in records if r.get(field) != value]
        removed = len(records) - len(remaining)
        if removed:
            save_json(collection, remaining)
        return removed
