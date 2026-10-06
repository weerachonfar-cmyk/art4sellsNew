"""api.py - ตัวรับ request (Request Router)  ไม่ผูกกับ HTTP server จึงเทสต์ได้โดยไม่ต้องเปิด port

Request Flow (ใช้ร่วมกันทั้ง server.py ตอน Local และ api/index.py ตอนอยู่บน Vercel):
    transport  ->  dispatch(method, path, query, headers, raw_body, peer_ip)
        1) หา route ที่ตรงกับ method + path
        2) หา session token: HttpOnly cookie (เบราว์เซอร์) หรือ Authorization: Bearer (โปรแกรม/เทสต์) -> actor (ผู้เรียก)
        3) ตรวจ Origin / CSRF สำหรับคำขอที่เปลี่ยนข้อมูล (บังคับเข้มเมื่อยืนยันตัวตนด้วย cookie)
        4) แปลง body JSON (try/except, ต้องเป็น application/json)
        5) เรียกฟังก์ชัน business logic ใน modules/*   (ตรวจสิทธิ์ซ้ำที่นั่น)
        6) แปลงผลลัพธ์/error เป็น Response(status, dict, headers)  - ไม่ปล่อย traceback ให้ผู้ใช้
    handle_request(...) เป็นตัวห่อแบบเดิมที่คืนแค่ (status, dict) - ใช้ในเทสต์ที่ไม่ต้องดู header

ทุก response เป็น JSON  สำเร็จ: {...ข้อมูล...}   ผิดพลาด: {"error": {"code", "message", "fields"}}
"""
import json
from collections import namedtuple
from urllib.parse import urlsplit

from backend import config
from backend.modules import (admin, artwork, artwork_files, auth, cart, category, data_management, dev_tools, follow, health, logger,
                             notification, order, password, permissions, review, session_cookie, storage, user, moderation, payment, promotion, commission,
                             validation, wishlist)
from backend.modules.errors import AppError, StorageError, not_found, validation_error, forbidden_error


class Request:
    """ข้อมูลของ request หนึ่งครั้ง ที่ส่งให้ handler ของแต่ละ route"""

    def __init__(self, params, query, body, actor, token, client_ip="unknown", secure=False):
        self.params = params      # dict จาก path เช่น {"id": "w1"}
        self.query = query        # dict จาก query string เช่น {"page": "2"}
        self.body = body          # dict จาก JSON body
        self.actor = actor        # dict ของผู้เรียก หรือ None ถ้ายังไม่ login
        self.token = token        # session token ที่ส่งมา (ใช้ตอน logout / เปลี่ยนรหัสผ่าน)
        self.client_ip = client_ip    # IP ของผู้เรียก (ใช้ทำ rate limit)
        self.secure = secure          # คำขอมาทาง HTTPS หรือไม่ (ใช้ตัดสินว่า cookie ต้องมี Secure)
        self.response_headers = []    # header เพิ่มเติมที่ handler ต้องการส่งกลับ เช่น Set-Cookie

    def set_session_cookie(self, token):
        ttl_seconds = config.SESSION_TTL_HOURS * 3600
        self.response_headers.append(("Set-Cookie", session_cookie.build_session_cookie(token, ttl_seconds, self.secure)))

    def clear_session_cookie(self):
        self.response_headers.append(("Set-Cookie", session_cookie.build_clear_cookie(self.secure)))


# ---------------------------------------------------------------------------
# Handler ของแต่ละ endpoint (แต่ละตัวสั้น ๆ: ส่งต่อให้ module ที่รับผิดชอบ)
# ---------------------------------------------------------------------------
def h_health(req):
    return health.build_health()


def _start_session(req, result):
    """ย้าย token ออกจาก JSON ไปเป็น HttpOnly cookie  (JavaScript ของหน้าเว็บจึงไม่เคยเห็น token)"""
    token = result.pop("token")
    req.set_session_cookie(token)
    return result


def h_register(req):
    return 201, _start_session(req, auth.register_user(req.body))


def h_login(req):
    return 200, _start_session(req, auth.login(req.body, req.client_ip))


