"""data_management.py - ผู้ดูแลระบบล้างข้อมูล / รีเซ็ตข้อมูลตัวอย่าง (ADMIN เท่านั้น)

ความปลอดภัยของงานอันตราย (ฝั่ง server บังคับเอง ไม่พึ่งแค่หน้าเว็บ):
  ขั้นที่ 1  POST .../preview  ดูว่าจะลบอะไรกี่รายการ + ได้ confirm_token (ใช้ครั้งเดียว อายุ 5 นาที ผูกกับ admin + รายการที่เลือก)
  ขั้นที่ 2  POST .../clear (หรือ reset)  ต้องส่ง confirm_token + พิมพ์ข้อความยืนยัน (CLEAR / RESET) ให้ตรงเป๊ะ
เพื่อกัน request เดียวล้างข้อมูลทั้งระบบ

กติกา: ไม่ลบ admin ที่กำลังใช้งาน (เด็ดขาด)  /  Preserve Admin Accounts เปิดไว้เป็นค่าเริ่มต้น
       บันทึก audit log "ก่อน" ลงมือลบ  และ log ของการกระทำนี้ไม่ถูกลบแม้เลือกล้าง Audit Logs
"""
import hashlib
import json

from backend import config, seed
from backend.modules import artwork_files, logger, payment, permissions, security, storage, validation
from backend.modules.errors import AppError, validation_error
from backend.modules.utils import is_expired, minutes_from_now_iso, now_iso

# ชื่อ scope ที่ admin เลือกได้ -> collection ที่เก็บจริง (dict)  ลำดับ = ลำดับการลบ (ข้อมูลที่อ้างอิงคนอื่นลบก่อน)
SCOPE_COLLECTIONS = {
    "reviews": "reviews", "orders": "orders", "cart": "carts", "wishlist": "wishlists", "follows": "follows",
    "notifications": "notifications", "artworks": "artworks", "categories": "categories",
    "users": "users", "audit_logs": "logs",
}
# ถ้าล้าง scope ซ้าย ต้องล้าง scope ขวาด้วย (ไม่งั้นข้อมูลขวาจะชี้ไปหาของที่หายไป = orphan)
DEPENDENTS = {
    "users": {"artworks", "orders", "reviews", "cart", "wishlist", "follows", "notifications"},
    "categories": {"artworks"},
    "artworks": {"orders", "reviews", "cart", "wishlist"},
    "orders": {"reviews"},
}
USER_OWNED_SCOPES = {"cart", "wishlist", "follows", "notifications"}


# ---------------------------------------------------------------------------
# ตรวจ input
# ---------------------------------------------------------------------------
def parse_scopes(raw):
    """ตรวจรายการ scope จาก client  คืน list ที่ไม่ซ้ำ (raise 400 ถ้ารูปแบบหรือค่าผิด)"""
    if not isinstance(raw, list) or not raw or len(raw) > len(SCOPE_COLLECTIONS):
        raise validation_error({"scopes": "ต้องเลือกอย่างน้อย 1 รายการ"})
    scopes = []
    for item in raw:
        if not isinstance(item, str) or item not in SCOPE_COLLECTIONS:
            raise validation_error({"scopes": "scope ไม่ถูกต้อง"})
        if item not in scopes:
            scopes.append(item)
    return scopes


def parse_preserve_flag(data):
    """preserve_admins ต้องเป็น boolean จริง (ข้อความ "false" ไม่นับ) ค่าเริ่มต้น True"""
    value, problem = validation.validate_boolean(data.get("preserve_admins", True), "preserve_admins")
    if problem:
        raise validation_error({"preserve_admins": problem})
    return value


def expand_scopes(scopes):
    """เพิ่ม scope ที่ต้องล้างตามกัน (dependency)  คืน tuple (scope ทั้งหมดเรียงตามลำดับลบ, ที่ถูกเพิ่มอัตโนมัติ)"""
    effective = set(scopes)
    changed = True
    while changed:                                     # วนจนไม่มี scope ใหม่ถูกเพิ่ม (dependency ต่อกันหลายชั้น)
        changed = False
        for scope in list(effective):
            for dependent in DEPENDENTS.get(scope, ()):
                if dependent not in effective:
                    effective.add(dependent)
                    changed = True
    ordered = [s for s in SCOPE_COLLECTIONS if s in effective]
    return tuple(ordered), tuple(s for s in ordered if s not in scopes)


