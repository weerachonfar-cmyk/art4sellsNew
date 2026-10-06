"""logger.py - บันทึกเหตุการณ์สำคัญ (Audit Log) และ log สำหรับ developer

1) Audit Log  -> เก็บลง logs.json  ใครทำอะไรกับอะไรเมื่อไร (admin เปิดดูได้)
2) Dev log    -> รายละเอียด error/traceback เขียนลงหน้าจอ server (และไฟล์ backend/logs/server.log)
                 ผู้ใช้ไม่เห็น traceback เด็ดขาด
"""
import logging
import sys

from backend import config
from backend.modules import storage
from backend.modules.errors import StorageError
from backend.modules.utils import now_iso, paginate

# รายการ action ที่อนุญาตให้บันทึก (set) - กันพิมพ์ชื่อ action ผิด
AUDIT_ACTIONS = {
    "USER_CREATED", "USER_LOGIN", "USER_LOGIN_FAILED", "USER_LOGOUT",
    "USER_UPDATED", "USER_BANNED", "USER_UNBANNED", "USER_DELETED",
    "CATEGORY_CREATED", "CATEGORY_UPDATED", "CATEGORY_DELETED",
    "ARTWORK_CREATED", "ARTWORK_UPDATED", "ARTWORK_DELETED",
    "ARTWORK_SUBMITTED", "ARTWORK_APPROVED", "ARTWORK_REJECTED", "ARTWORK_SOLD",
    "ORDER_CREATED", "ORDER_UPDATED", "ORDER_DELETED",
    "REVIEW_CREATED", "REVIEW_UPDATED", "REVIEW_DELETED",
    # Phase 3.5: รหัสผ่าน / OTP / จัดการข้อมูล
    "PASSWORD_CHANGE_SUCCESS", "PASSWORD_CHANGE_FAILED", "PASSWORD_CHANGE_REJECTED_COOLDOWN",
    "PASSWORD_RESET_REQUESTED", "PASSWORD_RESET_OTP_VERIFIED", "PASSWORD_RESET_SUCCESS", "PASSWORD_RESET_FAILED",
    "OTP_INVALID", "OTP_EXPIRED", "OTP_RATE_LIMITED",
    "ADMIN_DATA_CLEAR", "ADMIN_DATA_RESET",
    # Finale Prototype Part 1: security event / developer tools / ไฟล์งานศิลปะ
    "LOGIN_RATE_LIMITED", "DEV_MAILBOX_VIEWED", "DEV_MAILBOX_CLEARED",
    "ARTWORK_FILE_UPLOADED", "ARTWORK_FILE_DOWNLOADED", "ARTWORK_FILE_DOWNLOAD_DENIED",
    # Finale Prototype Part 2: commerce / commission / moderation
    "PAYMENT_SUBMITTED", "PAYMENT_REJECTED", "PAYMENT_VERIFIED",
    "PROMOTION_CREATED",
    "COMMISSION_LISTING_CREATED", "COMMISSION_CREATED", "COMMISSION_PAYMENT_SUBMITTED",
    "COMMISSION_PAYMENT_VERIFIED", "COMMISSION_ACCEPTED", "COMMISSION_REJECTED",
    "COMMISSION_IN_PROGRESS", "COMMISSION_DELIVERED", "COMMISSION_COMPLETED",
    "USER_BLACKLISTED", "USER_UNBLACKLISTED", "IP_BLOCKED", "IP_UNBLOCKED",
}

_DEV_LOGGER_NAME = "art4sells"
logging.getLogger(_DEV_LOGGER_NAME).addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Dev log
# ---------------------------------------------------------------------------
def setup_dev_logging(to_file=True):
    """เปิดการเขียน dev log ลงหน้าจอ (และไฟล์) - เรียกจาก server.py ตอนเริ่มทำงาน"""
    dev_logger = logging.getLogger(_DEV_LOGGER_NAME)
    dev_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    dev_logger.addHandler(stream)
    if to_file:
        try:
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(config.LOG_DIR / "server.log", encoding="utf-8")
            file_handler.setFormatter(formatter)
            dev_logger.addHandler(file_handler)
        except OSError:
            pass                                       # เขียนไฟล์ log ไม่ได้ก็ไม่เป็นไร ยังมีหน้าจอ


def log_info(message):
    logging.getLogger(_DEV_LOGGER_NAME).info(message)


def log_exception(message, error):
    """บันทึก error พร้อม traceback ลง dev log (ไม่ส่งให้ผู้ใช้)"""
    logging.getLogger(_DEV_LOGGER_NAME).error(message, exc_info=error)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def create_audit_log(actor_id, action, target_type, target_id, details=None, result="SUCCESS"):
    """บันทึก audit log ลง logs.json

    พารามิเตอร์: actor_id (ใครทำ; None = ระบบทำเอง), action (เช่น "ARTWORK_APPROVED"),
                target_type (เช่น "artwork"), target_id (id ของสิ่งที่ถูกทำ), details (dict รายละเอียด/metadata),
                result ("SUCCESS" / "FAILURE" / ...)  ห้ามใส่รหัสผ่านหรือ OTP จริงใน details
    คืนค่า: dict ของ log ที่บันทึก (หรือ None ถ้าเขียนไฟล์ไม่สำเร็จ)
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError("unknown audit action: " + str(action))
    entry = {
        "actor_id": actor_id or "system",
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "timestamp": now_iso(),
        "result": result,
        "details": details or {},
    }
    try:
        return storage.create_record("logs", entry, "log_")
    except StorageError as err:
        # เขียน audit ไม่ได้ ไม่ควรทำให้ action หลักล้ม แต่ต้องแจ้ง developer
        log_exception("audit log write failed: " + action, err)
        return None


def list_audit_logs(filters, page, page_size):
    """อ่าน audit log (ใหม่สุดก่อน) พร้อมกรองและแบ่งหน้า
    filters = dict ที่ใช้ได้: action, actor_id, target_type, target_id, result
    คืนค่า: dict {"items", "page", "page_size", "total", "total_pages"}
    """
    logs = storage.get_all("logs")
    matched = []
    for entry in logs:
        keep = True
        for field in ("action", "actor_id", "target_type", "target_id", "result"):
            wanted = filters.get(field)
            if wanted and entry.get(field, "SUCCESS" if field == "result" else None) != wanted:
                keep = False
                break
        if keep:
            matched.append(entry)
    matched.reverse()                                  # log ถูกเพิ่มต่อท้ายตามเวลา จึงกลับลำดับ = ใหม่สุดก่อน
    return paginate(matched, page, page_size)