def h_logout(req):
    req.clear_session_cookie()                         # ล้าง cookie เสมอ (แม้ session หมดอายุไปแล้ว cookie เก่าก็ต้องหายไป)
    return 200, auth.logout(req.token, req.actor)


# ---- ไฟล์งานศิลปะ (อัปโหลด / preview ลายน้ำ / original ของเจ้าของ / ดาวน์โหลดหลังชำระเงิน) ----
def h_artwork_file_upload(req):
    return 201, artwork_files.upload_artwork_file(req.params["id"], req.body, req.actor)


def h_artwork_files_list(req):
    return 200, artwork_files.list_artwork_files(req.params["id"], req.actor)


def h_artwork_preview(req):
    return 200, artwork_files.get_preview(req.params["id"], req.actor)


def h_artwork_original(req):
    return 200, artwork_files.get_original(req.params["id"], req.actor)


def h_order_download(req):
    return 200, artwork_files.download_delivery(req.params["order_id"], req.params["artwork_id"], req.actor)


# ---- developer tools (เปิดเมื่อ A4S_DEV_TOOLS=true + development เท่านั้น; ปิดอยู่ = 404) ----
def h_dev_mailbox_list(req):
    return 200, dev_tools.list_mailbox(req.actor)


def h_dev_mailbox_clear(req):
    return 200, dev_tools.clear_mailbox(req.actor)


def h_me(req):
    if req.actor is None:
        raise AppError("UNAUTHORIZED", "กรุณาเข้าสู่ระบบ", 401)
    allowed_at = password.next_change_allowed_at(user.get_user_record(req.actor["id"]))
    payload = {"user": req.actor,
               "password_change_available_at": allowed_at.isoformat(timespec="seconds") if allowed_at else None}
    if req.actor["role"] == "ADMIN" and config.dev_mailbox_enabled():
        payload["dev_tools"] = True                    # บอกเฉพาะ ADMIN เมื่อเปิด Developer Mailbox (ปิดอยู่ = ไม่มี field นี้เลย)
    return 200, payload


# ---- categories ----
def h_categories_list(req):
    return 200, category.list_categories()


def h_categories_create(req):
    return 201, category.create_category(req.body, req.actor)


def h_categories_update(req):
    return 200, category.update_category(req.params["id"], req.body, req.actor)


def h_categories_delete(req):
    return 200, category.delete_category(req.params["id"], req.actor)


# ---- artworks ----
def h_artworks_list(req):
    return 200, artwork.list_artworks(req.query, req.actor, order.get_locked_artwork_ids())


def h_artworks_get(req):
    return 200, artwork.get_artwork(req.params["id"], req.actor, order.get_locked_artwork_ids())


def h_artworks_create(req):
    return 201, artwork.create_artwork(req.body, req.actor)


def h_artworks_update(req):
    return 200, artwork.update_artwork(req.params["id"], req.body, req.actor)


def h_artworks_delete(req):
    return 200, artwork.delete_artwork(req.params["id"], req.actor)


def h_artworks_submit(req):
    return 200, artwork.submit_artwork(req.params["id"], req.actor)


def h_artworks_approve(req):
    return 200, artwork.approve_artwork(req.params["id"], req.actor)


def h_artworks_reject(req):
    return 200, artwork.reject_artwork(req.params["id"], req.actor, req.body)


def h_artworks_eligibility(req):
    eligible, reason, order_id = review.check_review_eligibility(req.actor, req.params["id"])
    return 200, {"eligible": eligible, "reason": reason, "order_id": order_id}


# ---- artists ----
def h_artists_list(req):
    return 200, user.list_artists()


def h_artists_get(req):
    return 200, user.get_artist(req.params["id"])


# ---- orders ----
def h_orders_list(req):
    return 200, order.list_orders(req.query, req.actor)


def h_orders_get(req):
    return 200, order.get_order(req.params["id"], req.actor)


def h_orders_create(req):
    return 201, order.create_order(req.body, req.actor)


def h_orders_update(req):
    return 200, order.update_order_status(req.params["id"], req.body, req.actor)


