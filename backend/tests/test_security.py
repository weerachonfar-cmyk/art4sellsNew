"""test_security.py - ชุดทดสอบ Phase 3.5 (ข้อมูลส่วนตัวรายผู้ใช้, รหัสผ่าน/OTP, จัดการข้อมูลของ admin, input security, fuzz)

ไม่ต้องรันไฟล์นี้ตรง ๆ - ถูกเรียกพร้อมกับ test_backend.py:   python backend/tests/test_backend.py
(ใช้ตัวช่วยและข้อมูลตัวอย่างชุดเดียวกัน: call(), login(), WORK_DIR ฯลฯ)
"""
import contextlib
import inspect
import io
import json
import random
import re
import secrets
import socket
import string
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import test_backend as tb
from backend import config, seed
from backend.modules import auth, email_service, password, security, storage, uploads, validation

call, login = tb.call, tb.login
NEW_PASSWORD = "Another9Pass!"


# ---------------------------------------------------------------------------
# ตัวช่วย
# ---------------------------------------------------------------------------
def code_of(message):
    """ดึงรหัส OTP 5 หลักจากอีเมลที่ถูกส่ง (เทสต์เท่านั้น)"""
    return re.search(r"\b(\d{5})\b", message["body"]).group(1)


@contextlib.contextmanager
def mailbox():
    """เก็บอีเมลที่ระบบส่งไว้ในรายการ แทนการพิมพ์ลงหน้าจอ"""
    outbox = []
    email_service.set_transport(outbox.append)
    try:
        yield outbox
    finally:
        email_service.set_transport(None)


def age_reset_requests(seconds=7200):
    """ทำให้การขอรหัสครั้งก่อน ๆ เก่าลง (เลี่ยงการรอ cooldown จริง)"""
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    for entry in storage.get_all("reset_requests"):
        storage.update_record("reset_requests", entry["id"], {"requested_at": old})


def logs(action=None):
    entries = tb.read_json_file("logs")
    return [e for e in entries if action is None or e["action"] == action]


def ask_code(outbox, email="buyer@art4sells.test"):
    status, data = call("POST", "/api/auth/forgot-password", {"email": email})
    assert status == 200, data
    return code_of(outbox[-1])


def count_private():
    return {name: len(tb.read_json_file(name)) for name in ("carts", "wishlists", "follows", "notifications")}


# ---------------------------------------------------------------------------
# A) ต้อง login + ข้อมูลส่วนตัวรายผู้ใช้
# ---------------------------------------------------------------------------
def test_private_endpoints_require_login_and_create_nothing():
    before = count_private()
    cases = [("GET", "/api/cart", None), ("POST", "/api/cart", {"artwork_id": "w3"}), ("DELETE", "/api/cart", None),
             ("POST", "/api/cart/checkout", None), ("PUT", "/api/cart/c1", {"quantity": 2}), ("DELETE", "/api/cart/c1", None),
             ("GET", "/api/wishlist", None), ("POST", "/api/wishlist", {"artwork_id": "w3"}), ("DELETE", "/api/wishlist/f1", None),
             ("GET", "/api/follows", None), ("POST", "/api/follows", {"artist_id": "a1"}), ("DELETE", "/api/follows/fl1", None),
             ("GET", "/api/me/notifications", None), ("POST", "/api/me/notifications/read-all", None),
             ("PUT", "/api/me/notifications/n1", None), ("POST", "/api/auth/change-password", {"current_password": "x"})]
    for method, path, body in cases:
        assert call(method, path, body)[0] == 401, (method, path)
        assert call(method, path, body, "not-a-real-token")[0] == 401, (method, path)
    assert count_private() == before, "ห้ามเกิด record ใด ๆ ก่อน login (ไม่มี anonymous cart/wishlist)"


def test_cart_add_list_update_remove_clear():
    buyer = login("buyer")
    status, data = call("POST", "/api/cart", {"artwork_id": "w3", "quantity": 2}, buyer)
    assert status == 201 and data["created"] and data["item"]["user_id"] == "u1" and data["item"]["quantity"] == 2
    status, data = call("POST", "/api/cart", {"artwork_id": "w3"}, buyer)
    assert status == 200 and not data["created"] and data["item"]["quantity"] == 3, "UNLIMITED บวกจำนวนเพิ่ม ไม่สร้าง record ซ้ำ"
    limited = call("POST", "/api/cart", {"artwork_id": "w1", "quantity": 5}, buyer)[1]
    assert limited["item"]["quantity"] == 1, "งาน LIMITED ได้ 1 ชิ้นเสมอ"
    again = call("POST", "/api/cart", {"artwork_id": "w1"}, buyer)
    assert again[0] == 200 and not again[1]["created"]
    view = call("GET", "/api/cart", None, buyer)[1]
    assert view["count"] == 4 and len(view["items"]) == 2
    assert view["total"] == round(650 * 3 + 1200, 2), "ยอดรวมคำนวณที่ server จากราคาในฐานข้อมูล"
    assert view["items"][0]["artwork"]["title"] and view["items"][0]["purchasable"] is True
    item_id = [i for i in view["items"] if i["artwork_id"] == "w3"][0]["id"]
    assert call("PUT", "/api/cart/" + item_id, {"quantity": 1}, buyer)[1]["quantity"] == 1
    limited_id = [i for i in view["items"] if i["artwork_id"] == "w1"][0]["id"]
    assert call("PUT", "/api/cart/" + limited_id, {"quantity": 2}, buyer)[0] == 400
    assert call("DELETE", "/api/cart/" + item_id, None, buyer)[0] == 200
    assert call("DELETE", "/api/cart/" + item_id, None, buyer)[0] == 404
    assert call("DELETE", "/api/cart", None, buyer)[1]["deleted"] == 1
    assert call("GET", "/api/cart", None, buyer)[1]["items"] == []
    assert len([c for c in tb.read_json_file("carts") if c["user_id"] == "u1"]) == 0


def test_cart_rejects_bad_artworks_and_inputs():
    buyer, mika, admin = login("buyer"), login("mika"), login("admin")
    expected = {"does-not-exist": 404, "w13": 404, "w8": 409, "w6": 409}      # ไม่มี / ยังไม่อนุมัติ / ขายแล้ว / มีคนรอจ่ายเงิน
    for artwork_id, status in expected.items():
        assert call("POST", "/api/cart", {"artwork_id": artwork_id}, buyer)[0] == status, artwork_id
    assert call("POST", "/api/cart", {"artwork_id": "w1"}, mika)[0] == 409, "ซื้องานตัวเองไม่ได้"
    assert call("POST", "/api/cart", {"artwork_id": "w3"}, admin)[0] == 403, "admin ไม่ใช้ตะกร้า"
    for bad_id in (None, 123, "", "a b", "../x", "<script>", "x" * 65, ["w3"], {"a": 1}, True):
        assert call("POST", "/api/cart", {"artwork_id": bad_id}, buyer)[0] == 400, bad_id
    for bad_qty in (0, -1, 1.5, "abc", 100, True, None, [1]):
        assert call("POST", "/api/cart", {"artwork_id": "w3", "quantity": bad_qty}, buyer)[0] == 400, bad_qty
    assert count_private()["carts"] == 0
    # ราคา/เจ้าของ ที่ client ส่งมาไม่ถูกใช้
    item = call("POST", "/api/cart", {"artwork_id": "w3", "price": 1, "user_id": "u2", "role": "ADMIN"}, buyer)[1]["item"]
    assert item["user_id"] == "u1" and "price" not in item


def test_cart_isolation_between_users():
    buyer, ton = login("buyer"), login("ton")
    mine = call("POST", "/api/cart", {"artwork_id": "w3"}, buyer)[1]["item"]
    theirs = call("POST", "/api/cart", {"artwork_id": "w9", "user_id": "u1"}, ton)[1]["item"]
    assert theirs["user_id"] == "u2", "เจ้าของมาจาก session ไม่ใช่ body"
    assert [i["artwork_id"] for i in call("GET", "/api/cart", None, buyer)[1]["items"]] == ["w3"]
    assert [i["artwork_id"] for i in call("GET", "/api/cart", None, ton)[1]["items"]] == ["w9"]
    assert call("PUT", "/api/cart/" + mine["id"], {"quantity": 2}, ton)[0] == 403
    assert call("DELETE", "/api/cart/" + mine["id"], None, ton)[0] == 403
    assert call("DELETE", "/api/cart/not-found-id", None, ton)[0] == 404
    assert call("GET", "/api/cart", None, buyer)[1]["count"] == 1, "ถูกลองแก้ แต่ของเดิมต้องไม่เปลี่ยน"
    # สลับผู้ใช้: A -> logout -> B -> logout -> A  ต้องได้ข้อมูลของตัวเองเสมอ
    assert call("POST", "/api/logout", None, buyer)[0] == 200
    assert call("GET", "/api/cart", None, buyer)[0] == 401
    assert call("DELETE", "/api/cart", None, ton)[0] == 200
    buyer_again = login("buyer")
    assert [i["artwork_id"] for i in call("GET", "/api/cart", None, buyer_again)[1]["items"]] == ["w3"]
    assert call("GET", "/api/cart", None, login("ton"))[1]["items"] == []


def test_cart_checkout_creates_order_and_clears_cart():
    buyer, ton = login("buyer"), login("ton")
    assert call("POST", "/api/cart/checkout", None, buyer)[0] == 400, "ตะกร้าว่าง"
    call("POST", "/api/cart", {"artwork_id": "w3", "quantity": 2}, buyer)
    call("POST", "/api/cart", {"artwork_id": "w9"}, buyer)
    status, order = call("POST", "/api/cart/checkout", {"total": 1, "items": [{"artwork_id": "w1"}]}, buyer)
    assert status == 201 and order["total"] == 650 * 2 + 450 and order["status"] == "PENDING_PAYMENT"
    assert {i["artwork_id"] for i in order["items"]} == {"w3", "w9"}, "ใช้ตะกร้าบน server เท่านั้น"
    assert call("GET", "/api/cart", None, buyer)[1]["items"] == []
    # งาน LIMITED ที่มีคนอื่นจองไปก่อน -> checkout ล้มเหลวและตะกร้าไม่หาย
    call("POST", "/api/cart", {"artwork_id": "w5"}, ton)
    call("PUT", "/api/artworks/w5", {"sale_type": "LIMITED"}, login("admin"))
    call("POST", "/api/cart", {"artwork_id": "w2"}, buyer)
    call("POST", "/api/orders", {"items": [{"artwork_id": "w2", "quantity": 1}]}, ton)
    status, data = call("POST", "/api/cart/checkout", None, buyer)
    assert status == 409 and data["error"]["code"] == "ARTWORK_LOCKED"
    assert len(call("GET", "/api/cart", None, buyer)[1]["items"]) == 1


def test_wishlist_prevents_duplicates_and_isolation():
    buyer, ton = login("buyer"), login("ton")
    first = call("POST", "/api/wishlist", {"artwork_id": "w3"}, buyer)
    second = call("POST", "/api/wishlist", {"artwork_id": "w3"}, buyer)
    assert first[0] == 201 and second[0] == 200 and first[1]["item"]["id"] == second[1]["item"]["id"]
    assert len([w for w in tb.read_json_file("wishlists") if w["user_id"] == "u1" and w["artwork_id"] == "w3"]) == 1
    assert call("POST", "/api/wishlist", {"artwork_id": "w3"}, ton)[0] == 201, "คนละคนเพิ่มงานเดียวกันได้"
    for artwork_id, status in (("nope", 404), ("w13", 404), ("w8", 409)):
        assert call("POST", "/api/wishlist", {"artwork_id": artwork_id}, buyer)[0] == status
    assert call("POST", "/api/wishlist", {"artwork_id": "../w3"}, buyer)[0] == 400
    items = call("GET", "/api/wishlist", None, buyer)[1]["items"]
    assert len(items) == 1 and items[0]["artwork"]["title"] == "Fox Ranger"
    assert call("DELETE", "/api/wishlist/" + items[0]["id"], None, ton)[0] == 403
    assert call("DELETE", "/api/wishlist/" + items[0]["id"], None, buyer)[0] == 200
    assert call("GET", "/api/wishlist", None, buyer)[1]["items"] == []
    assert len(call("GET", "/api/wishlist", None, ton)[1]["items"]) == 1


def test_follow_artists_per_user():
    buyer, ton, mika = login("buyer"), login("ton"), login("mika")
    assert call("POST", "/api/follows", {"artist_id": "a1"}, buyer)[0] == 201
    assert call("POST", "/api/follows", {"artist_id": "a1"}, buyer)[0] == 200
    assert len([f for f in tb.read_json_file("follows") if f["user_id"] == "u1"]) == 1
    assert call("POST", "/api/follows", {"artist_id": "u2"}, buyer)[0] == 404, "ไม่ใช่ศิลปิน"
    assert call("POST", "/api/follows", {"artist_id": "a1"}, mika)[0] == 409, "ติดตามตัวเองไม่ได้"
    assert call("POST", "/api/follows", {"artist_id": "bad id"}, buyer)[0] == 400
    follows = call("GET", "/api/follows", None, buyer)[1]["items"]
    assert [f["artist_id"] for f in follows] == ["a1"] and follows[0]["artist_name"] == "Mika Sorn"
    assert call("GET", "/api/follows", None, ton)[1]["items"] == []
    assert call("DELETE", "/api/follows/" + follows[0]["id"], None, ton)[0] == 403
    assert call("DELETE", "/api/follows/" + follows[0]["id"], None, buyer)[0] == 200


