"""moderation.py - account blacklist and IP block foundation. IP is a secondary signal only."""
from backend.modules import logger, permissions, storage, validation
from backend.modules.errors import conflict_error, not_found, validation_error
from backend.modules.utils import now_iso
import ipaddress

def add_blacklist(data, actor):
    permissions.check_permission(actor, "admin.blacklist")
    user_id = data.get("user_id") if isinstance(data, dict) else None
    reason = data.get("reason", "") if isinstance(data, dict) else ""
    problem = validation.validate_id(user_id, "user_id")
    if problem: raise validation_error({"user_id": problem})
    if not isinstance(reason, str) or len(reason) > 300: raise validation_error({"reason": "เหตุผลไม่ถูกต้อง"})
    user = storage.get_record("users", user_id)
    if not user: raise not_found("ผู้ใช้")
    existing = next((x for x in storage.get_all("blacklist") if x["user_id"] == user_id), None)
    if existing: raise conflict_error("ALREADY_BLACKLISTED", "ผู้ใช้นี้อยู่ใน blacklist แล้ว")
    rec = storage.create_record("blacklist", {"user_id": user_id, "reason": reason.strip(), "created_at": now_iso(), "created_by": actor["id"]}, "bl")
    logger.create_audit_log(actor["id"], "USER_BLACKLISTED", "user", user_id, {"reason": reason.strip()})
    return rec

def remove_blacklist(user_id, actor):
    permissions.check_permission(actor, "admin.blacklist")
    rec = next((x for x in storage.get_all("blacklist") if x["user_id"] == user_id), None)
    if not rec: raise not_found("Blacklist entry")
    storage.delete_record("blacklist", rec["id"])
    logger.create_audit_log(actor["id"], "USER_UNBLACKLISTED", "user", user_id, {})
    return {"deleted": True, "user_id": user_id}

def list_blacklist(actor):
    permissions.check_permission(actor, "admin.blacklist")
    names = {u["id"]: u["name"] for u in storage.get_all("users")}
    return {"items": [dict(x, user_name=names.get(x["user_id"], "")) for x in storage.get_all("blacklist")]}

def add_ip(data, actor):
    permissions.check_permission(actor, "admin.ip_block")
    raw = data.get("ip") if isinstance(data, dict) else None
    reason = data.get("reason", "") if isinstance(data, dict) else ""
    if not isinstance(raw, str): raise validation_error({"ip": "IP ต้องเป็นข้อความ"})
    try: addr = str(ipaddress.ip_address(raw.strip()))
    except ValueError: raise validation_error({"ip": "IP address ไม่ถูกต้อง"})
    if not isinstance(reason, str) or len(reason) > 300: raise validation_error({"reason": "เหตุผลไม่ถูกต้อง"})
    if any(x["ip"] == addr for x in storage.get_all("blocked_ips")): raise conflict_error("IP_ALREADY_BLOCKED", "IP นี้ถูกบล็อกอยู่แล้ว")
    rec = storage.create_record("blocked_ips", {"ip": addr, "reason": reason.strip(), "created_at": now_iso(), "created_by": actor["id"]}, "ip")
    logger.create_audit_log(actor["id"], "IP_BLOCKED", "ip", addr, {"reason": reason.strip()})
    return rec

def remove_ip(record_id, actor):
    permissions.check_permission(actor, "admin.ip_block")
    rec = storage.get_record("blocked_ips", record_id)
    if not rec: raise not_found("Blocked IP")
    storage.delete_record("blocked_ips", record_id)
    logger.create_audit_log(actor["id"], "IP_UNBLOCKED", "ip", rec["ip"], {})
    return {"deleted": True, "ip": rec["ip"]}

def list_ips(actor):
    permissions.check_permission(actor, "admin.ip_block")
    return {"items": list(storage.get_all("blocked_ips"))}

def is_blocked_ip(ip):
    return any(x["ip"] == ip for x in storage.get_all("blocked_ips"))