def h_orders_delete(req):
    return 200, order.delete_order(req.params["id"], req.actor)


# ---- reviews ----
def h_reviews_list(req):
    return 200, review.list_reviews(req.query, req.actor)


def h_reviews_create(req):
    return 201, review.create_review(req.body, req.actor)


def h_reviews_update(req):
    return 200, review.update_review(req.params["id"], req.body, req.actor)


def h_reviews_delete(req):
    return 200, review.delete_review(req.params["id"], req.actor)


# ---- users (admin) ----
def h_users_list(req):
    return 200, user.list_users(req.query, req.actor)


def h_users_get(req):
    return 200, user.get_user(req.params["id"], req.actor)


def h_users_create(req):
    permissions.check_permission(req.actor, "user.manage")
    return 201, user.create_user(req.body, config.ROLES, actor=req.actor)


def h_users_update(req):
    return 200, user.update_user(req.params["id"], req.body, req.actor)


def h_users_delete(req):
    return 200, user.delete_user(req.params["id"], req.actor)


def h_users_ban(req):
    return 200, admin.ban_user(req.params["id"], req.actor)


def h_users_unban(req):
    return 200, admin.unban_user(req.params["id"], req.actor)


# ---- admin ----
def h_dashboard(req):
    return 200, admin.get_dashboard_summary(req.actor)


def h_logs(req):
    return 200, admin.get_audit_logs(req.query, req.actor)


# ---- password management (Phase 3.5) ----
def h_change_password(req):
    return 200, password.change_password(req.body, req.actor, req.token)


def h_forgot_password(req):
    return 200, password.request_password_reset(req.body)


def h_verify_reset_code(req):
    return 200, password.verify_reset_code(req.body)


def h_reset_password(req):
    return 200, password.reset_password(req.body)


# ---- cart / wishlist / follows / notifications (ข้อมูลส่วนตัว: ต้อง login และเป็นของตัวเองเท่านั้น) ----
def h_cart_get(req):
    return 200, cart.build_cart_view(req.actor)


def h_cart_add(req):
    result = cart.add_to_cart(req.body, req.actor)
    return (201 if result["created"] else 200), result


def h_cart_update(req):
    return 200, cart.update_item(req.params["id"], req.body, req.actor)


def h_cart_remove(req):
    return 200, cart.remove_item(req.params["id"], req.actor)


def h_cart_clear(req):
    return 200, cart.clear_cart(req.actor)


def h_cart_checkout(req):
    return 201, cart.checkout(req.actor)


def h_wishlist_get(req):
    return 200, wishlist.list_wishlist(req.actor)


def h_wishlist_add(req):
    result = wishlist.add_to_wishlist(req.body, req.actor)
    return (201 if result["created"] else 200), result


def h_wishlist_remove(req):
    return 200, wishlist.remove_from_wishlist(req.params["id"], req.actor)


def h_follows_get(req):
    return 200, follow.list_follows(req.actor)


def h_follows_add(req):
    result = follow.follow_artist(req.body, req.actor)
    return (201 if result["created"] else 200), result


def h_follows_remove(req):
    return 200, follow.unfollow(req.params["id"], req.actor)


def h_notifications_list(req):
    return 200, notification.list_notifications(req.query, req.actor)


def h_notifications_read(req):
    return 200, notification.mark_read(req.params["id"], req.actor)


def h_notifications_read_all(req):
    return 200, notification.mark_all_read(req.actor)


# ---- admin data management ----
def h_data_clear_preview(req):
    return 200, data_management.preview_clear(req.body, req.actor)


def h_data_clear(req):
    return 200, data_management.clear_data(req.body, req.actor)


def h_data_reset_preview(req):
    return 200, data_management.preview_reset(req.body, req.actor)


def h_data_reset(req):
    return 200, data_management.reset_demo_data(req.body, req.actor)



# ---- payments / promotions / commissions / moderation (PART 2) ----
def h_payment_get(req):
    return 200, payment.get_payment(req.params["order_id"], req.actor)

def h_payment_submit(req):
    return 200, payment.submit_payment(req.body, req.actor)

