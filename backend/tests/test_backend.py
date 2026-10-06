"""test_backend.py - ชุดทดสอบ backend (ไม่ใช้ framework ภายนอก ใช้ assert + Standard Library)

รัน:   python backend/tests/test_backend.py          (จากโฟลเดอร์ art4sells)
ผลลัพธ์: บรรทัด "ok" / "FAIL" ต่อ 1 test และสรุปจำนวนที่ผ่าน

ทุก test ทำงานบน "สำเนา" ของข้อมูลตัวอย่างในโฟลเดอร์ชั่วคราว จึงไม่แตะข้อมูลจริงของโปรเจกต์
"""
import contextlib
import csv
import io
import json
import shutil
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import config, seed                         # noqa: E402
from backend.modules import api, order, security, storage, utils, validation  # noqa: E402
from backend.modules.errors import StorageError             # noqa: E402
import backend.server as server_module                      # noqa: E402
from training import console_menu                           # noqa: E402

config.PASSWORD_ITERATIONS = 1000                           # ลดรอบ hash เฉพาะตอนเทสต์ให้รันเร็ว
PASSWORD = "Demo1234!"
TEMPLATE_DIR = None                                         # สร้างตอนเริ่มรัน (prepare_template)
WORK_DIR = None


def real_rate_limit(func):
    """ตัวกำกับ test: ให้ใช้เพดาน rate limit จริงจาก config.py (ไม่ถูกผ่อนเหมือน test อื่น)"""
    func.uses_real_rate_limit = True
    return func


# ---------------------------------------------------------------------------
# ตัวช่วยของชุดทดสอบ
# ---------------------------------------------------------------------------
def call_full(method, path, body=None, token=None, query=None, headers=None, ip=None):
    """เรียก API ผ่าน api.dispatch (ไม่ต้องเปิด server) คืน Response(status, payload, headers)
    token ส่งแบบ Authorization: Bearer (เหมือนโปรแกรมที่ไม่ใช่เบราว์เซอร์)  ip = IP ที่ต่อเข้ามา (ไม่ระบุ = "unknown")
    """
    all_headers = dict(headers or {})
    if token:
        all_headers["Authorization"] = "Bearer " + token
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
    if raw:
        all_headers.setdefault("Content-Type", "application/json")
    return api.dispatch(method, path, query or {}, all_headers, raw, ip)


def call(method, path, body=None, token=None, query=None):
    """เรียก API ผ่าน api.handle_request (ไม่ต้องเปิด server) คืน tuple (status, dict)"""
    result = call_full(method, path, body, token, query)
    return result.status, result.payload


def cookie_token(result):
    """ดึงค่า session token จาก header Set-Cookie ของ response (Phase Finale: token ไม่อยู่ใน JSON อีกแล้ว) ไม่มี -> None"""
    for name, value in result.headers:
        if name.lower() == "set-cookie" and value.startswith(config.SESSION_COOKIE_NAME + "="):
            token = value.split(";", 1)[0].split("=", 1)[1]
            return token or None
    return None


def call_login(method_path_body_email, password=None, ip=None):
    """login แล้วคืน (status, dict, token จาก cookie)  ใช้กับ test ที่ต้องการทั้ง response และ token"""
    result = call_full("POST", "/api/login", {"email": method_path_body_email, "password": password}, ip=ip)
    return result.status, result.payload, cookie_token(result)


def call_with_token(method, path, body=None):
    """เรียก endpoint ที่เปิด session (login/register) คืน (status, dict, token จาก cookie)"""
    result = call_full(method, path, body)
    return result.status, result.payload, cookie_token(result)


def login(email_name):
    """login ด้วยบัญชีตัวอย่าง (mika, buyer, ton, admin, kenji, ...) คืน token (อ่านจาก Set-Cookie)"""
    status, data, token = call_login(email_name + "@art4sells.test", PASSWORD)
    assert status == 200, "login failed for " + email_name + ": " + str(data)
    assert "token" not in data, "token ต้องไม่อยู่ใน JSON (ส่งทาง HttpOnly cookie เท่านั้น)"
    assert token, "ต้องมี Set-Cookie"
    return token


def error_code(result):
    return result[1]["error"]["code"]


def new_artwork_body(**changes):
    body = {"title": "Test Piece", "description": "ทดสอบ", "category": "illustration",
            "price": 300, "sale_type": "UNLIMITED", "tags": ["test", "demo"]}
    body.update(changes)
    return body


def make_approved_artwork(artist_token, admin_token, **changes):
    status, art = call("POST", "/api/artworks", new_artwork_body(**changes), artist_token)
    assert status == 201, art
    assert call("POST", "/api/artworks/" + art["id"] + "/submit", None, artist_token)[0] == 200
    assert call("POST", "/api/artworks/" + art["id"] + "/approve", None, admin_token)[0] == 200
    return art["id"]


def pay_and_complete(order_id, admin_token):
    """admin จำลองการยืนยันชำระเงินจนออเดอร์ COMPLETED (Phase นี้ยังไม่มี payment จริง)"""
    for next_status in ("PAYMENT_VERIFIED", "PAID", "COMPLETED"):
        status, data = call("PUT", "/api/orders/" + order_id, {"status": next_status}, admin_token)
        assert status == 200, data


