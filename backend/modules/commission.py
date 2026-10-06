"""commission.py - commission marketplace workflow (prototype)."""
from backend import config
from backend.modules import logger, notification, permissions, storage, validation, payment
from backend.modules.errors import conflict_error, forbidden_error, not_found, validation_error
from backend.modules.utils import now_iso, minutes_from_now_iso

LISTING_STATUSES = ("LISTING", "PAUSED")
JOB_STATES = config.COMMISSION_STATES

def _listing(id):
    return storage.get_record("commission_listings", id)

def _job(id):
    return storage.get_record("commissions", id)

def validate_listing(data):
    clean, errors = {}, {}
    for field, label, lo, hi in (("title", "title", 2, 100), ("description", "description", 10, 2000), ("conditions", "conditions", 0, 1500)):
        if field in data or field != "conditions":
            problem = validation.validate_string(data.get(field, ""), label, lo, hi, single_line=(field=="title"))
            if problem: errors[field] = problem
            else: clean[field] = validation.clean_text(data.get(field, ""))
    price, problem = validation.validate_price(data.get("price"))
    if problem: errors["price"] = problem
    else: clean["price"] = price
    days, problem = validation.validate_integer(data.get("days", 7), "days", 1, 365)
    if problem: errors["days"] = problem
    else: clean["days"] = days
    revisions, problem = validation.validate_integer(data.get("revisions", 1), "revisions", 0, 20)
    if problem: errors["revisions"] = problem
    else: clean["revisions"] = revisions
    samples = data.get("samples", [])
    if not isinstance(samples, list) or len(samples) > 20 or any(not isinstance(x, str) or len(x) > 2048 for x in samples):
        errors["samples"] = "samples ต้องเป็นรายการ URL ไม่เกิน 20 รายการ"
    else: clean["samples"] = list(samples)
    return clean, errors

def create_listing(data, actor):
    permissions.check_permission(actor, "commission.manage")
    clean, errors = validate_listing(data)
    if errors: raise validation_error(errors)
    rec = {**clean, "artist_id": actor["id"], "status": "LISTING", "created_at": now_iso(), "updated_at": now_iso()}
    out = storage.create_record("commission_listings", rec, "cl")
    logger.create_audit_log(actor["id"], "COMMISSION_LISTING_CREATED", "commission_listing", out["id"], {})
    return out

def list_listings(artist_id=None):
    rows = [x for x in storage.get_all("commission_listings") if x["status"] == "LISTING"]
    if artist_id: rows = [x for x in rows if x["artist_id"] == artist_id]
    return {"items": list(reversed(rows))}

def list_jobs(actor, scope=None):
    """List commission jobs visible to the current user.
    USER -> buyer jobs, ARTIST -> artist jobs, ADMIN -> all jobs.
    """
    if actor is None:
        from backend.modules.errors import unauthorized_error
        raise unauthorized_error()
    role = actor.get("role")
    if scope is None or scope == "mine":
        scope = "sales" if role == "ARTIST" else "mine"
    if scope not in ("mine", "sales", "all"):
        raise validation_error({"scope": "scope ต้องเป็น mine, sales หรือ all"})
    if scope == "all":
        permissions.check_permission(actor, "commission.manage_any")
    elif scope == "sales":
        permissions.check_permission(actor, "commission.manage")
    else:
        permissions.check_permission(actor, "commission.request")
    rows=[]
    for job in storage.get_all("commissions"):
        if scope == "mine" and job["buyer_id"] != actor["id"]:
            continue
        if scope == "sales" and job["artist_id"] != actor["id"]:
            continue
        rows.append(dict(job))
    rows.reverse()
    for row in rows:
        if row.get("deadline_at"):
            import datetime
            try:
                due=datetime.datetime.fromisoformat(row["deadline_at"].replace("Z", "+00:00"))
                row["deadline_passed"]=datetime.datetime.now(datetime.timezone.utc) > due and row.get("state") not in ("COMPLETED", "CANCELLED", "REJECTED")
            except ValueError:
                row["deadline_passed"]=False
        else:
            row["deadline_passed"]=False
    return {"items": rows}

def create_job(data, actor):
    permissions.check_permission(actor, "commission.request")
    body = validation.pick_fields(data, ("listing_id", "brief", "payment_method"))
    problem = validation.validate_id(body.get("listing_id"), "listing_id")
    if problem: raise validation_error({"listing_id": problem})
    listing = _listing(body["listing_id"])
    if not listing or listing["status"] != "LISTING": raise not_found("Commission listing")
    if listing["artist_id"] == actor["id"]: raise conflict_error("OWN_COMMISSION", "รับงานของตัวเองไม่ได้")
    brief = body.get("brief")
    if not isinstance(brief, dict): raise validation_error({"brief": "brief ต้องเป็น object"})
    clean_brief = {}
    for key in ("type", "details", "references", "size", "style", "background", "character_count", "additional_requests"):
        val = brief.get(key, "")
        if key == "character_count":
            num, err = validation.validate_integer(val or 1, key, 1, 50)
            if err: raise validation_error({key: err})
            clean_brief[key] = num
        elif isinstance(val, str):
            if len(val) > 2000: raise validation_error({key: key + " ยาวเกินไป"})
            clean_brief[key] = validation.clean_text(val)
        else:
            clean_brief[key] = val
    method = body.get("payment_method", "QR_PAYMENT")
    if method not in payment.METHODS: raise validation_error({"payment_method": "payment_method ไม่ถูกต้อง"})
    now = now_iso()
    job = {"listing_id": listing["id"], "artist_id": listing["artist_id"], "buyer_id": actor["id"], "title": listing["title"],
           "price": listing["price"], "duration_days": listing["days"], "revision_count": listing["revisions"],
           "brief": clean_brief, "brief_snapshot": None, "payment_method": method, "payment_status": "UNPAID",
           "state": "BRIEF", "created_at": now, "updated_at": now, "accepted_at": None, "deadline_at": None,
           "delivered_at": None, "completed_at": None, "delivery_note": None}
    job = storage.create_record("commissions", job, "co")
    logger.create_audit_log(actor["id"], "COMMISSION_CREATED", "commission", job["id"], {})
    return job