def h_payment_verify(req):
    return 200, payment.verify_payment(req.params["order_id"], req.body, req.actor)

def h_promotions_list(req):
    return 200, promotion.list_promotions(req.actor, req.query.get("artist_id"))

def h_promotions_create(req):
    return 201, promotion.create_promotion(req.body, req.actor)

def h_price_history(req):
    return 200, promotion.history(req.params["artwork_id"])

def h_commission_listings(req):
    return 200, commission.list_listings(req.query.get("artist_id"))

def h_commission_listing_create(req):
    return 201, commission.create_listing(req.body, req.actor)

def h_commissions_list(req):
    return 200, commission.list_jobs(req.actor, req.query.get("scope"))

def h_commissions_create(req):
    return 201, commission.create_job(req.body, req.actor)

def h_commissions_get(req):
    record = commission._job(req.params["id"])
    if not record:
        raise not_found("Commission")
    if req.actor is None or req.actor["id"] not in (record["artist_id"], record["buyer_id"]) and not permissions.has_permission(req.actor, "commission.manage_any"):
        raise forbidden_error()
    return 200, record

def h_commissions_action(req):
    return 200, commission.advance(req.params["id"], req.params["action"].upper(), req.actor)

def h_commissions_pay_verified(req):
    return 200, commission.mark_payment_verified(req.params["id"], req.actor)

def h_commissions_submit_payment(req):
    return 200, commission.submit_payment(req.params["id"], req.actor)

def h_blacklist_list(req):
    return 200, moderation.list_blacklist(req.actor)

def h_blacklist_add(req):
    return 201, moderation.add_blacklist(req.body, req.actor)

def h_blacklist_remove(req):
    return 200, moderation.remove_blacklist(req.params["id"], req.actor)

def h_ip_list(req):
    return 200, moderation.list_ips(req.actor)

def h_ip_add(req):
    return 201, moderation.add_ip(req.body, req.actor)

def h_ip_remove(req):
    return 200, moderation.remove_ip(req.params["ip"], req.actor)

UPLOAD_HANDLERS = {h_artwork_file_upload}              # handler ที่รับ body ใหญ่ (ไฟล์ภาพส่งเป็น base64 ใน JSON)