def test_notifications_are_private_and_created_by_events():
    admin, mika, buyer = login("admin"), login("mika"), login("buyer")
    call("POST", "/api/artworks/w13/approve", None, admin)
    call("POST", "/api/artworks/w15/reject", None, admin)
    call("PUT", "/api/orders/o1", {"status": "CANCELLED"}, buyer)
    mine = call("GET", "/api/me/notifications", None, login("kenji"))[1]       # w13 เป็นของ kenji (a2)
    assert mine["total"] == 1 and mine["unread_count"] == 1 and "อนุมัติ" in mine["items"][0]["message"]
    assert call("GET", "/api/me/notifications", None, mika)[1]["total"] == 1, "mika ได้แจ้งว่า w15 ไม่ผ่าน"
    buyer_list = call("GET", "/api/me/notifications", None, buyer)[1]
    assert buyer_list["total"] == 1 and "o1" in buyer_list["items"][0]["message"]
    note_id = buyer_list["items"][0]["id"]
    assert call("PUT", "/api/me/notifications/" + note_id, None, mika)[0] == 403
    assert call("PUT", "/api/me/notifications/" + note_id, None, buyer)[1]["read"] is True
    assert call("GET", "/api/me/notifications", None, buyer, {"unread": "true"})[1]["total"] == 0
    assert call("POST", "/api/me/notifications/read-all", None, mika)[1]["updated"] == 1
    for bad in ({"unread": "maybe"}, {"page": "0"}, {"x": "1"}):
        assert call("GET", "/api/me/notifications", None, buyer, bad)[0] == 400, bad


def test_deleting_artwork_or_user_removes_private_references():
    mika, admin, buyer = login("mika"), login("admin"), login("buyer")
    art_id = tb.make_approved_artwork(mika, admin, title="Cascade Me")
    call("POST", "/api/cart", {"artwork_id": art_id}, buyer)
    call("POST", "/api/wishlist", {"artwork_id": art_id}, buyer)
    assert call("DELETE", "/api/artworks/" + art_id, None, mika)[0] == 200
    assert not [c for c in tb.read_json_file("carts") if c["artwork_id"] == art_id]
    assert not [w for w in tb.read_json_file("wishlists") if w["artwork_id"] == art_id]
    # ลบ user: ข้อมูลส่วนตัวทั้งหมดไปด้วย
    _st, new_user, tok = tb.call_with_token("POST", "/api/register", {"name": "Temp User", "email": "temp@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"})
    uid = new_user["user"]["id"]
    call("POST", "/api/cart", {"artwork_id": "w3"}, tok)
    call("POST", "/api/wishlist", {"artwork_id": "w3"}, tok)
    call("POST", "/api/follows", {"artist_id": "a1"}, tok)
    assert call("DELETE", "/api/users/" + uid, None, admin)[0] == 200
    for name in ("carts", "wishlists", "follows", "notifications", "sessions", "password_resets"):
        assert not [r for r in tb.read_json_file(name) if r.get("user_id") == uid], name
    assert call("GET", "/api/me", None, tok)[0] == 401


# ---------------------------------------------------------------------------
# B) เปลี่ยนรหัสผ่าน + cooldown
# ---------------------------------------------------------------------------
def test_change_password_rules_success_and_cooldown():
    buyer = login("buyer")
    other_session = login("buyer")
    url = "/api/auth/change-password"
    good = {"current_password": tb.PASSWORD, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    assert call("POST", url, dict(good, current_password="WrongPass1"), buyer)[0] == 403
    assert call("POST", url, dict(good, new_password="short1", confirm_password="short1"), buyer)[0] == 400
    assert call("POST", url, dict(good, new_password="lettersonly", confirm_password="lettersonly"), buyer)[0] == 400
    assert call("POST", url, dict(good, confirm_password="Different9Pass"), buyer)[0] == 400
    same = call("POST", url, dict(good, new_password=tb.PASSWORD, confirm_password=tb.PASSWORD), buyer)
    assert same[0] == 400 and "new_password" in same[1]["error"]["fields"]
    for bad in ({}, {"current_password": 123, "new_password": 456, "confirm_password": 789},
                dict(good, current_password=None), dict(good, new_password=["x"])):
        assert call("POST", url, bad, buyer)[0] == 400, bad
    assert logs("PASSWORD_CHANGE_FAILED"), "ใส่รหัสเดิมผิดต้องมี log"

    status, data = call("POST", url, dict(good, user_id="u2", role="ADMIN"), buyer)
    assert status == 200 and data["changed"] is True
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": tb.PASSWORD})[0] == 401
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": NEW_PASSWORD})[0] == 200
    assert call("GET", "/api/me", None, other_session)[0] == 401, "session อื่นต้องถูกตัด"
    assert call("GET", "/api/me", None, buyer)[0] == 200, "session ที่ใช้เปลี่ยนรหัสยังอยู่"
    assert logs("PASSWORD_CHANGE_SUCCESS")
    assert call("GET", "/api/me", None, buyer)[1]["user"]["role"] == "USER"

    # ภายใน 30 วัน: ปฏิเสธ + บอกวันที่จาก timestamp จริง
    again = {"current_password": NEW_PASSWORD, "new_password": "Third8Password!", "confirm_password": "Third8Password!"}
    status, data = call("POST", url, again, buyer)
    assert status == 429 and data["error"]["code"] == "PASSWORD_CHANGE_COOLDOWN"
    changed_at = datetime.fromisoformat(storage.get_record("users", "u1")["password_changed_at"])
    allowed = changed_at + timedelta(days=30)
    expected_text = str(allowed.day) + " " + allowed.strftime("%B") + " " + str(allowed.year)
    assert expected_text in data["error"]["message"] and data["error"]["details"]["available_at"].startswith(allowed.isoformat()[:10]) and not data["error"]["fields"]
    assert logs("PASSWORD_CHANGE_REJECTED_COOLDOWN")
    # วันที่ 29 ยังไม่ได้ / วันที่ 31 ได้
    for days, expected in ((29, 429), (31, 200)):
        past = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        storage.update_record("users", "u1", {"password_changed_at": past})
        assert call("POST", url, again, buyer)[0] == expected, days
    assert "Passw0rd" not in json.dumps(tb.read_json_file("logs")) and NEW_PASSWORD not in json.dumps(tb.read_json_file("logs"))


def test_passwords_with_special_characters_are_never_sanitized():
    weird = "  <b>\"';--  Aa1 ผ่าน  "
    status, data = call("POST", "/api/register", {"name": "Special Pw", "email": "sp@x.io", "password": weird, "confirm_password": weird, "role": "USER"})
    assert status == 201
    assert call("POST", "/api/login", {"email": "sp@x.io", "password": weird})[0] == 200
    assert call("POST", "/api/login", {"email": "sp@x.io", "password": weird.strip()})[0] == 401, "ช่องว่างเป็นส่วนหนึ่งของรหัสผ่าน (ไม่มี strip)"
    assert weird not in (tb.WORK_DIR / "users.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# C) Forgot password + OTP
# ---------------------------------------------------------------------------
def test_forgot_password_response_is_generic_for_known_and_unknown_email():
    with mailbox() as outbox:
        known = call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})
        unknown = call("POST", "/api/auth/forgot-password", {"email": "nobody@art4sells.test"})
    assert known == unknown and known[0] == 200, "ตอบเหมือนกันทุกตัวอักษร"
    assert "ลงทะเบียนไว้" in known[1]["message"]
    assert len(outbox) == 1 and outbox[0]["to"] == "buyer@art4sells.test", "ส่งอีเมลเฉพาะบัญชีที่มีจริง"
    for bad in ({"email": "not-an-email"}, {"email": ""}, {"email": 123}, {}, {"email": ["a@b.co"]}):
        assert call("POST", "/api/auth/forgot-password", bad)[0] == 400, bad


def test_otp_end_to_end_hashed_single_use_and_session_invalidation():
    old_session = login("buyer")
    with mailbox() as outbox:
        status, body = call("POST", "/api/auth/forgot-password", {"email": "Buyer@Art4Sells.test"})
        code = code_of(outbox[0])
    assert re.fullmatch(r"\d{5}", code) and code not in json.dumps(body), "OTP 5 หลัก และไม่อยู่ใน response"
    record = [r for r in tb.read_json_file("password_resets") if r["kind"] == "OTP"][0]
    assert record["otp_hash"].startswith("pbkdf2_sha256$") and "code" not in record and record["attempts"] == 0
    assert record["state"] == "OTP_PENDING" and record["used"] is False
    lifetime = datetime.fromisoformat(record["expires_at"]) - datetime.fromisoformat(record["created_at"])
    assert timedelta(minutes=9) < lifetime <= timedelta(minutes=10, seconds=5)
    leak = re.compile(r"(?<![0-9A-Za-z])" + code + r"(?![0-9A-Za-z])")        # รหัสทั้งก้อน (ไม่นับเลขที่บังเอิญอยู่ใน hash/เวลา)
    for data_file in tb.WORK_DIR.glob("*.json"):
        assert not leak.search(data_file.read_text(encoding="utf-8")), "OTP plaintext ห้ามอยู่ในไฟล์ข้อมูล: " + data_file.name
    # reset โดยไม่ยืนยัน OTP ไม่ได้
    assert call("POST", "/api/auth/reset-password", {"reset_token": code, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})[0] == 400
    status, verified = call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": code})
    assert status == 200 and len(verified["reset_token"]) >= 30 and "code" not in verified
    assert call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": code})[0] == 400, "OTP ใช้ได้ครั้งเดียว"
    token = verified["reset_token"]
    stored_auth = [r for r in tb.read_json_file("password_resets") if r["kind"] == "AUTH"][0]
    assert token not in json.dumps(tb.read_json_file("password_resets")) and stored_auth["state"] == "RESET_AUTHORIZED"
    # ตั้งรหัสใหม่: รหัสไม่ผ่านนโยบายยังไม่ใช้ token
    assert call("POST", "/api/auth/reset-password", {"reset_token": token, "new_password": "weak", "confirm_password": "weak"})[0] == 400
    assert call("POST", "/api/auth/reset-password", {"reset_token": token, "new_password": NEW_PASSWORD, "confirm_password": "x"})[0] == 400
    status, done = call("POST", "/api/auth/reset-password", {"reset_token": token, "new_password": NEW_PASSWORD,
                                                             "confirm_password": NEW_PASSWORD, "user_id": "u2"})
    assert status == 200 and done["reset"] is True
    assert call("POST", "/api/auth/reset-password", {"reset_token": token, "new_password": "Reuse1Token9!", "confirm_password": "Reuse1Token9!"})[0] == 400
    assert call("GET", "/api/me", None, old_session)[0] == 401, "reset แล้วทุก session ต้องหมดอายุ"
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": tb.PASSWORD})[0] == 401
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": NEW_PASSWORD})[0] == 200
    assert call("POST", "/api/login", {"email": "ton@art4sells.test", "password": NEW_PASSWORD})[0] == 401, "ไม่ใช่บัญชีอื่น"
    actions = [e["action"] for e in tb.read_json_file("logs")]
    for needed in ("PASSWORD_RESET_REQUESTED", "PASSWORD_RESET_OTP_VERIFIED", "PASSWORD_RESET_SUCCESS"):
        assert needed in actions, needed
    assert NEW_PASSWORD not in (tb.WORK_DIR / "logs.json").read_text(encoding="utf-8")


def test_otp_wrong_attempts_invalidate_the_code():
    with mailbox() as outbox:
        code = ask_code(outbox)
        wrong = "00000" if code != "00000" else "11111"
        messages = set()
        for attempt in range(config.MAX_OTP_ATTEMPTS):
            status, data = call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": wrong})
            assert status == 400
            messages.add(data["error"]["message"])
        assert len(messages) == 1, "ข้อความผิดเหมือนกันทุกครั้ง"
        assert call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": code})[0] == 400, \
            "ผิดครบแล้ว รหัสที่ถูกก็ใช้ไม่ได้ ต้องขอใหม่"
        assert len(logs("OTP_INVALID")) == config.MAX_OTP_ATTEMPTS and logs("OTP_RATE_LIMITED")
        age_reset_requests()
        fresh = ask_code(outbox)
        assert call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": fresh})[0] == 200


