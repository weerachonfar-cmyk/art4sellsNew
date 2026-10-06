"""rate_limit.py - จำกัดจำนวนครั้งที่ login ผิด (กันเดารหัสผ่าน)

ไม่ใช้ IP เป็นตัวตนเดียว (หลายคนอยู่หลัง IP เดียวกันได้ / คนร้ายเปลี่ยน IP ได้) จึงนับ 3 แบบพร้อมกัน:
    pair     IP + อีเมลเดียวกัน   ผิด 5 ครั้ง / 10 นาที -> ถูกบล็อก   (กันเดารหัสของบัญชีหนึ่งจากเครื่องเดียว)
    account  อีเมลเดียวกัน (ทุก IP) ผิด 15 ครั้ง / 10 นาที             (กันเดาแบบกระจายหลาย IP แต่ไม่ล็อกเจ้าของบัญชีง่ายเกินไป)
    ip       IP เดียวกัน (ทุกอีเมล) ผิด 30 ครั้ง / 10 นาที             (กันไล่เดาหลายบัญชี)
นับเหมือนกันไม่ว่าอีเมลจะมีในระบบหรือไม่ จึงไม่เผยว่ามีบัญชีนี้อยู่จริง
เก็บเฉพาะ hash ของ IP และอีเมล ลงใน collection "login_attempts" (ผ่าน storage.py จึงใช้ได้ทั้ง JSON และ Redis)
ข้อจำกัด (prototype): ไม่ใช่ WAF / ไม่กันการโจมตีระดับเครือข่าย  ดู docs/SECURITY_STATUS.md
"""
import hashlib
from datetime import timedelta

from backend import config
from backend.modules import logger, storage
from backend.modules.errors import AppError
from backend.modules.utils import now_iso, now_utc, parse_iso

RATE_LIMIT_MESSAGE = "พยายามเข้าสู่ระบบผิดหลายครั้งเกินไป กรุณารอสักครู่แล้วลองใหม่"


def _digest(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _window_start():
    return now_utc() - timedelta(minutes=config.LOGIN_WINDOW_MINUTES)


def _recent_failures():
    """รายการความพยายามที่ผิดภายในหน้าต่างเวลา (ลบของเก่าที่หมดหน้าต่างแล้วทิ้งไปพร้อมกัน)"""
    cutoff = _window_start()
    fresh, stale = [], False
    for entry in storage.get_all("login_attempts"):
        try:
            if parse_iso(entry["at"]) >= cutoff:
                fresh.append(entry)
                continue
        except (KeyError, TypeError, ValueError):
            pass
        stale = True
    if stale:
        storage.save_json("login_attempts", fresh)
    return fresh


def _limits():
    return (("pair", config.LOGIN_MAX_FAILS_PER_PAIR), ("account", config.LOGIN_MAX_FAILS_PER_ACCOUNT),
            ("ip", config.LOGIN_MAX_FAILS_PER_IP))


def _matches(entry, scope, ip_hash, email_hash):
    if scope == "pair":
        return entry["ip_hash"] == ip_hash and entry["email_hash"] == email_hash
    if scope == "account":
        return entry["email_hash"] == email_hash
    return entry["ip_hash"] == ip_hash


def _blocked_scope(failures, ip_hash, email_hash):
    """คืน (ชื่อ scope, จำนวนวินาทีที่ต้องรอ) ของข้อจำกัดที่ถูกชนอยู่ หรือ None ถ้ายังไม่ถูกบล็อก"""
    for scope, maximum in _limits():
        hits = sorted(parse_iso(e["at"]) for e in failures if _matches(e, scope, ip_hash, email_hash))
        if len(hits) >= maximum:
            # รอจนกว่าความพยายามที่ทำให้เต็ม จะหลุดจากหน้าต่างเวลา
            free_at = hits[len(hits) - maximum] + timedelta(minutes=config.LOGIN_WINDOW_MINUTES)
            return scope, max(1, int((free_at - now_utc()).total_seconds()) + 1)
    return None


def check_login_allowed(client_ip, email):
    """เรียกก่อนตรวจรหัสผ่านทุกครั้ง  ถูกบล็อก -> raise AppError 429 (รหัส LOGIN_RATE_LIMITED + retry_after_seconds)"""
    ip_hash, email_hash = _digest(client_ip), _digest(email)
    with storage.transaction():
        blocked = _blocked_scope(_recent_failures(), ip_hash, email_hash)
    if blocked is not None:
        raise AppError("LOGIN_RATE_LIMITED", RATE_LIMIT_MESSAGE, 429, details={"retry_after_seconds": blocked[1]})


def record_failed_login(client_ip, email, known_user_id=None):
    """บันทึกการ login ผิด 1 ครั้ง  ถ้าครั้งนี้ทำให้ถึงเพดานพอดี -> บันทึก security event (audit log)"""
    ip_hash, email_hash = _digest(client_ip), _digest(email)
    with storage.transaction():
        failures = _recent_failures()
        before = _blocked_scope(failures, ip_hash, email_hash)
        storage.create_record("login_attempts", {"ip_hash": ip_hash, "email_hash": email_hash, "at": now_iso()}, "la")
        after = _blocked_scope(failures + [{"ip_hash": ip_hash, "email_hash": email_hash, "at": now_iso()}],
                               ip_hash, email_hash)
    if before is None and after is not None:           # เพิ่งถูกบล็อกเป็นครั้งแรก (ไม่ log ซ้ำทุกครั้งที่ยิงต่อ)
        logger.create_audit_log(None, "LOGIN_RATE_LIMITED", "user", known_user_id,
                                {"scope": after[0], "ip_ref": ip_hash[:12], "retry_after_seconds": after[1]},
                                result="REJECTED")


def clear_failures_for_pair(client_ip, email):
    """login สำเร็จ -> ล้างความพยายามที่ผิดของคู่ IP+อีเมลนี้ (ไม่ล้างของ scope อื่น เพื่อไม่ให้คนร้ายล้างตัวนับได้)"""
    ip_hash, email_hash = _digest(client_ip), _digest(email)
    with storage.transaction():
        remaining = [e for e in storage.get_all("login_attempts")
                     if not (e["ip_hash"] == ip_hash and e["email_hash"] == email_hash)]
        if len(remaining) != len(storage.get_all("login_attempts")):
            storage.save_json("login_attempts", remaining)