# ตารางเส้นทาง: (method, path, handler)  ส่วนที่ขึ้นต้นด้วย ":" คือตัวแปรใน path
ROUTES = [
    ("GET", "/api/health", h_health),
    ("POST", "/api/register", h_register),
    ("POST", "/api/login", h_login),
    ("POST", "/api/logout", h_logout),
    ("GET", "/api/me", h_me),

    ("GET", "/api/categories", h_categories_list),
    ("POST", "/api/categories", h_categories_create),
    ("PUT", "/api/categories/:id", h_categories_update),
    ("DELETE", "/api/categories/:id", h_categories_delete),

    ("GET", "/api/artworks", h_artworks_list),
    ("POST", "/api/artworks", h_artworks_create),
    ("GET", "/api/artworks/:id", h_artworks_get),
    ("PUT", "/api/artworks/:id", h_artworks_update),
    ("DELETE", "/api/artworks/:id", h_artworks_delete),
    ("POST", "/api/artworks/:id/submit", h_artworks_submit),
    ("POST", "/api/artworks/:id/approve", h_artworks_approve),
    ("POST", "/api/artworks/:id/reject", h_artworks_reject),
    ("GET", "/api/artworks/:id/review-eligibility", h_artworks_eligibility),

    ("POST", "/api/artworks/:id/file", h_artwork_file_upload),
    ("GET", "/api/artworks/:id/files", h_artwork_files_list),
    ("GET", "/api/artworks/:id/preview", h_artwork_preview),
    ("GET", "/api/artworks/:id/original", h_artwork_original),
    ("GET", "/api/orders/:order_id/artworks/:artwork_id/download", h_order_download),

    ("GET", "/api/artists", h_artists_list),
    ("GET", "/api/artists/:id", h_artists_get),

    ("GET", "/api/orders", h_orders_list),
    ("POST", "/api/orders", h_orders_create),
    ("GET", "/api/orders/:id", h_orders_get),
    ("PUT", "/api/orders/:id", h_orders_update),
    ("DELETE", "/api/orders/:id", h_orders_delete),

    ("GET", "/api/reviews", h_reviews_list),
    ("POST", "/api/reviews", h_reviews_create),
    ("PUT", "/api/reviews/:id", h_reviews_update),
    ("DELETE", "/api/reviews/:id", h_reviews_delete),

    ("GET", "/api/users", h_users_list),
    ("POST", "/api/users", h_users_create),
    ("GET", "/api/users/:id", h_users_get),
    ("PUT", "/api/users/:id", h_users_update),
    ("DELETE", "/api/users/:id", h_users_delete),
    ("POST", "/api/users/:id/ban", h_users_ban),
    ("POST", "/api/users/:id/unban", h_users_unban),

    ("GET", "/api/dashboard", h_dashboard),
    ("GET", "/api/logs", h_logs),

    ("POST", "/api/auth/change-password", h_change_password),
    ("POST", "/api/auth/forgot-password", h_forgot_password),
    ("POST", "/api/auth/resend-reset-code", h_forgot_password),
    ("POST", "/api/auth/verify-reset-code", h_verify_reset_code),
    ("POST", "/api/auth/reset-password", h_reset_password),

    ("GET", "/api/cart", h_cart_get),
    ("POST", "/api/cart", h_cart_add),
    ("DELETE", "/api/cart", h_cart_clear),
    ("POST", "/api/cart/checkout", h_cart_checkout),
    ("PUT", "/api/cart/:id", h_cart_update),
    ("DELETE", "/api/cart/:id", h_cart_remove),
    ("GET", "/api/wishlist", h_wishlist_get),
    ("POST", "/api/wishlist", h_wishlist_add),
    ("DELETE", "/api/wishlist/:id", h_wishlist_remove),
    ("GET", "/api/follows", h_follows_get),
    ("POST", "/api/follows", h_follows_add),
    ("DELETE", "/api/follows/:id", h_follows_remove),
    ("GET", "/api/me/notifications", h_notifications_list),
    ("POST", "/api/me/notifications/read-all", h_notifications_read_all),
    ("PUT", "/api/me/notifications/:id", h_notifications_read),

    ("GET", "/api/orders/:order_id/payment", h_payment_get),
    ("POST", "/api/orders/:order_id/payment", h_payment_submit),
    ("POST", "/api/orders/:order_id/payment/verify", h_payment_verify),
    ("GET", "/api/promotions", h_promotions_list),
    ("POST", "/api/promotions", h_promotions_create),
    ("GET", "/api/artworks/:artwork_id/price-history", h_price_history),
    ("GET", "/api/commission-listings", h_commission_listings),
    ("POST", "/api/commission-listings", h_commission_listing_create),
    ("GET", "/api/commissions", h_commissions_list),
    ("GET", "/api/commissions/:id", h_commissions_get),
    ("POST", "/api/commissions", h_commissions_create),
    ("POST", "/api/commissions/:id/payment", h_commissions_submit_payment),
    ("POST", "/api/commissions/:id/verify-payment", h_commissions_pay_verified),
    ("POST", "/api/commissions/:id/:action", h_commissions_action),
    ("GET", "/api/admin/blacklist", h_blacklist_list),
    ("POST", "/api/admin/blacklist", h_blacklist_add),
    ("DELETE", "/api/admin/blacklist/:id", h_blacklist_remove),
    ("GET", "/api/admin/ip-blocks", h_ip_list),
    ("POST", "/api/admin/ip-blocks", h_ip_add),
    ("DELETE", "/api/admin/ip-blocks/:id", h_ip_remove),

    ("GET", "/api/dev/mailbox", h_dev_mailbox_list),
    ("DELETE", "/api/dev/mailbox", h_dev_mailbox_clear),

    ("POST", "/api/admin/data/clear/preview", h_data_clear_preview),
    ("POST", "/api/admin/data/clear", h_data_clear),
    ("POST", "/api/admin/data/reset/preview", h_data_reset_preview),
    ("POST", "/api/admin/data/reset", h_data_reset),
]