def test_otp_expired_and_malformed_codes():
    with mailbox() as outbox:
        code = ask_code(outbox)
        for bad in ("1234", "123456", "abcde", "12 45", "١٢٣٤٥", None, 12345, ["12345"], "", "1234\n"):
            assert call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": bad})[0] == 400, bad
        record = [r for r in tb.read_json_file("password_resets") if r["kind"] == "OTP"][0]
        storage.update_record("password_resets", record["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
        status, data = call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": code})
        assert status == 400 and logs("OTP_EXPIRED")
        unknown = call("POST", "/api/auth/verify-reset-code", {"email": "nobody@art4sells.test", "code": code})
        assert unknown[0] == 400 and unknown[1] == data, "อีเมลที่ไม่มีในระบบ ตอบเหมือนรหัสผิด"


def test_reset_password_requires_valid_authorization():
    good = {"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    for token in (None, "", "short", "x" * 43, 12345, ["t"], {"a": 1}, "A" * 200):
        assert call("POST", "/api/auth/reset-password", dict(good, reset_token=token))[0] == 400, token
    with mailbox() as outbox:
        code = ask_code(outbox)
        token = call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": code})[1]["reset_token"]
    auth = [r for r in tb.read_json_file("password_resets") if r["kind"] == "AUTH"][0]
    storage.update_record("password_resets", auth["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
    status, data = call("POST", "/api/auth/reset-password", dict(good, reset_token=token))
    assert status == 400 and data["error"]["code"] == "INVALID_RESET" and logs("PASSWORD_RESET_FAILED")
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": tb.PASSWORD})[0] == 200


def test_forgot_password_is_not_blocked_by_change_password_cooldown():
    buyer = login("buyer")
    changed = call("POST", "/api/auth/change-password", {"current_password": tb.PASSWORD, "new_password": NEW_PASSWORD,
                                                         "confirm_password": NEW_PASSWORD}, buyer)
    assert changed[0] == 200
    assert call("POST", "/api/auth/change-password", {"current_password": NEW_PASSWORD, "new_password": "Third8Password!",
                                                      "confirm_password": "Third8Password!"}, buyer)[0] == 429
    with mailbox() as outbox:
        code = ask_code(outbox)
        token = call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": code})[1]["reset_token"]
        status, _ = call("POST", "/api/auth/reset-password", {"reset_token": token, "new_password": "Recovered7Pw!",
                                                              "confirm_password": "Recovered7Pw!"})
    assert status == 200, "ลืมรหัสผ่านต้องกู้ได้แม้อยู่ใน cooldown"
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": "Recovered7Pw!"})[0] == 200


def test_otp_request_rate_limit_is_identical_for_known_and_unknown_emails():
    with mailbox() as outbox:
        assert call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})[0] == 200
        known_fast = call("POST", "/api/auth/resend-reset-code", {"email": "buyer@art4sells.test"})
        assert call("POST", "/api/auth/forgot-password", {"email": "ghost@art4sells.test"})[0] == 200
        unknown_fast = call("POST", "/api/auth/resend-reset-code", {"email": "ghost@art4sells.test"})
        assert known_fast == unknown_fast and known_fast[0] == 429 and known_fast[1]["error"]["code"] == "RATE_LIMITED"
        assert len(outbox) == 1, "ถูกจำกัดแล้วต้องไม่ส่งอีเมลเพิ่ม"
        # ครบ 5 ครั้ง/ชั่วโมง แม้เว้นเกิน 60 วินาทีแล้ว
        age_reset_requests(seconds=300)
        for _ in range(config.OTP_MAX_REQUESTS_PER_HOUR - 1):
            storage.create_record("reset_requests", {"email_hash": storage.get_all("reset_requests")[0]["email_hash"],
                                                     "requested_at": (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat(timespec="seconds")}, "rq")
        assert call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})[0] == 429
    assert logs("OTP_RATE_LIMITED")


def test_email_service_modes_never_leak_or_crash():
    message = email_service.build_reset_code_message("a@b.co", "48213", 10)
    assert "48213" in message["body"] and message["to"] == "a@b.co"
    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        assert email_service.send_password_reset_code("a@b.co", "48213", 10) is True
    assert "DEV ONLY" in captured.getvalue()
    original = config.EMAIL_MODE
    try:
        config.EMAIL_MODE = "smtp"                             # ยังไม่มี provider จริง
        assert email_service.send_password_reset_code("a@b.co", "48213", 10) is False
        status, data = call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})
        assert status == 200 and "48213" not in json.dumps(data)
    finally:
        config.EMAIL_MODE = original
    email_service.set_transport(lambda m: 1 / 0)               # transport พัง ต้องไม่ทำให้ request ล้ม
    try:
        age_reset_requests()
        assert call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})[0] == 200
    finally:
        email_service.set_transport(None)


# ---------------------------------------------------------------------------
# D) Admin data management
# ---------------------------------------------------------------------------
def preview(token, scopes, **extra):
    return call("POST", "/api/admin/data/clear/preview", dict({"scopes": scopes}, **extra), token)


def clear(token, scopes, confirm, text="CLEAR", **extra):
    body = dict({"scopes": scopes, "confirm_token": confirm, "confirm_text": text}, **extra)
    return call("POST", "/api/admin/data/clear", body, token)