def read_json_file(name):
    return json.loads((WORK_DIR / (name + ".json")).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Test: Auth
# ---------------------------------------------------------------------------
def test_register_success_and_password_not_plaintext():
    status, data, token = call_with_token("POST", "/api/register", {"name": "Zed Artist", "email": "Zed@Example.io",
                                                  "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "ARTIST"})
    assert status == 201 and data["user"]["role"] == "ARTIST"
    assert data["user"]["email"] == "zed@example.io", "อีเมลต้องถูกแปลงเป็นตัวพิมพ์เล็ก"
    assert "password_hash" not in data["user"] and token and "token" not in data
    raw_text = (WORK_DIR / "users.json").read_text(encoding="utf-8")
    assert "Passw0rd1!" not in raw_text, "ห้ามมี plaintext password ในไฟล์"
    assert "pbkdf2_sha256$" in raw_text
    assert "USER_CREATED" in (WORK_DIR / "logs.json").read_text(encoding="utf-8")


def test_register_cannot_choose_admin():
    status, data = call("POST", "/api/register", {"name": "Evil", "email": "evil@x.io",
                                                  "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "ADMIN"})
    assert status == 400 and "role" in data["error"]["fields"]


def test_register_duplicate_email():
    body = {"name": "Dup One", "email": "dup@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"}
    assert call("POST", "/api/register", body)[0] == 201
    second = call("POST", "/api/register", dict(body, email="DUP@x.io"))
    assert second[0] == 409 and error_code(second) == "EMAIL_EXISTS"


def test_register_invalid_email_and_passwords():
    base = {"name": "Okay Name", "email": "ok@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"}
    assert "email" in call("POST", "/api/register", dict(base, email="not-an-email"))[1]["error"]["fields"]
    assert "password" in call("POST", "/api/register", dict(base, password="short1"))[1]["error"]["fields"]
    assert "password" in call("POST", "/api/register", dict(base, password="onlyletters"))[1]["error"]["fields"]
    assert "password" in call("POST", "/api/register", dict(base, password="12345678"))[1]["error"]["fields"]
    assert "name" in call("POST", "/api/register", dict(base, name="A"))[1]["error"]["fields"]


def test_login_logout_and_current_user():
    status, data, token = call_login("buyer@art4sells.test", PASSWORD)
    assert status == 200 and data["user"]["role"] == "USER" and token
    assert call("GET", "/api/me", None, token)[1]["user"]["email"] == "buyer@art4sells.test"
    assert call("POST", "/api/logout", None, token)[0] == 200
    assert call("GET", "/api/me", None, token)[0] == 401, "token หลัง logout ต้องใช้ไม่ได้"


def test_login_failures_do_not_reveal_which_part_is_wrong():
    wrong_pw = call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": "WrongPass1"})
    no_user = call("POST", "/api/login", {"email": "nobody@art4sells.test", "password": "WrongPass1"})
    assert wrong_pw[0] == 401 and no_user[0] == 401
    assert wrong_pw[1]["error"]["message"] == no_user[1]["error"]["message"]
    assert call("POST", "/api/login", {"email": "bad", "password": ""})[0] == 400


def test_banned_user_cannot_login_and_loses_session():
    admin = login("admin")
    buyer_token = login("buyer")
    assert call("POST", "/api/users/u1/ban", None, admin)[0] == 200
    assert call("GET", "/api/me", None, buyer_token)[0] == 401, "session ต้องถูกตัดทันที"
    banned_login = call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": PASSWORD})
    assert banned_login[0] == 403 and error_code(banned_login) == "ACCOUNT_BANNED"
    assert call("POST", "/api/users/u1/unban", None, admin)[0] == 200
    assert call("POST", "/api/login", {"email": "buyer@art4sells.test", "password": PASSWORD})[0] == 200
    actions = [e["action"] for e in read_json_file("logs")]
    assert "USER_BANNED" in actions and "USER_UNBANNED" in actions


def test_expired_session_is_rejected():
    token = login("buyer")
    sessions = read_json_file("sessions")
    for s in sessions:
        s["expires_at"] = "2000-01-01T00:00:00+00:00"
    storage.save_json("sessions", sessions)
    assert call("GET", "/api/me", None, token)[0] == 401


def test_password_hash_functions():
    hashed = security.hash_password("Passw0rd1", iterations=1000)
    assert security.verify_password("Passw0rd1", hashed)
    assert not security.verify_password("passw0rd1", hashed)
    assert not security.verify_password("x", "garbage-hash")
    assert hashed != security.hash_password("Passw0rd1", iterations=1000), "salt ต้องสุ่มใหม่ทุกครั้ง"


# ---------------------------------------------------------------------------
# Test: RBAC
# ---------------------------------------------------------------------------
def test_rbac_matrix():
    anon, buyer, mika, admin = None, login("buyer"), login("mika"), login("admin")
    # ยังไม่ login -> 401
    assert call("POST", "/api/artworks", new_artwork_body(), anon)[0] == 401
    assert call("GET", "/api/orders", None, anon)[0] == 401
    # USER สร้างงานไม่ได้ -> 403
    assert call("POST", "/api/artworks", new_artwork_body(), buyer)[0] == 403
    # ARTIST อนุมัติไม่ได้ / ดู logs ไม่ได้ / ดู dashboard ไม่ได้
    assert call("POST", "/api/artworks/w13/approve", None, mika)[0] == 403
    assert call("GET", "/api/logs", None, mika)[0] == 403
    assert call("GET", "/api/dashboard", None, mika)[0] == 403
    # USER ban/ดูรายชื่อ user ไม่ได้
    assert call("POST", "/api/users/a1/ban", None, buyer)[0] == 403
    assert call("GET", "/api/users", None, buyer)[0] == 403
    # ADMIN ทำได้
    assert call("GET", "/api/logs", None, admin)[0] == 200
    assert call("GET", "/api/users", None, admin)[0] == 200
    # ADMIN ไม่มีสิทธิ์สร้างงานในฐานะศิลปิน (สิทธิ์แยกกัน)
    assert call("POST", "/api/artworks", new_artwork_body(), admin)[0] == 403


def test_user_cannot_escalate_own_role():
    buyer = login("buyer")
    status, data = call("PUT", "/api/users/u1", {"role": "ADMIN"}, buyer)
    assert status == 403
    assert call("GET", "/api/users/u1", None, buyer)[1]["role"] == "USER"
    assert call("GET", "/api/users/u2", None, buyer)[0] == 403, "ดูข้อมูล user คนอื่นไม่ได้"


def test_admin_user_management():
    admin = login("admin")
    status, created = call("POST", "/api/users", {"name": "Second Admin", "email": "admin2@x.io",
                                                  "password": "Passw0rd1!", "role": "ADMIN"}, admin)
    assert status == 201 and created["role"] == "ADMIN"
    assert call("PUT", "/api/users/" + created["id"], {"name": "Renamed Admin"}, admin)[1]["name"] == "Renamed Admin"
    assert call("POST", "/api/users/ad1/ban", None, admin)[0] == 409, "ห้ามระงับ admin"
    assert call("DELETE", "/api/users/ad1", None, admin)[0] == 409, "ห้ามลบตัวเอง"
    assert call("DELETE", "/api/users/a1", None, admin)[0] == 409, "ลบ user ที่มีข้อมูลเกี่ยวข้องไม่ได้"
    assert call("DELETE", "/api/users/" + created["id"], None, admin)[0] == 200
    listing = call("GET", "/api/users", None, admin, {"role": "ARTIST"})[1]
    assert listing["total"] == 4 and all(u["role"] == "ARTIST" for u in listing["items"])
    assert all("password_hash" not in u for u in listing["items"])


def test_unknown_user_id():
    admin = login("admin")
    assert call("GET", "/api/users/nope", None, admin)[0] == 404
    assert call("POST", "/api/users/nope/ban", None, admin)[0] == 404
    assert call("GET", "/api/artists/u1")[0] == 404, "u1 ไม่ใช่ศิลปิน"


# ---------------------------------------------------------------------------
# Test: Artwork CRUD + validation
# ---------------------------------------------------------------------------
def test_artwork_crud_full_cycle():
    mika, admin = login("mika"), login("admin")
    status, art = call("POST", "/api/artworks", new_artwork_body(price="1200.50"), mika)   # ราคาเป็นข้อความ -> float
    assert status == 201 and art["status"] == "DRAFT" and art["artist_id"] == "a1"
    assert isinstance(art["price"], float) and art["price"] == 1200.5
    path = "/api/artworks/" + art["id"]
    # Read: เจ้าของเห็น / คนทั่วไปไม่เห็น (ยังเป็น DRAFT)
    assert call("GET", path, None, mika)[0] == 200
    assert call("GET", path)[0] == 404
    assert call("GET", path, None, login("buyer"))[0] == 404
    # Update
    status, updated = call("PUT", path, {"price": 999, "title": "New Title"}, mika)
    assert status == 200 and updated["price"] == 999.0 and updated["title"] == "New Title"
    # Delete: ศิลปินคนอื่นลบไม่ได้, เจ้าของลบได้
    assert call("DELETE", path, None, login("kenji"))[0] == 403
    assert call("DELETE", path, None, mika)[0] == 200
    assert call("GET", path, None, mika)[0] == 404
    assert any(r["id"] == art["id"] for r in read_json_file("artworks")) is False


def test_artwork_validation_errors():
    mika = login("mika")
    cases = [
        (dict(title=""), "title"), (dict(title="   "), "title"), (dict(title="x" * 81), "title"),
        (dict(price=-1), "price"), (dict(price="abc"), "price"), (dict(price=None), "price"),
        (dict(price=float("inf")), "price"), (dict(price=True), "price"),
        (dict(category="no-such-category"), "category"),
        (dict(sale_type="MAYBE"), "sale_type"),
        (dict(tags=["t" + str(n) for n in range(11)]), "tags"), (dict(tags="notalist"), None),
    ]
    for changes, field in cases:
        body = new_artwork_body(**changes)
        raw = json.dumps(body).encode("utf-8") if "inf" not in str(changes) else \
            json.dumps(body).replace("Infinity", "1e999").encode("utf-8")
        status, data = call("POST", "/api/artworks", raw, mika)
        if changes == dict(tags="notalist"):
            assert status == 201, "tags แบบข้อความคั่นด้วย , ถือว่าถูกต้อง"
            continue
        assert status == 400 and field in data["error"]["fields"], (changes, data)
    assert call("POST", "/api/artworks", new_artwork_body(price=0), mika)[0] == 201, "ราคา 0 ต้องได้ (price >= 0)"


def test_artwork_mass_assignment_is_ignored():
    mika = login("mika")
    art_id = call("POST", "/api/artworks", new_artwork_body(), mika)[1]["id"]
    status, updated = call("PUT", "/api/artworks/" + art_id,
                           {"title": "Renamed", "status": "APPROVED", "artist_id": "a2", "rating": 5}, mika)
    assert status == 200 and updated["status"] == "DRAFT" and updated["artist_id"] == "a1" and updated["rating"] == 0
    assert call("PUT", "/api/artworks/" + art_id, {"status": "APPROVED"}, mika)[0] == 400, "ไม่มี field ที่แก้ได้"


def test_artwork_unknown_id_and_ownership():
    mika = login("mika")
    assert call("GET", "/api/artworks/does-not-exist")[0] == 404
    assert call("PUT", "/api/artworks/does-not-exist", {"title": "x"}, mika)[0] == 404
    assert call("DELETE", "/api/artworks/does-not-exist", None, mika)[0] == 404
    assert call("PUT", "/api/artworks/w4", {"title": "hack"}, mika)[0] == 403, "แก้งานของศิลปินอื่นไม่ได้"
    assert call("PUT", "/api/artworks/w1", {"title": "x"}, mika)[0] == 409, "งาน APPROVED ศิลปินแก้ไม่ได้"


def test_cannot_delete_artwork_with_orders():
    admin = login("admin")
    status, data = call("DELETE", "/api/artworks/w3", None, admin)
    assert status == 409 and data["error"]["code"] == "ARTWORK_IN_USE"


def test_category_crud_and_rules():
    admin, mika = login("admin"), login("mika")
    assert call("POST", "/api/categories", {"name": "Comics"}, mika)[0] == 403
    status, cat = call("POST", "/api/categories", {"name": "Comics", "description": "Comic pages"}, admin)
    assert status == 201 and cat["id"] == "comics"
    assert call("POST", "/api/categories", {"name": "comics"}, admin)[0] == 409
    assert call("POST", "/api/categories", {"name": "x"}, admin)[0] == 400
    assert call("PUT", "/api/categories/comics", {"description": "Updated"}, admin)[1]["description"] == "Updated"
    assert call("DELETE", "/api/categories/illustration", None, admin)[0] == 409, "ยังมีงานใช้อยู่"
    assert call("DELETE", "/api/categories/comics", None, admin)[0] == 200
    assert call("DELETE", "/api/categories/comics", None, admin)[0] == 404
    assert len(call("GET", "/api/categories")[1]["items"]) == 8


# ---------------------------------------------------------------------------
# Test: Search / Filter / Sort / Pagination
# ---------------------------------------------------------------------------
def list_artworks(**query):
    status, data = call("GET", "/api/artworks", None, None, {k: str(v) for k, v in query.items()})
    assert status == 200, data
    return data


def test_default_list_shows_only_public_artworks():
    data = list_artworks(page_size=50)
    assert data["total"] == 12
    assert all(a["status"] in ("APPROVED", "SOLD") for a in data["items"])


def test_search():
    assert list_artworks(q="koi")["total"] == 1
    assert list_artworks(q="KOI")["total"] == 1, "ไม่สนตัวพิมพ์เล็ก/ใหญ่"
    assert list_artworks(q="kenji", search_in="artist")["total"] == 3
    assert list_artworks(q="night", search_in="tag")["total"] == 2
    assert list_artworks(q="night", search_in="title")["total"] == 0
    assert list_artworks(q="zzzz-nothing")["total"] == 0
    assert call("GET", "/api/artworks", None, None, {"search_in": "weird"})[0] == 400


def test_filter():
    assert list_artworks(category="3d-art")["total"] == 2
    assert list_artworks(max_price=500)["total"] == 1
    assert list_artworks(min_price=1500)["total"] == 2
    assert list_artworks(min_price=1000, max_price=1500)["total"] == 4
    assert list_artworks(sale_type="UNLIMITED")["total"] == 5
    assert list_artworks(artist_id="a1")["total"] == 4
    assert list_artworks(min_rating=4.5)["total"] == 1
    assert list_artworks(available="true")["total"] == 10, "ไม่รวมงานที่ขายแล้ว และงานที่ถูกล็อกรอจ่ายเงิน (w6)"
    assert list_artworks(category="3d-art", sale_type="LIMITED")["total"] == 1, "กรองหลายเงื่อนไขพร้อมกัน"
    for bad in ({"min_price": "abc"}, {"max_price": "-5"}, {"sale_type": "X"}, {"min_price": "10", "max_price": "5"}):
        assert call("GET", "/api/artworks", None, None, bad)[0] == 400, bad


def test_sort():
    assert list_artworks(sort="price_asc")["items"][0]["price"] == 450
    assert list_artworks(sort="price_desc")["items"][0]["price"] == 2200
    prices = [a["price"] for a in list_artworks(sort="price_asc", page_size=50)["items"]]
    assert prices == sorted(prices)
    assert list_artworks(sort="rating")["items"][0]["rating"] == 5.0
    assert call("GET", "/api/artworks", None, None, {"sort": "random"})[0] == 400


def test_pagination():
    page3 = list_artworks(page_size=5, page=3)
    assert page3["total"] == 12 and page3["total_pages"] == 3 and len(page3["items"]) == 2
    assert set(page3) == {"items", "page", "page_size", "total", "total_pages"}
    ids = []
    for p in (1, 2, 3):
        ids += [a["id"] for a in list_artworks(page_size=5, page=p)["items"]]
    assert len(ids) == len(set(ids)) == 12, "ทุกหน้ารวมกันต้องครบและไม่ซ้ำ"
    assert list_artworks(page_size=5, page=99)["page"] == 3, "หน้าเกินช่วงถูกปรับเป็นหน้าสุดท้าย"
    for bad in ({"page": "0"}, {"page": "-1"}, {"page": "abc"}, {"page": "1.5"},
                {"page_size": "0"}, {"page_size": "500"}, {"page_size": "x"}):
        status, data = call("GET", "/api/artworks", None, None, bad)
        assert status == 400 and "fields" in data["error"], bad


def test_mine_and_submitted_views_need_permission():
    mika, admin = login("mika"), login("admin")
    assert call("GET", "/api/artworks", None, None, {"mine": "true"})[0] == 401
    mine = call("GET", "/api/artworks", None, mika, {"mine": "true", "page_size": "50"})[1]
    assert mine["total"] == 5 and {a["status"] for a in mine["items"]} == {"APPROVED", "PENDING_APPROVAL"}
    assert call("GET", "/api/artworks", None, mika, {"submitted": "true"})[0] == 403
    subs = call("GET", "/api/artworks", None, admin, {"status": "PENDING_APPROVAL"})[1]
    assert subs["total"] == 4
    assert call("GET", "/api/artworks", None, None, {"status": "DRAFT"})[0] == 403, "คนทั่วไปดู DRAFT ไม่ได้"


# ---------------------------------------------------------------------------
# Test: Approval workflow
# ---------------------------------------------------------------------------
def test_approval_workflow_approve():
    mika, admin = login("mika"), login("admin")
    art_id = call("POST", "/api/artworks", new_artwork_body(title="Workflow A"), mika)[1]["id"]
    assert call("POST", "/api/artworks/" + art_id + "/approve", None, admin)[0] == 409, "DRAFT ข้ามไป APPROVED ไม่ได้"
    assert call("POST", "/api/artworks/" + art_id + "/submit", None, login("kenji"))[0] == 403
    status, data = call("POST", "/api/artworks/" + art_id + "/submit", None, mika)
    assert status == 200 and data["status"] == "PENDING_APPROVAL"
    assert call("GET", "/api/artworks/" + art_id)[0] == 404, "ยังไม่อนุมัติ คนทั่วไปไม่เห็น"
    assert call("POST", "/api/artworks/" + art_id + "/approve", None, mika)[0] == 403
    assert call("POST", "/api/artworks/" + art_id + "/submit", None, mika)[0] == 409, "ส่งซ้ำไม่ได้"
    assert call("PUT", "/api/artworks/" + art_id, {"title": "edit"}, mika)[0] == 409, "รออนุมัติอยู่ แก้ไม่ได้"
    status, data = call("POST", "/api/artworks/" + art_id + "/approve", None, admin)
    assert status == 200 and data["status"] == "APPROVED" and data["reviewed_by"] == "ad1"
    assert call("GET", "/api/artworks/" + art_id)[1]["availability"] == "AVAILABLE"
    assert call("POST", "/api/artworks/" + art_id + "/reject", None, admin)[0] == 409, "APPROVED -> REJECTED ไม่ได้"


def test_approval_workflow_reject_edit_resubmit():
    mika, admin = login("mika"), login("admin")
    art_id = call("POST", "/api/artworks", new_artwork_body(title="Workflow B"), mika)[1]["id"]
    call("POST", "/api/artworks/" + art_id + "/submit", None, mika)
    status, data = call("POST", "/api/artworks/" + art_id + "/reject", {"reason": "ภาพไม่ชัด"}, admin)
    assert status == 200 and data["status"] == "REJECTED" and data["reject_reason"] == "ภาพไม่ชัด"
    assert call("PUT", "/api/artworks/" + art_id, {"title": "Workflow B v2"}, mika)[0] == 200, "REJECTED ศิลปินแก้ได้"
    status, data = call("POST", "/api/artworks/" + art_id + "/submit", None, mika)
    assert status == 200 and data["status"] == "PENDING_APPROVAL" and data["reject_reason"] is None
    actions = [e["action"] for e in read_json_file("logs") if e["target_id"] == art_id]
    assert actions == ["ARTWORK_CREATED", "ARTWORK_SUBMITTED", "ARTWORK_REJECTED", "ARTWORK_UPDATED",
                       "ARTWORK_SUBMITTED"], actions


def test_reject_reason_too_long():
    admin = login("admin")
    assert call("POST", "/api/artworks/w13/reject", {"reason": "x" * 301}, admin)[0] == 400


# ---------------------------------------------------------------------------
# Test: Orders
# ---------------------------------------------------------------------------
def test_order_create_locks_limited_artwork_and_uses_server_price():
    buyer, ton = login("buyer"), login("ton")
    status, o = call("POST", "/api/orders", {"items": [{"artwork_id": "w2", "quantity": 1, "unit_price": 1}]}, buyer)
    assert status == 201 and o["status"] == "PENDING_PAYMENT"
    assert o["total"] == 900.0 and o["items"][0]["unit_price"] == 900.0, "ต้องใช้ราคาจากฐานข้อมูล ไม่ใช่ที่ client ส่ง"
    assert call("GET", "/api/artworks/w2")[1]["availability"] == "PROCESSING"
    second = call("POST", "/api/orders", {"items": [{"artwork_id": "w2", "quantity": 1}]}, ton)
    assert second[0] == 409 and error_code(second) == "ARTWORK_LOCKED"
    assert call("PUT", "/api/orders/" + o["id"], {"status": "CANCELLED"}, buyer)[0] == 200
    assert call("GET", "/api/artworks/w2")[1]["availability"] == "AVAILABLE", "ยกเลิกแล้วต้องปลดล็อก"
    assert call("POST", "/api/orders", {"items": [{"artwork_id": "w2", "quantity": 1}]}, ton)[0] == 201


def test_order_validation_and_rules():
    buyer, mika = login("buyer"), login("mika")
    bad_bodies = [
        {}, {"items": []}, {"items": "x"}, {"items": [5]}, {"items": [{"quantity": 1}]},
        {"items": [{"artwork_id": "w3", "quantity": 0}]}, {"items": [{"artwork_id": "w3", "quantity": "two"}]},
        {"items": [{"artwork_id": "w3", "quantity": 1.5}]}, {"items": [{"artwork_id": "w3", "quantity": 100}]},
        {"items": [{"artwork_id": "w3", "quantity": 1}, {"artwork_id": "w3", "quantity": 1}]},
        {"items": [{"artwork_id": "w2", "quantity": 2}]},
    ]
    for body in bad_bodies:
        assert call("POST", "/api/orders", body, buyer)[0] == 400, body
    assert call("POST", "/api/orders", {"items": [{"artwork_id": "nope", "quantity": 1}]}, buyer)[0] == 404
    assert call("POST", "/api/orders", {"items": [{"artwork_id": "w13", "quantity": 1}]}, buyer)[0] == 404, "ยังไม่อนุมัติ"
    assert call("POST", "/api/orders", {"items": [{"artwork_id": "w8", "quantity": 1}]}, buyer)[0] == 409, "ขายแล้ว"
    assert call("POST", "/api/orders", {"items": [{"artwork_id": "w1", "quantity": 1}]}, mika)[0] == 409, "ซื้องานตัวเองไม่ได้"
    assert call("POST", "/api/orders", {"items": [{"artwork_id": "w3", "quantity": 3}]}, buyer)[1]["total"] == 1950.0


def test_order_state_transitions():
    admin, buyer = login("admin"), login("buyer")
    # COMPLETED -> PENDING_PAYMENT ต้องถูกปฏิเสธ (ตัวอย่างจากโจทย์)
    status, data = call("PUT", "/api/orders/o2", {"status": "PENDING_PAYMENT"}, admin)
    assert status == 409 and data["error"]["code"] == "INVALID_TRANSITION"
    assert call("PUT", "/api/orders/o2", {"status": "PENDING_PAYMENT"}, buyer)[0] == 403, "ผู้ซื้อเปลี่ยนเป็นสถานะนี้ไม่ได้"
    assert call("PUT", "/api/orders/o2", {"status": "NOT_A_STATE"}, admin)[0] == 400
    # ผู้ซื้อกระโดดไป PAID เองไม่ได้
    assert call("PUT", "/api/orders/o1", {"status": "PAID"}, buyer)[0] == 403
    # admin ข้ามขั้นไม่ได้
    assert call("PUT", "/api/orders/o1", {"status": "PAID"}, admin)[0] == 409
    assert call("PUT", "/api/orders/o1", {"status": "COMPLETED"}, admin)[0] == 409
    # ลำดับถูกต้อง
    for next_status in ("PAYMENT_VERIFIED", "PAID"):
        assert call("PUT", "/api/orders/o1", {"status": next_status}, admin)[0] == 200
    assert call("GET", "/api/artworks/w6")[1]["status"] == "SOLD", "จ่ายแล้ว งาน LIMITED ต้องเป็น SOLD"
    assert call("PUT", "/api/orders/o1", {"status": "CANCELLED"}, admin)[0] == 409, "จ่ายแล้วยกเลิกไม่ได้"
    assert call("PUT", "/api/orders/o1", {"status": "COMPLETED"}, buyer)[0] == 200
    # ออเดอร์ของคนอื่น -> 404
    assert call("PUT", "/api/orders/o3", {"status": "CANCELLED"}, buyer)[0] == 404
    assert call("GET", "/api/orders/o3", None, buyer)[0] == 404
    assert call("GET", "/api/orders/unknown", None, admin)[0] == 404


def test_order_expiry():
    buyer = login("buyer")
    order_id = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    storage.update_record("orders", order_id, {"expires_at": "2000-01-01T00:00:00+00:00"})
    status, data = call("GET", "/api/orders/" + order_id, None, buyer)
    assert status == 200 and data["status"] == "EXPIRED"
    assert call("PUT", "/api/orders/" + order_id, {"status": "PAID"}, login("admin"))[0] == 409


def test_order_listing_scopes_and_delete():
    buyer, admin, mika, kenji = login("buyer"), login("admin"), login("mika"), login("kenji")
    mine = call("GET", "/api/orders", None, buyer)[1]
    assert mine["total"] == 2 and all(o["user_id"] == "u1" for o in mine["items"])
    assert call("GET", "/api/orders", None, admin)[1]["total"] == 3
    assert call("GET", "/api/orders", None, buyer, {"scope": "all"})[0] == 403
    sales = call("GET", "/api/orders", None, mika, {"scope": "sales"})[1]
    assert sales["total"] == 1 and sales["items"][0]["sales_total"] == 650.0
    assert call("GET", "/api/orders", None, kenji, {"scope": "sales"})[1]["total"] == 0, "o1 ยังไม่จ่าย ไม่นับเป็นยอดขาย"
    assert call("GET", "/api/orders", None, buyer, {"status": "BAD"})[0] == 400
    assert call("DELETE", "/api/orders/o2", None, admin)[0] == 409, "ลบออเดอร์ที่เสร็จแล้วไม่ได้"
    order_id = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    call("PUT", "/api/orders/" + order_id, {"status": "CANCELLED"}, buyer)
    assert call("DELETE", "/api/orders/" + order_id, None, buyer)[0] == 403
    assert call("DELETE", "/api/orders/" + order_id, None, admin)[0] == 200


# ---------------------------------------------------------------------------
# Test: Reviews
# ---------------------------------------------------------------------------
def test_review_eligibility_and_creation():
    buyer, admin, ton = login("buyer"), login("admin"), login("ton")
    review_body = {"artwork_id": "w5", "rating": 5, "comment": "Great props pack"}
    # ยังไม่ซื้อ -> รีวิวไม่ได้
    assert call("GET", "/api/artworks/w5/review-eligibility", None, buyer)[1]["eligible"] is False
    status, data = call("POST", "/api/reviews", review_body, buyer)
    assert status == 403 and data["error"]["code"] == "REVIEW_NOT_ALLOWED"
    # ซื้อแต่ยังไม่ COMPLETED -> ยังไม่ได้
    order_id = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    assert call("POST", "/api/reviews", review_body, buyer)[0] == 403
    pay_and_complete(order_id, admin)
    status, eligibility = call("GET", "/api/artworks/w5/review-eligibility", None, buyer)
    assert eligibility["eligible"] is True and eligibility["order_id"] == order_id
    # ข้อมูลไม่ถูกต้อง
    assert call("POST", "/api/reviews", dict(review_body, rating=9), buyer)[0] == 400
    assert call("POST", "/api/reviews", dict(review_body, rating="abc"), buyer)[0] == 400
    assert call("POST", "/api/reviews", dict(review_body, comment="no"), buyer)[0] == 400
    assert call("POST", "/api/reviews", {"rating": 5, "comment": "no artwork id"}, buyer)[0] == 400
    assert call("POST", "/api/reviews", dict(review_body, artwork_id="nope"), buyer)[0] == 404
    # สำเร็จ + ผูกกับ order
    status, review = call("POST", "/api/reviews", review_body, buyer)
    assert status == 201 and review["order_id"] == order_id and review["artist_id"] == "a2"
    assert review["status"] == "PUBLISHED"
    # รีวิวซ้ำไม่ได้ / คนอื่นที่ไม่ได้ซื้อรีวิวไม่ได้
    assert call("POST", "/api/reviews", review_body, buyer)[0] == 403
    assert call("POST", "/api/reviews", review_body, ton)[0] == 403
    # คำนวณคะแนนเฉลี่ยใหม่
    assert call("GET", "/api/artworks/w5")[1]["rating"] == 5.0
    assert call("GET", "/api/reviews", None, None, {"artwork_id": "w5"})[1]["total"] == 1


def test_review_rating_average_and_moderation():
    buyer, ton, admin = login("buyer"), login("ton"), login("admin")
    for token, rating in ((buyer, 5), (ton, 2)):
        oid = call("POST", "/api/orders", {"items": [{"artwork_id": "w4", "quantity": 1}]}, token)[1]["id"]
        pay_and_complete(oid, admin)
        assert call("POST", "/api/reviews", {"artwork_id": "w4", "rating": rating, "comment": "Review text"}, token)[0] == 201
    assert call("GET", "/api/artworks/w4")[1]["rating"] == 3.5, "(5+2)/2"
    reviews = call("GET", "/api/reviews", None, None, {"artwork_id": "w4"})[1]["items"]
    ton_review = [r for r in reviews if r["user_id"] == "u2"][0]
    assert call("PUT", "/api/reviews/" + ton_review["id"], {"status": "HIDDEN"}, ton)[0] == 403
    assert call("PUT", "/api/reviews/" + ton_review["id"], {"status": "HIDDEN"}, admin)[0] == 200
    assert call("GET", "/api/artworks/w4")[1]["rating"] == 5.0, "รีวิวที่ถูกซ่อนไม่นับ"
    assert call("GET", "/api/reviews", None, None, {"artwork_id": "w4"})[1]["total"] == 1
    assert call("PUT", "/api/reviews/" + ton_review["id"], {"comment": "edited by admin"}, admin)[0] == 403
    assert call("PUT", "/api/reviews/" + ton_review["id"], {"comment": "edited by me!"}, ton)[0] == 200
    assert call("DELETE", "/api/reviews/" + ton_review["id"], None, buyer)[0] == 403
    assert call("DELETE", "/api/reviews/" + ton_review["id"], None, ton)[0] == 200
    assert call("DELETE", "/api/reviews/" + ton_review["id"], None, ton)[0] == 404


def test_average_rating_function():
    from backend.modules import review
    assert review.calculate_average_rating([]) == 0.0
    assert review.calculate_average_rating([{"rating": 5}, {"rating": 4}]) == 4.5
    assert review.calculate_average_rating([{"rating": 5}, {"rating": 4}, {"rating": 4}]) == 4.3


# ---------------------------------------------------------------------------
# Test: Dashboard + Audit log
# ---------------------------------------------------------------------------
def test_dashboard_is_computed_from_real_data():
    admin, mika = login("admin"), login("mika")
    first = call("GET", "/api/dashboard", None, admin)[1]
    assert first["total_users"] == 7 and first["total_artists"] == 4 and first["total_artworks"] == 16
    assert first["pending_artworks"] == 4 and first["total_orders"] == 3 and first["total_reviews"] == 2
    assert first["total_sales"] == 2000.0, "เฉพาะออเดอร์ที่จ่ายแล้ว: 1350 + 650"
    # เปลี่ยนข้อมูลจริงแล้วตัวเลขต้องเปลี่ยนตาม
    call("POST", "/api/artworks", new_artwork_body(), mika)
    call("POST", "/api/register", {"name": "New Artist", "email": "na@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "ARTIST"})
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 2}]}, login("buyer"))[1]["id"]
    after_order = call("GET", "/api/dashboard", None, admin)[1]
    assert after_order["total_artworks"] == 17 and after_order["total_users"] == 8 and after_order["total_artists"] == 5
    assert after_order["total_orders"] == 4 and after_order["total_sales"] == 2000.0
    pay_and_complete(oid, admin)
    assert call("GET", "/api/dashboard", None, admin)[1]["total_sales"] == 2000.0 + 1980.0
    assert call("GET", "/api/dashboard")[0] == 401


def test_audit_log_fields_and_filters():
    admin = login("admin")
    mika = login("mika")
    art_id = call("POST", "/api/artworks", new_artwork_body(title="Audit Me"), mika)[1]["id"]
    call("DELETE", "/api/artworks/" + art_id, None, mika)
    status, data = call("GET", "/api/logs", None, admin, {"action": "ARTWORK_DELETED"})
    assert status == 200 and data["total"] == 1
    entry = data["items"][0]
    for field in ("id", "actor_id", "action", "target_type", "target_id", "timestamp", "details"):
        assert field in entry, field
    assert entry["actor_id"] == "a1" and entry["target_id"] == art_id and entry["details"]["title"] == "Audit Me"
    logins = call("GET", "/api/logs", None, admin, {"action": "USER_LOGIN"})[1]
    assert logins["total"] >= 2
    assert call("GET", "/api/logs", None, admin, {"action": "NOT_AN_ACTION"})[0] == 400
    assert call("GET", "/api/logs", None, admin, {"page": "0"})[0] == 400
    newest_first = call("GET", "/api/logs", None, admin, {"page_size": "50"})[1]["items"]
    stamps = [e["timestamp"] for e in newest_first]
    assert stamps == sorted(stamps, reverse=True)
    call("POST", "/api/login", {"email": "mika@art4sells.test", "password": "WrongPass1"})
    assert call("GET", "/api/logs", None, admin, {"action": "USER_LOGIN_FAILED"})[1]["total"] == 1


def test_all_required_audit_actions_are_written():
    admin, mika, buyer = login("admin"), login("mika"), login("buyer")
    art_id = make_approved_artwork(mika, admin, title="Log Flow", sale_type="LIMITED")
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": art_id, "quantity": 1}]}, buyer)[1]["id"]
    pay_and_complete(oid, admin)
    call("POST", "/api/reviews", {"artwork_id": art_id, "rating": 4, "comment": "Nice work"}, buyer)
    call("POST", "/api/artworks/w13/reject", None, admin)
    call("POST", "/api/users/u2/ban", None, admin)
    seen = {e["action"] for e in read_json_file("logs")}
    required = {"USER_LOGIN", "ARTWORK_CREATED", "ARTWORK_SUBMITTED", "ARTWORK_APPROVED", "ARTWORK_REJECTED",
                "ORDER_CREATED", "ORDER_UPDATED", "REVIEW_CREATED", "USER_BANNED", "ARTWORK_SOLD"}
    assert required <= seen, required - seen


# ---------------------------------------------------------------------------
# Test: Persistence + file handling + error handling
# ---------------------------------------------------------------------------
def http_json_full(base, method, path, body=None, token=None, cookie=None, extra_headers=None):
    """เรียก server จริงผ่าน HTTP (urllib) คืน (status, dict, headers)  token = Bearer, cookie = ค่า a4s_session ที่จะแนบเป็น Cookie"""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    if cookie:
        request.add_header("Cookie", config.SESSION_COOKIE_NAME + "=" + cookie)
    for name, value in (extra_headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8")), response.headers
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8")), err.headers


def http_json(base, method, path, body=None, token=None):
    """เรียก server จริงผ่าน HTTP (urllib) คืน (status, dict)"""
    status, payload, _headers = http_json_full(base, method, path, body, token)
    return status, payload


def http_cookie_of(headers):
    """ค่า session token จาก Set-Cookie ของ response HTTP จริง (ไม่มี -> None)"""
    for value in headers.get_all("Set-Cookie") or []:
        if value.startswith(config.SESSION_COOKIE_NAME + "="):
            return value.split(";", 1)[0].split("=", 1)[1] or None
    return None


def start_server():
    httpd = server_module.create_server("127.0.0.1", 0)       # port 0 = ให้ระบบเลือก port ว่างให้
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, "http://127.0.0.1:" + str(httpd.server_address[1])


def stop_server(httpd):
    httpd.shutdown()
    httpd.server_close()


def test_persistence_survives_server_restart():
    httpd, base = start_server()
    try:
        status, data, headers = http_json_full(base, "POST", "/api/login", {"email": "mika@art4sells.test", "password": PASSWORD})
        assert status == 200 and "token" not in data
        cookie = http_cookie_of(headers)                      # login ผ่าน HTTP จริง -> ได้ session ทาง cookie
        # เบราว์เซอร์จริงแนบ Origin ให้ทุกคำขอ POST เสมอ (ระบบบังคับสำหรับคำขอที่ใช้ cookie) จึงจำลองด้วย
        status, art, _h = http_json_full(base, "POST", "/api/artworks", new_artwork_body(title="Persist Me"), cookie=cookie,
                                         extra_headers={"Origin": base})
        assert status == 201
    finally:
        stop_server(httpd)                                    # "ปิดโปรแกรม"
    assert "Persist Me" in (WORK_DIR / "artworks.json").read_text(encoding="utf-8"), "ต้องอยู่ในไฟล์จริง"
    httpd2, base2 = start_server()                            # "เปิดใหม่"
    try:
        status, data, headers = http_json_full(base2, "POST", "/api/login", {"email": "mika@art4sells.test", "password": PASSWORD})
        status, again, _h = http_json_full(base2, "GET", "/api/artworks/" + art["id"], None, cookie=http_cookie_of(headers))
        assert status == 200 and again["title"] == "Persist Me"
    finally:
        stop_server(httpd2)


def test_http_layer_end_to_end_and_error_shapes():
    httpd, base = start_server()
    try:
        assert http_json(base, "GET", "/api/health")[0] == 200
        assert http_json(base, "GET", "/api/artworks?page_size=3")[1]["page_size"] == 3
        assert http_json(base, "GET", "/api/artworks?page=abc")[0] == 400
        assert http_json(base, "GET", "/api/nope")[0] == 404
        assert http_json(base, "DELETE", "/api/artworks")[0] == 405
        assert http_json(base, "POST", "/api/artworks", new_artwork_body())[0] == 401
        request = urllib.request.Request(base + "/api/login", data=b"{broken json", method="POST")
        request.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("ต้องตอบ error")
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8")
            assert err.code == 400 and "INVALID_JSON" in body and "Traceback" not in body
        with urllib.request.urlopen(base + "/") as page:
            assert page.status == 200 and b"Art 4 Sells" in page.read()
        for blocked in ("/backend/data/users.json", "/public/../backend/config.py", "/src/../backend/server.py"):
            try:
                urllib.request.urlopen(base + blocked, timeout=10)
                raise AssertionError("ต้องเปิดไม่ได้: " + blocked)
            except urllib.error.HTTPError as err:
                assert err.code == 404
    finally:
        stop_server(httpd)


def test_static_path_traversal_blocked():
    resolve = server_module.resolve_static_path
    assert resolve("/public/index.html") is not None
    assert resolve("/public/../backend/config.py") is None
    assert resolve("/public/%2e%2e/backend/config.py") is None
    assert resolve("/backend/data/users.json") is None
    assert resolve("/public/missing.html") is None
    assert resolve("/public/..%5cbackend") is None
    # เหมือนบน Vercel: ไฟล์ใน public/ อยู่ที่รากเว็บ (หน้า HTML อ้าง style.css / login.html แบบนี้ - เคยได้ 404 ตอนรันในเครื่อง)
    assert resolve("/style.css") == (config.STATIC_ROOTS["public"] / "style.css").resolve()
    assert resolve("/login.html") is not None and resolve("/artwork.html") is not None
    assert resolve("/src/core/constants.js") is not None
    assert resolve("/backend/config.py") is None and resolve("/config.py") is None and resolve("/.env") is None
    assert resolve("/..%2fbackend/config.py") is None and resolve("/%2e%2e/backend/config.py") is None


def test_invalid_json_file_is_reported_not_overwritten():
    (WORK_DIR / "artworks.json").write_text("{this is not valid json", encoding="utf-8")
    status, data = call("GET", "/api/artworks")
    assert status == 500 and data["error"]["code"] == "DATA_CORRUPT"
    assert "Traceback" not in json.dumps(data) and "JSONDecodeError" not in json.dumps(data)
    assert (WORK_DIR / "artworks.json").read_text(encoding="utf-8") == "{this is not valid json", "ห้ามเขียนทับไฟล์ที่เสีย"
    try:
        storage.load_json("artworks")
        raise AssertionError("ต้อง raise StorageError")
    except StorageError as err:
        assert err.code == "DATA_CORRUPT" and err.detail != "", "detail ไว้ให้ developer"


def test_json_wrong_shape_is_reported():
    (WORK_DIR / "reviews.json").write_text('{"not": "a list"}', encoding="utf-8")
    assert call("GET", "/api/reviews")[0] == 500


def test_missing_data_file_is_handled():
    (WORK_DIR / "reviews.json").unlink()
    status, data = call("GET", "/api/reviews")
    assert status == 200 and data["items"] == [] and data["total"] == 0
    assert storage.load_json("reviews") == []
    assert storage.get_record("reviews", "r1") is None


def test_file_write_error_is_handled():
    blocker = WORK_DIR / "blocker.txt"
    blocker.write_text("i am a file, not a folder", encoding="utf-8")
    storage.configure(blocker / "sub")                        # โฟลเดอร์ปลายทางสร้างไม่ได้ (พ่อเป็นไฟล์)
    try:
        storage.save_json("artworks", [])
        raise AssertionError("ต้อง raise StorageError")
    except StorageError as err:
        assert err.code == "DATA_WRITE_FAILED" and err.message == "ไม่สามารถบันทึกข้อมูลได้"


def test_unknown_collection_and_provider_rejected():
    for name in ("../../etc/passwd", "secrets", ""):
        try:
            storage.load_json(name)
            raise AssertionError("ต้องปฏิเสธ: " + name)
        except StorageError as err:
            assert err.code == "UNKNOWN_COLLECTION"


def test_storage_crud_functions():
    created = storage.create_record("categories", {"name": "Temp"}, "tmp_")
    assert created["id"].startswith("tmp_")
    assert storage.get_record("categories", created["id"])["name"] == "Temp"
    assert storage.update_record("categories", created["id"], {"name": "Temp2"})["name"] == "Temp2"
    assert storage.find_one("categories", "name", "Temp2")["id"] == created["id"]
    assert storage.delete_record("categories", created["id"]) is True
    assert storage.delete_record("categories", created["id"]) is False
    assert storage.update_record("categories", "missing", {"a": 1}) is None
    assert not list(WORK_DIR.glob("*.tmp")), "ต้องไม่มีไฟล์ชั่วคราวค้าง"


def test_request_body_errors_and_unexpected_errors_are_safe():
    mika = login("mika")
    for bad in (b"{oops", b"[1, 2, 3]", b'"just a string"', b"\xff\xfe\x00"):
        status, data = call("POST", "/api/artworks", bad, mika)
        assert status == 400 and data["error"]["code"] == "INVALID_JSON", bad
    assert call("POST", "/api/artworks", b"x" * (config.MAX_BODY_BYTES + 1), mika)[0] == 413
    # จำลอง bug ที่คาดไม่ถึงในระบบ: ผู้ใช้ต้องไม่เห็น traceback
    original = order.get_locked_artwork_ids
    order.get_locked_artwork_ids = lambda: 1 / 0
    try:
        status, data = call("GET", "/api/artworks")
    finally:
        order.get_locked_artwork_ids = original
    assert status == 500 and data["error"]["code"] == "INTERNAL_ERROR"
    assert "ZeroDivision" not in json.dumps(data) and "Traceback" not in json.dumps(data)


def test_validation_and_conversion_functions():
    assert validation.to_float("12.5") == (12.5, None)
    assert validation.to_float("abc")[0] is None and validation.to_float(None)[0] is None
    assert validation.to_float(True)[0] is None and validation.to_float("nan")[0] is None
    assert validation.to_int("7") == (7, None) and validation.to_int(7.0) == (7, None)
    assert validation.to_int("7.5")[0] is None and validation.to_int(7.5)[0] is None and validation.to_int(False)[0] is None
    assert validation.to_bool("true") == (True, None) and validation.to_bool("0") == (False, None)
    assert validation.to_bool("maybe")[0] is None
    assert validation.validate_email("a@b.co") is None and validation.validate_email("a@b") is not None
    assert validation.normalize_tags("Fox, fox , FIRE") == (["fox", "fire"], None)
    assert validation.can_transition("DRAFT", "PENDING_APPROVAL", config.ARTWORK_TRANSITIONS)
    assert not validation.can_transition("APPROVED", "DRAFT", config.ARTWORK_TRANSITIONS)


def test_pagination_helpers():
    assert utils.calculate_pagination(0, 1, 10) == (1, 1, 0)
    assert utils.calculate_pagination(25, 3, 10) == (3, 3, 20)
    assert utils.calculate_pagination(25, 99, 10) == (3, 3, 20)
    assert utils.paginate(list(range(5)), 2, 2)["items"] == [2, 3]


# ---------------------------------------------------------------------------
# Test: การทำงานพร้อมกัน (หลาย request พร้อมกัน ต้องไม่ผ่านการตรวจซ้อนกัน)
# ---------------------------------------------------------------------------
def run_in_threads(count, job):
    """รัน job(i) พร้อมกัน count ตัว คืนรายการผลลัพธ์ (status, data)"""
    results, workers = [], []

    def worker(index):
        results.append(job(index))

    for i in range(count):
        workers.append(threading.Thread(target=worker, args=(i,)))
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    return results


def test_concurrent_orders_for_one_limited_artwork_only_one_wins():
    tokens = [login("buyer"), login("ton")] * 4
    body = {"items": [{"artwork_id": "w5", "quantity": 1}]}
    call("PUT", "/api/artworks/w5", {"sale_type": "LIMITED"}, login("admin"))     # ทำให้ w5 เป็นงาน LIMITED
    results = run_in_threads(8, lambda i: call("POST", "/api/orders", body, tokens[i]))
    wins = [r for r in results if r[0] == 201]
    assert len(wins) == 1, [r[0] for r in results]
    assert all(r[0] == 409 for r in results if r[0] != 201)
    assert len([o for o in read_json_file("orders") if o["items"][0]["artwork_id"] == "w5"]) == 1


def test_concurrent_duplicate_register_creates_one_user():
    body = {"name": "Race User", "email": "race@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"}
    results = run_in_threads(6, lambda i: call("POST", "/api/register", body))
    assert len([r for r in results if r[0] == 201]) == 1, [r[0] for r in results]
    assert len([u for u in read_json_file("users") if u["email"] == "race@x.io"]) == 1


def test_concurrent_duplicate_review_creates_one_review():
    admin, buyer = login("admin"), login("buyer")
    oid = call("POST", "/api/orders", {"items": [{"artwork_id": "w5", "quantity": 1}]}, buyer)[1]["id"]
    pay_and_complete(oid, admin)
    body = {"artwork_id": "w5", "rating": 5, "comment": "Concurrent review"}
    results = run_in_threads(6, lambda i: call("POST", "/api/reviews", body, buyer))
    assert len([r for r in results if r[0] == 201]) == 1, [r[0] for r in results]
    assert len([r for r in read_json_file("reviews") if r["artwork_id"] == "w5"]) == 1



# ---------------------------------------------------------------------------
# Test: Console menu (training/console_menu.py) - ใช้ logic จริงเดียวกับ API
# ---------------------------------------------------------------------------
def run_console(answers, passwords, export_path=None):
    """รันเมนู console ด้วยคำตอบสำเร็จรูป คืน tuple (exit_code, ข้อความที่พิมพ์ออกหน้าจอ)"""
    answer_list, password_list = list(answers), list(passwords)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = console_menu.main_menu(lambda prompt: answer_list.pop(0), lambda prompt: password_list.pop(0),
                                      export_path or (WORK_DIR / "export.csv"))
    assert not answer_list, "คำตอบเหลือ แปลว่าเมนูไม่ได้ถามตามที่คาด: " + str(answer_list)
    return code, output.getvalue()


def test_console_artist_session_create_update_delete_export():
    answers = [
        "mika@art4sells.test",
        "1", "y",                                                  # list: เฉพาะงานของฉัน
        "3", "Console Piece", "abc", "-5", "250.5", "illustration", "unlimited", "a, b", "from console",
        "2", "Koi", "", "", "",                                    # search
        "4", "w15", "New title",  "",                              # w15 รออนุมัติ -> แก้ไม่ได้
        "4", "w4", "x", "",                                        # งานของศิลปินอื่น -> ไม่มีสิทธิ์
        "5", "w15", "yes",                                         # ลบงานของตัวเอง
        "5", "w11", "no",                                          # ยกเลิกการลบ
        "6",                                                       # เมนู admin -> ถูกปฏิเสธ
        "99", "8", "0",
    ]
    code, text = run_console(answers, [PASSWORD])
    assert code == 0 and "ออกจากโปรแกรม" in text
    assert "ราคาต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป" in text, "ต้องวนถามราคาใหม่เมื่อกรอกผิด"
    assert "สร้างงานสำเร็จ" in text and "Moonlit Koi" in text, "สร้างสำเร็จ และค้นหาเจอ"
    assert "แก้ไขงานในสถานะ PENDING_APPROVAL ไม่ได้" in text and "ไม่มีสิทธิ์ดำเนินการ" in text
    assert "ลบงานแล้ว" in text and "ยกเลิกการลบ" in text
    assert "เมนูนี้สำหรับผู้ดูแลระบบ" in text and "ไม่มีเมนูนี้" in text
    stored = read_json_file("artworks")
    assert any(a["title"] == "Console Piece" and a["price"] == 250.5 and a["tags"] == ["a", "b"] for a in stored)
    assert not any(a["id"] == "w15" for a in stored) and any(a["id"] == "w11" for a in stored)
    with open(WORK_DIR / "export.csv", newline="", encoding="utf-8-sig") as file:
        rows = list(csv.reader(file))
    assert rows[0][0] == "id" and len(rows) == 13, "header + 12 งานที่เผยแพร่"
    actions = [e["action"] for e in read_json_file("logs")]
    assert "ARTWORK_CREATED" in actions and "ARTWORK_DELETED" in actions


def test_console_admin_session_and_login_limit():
    code, text = run_console(["admin@art4sells.test", "6", "7", "3", "0"], [PASSWORD])
    assert code == 0 and "ผู้ใช้ทั้งหมด" in text and "7" in text and "USER_LOGIN" in text
    assert "เมนูนี้สำหรับศิลปิน" in text
    code, text = run_console(["a@x.io", "b@x.io", "c@x.io"], ["bad1", "bad2", "bad3"])
    assert code == 1 and "3/3" in text and "ปิดโปรแกรม" in text, "login ผิดครบ 3 ครั้งต้องออก"


def test_console_export_failure_is_reported_not_crashed():
    ok, info = console_menu.export_artworks_csv([{"id": "w1"}], WORK_DIR / "artworks.json" / "cannot.csv")
    assert ok is False and "ไม่สามารถบันทึกไฟล์ได้" in info


def test_console_helpers():
    answers = iter(["", "  ", "Hello"])
    with contextlib.redirect_stdout(io.StringIO()):
        assert console_menu.ask_text("t: ", lambda p: next(answers)) == "Hello"
        assert console_menu.ask_float("p: ", lambda p, it=iter(["x", "-1", "12.5"]): next(it)) == 12.5
        assert console_menu.ask_float("p: ", lambda p: "q") is None
        assert console_menu.ask_int("n: ", lambda p, it=iter(["0", "1.5", "3"]): next(it)) == 3
    assert console_menu.is_allowed("3", {"role": "USER"})[0] is False
    assert console_menu.is_allowed("3", {"role": "ARTIST"}) == (True, "")
    assert console_menu.is_allowed("6", {"role": "ADMIN"})[0] is True
    assert console_menu.is_allowed("5", {"role": "USER"})[0] is False
    assert "w1 | Moonlit Koi" in console_menu.format_artwork_line(
        {"id": "w1", "title": "Moonlit Koi", "price": 1200, "status": "APPROVED", "artist_name": "Mika"})



# ---------------------------------------------------------------------------
# ตัวรัน test
# ---------------------------------------------------------------------------
def prepare_template():
    """สร้างข้อมูลตัวอย่างหนึ่งชุด แล้วคัดลอกให้แต่ละ test ใช้ (เร็วกว่า seed ใหม่ทุกครั้ง)"""
    global TEMPLATE_DIR
    TEMPLATE_DIR = Path(tempfile.mkdtemp(prefix="a4s_template_"))
    storage.configure(TEMPLATE_DIR)
    seed.seed_all()


def run_one(name, func):
    """รัน test หนึ่งตัวบนสำเนาข้อมูลสดใหม่ คืน True ถ้าผ่าน"""
    global WORK_DIR
    WORK_DIR = Path(tempfile.mkdtemp(prefix="a4s_test_"))
    shutil.rmtree(WORK_DIR)
    shutil.copytree(TEMPLATE_DIR, WORK_DIR)
    storage.configure(WORK_DIR)
    from backend.modules import file_storage
    file_storage.use_store(file_storage.LocalFileStore(WORK_DIR / "_uploads"))   # ไฟล์ภาพของเทสต์อยู่ในโฟลเดอร์ชั่วคราว ไม่แตะ uploads/ จริง
    saved = (config.LOGIN_MAX_FAILS_PER_PAIR, config.LOGIN_MAX_FAILS_PER_ACCOUNT, config.LOGIN_MAX_FAILS_PER_IP)
    if not getattr(func, "uses_real_rate_limit", False):
        # test เดิมหลายตัวจงใจกรอกรหัสผิดซ้ำ ๆ เพื่อทดสอบการตรวจรหัสผ่าน  จึงเพิ่มเพดานเฉพาะระหว่างเทสต์เหล่านั้น
        # ส่วน test ที่ทดสอบ rate limit (ใส่ @real_rate_limit) ใช้ค่าจริงใน config.py
        config.LOGIN_MAX_FAILS_PER_PAIR = config.LOGIN_MAX_FAILS_PER_ACCOUNT = config.LOGIN_MAX_FAILS_PER_IP = 10_000
    try:
        func()
        print("ok    " + name)
        return True
    except Exception as err:                                   # test ล้ม: แสดงสาเหตุแล้วไปตัวถัดไป
        print("FAIL  " + name + " -> " + repr(err))
        if not isinstance(err, AssertionError):
            traceback.print_exc()
        else:
            print("      " + traceback.format_exc().strip().splitlines()[-3].strip())
        return False
    finally:
        config.LOGIN_MAX_FAILS_PER_PAIR, config.LOGIN_MAX_FAILS_PER_ACCOUNT, config.LOGIN_MAX_FAILS_PER_IP = saved
        file_storage.reset_store()
        storage.configure(TEMPLATE_DIR)
        shutil.rmtree(WORK_DIR, ignore_errors=True)


def collect_tests():
    """รวม test จากไฟล์นี้ test_security.py (Phase 3.5) และ test_finale.py (Finale Part 1)  คืน list ของ (ชื่อ, ฟังก์ชัน)"""
    import test_finale
    import test_security
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    tests += [("security." + n, f) for n, f in sorted(vars(test_security).items()) if n.startswith("test_") and callable(f)]
    tests += [("finale." + n, f) for n, f in sorted(vars(test_finale).items()) if n.startswith("test_") and callable(f)]
    return tests


def main():
    prepare_template()
    tests = collect_tests()
    passed = 0
    for name, func in tests:
        if run_one(name, func):
            passed += 1
    shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
    print("\n" + str(passed) + "/" + str(len(tests)) + " tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    import test_backend as _suite              # รันผ่านชื่อโมดูลจริง เพื่อให้ test_security ใช้ตัวแปรชุดเดียวกัน
    sys.exit(_suite.main())