# query string ที่แต่ละ endpoint รู้จัก (allowlist)  endpoint ที่ไม่อยู่ในตาราง = ไม่รับ query เลย
QUERY_PARAMS = {
    h_artworks_list: validation.ARTWORK_QUERY_PARAMS,
    h_orders_list: {"scope", "status", "page", "page_size"},
    h_reviews_list: {"artwork_id", "artist_id", "user_id", "page", "page_size"},
    h_users_list: {"q", "role", "status", "page", "page_size"},
    h_logs: {"action", "actor_id", "target_type", "target_id", "result", "page", "page_size"},
    h_notifications_list: {"unread", "page", "page_size"},
    h_promotions_list: {"artist_id"},
    h_commission_listings: {"artist_id"},
    h_commissions_list: {"scope"},
}


# ---------------------------------------------------------------------------
# ส่วนกลางของการรับ request
# ---------------------------------------------------------------------------
def match_route(method, path):
    """หา route ที่ตรง  คืน tuple (handler, params, path_exists)
    path_exists=True แต่ handler=None หมายถึง path มีจริงแต่ method ไม่ถูก (405)
    """
    parts = [p for p in path.strip("/").split("/")]
    path_exists = False
    for route_method, pattern, handler in ROUTES:
        pattern_parts = pattern.strip("/").split("/")
        if len(pattern_parts) != len(parts):
            continue
        params, matched = {}, True
        for pattern_part, actual in zip(pattern_parts, parts):
            if pattern_part.startswith(":"):
                params[pattern_part[1:]] = actual
            elif pattern_part != actual:
                matched = False
                break
        if not matched:
            continue
        path_exists = True
        if route_method == method:
            return handler, params, True
    return None, {}, path_exists


def extract_bearer_token(headers):
    """ดึง token จาก header  Authorization: Bearer <token>  (ไม่มี/รูปแบบผิด -> None)
    ใช้สำหรับโปรแกรม/เทสต์ที่ไม่ใช่เบราว์เซอร์  เบราว์เซอร์ใช้ HttpOnly cookie แทน"""
    value = ""
    for key, header_value in headers.items():
        if key.lower() == "authorization":
            value = header_value
    pieces = value.split(" ", 1)
    if len(pieces) == 2 and pieces[0].lower() == "bearer" and pieces[1].strip():
        return pieces[1].strip()
    return None


def extract_token(headers):
    """หา session token ของคำขอนี้  คืน tuple (token, แหล่งที่มา)  แหล่งที่มา = "bearer" / "cookie" / None
    Bearer ที่ส่งมาชัดเจนมาก่อน (โปรแกรมที่ตั้งใจส่งเอง ไม่ใช่ credential ที่เบราว์เซอร์แนบให้อัตโนมัติ จึงไม่เสี่ยง CSRF)"""
    bearer = extract_bearer_token(headers)
    if bearer:
        return bearer, "bearer"
    cookie_token = session_cookie.read_session_token(headers)
    if cookie_token:
        return cookie_token, "cookie"
    return None, None


def _reject_constant(name):
    """json.loads เรียกเมื่อเจอ NaN / Infinity / -Infinity (ไม่ใช่ JSON มาตรฐาน) -> ปฏิเสธ"""
    raise ValueError("non-standard JSON constant: " + name)