# ---------------------------------------------------------------------------
# แผนการลบ (ใช้ร่วมกันทั้ง preview และตอนลบจริง)
# ---------------------------------------------------------------------------
def kept_admin_ids(actor, preserve_admins):
    """set ของ user id ที่ห้ามลบ: admin ที่กำลังใช้งานเสมอ (+ admin ทั้งหมดถ้า preserve_admins)"""
    kept = {actor["id"]}
    if preserve_admins:
        kept |= {u["id"] for u in storage.get_all("users") if u["role"] == "ADMIN"}
    return kept


def build_plan(effective_scopes, actor, preserve_admins):
    """คำนวณว่าแต่ละ collection จะลบ record ไหนบ้าง  คืน dict {collection: set ของ id}  (ยังไม่ลบอะไร)"""
    kept = kept_admin_ids(actor, preserve_admins)
    plan = {}
    for scope in effective_scopes:
        collection = SCOPE_COLLECTIONS[scope]
        rows = storage.get_all(collection)
        if scope == "users":
            doomed = {r["id"] for r in rows if r["id"] not in kept}
        elif scope in USER_OWNED_SCOPES and preserve_admins:
            doomed = {r["id"] for r in rows if r.get("user_id") not in kept}      # ข้อมูลของ admin ที่เก็บไว้ไม่ถูกลบ
        else:
            doomed = {r["id"] for r in rows}
        plan[collection] = doomed
    if "users" in effective_scopes:                    # user ที่ถูกลบ: session และสิทธิ์กู้รหัสผ่านต้องไปด้วย
        for collection in ("sessions", "password_resets"):
            plan[collection] = {r["id"] for r in storage.get_all(collection) if r.get("user_id") in plan["users"]}
    return plan


def _counts(plan):
    return {collection: len(ids) for collection, ids in plan.items()}


# ---------------------------------------------------------------------------
# ขั้นยืนยันที่ 2 (confirm token)
# ---------------------------------------------------------------------------
def _scope_key(operation, scopes, preserve_admins):
    """ลายนิ้วมือของรายการที่ admin เห็นตอน preview - ถ้าเปลี่ยนรายการ token เดิมใช้ไม่ได้"""
    raw = json.dumps([operation, sorted(scopes), preserve_admins])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _issue_confirmation(actor, operation, scopes, preserve_admins):
    for old in storage.get_all("confirmations"):       # เก็บกวาดอันหมดอายุ/ถูกใช้แล้ว
        if old["used"] or is_expired(old["expires_at"]):
            storage.delete_record("confirmations", old["id"])
    token = security.new_secret_token()
    storage.create_record("confirmations", {
        "admin_id": actor["id"], "operation": operation, "scope_key": _scope_key(operation, scopes, preserve_admins),
        "token_hash": security.hash_token(token), "expires_at": minutes_from_now_iso(config.CONFIRM_TOKEN_MINUTES),
        "used": False, "created_at": now_iso(),
    }, "cf")
    return token


def _consume_confirmation(token, actor, operation, scopes, preserve_admins):
    """ตรวจ + ใช้ confirm token (ใช้ได้ครั้งเดียว) ไม่ผ่าน -> raise 400"""
    error = AppError("CONFIRMATION_REQUIRED", "ต้องดูสรุปและยืนยันสองขั้นตอนก่อน (ขอรหัสยืนยันใหม่จากขั้นตอนแรก)", 400)
    if not isinstance(token, str) or not (20 <= len(token) <= 100):
        raise error
    entry = storage.find_one("confirmations", "token_hash", security.hash_token(token))
    valid = (entry is not None and not entry["used"] and not is_expired(entry["expires_at"])
             and entry["admin_id"] == actor["id"] and entry["operation"] == operation
             and entry["scope_key"] == _scope_key(operation, scopes, preserve_admins))
    if not valid:
        raise error
    storage.update_record("confirmations", entry["id"], {"used": True})