def submit_payment(job_id, actor):
    permissions.check_permission(actor, "payment.submit")
    job = _job(job_id)
    if not job: raise not_found("Commission")
    if job["buyer_id"] != actor["id"]: raise forbidden_error()
    if job["state"] not in ("BRIEF", "PAYMENT"):
        raise conflict_error("PAYMENT_NOT_ALLOWED", "Commission ยังไม่อยู่ในขั้นตอนชำระเงิน")
    updated = storage.update_record("commissions", job_id, {"state": "PAYMENT", "payment_status": "PENDING_VERIFICATION", "updated_at": now_iso()})
    logger.create_audit_log(actor["id"], "COMMISSION_PAYMENT_SUBMITTED", "commission", job_id, {})
    return updated

def advance(job_id, new_state, actor):
    job = _job(job_id)
    if not job: raise not_found("Commission")
    owns = actor and actor["id"] in (job["artist_id"], job["buyer_id"])
    if not owns and not permissions.has_permission(actor, "commission.manage_any"): raise forbidden_error()
    if new_state not in config.COMMISSION_STATES or not validation.can_transition(job["state"], new_state, config.COMMISSION_TRANSITIONS):
        raise conflict_error("INVALID_TRANSITION", "เปลี่ยนสถานะ commission ไม่ได้")
    changes = {"state": new_state, "updated_at": now_iso()}
    if new_state == "ACCEPTED":
        if actor["id"] != job["artist_id"]: raise forbidden_error()
        changes.update({"accepted_at": now_iso(), "brief_snapshot": dict(job["brief"], snapshot_at=now_iso()),
                        "deadline_at": minutes_from_now_iso(job["duration_days"] * 24 * 60)})
        # payment must be verified conceptually before timer, but prototype stores the verified gate
        if job.get("payment_status") != "PAID": raise conflict_error("PAYMENT_REQUIRED", "ต้องยืนยันการชำระเงินก่อนรับงาน")
    elif new_state == "REJECTED":
        if actor["id"] != job["artist_id"]: raise forbidden_error()
    elif new_state == "IN_PROGRESS":
        if actor["id"] != job["artist_id"]: raise forbidden_error()
        if not job.get("accepted_at") or not job.get("deadline_at"): raise conflict_error("TIMER_NOT_READY", "ยังไม่ถึงขั้นเริ่มนับเวลา")
    elif new_state == "DELIVERED":
        if actor["id"] != job["artist_id"]: raise forbidden_error()
        changes["delivered_at"] = now_iso()
    elif new_state == "COMPLETED":
        if actor["id"] != job["buyer_id"]: raise forbidden_error()
        changes["completed_at"] = now_iso()
    updated = storage.update_record("commissions", job_id, changes)
    logger.create_audit_log(actor["id"], "COMMISSION_" + new_state, "commission", job_id, {})
    notification.notify(job["buyer_id"], "COMMISSION_UPDATE", "Commission " + job_id + " -> " + new_state)
    notification.notify(job["artist_id"], "COMMISSION_UPDATE", "Commission " + job_id + " -> " + new_state)
    return updated

def mark_payment_verified(job_id, actor):
    job = _job(job_id)
    if not job: raise not_found("Commission")
    if not permissions.has_permission(actor, "payment.verify") and actor["id"] != job["artist_id"]: raise forbidden_error()
    if job.get("state") not in ("PAYMENT", "PAYMENT_VERIFIED"):
        raise conflict_error("PAYMENT_NOT_ALLOWED", "Commission ยังไม่อยู่ในขั้นตอนตรวจสอบการชำระเงิน")
    changes = {"payment_status": "PAID", "updated_at": now_iso()}
    if job.get("state") == "PAYMENT":
        changes["state"] = "PAYMENT_VERIFIED"
    updated = storage.update_record("commissions", job_id, changes)
    logger.create_audit_log(actor["id"], "COMMISSION_PAYMENT_VERIFIED", "commission", job_id, {})
    notification.notify(job["buyer_id"], "COMMISSION_UPDATE", "Commission " + job_id + " -> PAYMENT_VERIFIED")
    notification.notify(job["artist_id"], "COMMISSION_UPDATE", "Commission " + job_id + " -> PAYMENT_VERIFIED")
    return updated