def extract_header(headers, name):
    """อ่านค่า header แบบไม่สนตัวพิมพ์เล็ก/ใหญ่ (ไม่มี -> "")"""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def parse_json_body(raw_body, content_type="application/json", limit=None):
    """แปลง body (bytes) เป็น dict  body ว่างได้ แต่ถ้ามีต้องเป็น JSON object และส่งแบบ application/json
    (การบังคับ Content-Type ช่วยกัน cross-site form post ส่งข้อมูลมาโดยเบราว์เซอร์ไม่ถามก่อน)
    คืนค่า dict หรือ raise AppError (400 / 413 / 415)
    """
    if not raw_body:
        return {}
    if len(raw_body) > (limit or config.MAX_BODY_BYTES):
        raise AppError("PAYLOAD_TOO_LARGE", "ข้อมูลที่ส่งมามีขนาดใหญ่เกินไป", 413)
    if content_type.split(";")[0].strip().lower() != "application/json":
        raise AppError("UNSUPPORTED_MEDIA_TYPE", "ต้องส่งข้อมูลแบบ application/json", 415)
    try:
        data = json.loads(raw_body.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, RecursionError):               # ValueError ครอบคลุม JSON ผิด, UTF-8 ผิด, เลขใหญ่เกินกำหนด, NaN
        raise AppError("INVALID_JSON", "ข้อมูลที่ส่งมาไม่ถูกต้อง (ต้องเป็น JSON)", 400)
    if not isinstance(data, dict):
        raise AppError("INVALID_JSON", "ข้อมูลที่ส่งมาต้องเป็น JSON object", 400)
    return data


def error_payload(code, message):
    return {"error": {"code": code, "message": message, "fields": {}}}


STATE_CHANGING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def check_origin(method, headers, cookie_authenticated=False):
    """Origin / CSRF protection สำหรับคำขอที่เปลี่ยนข้อมูล (POST/PUT/PATCH/DELETE)

    เมื่อใช้ cookie เบราว์เซอร์จะแนบ cookie ให้เองแม้คำขอถูกสั่งมาจากเว็บอื่น (CSRF) จึงตรวจเป็นชั้น ๆ:
      1) มี Origin   -> ต้องเป็นเว็บเดียวกับ Host หรืออยู่ใน A4S_CORS_ORIGINS  ไม่งั้น 403   (Origin: null ก็ 403)
      2) ไม่มี Origin แต่มี Sec-Fetch-Site -> ต้องเป็น same-origin / none เท่านั้น
      3) ไม่มีทั้งสอง และ "ยืนยันตัวตนด้วย cookie" -> 403  (เบราว์เซอร์จริงแนบ Origin ให้ทุกคำขอ POST/PUT/DELETE เสมอ;
         ถ้าไม่มี แปลว่าไม่ใช่เบราว์เซอร์ที่ทำงานปกติ จึงไม่ยอมให้ใช้ cookie ทำรายการ)
      4) ไม่มีทั้งสอง และไม่ได้ใช้ cookie (curl, เทสต์, Bearer, คำขอที่ยังไม่ login) -> ผ่านตามปกติ
    ส่วนอื่นที่ช่วยกัน CSRF: SameSite=Lax บน cookie, บังคับ Content-Type: application/json (ฟอร์มข้ามเว็บส่งแบบนี้ไม่ได้
    โดยไม่ผ่าน CORS preflight), ไม่เปิด Access-Control-Allow-Origin: *   ดู docs/SECURITY_STATUS.md
    """
    if method.upper() not in STATE_CHANGING_METHODS:
        return
    origin = extract_header(headers, "Origin")
    if origin:
        if origin in config.ALLOWED_ORIGINS:
            return
        host = extract_header(headers, "Host")
        netloc = urlsplit(origin).netloc
        if netloc and host and netloc.lower() == host.lower():
            return
        raise AppError("CROSS_ORIGIN_BLOCKED", "คำขอนี้มาจากเว็บไซต์อื่นจึงไม่ได้รับอนุญาต", 403)
    fetch_site = extract_header(headers, "Sec-Fetch-Site").strip().lower()
    if fetch_site:
        if fetch_site in ("same-origin", "none"):
            return
        raise AppError("CROSS_ORIGIN_BLOCKED", "คำขอนี้มาจากเว็บไซต์อื่นจึงไม่ได้รับอนุญาต", 403)
    if cookie_authenticated:
        raise AppError("CROSS_ORIGIN_BLOCKED", "ไม่สามารถยืนยันที่มาของคำขอได้", 403)