def _check_text(value, expected, field="confirm_text"):
    """ข้อความยืนยันต้องตรงเป๊ะ (ตัวพิมพ์ใหญ่/เล็กมีผล)"""
    if not isinstance(value, str) or value != expected:
        raise validation_error({field: "พิมพ์ " + expected + " ให้ถูกต้องเพื่อยืนยัน"})


# ---------------------------------------------------------------------------
# Clear Data
# ---------------------------------------------------------------------------
def preview_clear(data, actor):
    """POST /api/admin/data/clear/preview  body: {"scopes": [...], "preserve_admins": true}"""
    permissions.check_permission(actor, "data.manage")
    body = validation.pick_fields(data, ("scopes", "preserve_admins"))
    scopes = parse_scopes(body.get("scopes"))
    preserve = parse_preserve_flag(body)
    effective, auto_added = expand_scopes(scopes)
    plan = build_plan(effective, actor, preserve)
    return {
        "scopes": scopes, "effective_scopes": list(effective), "auto_included": list(auto_added),
        "counts": _counts(plan), "preserve_admins": preserve, "preserve_system_config": True,
        "requires_audit_confirmation": "audit_logs" in effective,
        "confirm_token": _issue_confirmation(actor, "CLEAR", effective, preserve),
        "confirm_expires_in_minutes": config.CONFIRM_TOKEN_MINUTES,
    }


def clear_data(data, actor):
    """POST /api/admin/data/clear
    body: {"scopes", "preserve_admins", "confirm_token", "confirm_text": "CLEAR", "confirm_audit_text"?}
    """
    permissions.check_permission(actor, "data.manage")
    body = validation.pick_fields(data, ("scopes", "preserve_admins", "confirm_token", "confirm_text", "confirm_audit_text"))
    scopes = parse_scopes(body.get("scopes"))
    preserve = parse_preserve_flag(body)
    effective, _auto = expand_scopes(scopes)

    _check_text(body.get("confirm_text"), config.CLEAR_CONFIRM_TEXT)
    if "audit_logs" in effective:                      # ล้าง Audit Logs ต้องยืนยันเพิ่มอีกชั้น
        _check_text(body.get("confirm_audit_text"), config.CLEAR_AUDIT_CONFIRM_TEXT, "confirm_audit_text")

    with storage.transaction():
        _consume_confirmation(body.get("confirm_token"), actor, "CLEAR", effective, preserve)
        plan = build_plan(effective, actor, preserve)
        counts = _counts(plan)
        # PART 2 internal collections: keep admin scope UX stable while preventing orphan records.
        if "orders" in plan and plan["orders"]:
            order_ids = plan["orders"]
            payment.delete_slips_of_orders(order_ids)
            storage.save_json("payments", [r for r in storage.get_all("payments") if r.get("order_id") not in order_ids])
        if "artworks" in plan and plan["artworks"]:
            artwork_ids = plan["artworks"]
            storage.save_json("payments", [r for r in storage.get_all("payments") if not any(i.get("artwork_id") in artwork_ids for o in storage.get_all("orders") if r.get("order_id") == o.get("id") for i in o.get("items", []))])
            storage.save_json("promotions", [r for r in storage.get_all("promotions") if r.get("artwork_id") not in artwork_ids])
            storage.save_json("price_history", [r for r in storage.get_all("price_history") if r.get("artwork_id") not in artwork_ids])
        # บันทึก log "ก่อนลบ" และกันไม่ให้ log ของการกระทำนี้ถูกลบตามไปด้วย
        entry = logger.create_audit_log(actor["id"], "ADMIN_DATA_CLEAR", "data", ",".join(effective),
                                        {"scopes": list(effective), "counts": counts, "preserve_admins": preserve})
        if entry is None:
            raise AppError("AUDIT_UNAVAILABLE", "ไม่สามารถบันทึก log ได้ จึงไม่ลบข้อมูล", 500)
        for collection in _deletion_order(plan):
            doomed = plan[collection]
            if doomed:
                if collection == "artworks":               # ล้างงาน -> ล้างไฟล์ภาพของงานเหล่านั้นด้วย (ไม่ให้เหลือไฟล์กำพร้า)
                    for artwork_id in doomed:
                        artwork_files.delete_files_of_artwork(artwork_id)
                storage.save_json(collection, [r for r in storage.get_all(collection) if r["id"] not in doomed])
    return {"cleared": True, "counts": counts, "effective_scopes": list(effective)}