def test_data_management_is_admin_only_and_needs_two_steps():
    admin, mika, buyer = login("admin"), login("mika"), login("buyer")
    for token, expected in ((None, 401), (buyer, 403), (mika, 403)):
        assert preview(token, ["reviews"])[0] == expected
        assert clear(token, ["reviews"], "x" * 30)[0] == expected
        assert call("POST", "/api/admin/data/reset", {"confirm_text": "RESET"}, token)[0] == expected
    assert clear(admin, ["reviews"], None)[0] == 400, "ข้ามขั้นแรกไม่ได้"
    assert clear(admin, ["reviews"], "z" * 30)[0] == 400
    token = preview(admin, ["reviews"])[1]["confirm_token"]
    for wrong in ("clear", "Clear", "CLEAR ", "", None, 1, ["CLEAR"]):
        assert clear(admin, ["reviews"], token, text=wrong)[0] == 400, wrong
    assert clear(admin, ["orders"], token)[0] == 400, "token ใช้กับรายการอื่นไม่ได้"
    assert clear(admin, ["reviews"], token, preserve_admins=False)[0] == 400, "เปลี่ยนตัวเลือกแล้ว token ใช้ไม่ได้"
    assert tb.read_json_file("reviews"), "ยังไม่มีอะไรถูกลบ"
    status, done = clear(admin, ["reviews"], token)
    assert status == 200 and done["counts"]["reviews"] == 2 and tb.read_json_file("reviews") == []
    assert clear(admin, ["reviews"], token)[0] == 400, "token ใช้ได้ครั้งเดียว"
    second_admin = call("POST", "/api/users", {"name": "Admin Two", "email": "admin2@x.io", "password": "Passw0rd1!",
                                              "role": "ADMIN"}, admin)
    other = tb.call_login("admin2@x.io", "Passw0rd1!")[2]
    fresh = preview(admin, ["notifications"])[1]["confirm_token"]
    assert clear(other, ["notifications"], fresh)[0] == 400, "token ของ admin คนอื่นใช้ไม่ได้"
    expired = preview(admin, ["notifications"])[1]["confirm_token"]
    for entry in storage.get_all("confirmations"):
        storage.update_record("confirmations", entry["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
    assert clear(admin, ["notifications"], expired)[0] == 400, "token หมดอายุ"


def test_clear_data_follows_dependencies_and_keeps_integrity():
    admin = login("admin")
    status, plan = preview(admin, ["orders"])
    assert plan["auto_included"] == ["reviews"] and plan["counts"] == {"reviews": 2, "orders": 3}
    assert clear(admin, ["orders"], plan["confirm_token"])[0] == 200
    assert tb.read_json_file("orders") == [] and tb.read_json_file("reviews") == []
    assert len(tb.read_json_file("artworks")) == 16 and len(tb.read_json_file("users")) == 7
    # artworks -> ลากตะกร้า/wishlist/orders/reviews ไปด้วย
    call("POST", "/api/cart", {"artwork_id": "w3"}, login("buyer"))
    call("POST", "/api/wishlist", {"artwork_id": "w9"}, login("ton"))
    plan = preview(admin, ["artworks"])[1]
    assert set(plan["auto_included"]) == {"orders", "reviews", "cart", "wishlist"}
    assert clear(admin, ["artworks"], plan["confirm_token"])[0] == 200
    for name in ("artworks", "carts", "wishlists", "orders", "reviews"):
        assert tb.read_json_file(name) == [], name
    assert len(tb.read_json_file("users")) == 7 and len(tb.read_json_file("categories")) == 8
    # categories -> artworks
    plan = preview(admin, ["categories"])[1]
    assert "artworks" in plan["auto_included"]


def test_clear_users_keeps_admin_and_drops_everything_that_points_to_users():
    admin, buyer, mika = login("admin"), login("buyer"), login("mika")
    call("POST", "/api/cart", {"artwork_id": "w3"}, buyer)
    call("POST", "/api/follows", {"artist_id": "a1"}, buyer)
    plan = preview(admin, ["users"])[1]
    assert plan["preserve_admins"] is True and plan["counts"]["users"] == 6
    assert clear(admin, ["users"], plan["confirm_token"])[0] == 200
    users = tb.read_json_file("users")
    assert [u["id"] for u in users] == ["ad1"], "ลบทุกคนยกเว้น admin"
    for name in ("artworks", "orders", "reviews", "carts", "wishlists", "follows", "notifications"):
        assert tb.read_json_file(name) == [], name
    assert call("GET", "/api/me", None, buyer)[0] == 401 and call("GET", "/api/me", None, mika)[0] == 401
    assert call("GET", "/api/me", None, admin)[0] == 200, "admin ที่ใช้งานอยู่ไม่ถูกเตะออก"
    assert [s["user_id"] for s in tb.read_json_file("sessions")] == ["ad1"]


def test_preserve_admin_flag_and_current_admin_is_never_deleted():
    admin = login("admin")
    call("POST", "/api/users", {"name": "Admin Two", "email": "admin2@x.io", "password": "Passw0rd1!", "role": "ADMIN"}, admin)
    assert preview(admin, ["users"], preserve_admins="false")[0] == 400, "ต้องเป็น boolean จริง"
    assert preview(admin, ["users"], preserve_admins=0)[0] == 400
    on = preview(admin, ["users"])[1]
    assert on["preserve_admins"] is True and on["counts"]["users"] == 6, "ค่าเริ่มต้น = เก็บ admin ทุกคน"
    off = preview(admin, ["users"], preserve_admins=False)[1]
    assert off["counts"]["users"] == 7, "ปิดแล้วลบ admin คนอื่นได้"
    assert clear(admin, ["users"], off["confirm_token"], preserve_admins=False)[0] == 200
    assert [u["id"] for u in tb.read_json_file("users")] == ["ad1"], "แต่ admin ที่กำลังใช้งานอยู่ไม่ถูกลบเด็ดขาด"
    assert call("GET", "/api/me", None, admin)[0] == 200


def test_clear_audit_logs_needs_extra_confirmation_and_keeps_own_entry():
    admin = login("admin")
    plan = preview(admin, ["audit_logs"])[1]
    assert plan["requires_audit_confirmation"] is True
    assert clear(admin, ["audit_logs"], plan["confirm_token"])[0] == 400, "ล้าง log ต้องพิมพ์ยืนยันเพิ่ม"
    assert clear(admin, ["audit_logs"], plan["confirm_token"], confirm_audit_text="clear audit logs")[0] == 400
    before = len(tb.read_json_file("logs"))
    assert before >= 1
    status, done = clear(admin, ["audit_logs"], plan["confirm_token"], confirm_audit_text="CLEAR AUDIT LOGS")
    assert status == 200 and done["counts"]["logs"] == before
    remaining = tb.read_json_file("logs")
    assert len(remaining) == 1 and remaining[0]["action"] == "ADMIN_DATA_CLEAR" and remaining[0]["actor_id"] == "ad1"
    assert remaining[0]["result"] == "SUCCESS" and remaining[0]["details"]["counts"]["logs"] == before
    assert plan["confirm_token"] not in json.dumps(remaining)


def test_clear_data_input_validation():
    admin = login("admin")
    for bad in (None, [], "users", ["bogus"], [1], [None], ["users"] * 50, {"users": True}, [["users"]]):
        assert call("POST", "/api/admin/data/clear/preview", {"scopes": bad}, admin)[0] == 400, bad
    ok = preview(admin, ["cart", "cart"])
    assert ok[0] == 200 and ok[1]["scopes"] == ["cart"]
    assert preview(admin, ["follows"], role="x", user_id="u1")[0] == 200, "field แปลกถูกทิ้ง"


def test_reset_demo_data_restores_dataset_and_keeps_logs_and_admins():
    admin = login("admin")
    call("POST", "/api/users", {"name": "Admin Two", "email": "admin2@x.io", "password": "Passw0rd1!", "role": "ADMIN"}, admin)
    plan = preview(admin, ["artworks", "categories"])[1]
    clear(admin, ["artworks", "categories"], plan["confirm_token"])
    call("POST", "/api/cart", {"artwork_id": "w3"}, login("buyer"))
    logs_before = len(tb.read_json_file("logs"))
    pre = call("POST", "/api/admin/data/reset/preview", {}, admin)
    assert pre[0] == 200 and pre[1]["keeps_audit_logs"] is True
    reset_body = {"confirm_token": pre[1]["confirm_token"]}
    for wrong in ("reset", "RESET ", "", None, "CLEAR"):
        assert call("POST", "/api/admin/data/reset", dict(reset_body, confirm_text=wrong), admin)[0] == 400, wrong
    assert call("POST", "/api/admin/data/reset", {"confirm_text": "RESET"}, admin)[0] == 400, "ไม่มี token"
    status, done = call("POST", "/api/admin/data/reset", dict(reset_body, confirm_text="RESET"), admin)
    assert status == 200 and done["kept_admin_accounts"] == 2
    assert len(tb.read_json_file("artworks")) == 16 and len(tb.read_json_file("categories")) == 8
    assert len(tb.read_json_file("users")) == 8, "demo 7 + admin ที่เก็บไว้"
    assert tb.read_json_file("carts") == [] and len(tb.read_json_file("logs")) == logs_before + 1
    assert tb.read_json_file("logs")[-1]["action"] == "ADMIN_DATA_RESET"
    assert call("GET", "/api/me", None, admin)[0] == 200, "admin ยังไม่ถูกเตะออก"
    assert call("POST", "/api/login", {"email": "admin2@x.io", "password": "Passw0rd1!"})[0] == 200
    again = call("POST", "/api/admin/data/reset/preview", {"preserve_admins": False}, admin)[1]
    assert call("POST", "/api/admin/data/reset", {"confirm_token": again["confirm_token"], "confirm_text": "RESET",
                                                  "preserve_admins": False}, admin)[1]["kept_admin_accounts"] == 1
    assert call("POST", "/api/login", {"email": "admin2@x.io", "password": "Passw0rd1!"})[0] == 401


# ---------------------------------------------------------------------------
# E) Input validation / injection / XSS foundation
# ---------------------------------------------------------------------------
def test_id_and_query_validation():
    for bad_id in ("a$b", "<script>", "x" * 65, "%00", "a'b", "a;b", "a b", "-lead", "ก"):
        assert call("GET", "/api/artworks/" + bad_id)[0] == 400, bad_id
    assert call("GET", "/api/artworks/w1")[0] == 200 and call("GET", "/api/artworks/w99")[0] == 404
    for query in ({"artist_id": "<script>"}, {"category": "../../etc"}, {"artist_id": "x" * 65}, {"category": "a b"}):
        assert call("GET", "/api/artworks", None, None, query)[0] == 400, query
    assert call("GET", "/api/reviews", None, None, {"artwork_id": "a'b"})[0] == 400
    assert call("GET", "/api/me", None, None, {"x": "1"})[0] == 400, "endpoint ที่ไม่รับ query ปฏิเสธพารามิเตอร์แปลก ๆ"


def test_query_parameter_limits_and_allowlists():
    get = lambda **q: call("GET", "/api/artworks", None, None, {k: str(v) for k, v in q.items()})[0]
    assert get(q="x" * config.SEARCH_MAX_LENGTH) == 200 and get(q="x" * (config.SEARCH_MAX_LENGTH + 1)) == 400
    assert get(q="a\x00b") == 400 and get(q="line\nbreak") == 400
    assert get(q="x" * 300) == 400 and get(unknown="1") == 400 and get(limit="5") == 400
    for sort in ("price_asc; DROP TABLE", "__import__('os')", "PRICE_ASC", "", "rating,price", "title"):
        assert get(sort=sort) == 400, sort
    assert get(page_size=config.PAGE_SIZE_RANGE[1] + 1) == 400 and get(page_size=config.PAGE_SIZE_RANGE[1]) == 200
    assert get(q="<img src=x onerror=alert(1)>") == 200, "ข้อความหน้าตาอันตรายเป็นแค่ข้อความค้นหา ไม่ถูกตีความ"
    assert get(q="' OR 1=1 --") == 200 and get(q="{{7*7}}") == 200 and get(q="${jndi:ldap://x}") == 200
    result = call("GET", "/api/artworks", None, None, {"q": "' OR 1=1 --"})[1]
    assert result["total"] == 0


def test_text_fields_require_real_strings():
    mika = login("mika")
    base = tb.new_artwork_body()
    for field, value in (("title", 123), ("title", ["a"]), ("title", {"a": 1}), ("title", True), ("description", 5),
                         ("description", ["x"]), ("category", 1), ("category", ["illustration"]), ("sale_type", 1),
                         ("sale_type", ["LIMITED"]), ("tags", [1]), ("tags", ["a", {}]), ("tags", 5), ("tags", {"a": 1})):
        status, data = call("POST", "/api/artworks", dict(base, **{field: value}), mika)
        assert status == 400 and field in data["error"]["fields"], (field, value, data)
    for bad in ({"name": ["x"], "email": "a@b.co", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!"}, {"name": "Ok Name", "email": 5, "password": "Passw0rd1!", "confirm_password": "Passw0rd1!"},
                {"name": "Ok Name", "email": "a@b.co", "password": 12345678}, {"name": "Ok Name", "email": "a@b.co",
                 "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": True}, {"name": "Ok Name", "email": "a@b.co", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": ["ADMIN"]}):
        assert call("POST", "/api/register", bad)[0] == 400, bad
    assert call("POST", "/api/login", {"email": ["a@b.co"], "password": "x"})[0] == 400
    assert call("POST", "/api/login", {"email": "a@b.co", "password": {"a": 1}})[0] == 400


def test_unicode_control_chars_and_normalization():
    mika = login("mika")
    for bad_title in ("bad\x00title", "bad\ntitle", "bad\ttitle", "rtl\u202etitle", "iso\u2066late"):
        assert call("POST", "/api/artworks", tb.new_artwork_body(title=bad_title), mika)[0] == 400, repr(bad_title)
    assert call("POST", "/api/artworks", tb.new_artwork_body(description="บรรทัดหนึ่ง\nบรรทัดสอง\tแท็บ"), mika)[0] == 201
    assert call("POST", "/api/artworks", tb.new_artwork_body(description="bad\x07bell"), mika)[0] == 400
    tricky = "ภาพ \"A&B\" <i>Café</i> 😀 'x'"
    status, art = call("POST", "/api/artworks", tb.new_artwork_body(title=tricky), mika)
    assert status == 201 and art["title"] == tricky, "เก็บตามที่ผู้ใช้พิมพ์ (ไม่ลบ/แปลงสัญลักษณ์) การป้องกันอยู่ที่ตอนแสดงผล"
    decomposed = "Cafe\u0301"
    stored = call("POST", "/api/artworks", tb.new_artwork_body(title=decomposed), mika)[1]["title"]
    assert stored == "Caf\u00e9" and len(stored) == 4, "NFC normalization"
    assert call("POST", "/api/artworks", tb.new_artwork_body(title="   "), mika)[0] == 400
    assert call("POST", "/api/artworks", tb.new_artwork_body(title="x" * 81), mika)[0] == 400


def test_number_boundaries_and_json_edge_cases():
    mika = login("mika")
    post = lambda raw: call("POST", "/api/artworks", raw if isinstance(raw, bytes) else raw, mika)
    template = json.dumps(tb.new_artwork_body(price="PRICE"))
    for price_literal, expected in (("NaN", 400), ("Infinity", 400), ("-Infinity", 400), ("1e999", 400), ("-0.01", 400),
                                    ("999999999999999999999999", 400), ("1" * 5000, 400), ("true", 400), ("null", 400),
                                    ('"12.5"', 201), ("0", 201), ("12.345", 201), ("1000000", 201), ("1000000.01", 400)):
        raw = template.replace('"PRICE"', price_literal).encode("utf-8")
        status, data = post(raw)
        assert status == expected, (price_literal, status, data)
        if status == 201:
            assert round(data["price"], 2) == data["price"]
    nested = ("[" * 100000 + "]" * 100000).encode()
    assert post(nested)[0] == 400 and post(b'{"a":' * 50000 + b"1" + b"}" * 50000)[0] == 400
    assert post(b"\xef\xbb\xbf{}")[0] == 400, "BOM"
    assert post(b'{"title": "a", "title": "b"}')[0] == 400, "ซ้ำก็ยังผ่านการตรวจ field อื่น"
    for headers_type, expected in (("text/plain", 415), ("application/x-www-form-urlencoded", 415), ("", 415),
                                   ("application/json; charset=utf-8", 201), ("Application/JSON", 201)):
        h = {"Authorization": "Bearer " + mika, "Content-Type": headers_type}
        status, _ = tb.api.handle_request("POST", "/api/artworks", {}, h, json.dumps(tb.new_artwork_body()).encode())
        assert status == expected, headers_type


def test_mass_assignment_and_role_tampering_are_ignored():
    status, data, token = tb.call_with_token("POST", "/api/register", {"name": "Tamper One", "email": "t1@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER",
                                                  "is_admin": True, "permissions": ["data.manage"], "status": "ACTIVE",
                                                  "id": "ad1", "password_hash": "x", "password_changed_at": "2000-01-01"})
    assert status == 201 and data["user"]["role"] == "USER" and data["user"]["id"] != "ad1"
    assert call("GET", "/api/admin/data/clear", None, token)[0] == 405
    assert call("POST", "/api/admin/data/clear/preview", {"scopes": ["reviews"]}, token)[0] == 403
    string_admin = call("POST", "/api/register", {"name": "Tamper Two", "email": "t2@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "is_admin": "true"})
    assert string_admin[1]["user"]["role"] == "USER"
    record_before = storage.get_record("users", data["user"]["id"])
    status, updated = call("PUT", "/api/users/" + data["user"]["id"],
                           {"name": "New Name", "status": "BANNED", "email": "evil@x.io", "password_hash": "x",
                            "id": "zzz", "is_admin": True, "followers": 99999, "rating": 5}, token)
    assert status == 200 and updated["name"] == "New Name"
    after = storage.get_record("users", data["user"]["id"])
    for field in ("status", "email", "password_hash", "id", "followers", "rating", "role"):
        assert after[field] == record_before[field], field
    mika = login("mika")
    forged = call("POST", "/api/artworks", dict(tb.new_artwork_body(), artist_id="a2", status="APPROVED", rating=5,
                                               reviewed_by="ad1", id="w1"), mika)[1]
    assert forged["artist_id"] == "a1" and forged["status"] == "DRAFT" and forged["rating"] == 0 and forged["id"] != "w1"
    # รีวิวปลอมเจ้าของ/สถานะ
    admin, buyer = login("admin"), login("buyer")
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    tb.pay_and_complete(oid, admin)
    review = call("POST", "/api/reviews", {"artwork_id": "w5", "rating": 5, "comment": "Great pack", "user_id": "u2",
                                           "artist_id": "a1", "status": "HIDDEN", "order_id": "o1"}, buyer)[1]
    assert review["user_id"] == "u1" and review["artist_id"] == "a2" and review["status"] == "PUBLISHED" and review["order_id"] == oid


def test_review_value_boundaries():
    admin, buyer = login("admin"), login("buyer")
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    tb.pay_and_complete(oid, admin)
    for rating in (999, -1, 0, 6, True, False, "999", "x", 5.5, None, [5], {"a": 5}, 1e400):
        raw = json.dumps({"artwork_id": "w5", "rating": rating, "comment": "valid comment"})
        assert call("POST", "/api/reviews", raw.encode(), buyer)[0] == 400, rating
    for comment in (123, ["x"], None, "", "no", "x" * 1001, "bad\x00comment"):
        assert call("POST", "/api/reviews", {"artwork_id": "w5", "rating": 4, "comment": comment}, buyer)[0] == 400, comment
    assert call("POST", "/api/reviews", {"artwork_id": "w5", "rating": 4, "comment": "<script>alert(1)</script> fine"}, buyer)[0] == 201


def test_validation_helpers_and_upload_foundation():
    assert validation.validate_id("w13") is None and validation.validate_id("cat_ab12") is None
    for bad in ("", None, 5, "a b", "../a", "a/b", "x" * 65, "-a", "a\n"):
        assert validation.validate_id(bad) is not None, bad
    assert validation.validate_url("https://example.com/a?b=1") is None
    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x.com", "//evil.com", "http://", "", None, "https://a.com/\x00", "x" * 2100):
        assert validation.validate_url(bad) is not None, bad
    assert validation.validate_choice("a", {"a", "b"}, "x") is None and validation.validate_choice(["a"], {"a"}, "x") is not None
    assert validation.pick_fields({"a": 1, "role": "ADMIN", "b": 2}, ("a", "b")) == {"a": 1, "b": 2}
    assert validation.clean_text("  Cafe\u0301  ") == "Caf\u00e9"
    # upload metadata (ไม่เชื่อชื่อไฟล์จาก client)
    ok, errors = uploads.validate_upload_metadata("My Art.PNG", "image/png", 1000)
    assert not errors and ok["extension"] == "png"
    for filename, ctype, size in (("../../etc/passwd.png", "image/png", 10), ("a\\b.png", "image/png", 10), ("x.png\x00.php", "image/png", 10),
                                  ("shell.php", "image/png", 10), ("a.png", "text/html", 10), ("a.png", "image/jpeg", 10),
                                  ("noext", "image/png", 10), ("a.png", "image/png", 0), ("a.png", "image/png", config.MAX_UPLOAD_BYTES + 1),
                                  ("a.png", "image/png", "10"), (None, "image/png", 10), ("a.png", None, 10), ("a" * 300 + ".png", "image/png", 10)):
        assert uploads.validate_upload_metadata(filename, ctype, size)[1], (filename, ctype, size)
    name1, name2 = uploads.safe_server_filename("png"), uploads.safe_server_filename("png")
    assert re.fullmatch(r"[0-9a-f]{32}\.png", name1) and name1 != name2
    base = tb.WORK_DIR
    assert uploads.safe_join(base, name1) == (base / name1).resolve()
    for evil in ("../x.png", "/etc/passwd", "..\\x", "a/../../x", "", "\x00", "sub/../../x"):
        assert uploads.safe_join(base, evil) is None, evil


def test_frontend_source_has_no_dangerous_sinks():
    """ตรวจโค้ด frontend อัตโนมัติ: ห้ามมี eval / document.write / inline handler / javascript: URL ฯลฯ"""
    root = Path(config.PROJECT_DIR)
    sinks = [r"\beval\s*\(", r"new\s+Function", r"document\.write", r"insertAdjacentHTML", r"outerHTML", r"javascript:",
             r"\bsetTimeout\s*\(\s*['\"]", r"\son[a-z]+\s*=\s*[\"']", r"dangerouslySetInnerHTML"]
    scanned = list((root / "src").rglob("*.js")) + list((root / "public").glob("*.html"))
    assert len(scanned) > 20
    for path in scanned:
        if "test" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in sinks:
            assert not re.search(pattern, text), (str(path.relative_to(root)), pattern)
    html_text = "".join(p.read_text(encoding="utf-8") for p in (root / "public").glob("*.html"))
    assert "<script>" not in html_text, "ไม่มี inline script (CSP script-src 'self')"
    # innerHTML ใช้ได้เฉพาะไฟล์ที่ผ่านการ escape ด้วย U.esc ทุกค่าที่มาจากผู้ใช้
    allowed = {"src/app.js", "src/ui/pages/pages.js", "src/ui/components/ui.js"}
    for path in (root / "src").rglob("*.js"):
        rel = str(path.relative_to(root))
        if "innerHTML" in path.read_text(encoding="utf-8") and "test" not in path.parts:
            assert rel in allowed, rel


def test_backend_has_no_command_or_code_execution_calls():
    """ตรวจโค้ด backend อัตโนมัติ: ห้ามมี os.system / subprocess / eval / exec / pickle / shell=True (กัน command injection)"""
    banned = [r"\bos\.system\b", r"\bos\.popen\b", r"\bsubprocess\b", r"\beval\s*\(", r"\bexec\s*\(", r"\bpickle\b",
              r"shell\s*=\s*True", r"__import__"]
    files = list((Path(config.BASE_DIR) / "modules").glob("*.py")) + [Path(config.BASE_DIR) / n for n in ("server.py", "seed.py", "config.py")]
    assert len(files) >= 20
    for path in files:
        code = "\n".join(line.split("#")[0] for line in path.read_text(encoding="utf-8").splitlines())
        for pattern in banned:
            assert not re.search(pattern, code), (path.name, pattern)


# ---------------------------------------------------------------------------
# F) ชั้น HTTP: header ความปลอดภัย / error page
# ---------------------------------------------------------------------------
def test_http_security_headers_and_error_pages_are_safe():
    httpd, base = tb.start_server()
    try:
        port = httpd.server_address[1]
        import urllib.request
        with urllib.request.urlopen(base + "/public/index.html") as page:
            headers = {k.lower(): v for k, v in page.headers.items()}
        assert "script-src 'self'" in headers["content-security-policy"] and "frame-ancestors 'none'" in headers["content-security-policy"]
        assert headers["x-content-type-options"] == "nosniff" and "python" not in headers.get("server", "").lower()

        def raw(data):
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.sendall(data)
            time.sleep(0.2)
            out = s.recv(8000).decode("utf-8", "replace")
            s.close()
            return out
        for probe in (b"GARBAGE\r\n\r\n", b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n", b"BREW /api HTTP/1.1\r\nHost: x\r\n\r\n",
                      b"GET /api/artworks?q=%ff%fe HTTP/1.1\r\nHost: x\r\n\r\n", b"POST /api/login HTTP/1.1\r\nContent-Length: -5\r\n\r\n",
                      b"POST /api/login HTTP/1.1\r\nContent-Length: abc\r\n\r\n"):
            out = raw(probe)
            assert "Traceback" not in out and "Python/" not in out and "BaseHTTPServer" not in out, probe[:30]
    finally:
        tb.stop_server(httpd)


# ---------------------------------------------------------------------------
# H) ส่วนเพิ่มตามสเปกข้อ 51-65: CSRF/Origin, upload, ไม่รั่วข้อมูล, wrong-type, boundary, Thai/emoji, payload
# ---------------------------------------------------------------------------
NAN = float("nan")
INF = float("inf")


def test_origin_check_blocks_cross_site_state_changes_only():
    body = json.dumps({"email": "buyer@art4sells.test", "password": tb.PASSWORD}).encode()
    base = {"Content-Type": "application/json", "Host": "127.0.0.1:8000"}
    send = lambda method, origin=None: tb.api.handle_request(
        method, "/api/login", {}, dict(base, **({"Origin": origin} if origin else {})), body)
    assert send("POST", "https://evil.example")[0] == 403 and send("POST", "https://evil.example")[1]["error"]["code"] == "CROSS_ORIGIN_BLOCKED"
    assert send("POST", "null")[0] == 403, "Origin: null (iframe/ไฟล์ในเครื่อง) ไม่ใช่เว็บเดียวกัน"
    assert send("POST", "http://127.0.0.1:8000")[0] == 200, "เว็บเดียวกัน"
    assert send("POST")[0] == 200, "ไม่มี Origin (curl / โปรแกรมอื่น) ผ่านตามปกติ"
    assert tb.api.handle_request("GET", "/api/artworks", {}, {"Origin": "https://evil.example", "Host": "x"}, b"")[0] == 200, "การอ่านไม่ถูกบล็อก (เป็นเรื่องของ CORS)"
    assert tb.api.handle_request("DELETE", "/api/cart", {}, {"Origin": "https://evil.example", "Host": "x"}, b"")[0] == 403
    original = config.ALLOWED_ORIGINS
    try:
        config.ALLOWED_ORIGINS = ("https://app.example",)
        assert send("POST", "https://app.example")[0] == 200, "origin ที่ตั้งใจอนุญาต (A4S_CORS_ORIGINS)"
    finally:
        config.ALLOWED_ORIGINS = original


def test_security_headers_present_on_api_and_static():
    httpd, base = tb.start_server()
    try:
        import urllib.request
        for url in (base + "/public/index.html", base + "/api/health"):
            with urllib.request.urlopen(url) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
            for name in ("content-security-policy", "x-content-type-options", "referrer-policy", "x-frame-options", "permissions-policy"):
                assert name in headers, (url, name)
        assert headers["cache-control"] == "no-store", "API ห้ามถูก cache"
    finally:
        tb.stop_server(httpd)
    csp = tb.server_module.build_csp()
    assert "unsafe-eval" not in csp and "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0], "script ห้าม inline"


def test_pages_have_no_inline_scripts_so_strict_csp_is_safe():
    for page in (Path(config.PROJECT_DIR) / "public").glob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text), page.name


def png_bytes(extra=b""):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20 + extra


def test_upload_content_checks_and_safe_storage():
    ok, errors = uploads.validate_upload("art.png", "image/png", png_bytes())
    assert not errors and ok["detected_type"] == "png"
    assert not uploads.validate_upload("a.jpeg", "image/jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 30)[1]
    assert not uploads.validate_upload("a.webp", "image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 20)[1]
    bad_cases = [
        ("fake.png", "image/png", b"just plain text, not an image"),                       # ชื่อเป็นรูป เนื้อไม่ใช่
        ("a.png", "image/png", b"\xff\xd8\xff" + b"\x00" * 30),                             # เนื้อเป็น jpeg แต่ชื่อ png
        ("shell.php", "image/png", png_bytes()), ("a.png.php", "image/png", png_bytes()),   # นามสกุลอันตราย
        ("a.png", "text/html", png_bytes()), ("a.png", "image/png", png_bytes(b"<?php system($_GET[1]); ?>")),
        ("a.png", "image/png", png_bytes(b"<script>alert(1)</script>")), ("a.png", "image/png", png_bytes(b"<svg onload=1>")),
        ("a.png", "image/png", b""), ("../../x.png", "image/png", png_bytes()), ("a.png", "image/png", "not bytes"),
        ("MZ.exe", "application/octet-stream", b"MZ\x90\x00"), ("a.png", "image/png", b"#!/bin/sh\n" + png_bytes()),
        ("a.png", "image/png", png_bytes(b"\x00" * (config.MAX_UPLOAD_BYTES + 1))),
    ]
    for filename, ctype, data in bad_cases:
        assert uploads.validate_upload(filename, ctype, data)[1], (filename, ctype, str(data)[:30])
    folder = tb.WORK_DIR / "uploads_test"
    first, second = uploads.save_upload(folder, png_bytes(), "png"), uploads.save_upload(folder, png_bytes(), "png")
    assert first != second and re.fullmatch(r"[0-9a-f]{32}\.png", first)
    stored = folder / first
    assert stored.read_bytes() == png_bytes() and not (stored.stat().st_mode & 0o111), "ต้องไม่มีสิทธิ์ execute"
    assert sorted(p.name for p in folder.iterdir()) == sorted([first, second])
    for evil_extension in ("php", "exe", "../png", "png/../../x", ""):
        try:
            uploads.save_upload(folder, b"x", evil_extension)
            raise AssertionError("ต้องปฏิเสธ " + evil_extension)
        except ValueError:
            pass


def test_no_secrets_paths_or_internals_in_any_response():
    admin, buyer, mika = login("admin"), login("buyer"), login("mika")
    call("POST", "/api/cart", {"artwork_id": "w3"}, buyer)
    with mailbox():
        call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})
    forbidden = ["Traceback", 'File "', "/home/", "/tmp/", "backend/", ".py\"", "pbkdf2", "password_hash", "token_hash", "otp_hash",
                 "Errno", "JSONDecodeError", "KeyError", "Exception"]
    gets = [("/api/me", buyer), ("/api/users", admin), ("/api/users/u1", admin), ("/api/logs", admin), ("/api/orders", admin), ("/api/reviews", admin),
            ("/api/artworks", admin), ("/api/artworks/w1", None), ("/api/artists", None), ("/api/dashboard", admin), ("/api/cart", buyer),
            ("/api/wishlist", buyer), ("/api/follows", buyer), ("/api/me/notifications", buyer), ("/api/categories", None), ("/api/orders/o1", buyer),
            ("/api/artists/a1", None)]
    for path, token in gets:
        status, data = call("GET", path, None, token)
        text = json.dumps(data, ensure_ascii=False)
        assert status == 200, (path, status)
        for needle in forbidden:
            assert needle not in text, (path, needle)
    # หน้า error ต่าง ๆ ก็ต้องไม่รั่วเช่นกัน
    (tb.WORK_DIR / "artworks.json").write_text("{corrupt", encoding="utf-8")
    for path in ("/api/artworks", "/api/artworks/w1", "/api/cart", "/api/dashboard"):
        status, data = call("GET", path, None, admin if path != "/api/cart" else buyer)
        text = json.dumps(data, ensure_ascii=False)
        assert status == 500 and not any(n in text for n in forbidden), (path, text)
    assert data["error"]["message"] and "ไฟล์ข้อมูลเสียหาย" in call("GET", "/api/artworks")[1]["error"]["message"]


def test_boolean_type_confusion_is_rejected():
    admin, mika = login("admin"), login("mika")
    for confused in ("true", "false", "1", "0", 1, 0, None, [], {}, "yes", "True", [True]):
        assert call("POST", "/api/admin/data/clear/preview", {"scopes": ["reviews"], "preserve_admins": confused}, admin)[0] == 400, repr(confused)
        assert call("PUT", "/api/users/a1", {"accepts_commissions": confused}, mika)[0] == 400, repr(confused)
    assert call("PUT", "/api/users/a1", {"accepts_commissions": True}, mika)[0] == 200
    assert call("PUT", "/api/users/a1", {"accepts_commissions": False}, mika)[1]["accepts_commissions"] is False
    assert call("POST", "/api/admin/data/clear/preview", {"scopes": ["reviews"], "preserve_admins": False}, admin)[0] == 200
    for confused in ("maybe", "2", "", "null", "truee", "tru"):                    # query string: รับเฉพาะ true/false/1/0/yes/no (ไม่สนตัวพิมพ์/ช่องว่างหัวท้าย)
        assert call("GET", "/api/artworks", None, None, {"available": confused})[0] == 400, repr(confused)
    assert call("GET", "/api/artworks", None, None, {"available": "yes"})[0] == 200


WRONG_VALUES = [None, [], {}, "text", True, False, 1.5, 10 ** 400, NAN, INF, -INF, [1], [None], {"a": 1}]


def post_raw(path, body, token=None):
    """ส่ง JSON ที่อาจมี NaN/Infinity ตามจริง (json.dumps จะเขียนเป็น NaN / Infinity)"""
    return call("POST", path, json.dumps(body).encode("utf-8"), token)


def test_wrong_type_matrix_is_rejected_field_by_field():
    mika, buyer = login("mika"), login("buyer")
    admin = login("admin")
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    tb.pay_and_complete(oid, admin)
    review_ok = {"artwork_id": "w5", "rating": 4, "comment": "Valid comment"}
    artwork_ok = tb.new_artwork_body()
    register_ok = {"name": "Matrix User", "email": "matrix@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"}
    # (endpoint, ตัวอย่างข้อมูลที่ถูกต้อง, token, ช่อง, ค่าที่ "ถูกต้องจริง" ซึ่งไม่นับว่าผิด)
    matrix = [
        ("/api/artworks", artwork_ok, mika, "title", ["text"]),
        ("/api/artworks", artwork_ok, mika, "category", []),
        ("/api/artworks", artwork_ok, mika, "price", [1.5]),
        ("/api/artworks", artwork_ok, mika, "sale_type", []),
        ("/api/artworks", artwork_ok, mika, "description", [None, "text"]),
        ("/api/artworks", artwork_ok, mika, "tags", [None, [], "text"]),
        ("/api/reviews", review_ok, buyer, "rating", []),
        ("/api/reviews", review_ok, buyer, "comment", []),
        ("/api/reviews", review_ok, buyer, "artwork_id", ["text"]),
        ("/api/cart", {"artwork_id": "w3", "quantity": 1}, buyer, "artwork_id", ["text"]),
        ("/api/cart", {"artwork_id": "w3", "quantity": 1}, buyer, "quantity", []),
        ("/api/orders", {"items": [{"artwork_id": "w3", "quantity": 1}]}, buyer, "items", []),
        ("/api/register", register_ok, None, "name", ["text"]),
        ("/api/register", register_ok, None, "email", []),
        ("/api/register", register_ok, None, "password", []),
        ("/api/register", register_ok, None, "role", ["text"]),
        ("/api/login", {"email": "buyer@art4sells.test", "password": tb.PASSWORD}, None, "email", []),
        ("/api/login", {"email": "buyer@art4sells.test", "password": tb.PASSWORD}, None, "password", []),
        ("/api/categories", {"name": "Matrix Cat", "description": "d"}, admin, "name", ["text"]),
    ]
    checked = 0
    for path, good, token, field, valid_values in matrix:
        for wrong in WRONG_VALUES:
            if any(wrong == v and type(wrong) is type(v) for v in valid_values):
                continue
            body = dict(good, **{field: wrong})
            if path == "/api/orders":
                body = {"items": wrong}
            status, data = post_raw(path, body, token)
            assert status < 500, (path, field, wrong, status)
            assert status in (400, 401, 404, 409), (path, field, repr(wrong)[:30], status, data)       # ต้องถูกปฏิเสธ ไม่ใช่สำเร็จ
            assert "Traceback" not in json.dumps(data)
            checked += 1
    assert checked > 200
    assert post_raw("/api/reviews", review_ok, buyer)[0] == 201, "ข้อมูลถูกต้องต้องผ่าน (ตัวอย่างต้นแบบไม่ผิด)"


def test_missing_required_fields_are_rejected():
    mika, buyer = login("mika"), login("buyer")
    cases = [("/api/artworks", tb.new_artwork_body(), mika, ("title", "category", "price", "sale_type")),
             ("/api/register", {"name": "Missing One", "email": "m1@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!"}, None, ("name", "email", "password")),
             ("/api/login", {"email": "buyer@art4sells.test", "password": tb.PASSWORD}, None, ("email", "password")),
             ("/api/cart", {"artwork_id": "w3"}, buyer, ("artwork_id",)),
             ("/api/wishlist", {"artwork_id": "w3"}, buyer, ("artwork_id",)),
             ("/api/follows", {"artist_id": "a1"}, buyer, ("artist_id",)),
             ("/api/auth/forgot-password", {"email": "buyer@art4sells.test"}, None, ("email",)),
             ("/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": "12345"}, None, ("email", "code")),
             ("/api/auth/change-password", {"current_password": "x", "new_password": "y", "confirm_password": "y"}, buyer,
              ("current_password", "new_password", "confirm_password"))]
    for path, good, token, required in cases:
        for field in required:
            body = {k: v for k, v in good.items() if k != field}
            status, _ = call("POST", path, body, token)
            assert status == 400, (path, field, status)
        assert call("POST", path, {}, token)[0] == 400, path
    for body in ({"rating": 5, "comment": "no artwork"}, {"artwork_id": "w5", "comment": "no rating here"}, {"artwork_id": "w5", "rating": 5}):
        assert call("POST", "/api/reviews", body, buyer)[0] == 400, body


def test_length_boundaries_min_max_and_plus_one():
    admin, mika, buyer = login("admin"), login("mika"), login("buyer")
    count = [0]

    def register(**changes):
        count[0] += 1
        body = {"name": "Boundary User", "email": "b%d@x.io" % count[0], "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"}
        body.update(changes)
        if "confirm_password" not in changes:
            body["confirm_password"] = body["password"]            # confirm ตามรหัสผ่านที่ override (ไม่ให้ error ของ confirm บังเทสต์ความยาว)
        return call("POST", "/api/register", body)[0]
    low, high = config.DISPLAY_NAME_RANGE
    assert [register(name="n" * k) for k in (low - 1, low, high, high + 1)] == [400, 201, 201, 400]
    assert [register(password="Ab1!" + "x" * (k - 4)) for k in (config.PASSWORD_MIN_LENGTH - 1, config.PASSWORD_MIN_LENGTH,
                                                                config.PASSWORD_MAX_LENGTH, config.PASSWORD_MAX_LENGTH + 1)] == [400, 201, 201, 400]
    local254, local255 = "a" * (254 - 5), "a" * (255 - 5)
    assert [register(email=local + "@b.co") for local in (local254, local255)] == [201, 400]
    art = lambda **c: call("POST", "/api/artworks", tb.new_artwork_body(**c), mika)[0]
    assert [art(title="t" * k) for k in (0, 1, 80, 81)] == [400, 201, 201, 400]
    assert [art(description="d" * k) for k in (0, 2000, 2001)] == [201, 201, 400]
    assert [art(tags=["t%d" % i for i in range(k)]) for k in (0, config.MAX_TAGS, config.MAX_TAGS + 1)] == [201, 201, 400]
    assert [art(tags=["x" * k]) for k in (30, 31)] == [201, 400]
    assert [art(price=p) for p in (0, 0.01, config.PRICE_MAX, config.PRICE_MAX + 0.01, -0.01)] == [201, 201, 201, 400, 400]
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    tb.pay_and_complete(oid, admin)
    review = lambda **c: call("POST", "/api/reviews", dict({"artwork_id": "w5", "rating": 5, "comment": "Valid text"}, **c), buyer)[0]
    assert [review(comment="c" * k) for k in (4, 1001)] == [400, 400]
    assert [review(rating=r) for r in (0, 6, -1)] == [400, 400, 400]
    assert review(comment="c" * 1000, rating=1) == 201
    cart = lambda q: call("POST", "/api/cart", {"artwork_id": "w3", "quantity": q}, buyer)[0]
    assert [cart(q) for q in (0, config.MAX_ORDER_QUANTITY + 1)] == [400, 400]
    assert cart(config.MAX_ORDER_QUANTITY) == 201
    assert call("POST", "/api/cart", {"artwork_id": "w3", "quantity": 1}, buyer)[0] == 400, "บวกแล้วเกินจำนวนสูงสุด"
    assert call("GET", "/api/artworks", None, None, {"q": "ก" * 100})[0] == 200 and call("GET", "/api/artworks", None, None, {"q": "ก" * 101})[0] == 400


def test_thai_emoji_and_special_text_roundtrip_and_search():
    mika, admin, buyer = login("mika"), login("admin"), login("buyer")
    title = "ปลาคราฟใต้แสงจันทร์ 🎏"
    description = "ภาพวาดหมึก ‘คราฟ’ \"สวย\" <b>ไม่ใช่ตัวหนา</b>\nบรรทัดที่สอง\tแท็บ & เครื่องหมาย 'พิเศษ' ✨"
    status, art = call("POST", "/api/artworks", tb.new_artwork_body(title=title, description=description, tags=["ปลา", "🎏", "ญี่ปุ่น"]), mika)
    assert status == 201 and art["title"] == title and art["description"] == description and art["tags"] == ["ปลา", "🎏", "ญี่ปุ่น"]
    call("POST", "/api/artworks/" + art["id"] + "/submit", None, mika)
    call("POST", "/api/artworks/" + art["id"] + "/approve", None, admin)
    for q, search_in in (("ปลาคราฟ", "title"), ("🎏", "all"), ("ญี่ปุ่น", "tag"), ("MIKA", "artist")):
        found = call("GET", "/api/artworks", None, None, {"q": q, "search_in": search_in})[1]
        assert art["id"] in [a["id"] for a in found["items"]], (q, search_in)
    stored = [a for a in tb.read_json_file("artworks") if a["id"] == art["id"]][0]
    assert stored["title"] == title, "เก็บเป็น UTF-8 ตามจริง (ไม่ถูก escape ทิ้ง)"
    raw_file = (tb.WORK_DIR / "artworks.json").read_text(encoding="utf-8")
    assert "ปลาคราฟ" in raw_file, "ไฟล์ JSON เก็บภาษาไทยอ่านออกได้"
    status, user = call("POST", "/api/register", {"name": "สมชาย ใจดี 🎨", "email": "thai@x.io", "password": "รหัสผ่าน123Abc!", "confirm_password": "รหัสผ่าน123Abc!", "role": "USER"})
    assert status == 201 and user["user"]["name"] == "สมชาย ใจดี 🎨"
    assert call("POST", "/api/login", {"email": "thai@x.io", "password": "รหัสผ่าน123Abc!"})[0] == 200, "รหัสผ่านภาษาไทยใช้ได้"
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": art["id"], "quantity": 1}]}, buyer)[1]["id"]
    tb.pay_and_complete(oid, admin)
    comment = "งานสวยมาก 😍 ประทับใจ!\nขอบคุณค่ะ <3 'ok' \"ok\""
    review = call("POST", "/api/reviews", {"artwork_id": art["id"], "rating": 5, "comment": comment}, buyer)
    assert review[0] == 201 and review[1]["comment"] == comment
    assert call("GET", "/api/reviews", None, None, {"artwork_id": art["id"]})[1]["items"][0]["comment"] == comment


def test_injection_style_payloads_on_every_text_entry_are_inert():
    sql = ["' OR '1'='1", "'; DROP TABLE users;--", "\" OR \"\"=\"", "1; SELECT * FROM users", "admin'--", "' UNION SELECT password_hash FROM users--"]
    xss = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "\"><svg/onload=alert(1)>", "javascript:alert(1)", "{{7*7}}", "${7*7}", "%s%s%s%n"]
    path_payloads = ["../../../../etc/passwd", "..\\..\\windows\\system32", "/etc/passwd", "....//....//etc/passwd", "%2e%2e%2f%2e%2e%2f", "file:///etc/passwd"]
    shell = ["; ls -la", "| cat /etc/passwd", "`id`", "$(whoami)", "&& rm -rf /"]
    users_before = len(tb.read_json_file("users"))
    mika = login("mika")
    for index, payload in enumerate(sql + xss + path_payloads + shell):
        for status, _ in (call("POST", "/api/login", {"email": payload, "password": payload}),
                          call("POST", "/api/auth/forgot-password", {"email": payload}),
                          call("POST", "/api/auth/verify-reset-code", {"email": payload, "code": payload}),
                          call("POST", "/api/auth/reset-password", {"reset_token": payload, "new_password": payload, "confirm_password": payload}),
                          call("GET", "/api/artworks", None, None, {"q": payload}),
                          call("GET", "/api/artworks/" + payload),
                          call("POST", "/api/cart", {"artwork_id": payload}, mika),
                          call("POST", "/api/wishlist", {"artwork_id": payload}, mika)):
            assert status < 500, (payload, status)
        status, data = call("POST", "/api/artworks", tb.new_artwork_body(title="t" + payload[:70], description=payload), mika)
        assert status in (201, 400), payload
        if status == 201:
            assert data["description"] == payload.strip(), "เก็บเป็นข้อความตามเดิม ไม่ถูกตีความ"
        reg = call("POST", "/api/register", {"name": "P" + payload[:40], "email": "p%d@x.io" % index, "password": "Passw0rd1!" + payload[:20], "confirm_password": "Passw0rd1!" + payload[:20], "role": "USER"})[0]
        assert reg in (201, 400), payload
    users_after = tb.read_json_file("users")
    assert all(isinstance(u, dict) and u.get("id") for u in users_after) and len(users_after) >= users_before, "ตารางผู้ใช้ยังสมบูรณ์"
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": tb.PASSWORD})[0] == 200
    for name in storage.COLLECTIONS:
        assert isinstance(storage.load_json(name), list), name


def test_authorization_header_edge_cases_and_session_handling():
    good = login("buyer")
    for header in ("", "Bearer", "Bearer ", "Basic " + good, "bearer-" + good, good, "Bearer " + "a" * 10000, "Bearer\t" + good + " extra", "Token " + good):
        status, _ = tb.api.handle_request("GET", "/api/cart", {}, {"Authorization": header}, b"")
        assert status == 401, repr(header[:30])
    assert tb.api.handle_request("GET", "/api/cart", {}, {"authorization": "bearer " + good}, b"")[0] == 200, "ชื่อ header/scheme ไม่สนตัวพิมพ์"
    second = login("buyer")
    for _ in range(3):
        assert call("GET", "/api/me", None, good)[0] == 200 and call("GET", "/api/me", None, second)[0] == 200
    call("POST", "/api/logout", None, good)
    assert call("GET", "/api/me", None, good)[0] == 401 and call("GET", "/api/me", None, second)[0] == 200, "session แยกกัน"
    raw_sessions = (tb.WORK_DIR / "sessions.json").read_text(encoding="utf-8")
    assert second not in raw_sessions, "ไฟล์เก็บเฉพาะ hash ของ token"


def test_protected_admin_account_rules():
    admin = login("admin")
    assert call("POST", "/api/users/ad1/ban", None, admin)[0] == 409
    assert call("DELETE", "/api/users/ad1", None, admin)[0] == 409
    assert call("PUT", "/api/users/ad1", {"role": "USER"}, admin)[0] == 409, "admin เปลี่ยน role ตัวเองไม่ได้"
    assert call("PUT", "/api/users/ad1", {"role": "ARTIST"}, admin)[0] == 409
    second = call("POST", "/api/users", {"name": "Admin Two", "email": "a2@x.io", "password": "Passw0rd1!", "role": "ADMIN"}, admin)[1]
    assert call("POST", "/api/users/" + second["id"] + "/ban", None, admin)[0] == 409, "ห้ามระงับ admin คนไหนเลย"
    assert storage.get_record("users", "ad1")["role"] == "ADMIN" and storage.get_record("users", "ad1")["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# G) Fuzz: ข้อมูลสุ่มแปลก ๆ ต้องไม่ทำให้เกิด 500 / traceback / ไฟล์ข้อมูลเสีย
# ---------------------------------------------------------------------------
def random_value(rng, depth=0):
    nasty = ["", " ", "a" * 300, "<script>alert(1)</script>", "' OR '1'='1", "../../etc/passwd", "${7*7}", "%00", "\x00", "\u202e",
             "ก" * 100, "😀", "NaN", "null", "true", "{}", "[]", "\\", "\"", "w1", "a1", "u1", "o1", "r1", "ad1", "CLEAR", "RESET", "USER", "ADMIN"]
    kinds = ["none", "bool", "int", "big", "float", "str", "nasty", "list", "dict"]
    kind = rng.choice(kinds if depth < 3 else kinds[:7])
    if kind == "none":
        return None
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "int":
        return rng.choice([0, 1, -1, 5, 99, 10 ** 12, -10 ** 12, rng.randint(-1000, 1000)])
    if kind == "big":
        return 10 ** rng.randint(20, 300)
    if kind == "float":
        return rng.choice([0.0, -0.0, 1.5, 1e308, -1e308, 1e-320, 12.345])
    if kind == "str":
        return "".join(chr(rng.choice([rng.randint(32, 126), rng.randint(0, 31), rng.randint(0x80, 0x2FFF)])) for _ in range(rng.randint(0, 40)))
    if kind == "nasty":
        return rng.choice(nasty)
    if kind == "list":
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {rng.choice(["title", "price", "email", "password", "name", "artwork_id", "quantity", "rating", "comment", "role", "scopes",
                        "code", "reset_token", "status", "user_id", "items", "tags", "category", "confirm_text"]): random_value(rng, depth + 1)
            for _ in range(rng.randint(0, 5))}


def test_fuzz_endpoints_never_crash_or_leak():
    rng = random.Random(35)
    tokens = [None, login("buyer"), login("mika"), login("admin")]
    targets = [("POST", "/api/register"), ("POST", "/api/login"), ("POST", "/api/artworks"), ("PUT", "/api/artworks/w{n}"),
               ("POST", "/api/artworks/w{n}/reject"), ("POST", "/api/orders"), ("POST", "/api/reviews"), ("PUT", "/api/orders/o{n}"),
               ("POST", "/api/cart"), ("PUT", "/api/cart/c{n}"), ("POST", "/api/wishlist"), ("POST", "/api/follows"),
               ("POST", "/api/auth/change-password"), ("POST", "/api/auth/forgot-password"), ("POST", "/api/auth/verify-reset-code"),
               ("POST", "/api/auth/reset-password"), ("POST", "/api/admin/data/clear/preview"), ("POST", "/api/admin/data/clear"),
               ("POST", "/api/admin/data/reset"), ("POST", "/api/categories"), ("PUT", "/api/users/u{n}"), ("POST", "/api/users")]
    valid = {"/api/register": {"name": "Fuzz User", "email": "fz{n}@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"},
             "/api/artworks": tb.new_artwork_body(), "/api/orders": {"items": [{"artwork_id": "w3", "quantity": 1}]},
             "/api/reviews": {"artwork_id": "w3", "rating": 4, "comment": "Fuzzed comment"},
             "/api/cart": {"artwork_id": "w3", "quantity": 1}, "/api/wishlist": {"artwork_id": "w3"},
             "/api/follows": {"artist_id": "a1"}, "/api/categories": {"name": "Fuzz Cat {n}", "description": "d"},
             "/api/auth/forgot-password": {"email": "buyer@art4sells.test"}}
    lists = ["/api/artworks", "/api/orders", "/api/reviews", "/api/users", "/api/logs", "/api/me/notifications", "/api/cart", "/api/wishlist"]
    keys = ["q", "page", "page_size", "sort", "category", "artist_id", "min_price", "max_price", "status", "scope", "action", "unread", "x"]
    seen = {}
    with mailbox():
        for _ in range(900):
            token = rng.choice(tokens)
            method, path = rng.choice(targets)
            path = path.replace("{n}", str(rng.randint(1, 20)))
            body = json.dumps(random_value(rng)).encode("utf-8") if rng.random() < 0.9 else rng.choice([b"", b"{", b"\xff", b"[]", b"null"])
            status, data = call(method, path, body, token)
            seen[status] = seen.get(status, 0) + 1
            assert status < 500, (method, path, body[:120], data)
            assert "Traceback" not in json.dumps(data), (method, path)
        for round_number in range(400):                        # mutation fuzz: ข้อมูลที่ถูกต้อง แต่เสียหนึ่งช่อง
            path = rng.choice(sorted(valid))
            body = dict(valid[path])
            for key in list(body):
                if isinstance(body[key], str) and "{n}" in body[key]:
                    body[key] = body[key].replace("{n}", str(round_number))
            if rng.random() < 0.85:
                body[rng.choice(sorted(body))] = random_value(rng)
            status, data = call("POST", path, json.dumps(body).encode("utf-8"), rng.choice(tokens))
            seen[status] = seen.get(status, 0) + 1
            assert status < 500, (path, str(body)[:150], data)
            assert "Traceback" not in json.dumps(data)
        for _ in range(500):
            query = {rng.choice(keys): str(random_value(rng))[:60] for _ in range(rng.randint(0, 4))}
            status, data = call("GET", rng.choice(lists), None, rng.choice(tokens), query)
            assert status < 500, (query, data)
    assert max(seen) < 500 and any(code < 300 for code in seen) and any(code >= 400 for code in seen), seen
    for name in storage.COLLECTIONS:                           # ไฟล์ข้อมูลทุกไฟล์ต้องยังเป็น JSON list ที่อ่านได้
        assert isinstance(storage.load_json(name), list), name


# ===========================================================================
# Phase 3.5b: Login authentication hardening + password policy
# (login ต้องตรวจรหัสผ่านจริงทุกบัญชี, ไม่มี email bypass, นโยบายรหัสผ่านเดียวทั้งระบบ, confirm password, Forgot Password)
# ===========================================================================
DEMO_ACCOUNTS = {"admin": "ADMIN", "mika": "ARTIST", "kenji": "ARTIST", "nara": "ARTIST", "lumi": "ARTIST", "buyer": "USER", "ton": "USER"}
POLICY_REJECT = ["abcdefgh", "ABCDEFGH", "12345678", "Abcdefgh", "Abcdef12", "abcdef1!", "ABCDEF1!", "Abc!", "abcdef12",
                 "Abcdef12 ", "", "ÀÉÎõü123!"]          # "Abcdef12 " = ช่องว่างไม่นับเป็นอักษรพิเศษ,  ตัวอักษรนอก ASCII ไม่นับเป็น a-z/A-Z
POLICY_ACCEPT = ["Abcd1234!", "HelloWorld9@", "TestPass1#", "Abcdef12!", "รหัสผ่าน123Aa!"]
_email_counter = [0]


def fresh_email():
    _email_counter[0] += 1
    return "p35b%d@x.io" % _email_counter[0]


def register_with(password_value, confirm=None, _full=False, **extra):
    """สมัครสมาชิกด้วย email ใหม่ (confirm ไม่ระบุ = ตรงกับ password) คืน (status, data)  _full=True คืน Response เต็ม (ดู Set-Cookie)"""
    body = {"name": "Policy User", "email": fresh_email(), "password": password_value,
            "confirm_password": password_value if confirm is None else confirm, "role": "USER"}
    body.update(extra)
    if _full:
        return tb.call_full("POST", "/api/register", body)
    return call("POST", "/api/register", body)


def login_status(email, password_value):
    return call("POST", "/api/login", {"email": email, "password": password_value})[0]


def test_login_requires_the_correct_password():
    good, wrong = "buyer@art4sells.test", "WrongPass1!"
    assert login_status(good, tb.PASSWORD) == 200, "email ถูก + password ถูก"
    bad_pw, no_user = call("POST", "/api/login", {"email": good, "password": wrong}), call("POST", "/api/login", {"email": "nobody@art4sells.test", "password": wrong})
    assert bad_pw[0] == 401 and no_user[0] == 401, "email ถูก + password ผิด / email ไม่มี + password ใด ๆ"
    assert tb.error_code(bad_pw) == tb.error_code(no_user) == "INVALID_CREDENTIALS"
    assert bad_pw[1]["error"]["message"] == no_user[1]["error"]["message"] == "อีเมลหรือรหัสผ่านไม่ถูกต้อง", "ข้อความกลาง: ไม่เผยว่ามีอีเมลนี้หรือไม่"
    assert login_status("nobody@art4sells.test", tb.PASSWORD) == 401, "รหัสผ่านที่ถูกของบัญชีอื่นก็ใช้กับอีเมลที่ไม่มีไม่ได้"
    for empty in ({"email": good, "password": ""}, {"email": good, "password": None}, {"email": good}):
        assert call("POST", "/api/login", empty)[0] == 400, empty
    for wrong_type in (12345678, ["x"], {"a": 1}, True):
        assert call("POST", "/api/login", {"email": good, "password": wrong_type})[0] == 400, wrong_type      # ไม่แปลงชนิดเงียบ ๆ
    assert login_status(good, "x") == 401, "สั้นเกินไป -> ล้มเหลวแบบ auth fail"
    assert login_status(good, "A1!" + "x" * 126) == 400, "129 ตัวขึ้นไปถูกปฏิเสธ"
    # รหัสผ่านถูกเทียบตามที่พิมพ์ทุกตัวอักษร: ไม่ trim / ไม่แปลงตัวพิมพ์ / ไม่ตัดตัวอักษร
    for altered in (tb.PASSWORD + " ", " " + tb.PASSWORD, tb.PASSWORD.lower(), tb.PASSWORD.upper(), tb.PASSWORD[:-1], tb.PASSWORD[1:]):
        assert login_status(good, altered) == 401, repr(altered)
    assert login_status("  BUYER@Art4Sells.TEST ", tb.PASSWORD) == 200, "อีเมล normalize เป็นตัวพิมพ์เล็กตาม implementation เดิม"
    assert login_status("  BUYER@Art4Sells.TEST ", wrong) == 401


def test_login_does_not_apply_the_password_policy():
    """บัญชีเก่าที่รหัสผ่านอ่อน (ตั้งไว้ก่อนมีนโยบายใหม่) ยัง login ได้ด้วยรหัสของตัวเอง - login มีหน้าที่ verify ไม่ใช่บอกว่าครบเงื่อนไขไหม"""
    storage.update_record("users", "u2", {"password_hash": security.hash_password("legacy1234")})
    assert validation.validate_password("legacy1234") is not None
    assert login_status("ton@art4sells.test", "legacy1234") == 200
    assert login_status("ton@art4sells.test", "legacy1235") == 401
    weak_wrong = call("POST", "/api/login", {"email": "ton@art4sells.test", "password": "abc"})
    assert weak_wrong[0] == 401 and "ตัวพิมพ์" not in weak_wrong[1]["error"]["message"], "ห้ามบอกว่ารหัสขาดตัวพิมพ์ใหญ่/อักษรพิเศษตอน login"


def test_demo_accounts_do_not_bypass_password_verification():
    users_file = (tb.WORK_DIR / "users.json").read_text(encoding="utf-8")
    assert tb.PASSWORD not in users_file and users_file.count("pbkdf2_sha256$") >= len(DEMO_ACCOUNTS), "บัญชีตัวอย่างเก็บเป็น password hash จริง"
    for name, role in DEMO_ACCOUNTS.items():
        email = name + "@art4sells.test"
        status, data, token = tb.call_login(email, tb.PASSWORD)
        assert status == 200 and data["user"]["role"] == role and token and "token" not in data, email
        for wrong in (secrets.token_urlsafe(12), "12345678", "anything123", "Demo1234", "demo1234!", "DEMO1234!", "password", "Demo1234! "):
            assert login_status(email, wrong) == 401, (email, wrong)
        assert login_status(email, "") == 400 and login_status(email.upper(), "anything123") == 401, email


def test_no_email_based_authentication_bypass_in_backend_code():
    for source in sorted((Path(__file__).resolve().parent.parent / "modules").glob("*.py")) + [Path(__file__).resolve().parent.parent / "server.py"]:
        text = source.read_text(encoding="utf-8")
        assert "art4sells.test" not in text, source.name + ": อีเมลตัวอย่างต้องอยู่ใน seed เท่านั้น ห้ามเป็นเงื่อนไขใน logic"
        assert not re.search(r"endswith\(\s*[\"']@|is_demo|demo_email|known_test", text), source.name + ": พบรูปแบบ bypass ด้วยอีเมล"
        assert "Any 8+" not in text


def test_password_policy_table_through_validator_and_register():
    for pw in POLICY_REJECT:
        assert validation.validate_password(pw) is not None, repr(pw)
        status, data = register_with(pw)
        assert status == 400 and "password" in data["error"]["fields"], repr(pw)
    for pw in POLICY_ACCEPT:
        assert validation.validate_password(pw) is None, repr(pw)
        assert register_with(pw)[0] == 201, repr(pw)
    # ข้อความบอกกฎที่ขาดอย่างเข้าใจง่าย
    for pw, must_mention in (("Abc!", "8"), ("abcdef1!", "ตัวพิมพ์ใหญ่"), ("ABCDEF1!", "ตัวพิมพ์เล็ก"), ("Abcdefg!", "ตัวเลข"), ("Abcdef12", "อักษรพิเศษ")):
        assert must_mention in validation.validate_password(pw), pw
    for ch in string.punctuation:                                # ทุกอักษรพิเศษ ASCII นับ
        assert validation.validate_password("Abcdef1" + ch) is None, ch
    # ความยาว 8-128
    low, high = config.PASSWORD_MIN_LENGTH, config.PASSWORD_MAX_LENGTH
    assert (low, high) == (8, 128)
    for length, accepted in ((low - 1, False), (low, True), (high, True), (high + 1, False)):
        pw = "Aa1!" + "x" * (length - 4)
        assert len(pw) == length and (validation.validate_password(pw) is None) == accepted, length
        assert register_with(pw)[0] == (201 if accepted else 400), length
    # ชนิดข้อมูลแปลก ๆ ต้องถูกปฏิเสธ ไม่ crash
    for weird in (12345678, ["Abcdef12!"], {"a": 1}, True, None):
        assert register_with(weird, confirm="Abcdef12!")[0] == 400, weird
    assert register_with("Abcdef1!\ud800")[0] == 400, "อักขระที่เข้ารหัส UTF-8 ไม่ได้ต้องไม่ทำให้ server ล้ม"
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": "Abcdef1!\ud800"})[0] == 400


def test_register_confirm_password_must_match_exactly():
    mismatch = register_with("Abcd1234!", confirm="Abcd1234?")
    assert mismatch[0] == 400 and "confirm_password" in mismatch[1]["error"]["fields"]
    users_before = len(tb.read_json_file("users"))
    for bad_confirm in ("abcd1234!", "Abcd1234! ", " Abcd1234!", "", None, 12345678, ["Abcd1234!"]):
        body = {"name": "Confirm User", "email": fresh_email(), "password": "Abcd1234!", "role": "USER", "confirm_password": bad_confirm}
        assert call("POST", "/api/register", body)[0] == 400, repr(bad_confirm)
    missing = {"name": "Confirm User", "email": fresh_email(), "password": "Abcd1234!", "role": "USER"}
    assert call("POST", "/api/register", missing)[0] == 400, "ไม่ส่ง confirm_password"
    assert len(tb.read_json_file("users")) == users_before, "สมัครไม่สำเร็จต้องไม่สร้างบัญชี"
    assert register_with("Abcd1234!", confirm="Abcd1234!")[0] == 201, "ตรงกันทุกตัวอักษร"
    # เว้นวรรคท้ายเป็นส่วนหนึ่งของรหัสผ่าน: Abcd1234! กับ "Abcd1234! " เป็นคนละรหัส
    email = fresh_email()
    assert register_with("Abcd1234! ", email=email)[0] == 201
    assert login_status(email, "Abcd1234! ") == 200 and login_status(email, "Abcd1234!") == 401


def test_registered_account_can_logout_and_login_again_with_its_own_password():
    email, pw = fresh_email(), "Mine5ecret#"
    result = register_with(pw, email=email, _full=True)
    status, token = result.status, tb.cookie_token(result)
    assert status == 201 and token
    assert call("POST", "/api/logout", None, token)[0] == 200
    assert call("GET", "/api/me", None, token)[0] == 401, "token หลัง logout ใช้ไม่ได้"
    again = call("POST", "/api/login", {"email": email, "password": pw})
    assert again[0] == 200 and again[1]["user"]["email"] == email
    for wrong in ("Mine5ecret!", "mine5ecret#", pw + " ", tb.PASSWORD, "anything123", ""):
        assert login_status(email, wrong) in (400, 401), wrong
    other = fresh_email()
    assert register_with("Other5ecret#", email=other)[0] == 201
    assert login_status(email, "Other5ecret#") == 401 and login_status(other, pw) == 401, "รหัสของบัญชีหนึ่งใช้กับอีกบัญชีไม่ได้"


def test_admin_created_user_uses_the_same_password_policy():
    admin = login("admin")
    for pw in POLICY_REJECT:
        status, data = call("POST", "/api/users", {"name": "Made By Admin", "email": fresh_email(), "password": pw, "role": "USER"}, admin)
        assert status == 400 and "password" in data["error"]["fields"], repr(pw)
    email = fresh_email()
    assert call("POST", "/api/users", {"name": "Made By Admin", "email": email, "password": "Abcdef12!", "role": "USER"}, admin)[0] == 201
    assert login_status(email, "Abcdef12!") == 200 and login_status(email, "abcdef12") == 401


def test_change_password_uses_the_same_policy_and_old_password_stops_working():
    buyer, url = login("buyer"), "/api/auth/change-password"
    for weak in ("abcdef12", "Abcdef12", "abcdef1!", "ABCDEF1!", "Abc!"):
        status, data = call("POST", url, {"current_password": tb.PASSWORD, "new_password": weak, "confirm_password": weak}, buyer)
        assert status == 400 and "new_password" in data["error"]["fields"], weak
    mismatch = call("POST", url, {"current_password": tb.PASSWORD, "new_password": "Abcdef12!", "confirm_password": "Abcdef12?"}, buyer)
    assert mismatch[0] == 400 and "confirm_password" in mismatch[1]["error"]["fields"]
    assert login_status("buyer@art4sells.test", tb.PASSWORD) == 200, "ตั้งไม่สำเร็จ รหัสเดิมต้องยังใช้ได้"
    assert call("POST", url, {"current_password": tb.PASSWORD, "new_password": "Abcdef12!", "confirm_password": "Abcdef12!"}, buyer)[0] == 200
    assert login_status("buyer@art4sells.test", "Abcdef12!") == 200 and login_status("buyer@art4sells.test", tb.PASSWORD) == 401


def test_forgot_password_reset_uses_the_new_policy_end_to_end():
    old_session = login("buyer")
    with mailbox() as outbox:
        token = call("POST", "/api/auth/verify-reset-code", {"email": "buyer@art4sells.test", "code": ask_code(outbox)})[1]["reset_token"]
    reset = lambda pw, confirm=None: call("POST", "/api/auth/reset-password", {"reset_token": token, "new_password": pw, "confirm_password": pw if confirm is None else confirm})
    for weak in ("abcdef12", "Abcdef12", "abcdef1!", "ABCDEF1!", "Abc!"):
        assert reset(weak)[0] == 400, weak
    assert reset("Abcdef12!", confirm="Abcdef12?")[0] == 400
    assert login_status("buyer@art4sells.test", tb.PASSWORD) == 200, "reset ไม่สำเร็จ รหัสเดิมต้องยังใช้ได้ และ token ต้องยังไม่ถูกใช้"
    status, data = reset("Abcdef12!")
    assert status == 200 and data["reset"] is True
    assert login_status("buyer@art4sells.test", "Abcdef12!") == 200, "ใช้รหัสใหม่ login ได้"
    assert login_status("buyer@art4sells.test", tb.PASSWORD) == 401, "รหัสเก่าใช้ไม่ได้อีก"
    assert call("GET", "/api/me", None, old_session)[0] == 401, "session เดิมต้องหมดอายุหลัง reset"
    assert reset("Another9Pass!")[0] == 400, "reset authorization ใช้ครั้งเดียว"


def test_forgot_password_does_not_reveal_unknown_emails_and_ignores_change_cooldown():
    with mailbox() as outbox:
        known = call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})
        unknown = call("POST", "/api/auth/forgot-password", {"email": "nobody@art4sells.test"})
    assert known == unknown and known[0] == 200 and len(outbox) == 1
    storage.update_record("users", "u1", {"password_changed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    assert call("POST", "/api/auth/change-password", {"current_password": tb.PASSWORD, "new_password": "Abcdef12!", "confirm_password": "Abcdef12!"}, login("buyer"))[0] == 429
    age_reset_requests()
    with mailbox() as outbox:
        assert call("POST", "/api/auth/forgot-password", {"email": "buyer@art4sells.test"})[0] == 200 and len(outbox) == 1


def test_one_central_password_validator_is_used_by_every_entry_point():
    """register / admin-create (validate_user_data), change_password, reset_password ต้องเรียก validate_password ตัวเดียวกัน"""
    for func in (validation.validate_user_data, password.change_password, password.reset_password):
        assert "validate_password(" in inspect.getsource(func), func.__name__
    modules_dir = Path(__file__).resolve().parent.parent / "modules"
    definitions = [f.name for f in modules_dir.glob("*.py") if "def validate_password(" in f.read_text(encoding="utf-8")]
    assert definitions == ["validation.py"], definitions
    assert "verify_password" in inspect.getsource(auth.login) and "validate_password" not in inspect.getsource(auth.login)


def test_demo_seed_password_follows_the_policy_and_weak_override_is_refused():
    assert validation.validate_password(seed.DEMO_PASSWORD) is None and seed.DEMO_PASSWORD == tb.PASSWORD
    original = seed.DEMO_PASSWORD
    seed.DEMO_PASSWORD = "demo1234"
    try:
        try:
            seed.build_users()
        except SystemExit as err:
            assert "นโยบายรหัสผ่าน" in str(err)
        else:
            raise AssertionError("seed ต้องปฏิเสธรหัสตัวอย่างที่อ่อน")
    finally:
        seed.DEMO_PASSWORD = original