def check_request_inputs(handler, params, query):
    """ตรวจข้อมูลที่มากับ URL (untrusted): id ใน path, ชื่อ/ค่าของ query string  ผิด -> raise 400"""
    errors = {}
    for name, value in params.items():
        problem = validation.validate_id(value, name)
        if problem:
            errors[name] = problem
    errors.update(validation.check_query_values(query))
    errors.update(validation.check_allowed_params(query, QUERY_PARAMS.get(handler, set())))
    for name, value in query.items():
        if name.endswith("_id") and value and name not in errors:
            problem = validation.validate_id(value, name)
            if problem:
                errors[name] = problem
    if errors:
        raise validation_error(errors, "พารามิเตอร์ไม่ถูกต้อง")


Response = namedtuple("Response", "status payload headers")   # headers = list ของ (ชื่อ, ค่า) - Set-Cookie ซ้ำได้หลายตัว


def body_limit_for(method, path):
    """ขนาด body สูงสุดของ endpoint นั้น (ปกติ 1 MB / endpoint อัปโหลดไฟล์ใหญ่กว่าเพราะส่งเป็น base64)"""
    handler, _params, _exists = match_route(method.upper(), path)
    return config.UPLOAD_BODY_BYTES if handler in UPLOAD_HANDLERS else config.MAX_BODY_BYTES


def dispatch(method, path, query, headers, raw_body, peer_ip=None):
    """รับ request หนึ่งครั้ง คืน Response(status, payload, headers)

    พารามิเตอร์: method ("GET"...), path ("/api/artworks"), query (dict ข้อความ->ข้อความ), headers (dict),
                raw_body (bytes), peer_ip (IP ที่ต่อเข้ามาจริง จาก transport)
    ไม่ raise ออกไปข้างนอกเด็ดขาด - ทุก error ถูกแปลงเป็น JSON ภาษาอ่านง่าย (ไม่มี traceback)
    """
    req = None
    try:
        handler, params, path_exists = match_route(method.upper(), path)
        if handler is None:
            if path_exists:
                return Response(405, error_payload("METHOD_NOT_ALLOWED", "ไม่รองรับวิธีเรียกนี้"), [])
            raise not_found("ปลายทาง API")

        storage.begin_request()                        # cache การอ่านต่อ request (มีผลเฉพาะ Redis)
        token, token_source = extract_token(headers)
        client_ip = session_cookie.client_ip(headers, peer_ip)
        if path != "/api/health" and moderation.is_blocked_ip(client_ip):
            return Response(403, error_payload("IP_BLOCKED", "คำขอนี้ไม่ได้รับอนุญาต"), [])
        check_origin(method, headers, cookie_authenticated=(token_source == "cookie"))
        check_request_inputs(handler, params, query)
        actor = auth.authenticate(token)
        content_type = extract_header(headers, "Content-Type")
        body = parse_json_body(raw_body, content_type, body_limit_for(method, path)) \
            if method.upper() in ("POST", "PUT", "PATCH") else {}
        req = Request(params, query, body, actor, token, client_ip,
                      session_cookie.is_https(headers))
        status, payload = handler(req)
        return Response(status, payload, req.response_headers)

    except StorageError as err:                        # error ของที่เก็บข้อมูล: เก็บรายละเอียดไว้ใน log เท่านั้น
        logger.log_exception("storage error " + err.code + ": " + err.detail, err)
        return Response(err.status, err.to_dict(), req.response_headers if req else [])
    except AppError as err:                            # error ที่ระบบรู้จัก (validation, 403, 404 ...)
        return Response(err.status, err.to_dict(), req.response_headers if req else [])
    except Exception as err:                           # error ที่คาดไม่ถึง: log traceback แต่ตอบข้อความกลาง ๆ
        logger.log_exception("unexpected error on " + method + " " + path, err)
        return Response(500, error_payload("INTERNAL_ERROR", "เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่อีกครั้ง"), [])
    finally:
        storage.end_request()


def handle_request(method, path, query, headers, raw_body):
    """ตัวห่อแบบเดิม: คืนแค่ (status, dict)  ใช้ในเทสต์/ที่ไม่ต้องดู header (ผลลัพธ์เหมือน dispatch ทุกประการ)"""
    result = dispatch(method, path, query, headers, raw_body)
    return result.status, result.payload