def _deletion_order(plan):
    """ลำดับการเขียนไฟล์: ข้อมูลที่อ้างอิงคนอื่นก่อน (ถ้าหยุดกลางคันก็ไม่เกิด orphan)  ตามลำดับใน SCOPE_COLLECTIONS"""
    ordered = [SCOPE_COLLECTIONS[s] for s in SCOPE_COLLECTIONS if SCOPE_COLLECTIONS[s] in plan]
    ordered += [c for c in ("sessions", "password_resets") if c in plan]
    return ordered


# ---------------------------------------------------------------------------
# Reset Demo Data (ใช้ seed.py ตัวเดิม ไม่คัดลอกข้อมูลตัวอย่างมาเขียนซ้ำ)
# ---------------------------------------------------------------------------
def preview_reset(data, actor):
    """POST /api/admin/data/reset/preview  body: {"preserve_admins": true}"""
    permissions.check_permission(actor, "data.manage")
    body = validation.pick_fields(data, ("preserve_admins",))
    preserve = parse_preserve_flag(body)
    counts = {name: storage.count_records(name) for name in
              ("users", "artworks", "categories", "orders", "reviews", "carts", "wishlists", "follows", "notifications")}
    return {
        "will_replace_with_demo_data": True, "current_counts": counts, "preserve_admins": preserve,
        "keeps_audit_logs": True, "preserve_system_config": True,
        "confirm_token": _issue_confirmation(actor, "RESET", ("demo",), preserve),
        "confirm_expires_in_minutes": config.CONFIRM_TOKEN_MINUTES,
    }


def reset_demo_data(data, actor):
    """POST /api/admin/data/reset  body: {"preserve_admins", "confirm_token", "confirm_text": "RESET"}"""
    permissions.check_permission(actor, "data.manage")
    body = validation.pick_fields(data, ("preserve_admins", "confirm_token", "confirm_text"))
    preserve = parse_preserve_flag(body)
    _check_text(body.get("confirm_text"), config.RESET_CONFIRM_TEXT)

    with storage.transaction():
        _consume_confirmation(body.get("confirm_token"), actor, "RESET", ("demo",), preserve)
        kept_ids = kept_admin_ids(actor, preserve)
        kept_users = [u for u in storage.get_all("users") if u["id"] in kept_ids]
        kept_sessions = [s for s in storage.get_all("sessions") if s["user_id"] in kept_ids]
        entry = logger.create_audit_log(actor["id"], "ADMIN_DATA_RESET", "data", "demo",
                                        {"preserve_admins": preserve, "kept_users": len(kept_users)})
        if entry is None:
            raise AppError("AUDIT_UNAVAILABLE", "ไม่สามารถบันทึก log ได้ จึงไม่รีเซ็ตข้อมูล", 500)
        artwork_files.purge_all_files()                    # ข้อมูลตัวอย่างไม่มีไฟล์ภาพ: ลบไฟล์เดิมทั้งหมดก่อน แล้วค่อยเขียนข้อมูลใหม่
        for collection in ("payments", "promotions", "price_history", "commission_listings", "commissions", "commission_messages", "blacklist", "blocked_ips"):
            storage.save_json(collection, [])
        seed.seed_all(keep_users=kept_users, keep_sessions=kept_sessions, keep_logs=storage.get_all("logs"))
    return {"reset": True, "kept_admin_accounts": len(kept_users)}
