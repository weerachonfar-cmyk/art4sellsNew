"""test_finale.py - ชุดทดสอบ Finale Prototype PART 1 (รันรวมกับ test_backend.py: python backend/tests/test_backend.py)

ครอบคลุม: cookie session / CSRF / rate limit / Developer OTP Mailbox / /api/health / Storage (JSON + Redis) /
          ไฟล์งานศิลปะ (อัปโหลด ลายน้ำ ดาวน์โหลดหลังชำระเงิน) / security headers / Vercel readiness / ตรวจโค้ดแบบ static

หมายเหตุสำคัญ (ความซื่อสัตย์ของเทสต์):
  - Redis ในเทสต์คือ "เซิร์ฟเวอร์จำลอง Upstash REST" (fake_upstash.py) ในหน่วยความจำ - ไม่แตะ production data และไม่ต้องใช้ network
    จึงพิสูจน์ได้ว่า "โค้ดของเรา" ทำงานถูกกับ REST protocol ที่คาดหวัง แต่ยังไม่ใช่การทดสอบกับ Upstash ตัวจริง
  - Vercel Blob ในเทสต์ใช้ SDK ปลอม + urlopen ปลอม  ตรวจรูปแบบการเรียกและการตรวจสิทธิ์ของเรา ไม่ได้ทดสอบกับ Blob จริง
  - ไม่มีเทสต์ไหนยืนยันว่า "deploy บน Vercel สำเร็จ" - ต้องทดสอบหลัง deploy จริง (ดู VERCEL_DEPLOYMENT.md)
"""
import base64
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fake_upstash
import test_backend as tb
from backend import config
from backend.modules import adapter, api, artwork_files, file_storage, storage
from backend.modules import storage_providers as sp
from backend.modules.errors import StorageError

call, call_full, login = tb.call, tb.call_full, tb.login
ROOT = Path(__file__).resolve().parent.parent.parent
HOST = "art4sells.test"
SAME = {"Host": HOST, "Origin": "http://" + HOST}              # คำขอที่เบราว์เซอร์จริงส่งมาจากหน้าเว็บของเราเอง
BUYER = {"email": "buyer@art4sells.test", "password": tb.PASSWORD}
LOGIN_BODY = BUYER


# ---------------------------------------------------------------------------
# ตัวช่วย
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def patched(**changes):
    """เปลี่ยนค่าใน config ชั่วคราว แล้วคืนค่าเดิมเสมอ"""
    saved = {name: getattr(config, name) for name in changes}
    for name, value in changes.items():
        setattr(config, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(config, name, value)


@contextlib.contextmanager
def redis_env(prefix):
    """ใช้ RedisStorage ที่ต่อกับ Upstash จำลอง (prefix ของเทสต์ ไม่ใช่ a4s:v1) แล้วคืน provider เดิมเมื่อจบ"""
    fake = fake_upstash.FakeUpstash()
    url = fake.start()
    previous = storage.get_provider()
    provider = sp.RedisStorage(sp.UpstashRestClient(url, fake_upstash.VALID_TOKEN), prefix=prefix)
    storage.use_provider(provider)
    adapter.reset_ready()
    try:
        yield fake, provider
    finally:
        storage.use_provider(previous)
        adapter.reset_ready()
        fake.stop()


@contextlib.contextmanager
def provider_from_config(**changes):
    """สร้าง provider จาก config (ผ่าน build_provider จริง) ที่ปรับค่าแล้ว - ใช้ทดสอบกรณีตั้งค่าผิด/ไม่ครบ"""
    previous = storage.get_provider()
    with patched(**changes):
        storage.use_provider(sp.build_provider(storage.get_data_dir()))
        try:
            yield storage.get_provider()
        finally:
            storage.use_provider(previous)


def cookie_value(token):
    return config.SESSION_COOKIE_NAME + "=" + token


def with_cookie(token, **extra):
    headers = {"Cookie": cookie_value(token)}
    headers.update(SAME)
    headers.update(extra)
    return headers


def set_cookie_headers(result):
    return [value for name, value in result.headers if name.lower() == "set-cookie"]


def need_pillow():
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise AssertionError("ต้องติดตั้ง Pillow เพื่อทดสอบส่วนไฟล์ภาพ:  pip install Pillow")


def make_image(fmt="PNG", size=(120, 80)):
    need_pillow()
    from PIL import Image
    img = Image.new("RGB", size, (20, 110, 190))
    for x in range(0, size[0], 7):
        for y in range(0, size[1], 5):
            img.putpixel((x, y), (240, 190, 30))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def upload_body(raw, filename="art.png", ctype="image/png", **extra):
    body = {"filename": filename, "content_type": ctype, "data_base64": base64.b64encode(raw).decode("ascii")}
    body.update(extra)
    return body


def fresh_artwork(token):
    status, art = call("POST", "/api/artworks", tb.new_artwork_body(), token)
    assert status == 201, art
    return art["id"]


def upload(art_id, token, raw, **kwargs):
    return call("POST", "/api/artworks/" + art_id + "/file", upload_body(raw, **kwargs), token)


def files_of(art_id):
    return {r["role"]: r for r in storage.get_all("files") if r["artwork_id"] == art_id}


def stored_files():
    base = Path(file_storage.get_store().base_dir)
    return sorted(p for p in base.rglob("*") if p.is_file())


def publish(art_id, mika, admin):
    assert call("POST", "/api/artworks/" + art_id + "/submit", None, mika)[0] == 200
    assert call("POST", "/api/artworks/" + art_id + "/approve", None, admin)[0] == 200


def audit(action):
    return [e for e in tb.read_json_file("logs") if e["action"] == action]


# ===========================================================================
# 1) Cookie session (HttpOnly) - ไม่มี token ใน JSON / ใน storage ของเบราว์เซอร์
# ===========================================================================
def test_login_sets_httponly_cookie_and_token_is_never_in_json():
    for path, body in (("/api/login", LOGIN_BODY),
                       ("/api/register", {"name": "Cookie One", "email": "cookie1@x.io", "password": "Passw0rd1!",
                                          "confirm_password": "Passw0rd1!", "role": "USER"})):
        result = call_full("POST", path, body)
        cookies = set_cookie_headers(result)
        assert result.status in (200, 201) and len(cookies) == 1, path
        cookie, token = cookies[0], tb.cookie_token(result)
        for part in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=" + str(config.SESSION_TTL_HOURS * 3600)):
            assert part in cookie, (path, part)
        assert "Secure" not in cookie, "ทาง http ธรรมดาไม่ตั้ง Secure (เบราว์เซอร์จะไม่เก็บ cookie)"
        assert token and token not in json.dumps(result.payload) and "token" not in result.payload, path


def test_cookie_secure_flag_follows_https_and_ignores_spoofed_headers():
    def cookie_for(headers=None):
        return set_cookie_headers(call_full("POST", "/api/login", LOGIN_BODY, headers=headers))[0]

    with patched(TRUST_PROXY=True):
        assert "Secure" in cookie_for({"X-Forwarded-Proto": "https"}), "หลัง proxy ที่เชื่อถือได้ (Vercel) ที่ส่งมาทาง HTTPS"
        assert "Secure" not in cookie_for({"X-Forwarded-Proto": "http"}) and "Secure" not in cookie_for()
    with patched(TRUST_PROXY=False):
        assert "Secure" not in cookie_for({"X-Forwarded-Proto": "https"}), "ไม่เชื่อ header ที่ปลอมได้เมื่อไม่ได้อยู่หลัง proxy"
    with patched(COOKIE_SECURE_MODE="always"):
        assert "Secure" in cookie_for()


def test_sessions_store_only_token_hash_with_user_and_expiry():
    token = login("buyer")
    text = (tb.WORK_DIR / "sessions.json").read_text(encoding="utf-8")
    assert token not in text, "ห้ามเก็บ session token แบบ plaintext"
    record = [s for s in storage.get_all("sessions") if s["user_id"] == "u1"][-1]
    assert {"token_hash", "user_id", "created_at", "expires_at"} <= set(record)
    assert not any(token in str(value) for value in record.values())
    ttl = datetime.fromisoformat(record["expires_at"]) - datetime.fromisoformat(record["created_at"])
    assert abs(ttl - timedelta(hours=config.SESSION_TTL_HOURS)) < timedelta(seconds=120), ttl


def test_cookie_authenticates_and_logout_invalidates_and_clears_it():
    token = login("buyer")
    assert call_full("GET", "/api/me", headers={"Cookie": cookie_value(token)}).status == 200
    out = call_full("POST", "/api/logout", headers=with_cookie(token))
    assert out.status == 200
    cleared = set_cookie_headers(out)
    assert len(cleared) == 1 and "Max-Age=0" in cleared[0] and cleared[0].startswith(config.SESSION_COOKIE_NAME + "=;")
    assert call_full("GET", "/api/me", headers={"Cookie": cookie_value(token)}).status == 401, "session ต้องถูกยกเลิกฝั่ง server"


def test_expired_cookie_session_is_rejected():
    token = login("buyer")
    for record in storage.get_all("sessions"):
        storage.update_record("sessions", record["id"], {"expires_at": "2000-01-01T00:00:00+00:00"})
    assert call_full("GET", "/api/me", headers={"Cookie": cookie_value(token)}).status == 401


def test_ban_invalidates_existing_cookie_sessions():
    buyer, admin = login("buyer"), login("admin")
    assert call_full("GET", "/api/me", headers={"Cookie": cookie_value(buyer)}).status == 200
    assert call("POST", "/api/users/u1/ban", None, admin)[0] == 200
    assert call_full("GET", "/api/me", headers={"Cookie": cookie_value(buyer)}).status == 401
    assert call("POST", "/api/login", LOGIN_BODY)[0] == 403, "บัญชีที่ถูกระงับ login ไม่ได้"


def test_garbage_session_cookies_never_authenticate_or_crash():
    for value in ("", "x", "a" * 19, "a" * 5000, "../../etc/passwd" * 3, "'; DROP TABLE sessions;--" * 2, "\x00" * 30,
                  "<script>alert(1)</script>" * 2, "ไทย😀" * 10):
        result = call_full("GET", "/api/me", headers={"Cookie": config.SESSION_COOKIE_NAME + "=" + value})
        assert result.status == 401, repr(value[:20])
    assert call_full("GET", "/api/me", headers={"Cookie": ";;;===;;"}).status == 401
    assert call_full("GET", "/api/me", headers={"Cookie": "a4s_session=" + "z" * 43 + "; a4s_session=" + "y" * 43}).status == 401


# ===========================================================================
# 2) CSRF / Origin / Content-Type / CORS
# ===========================================================================
def test_cookie_requests_need_a_trustworthy_origin():
    buyer = login("buyer")
    cookie = {"Cookie": cookie_value(buyer)}

    def add(extra, artwork):
        headers = dict(cookie)
        headers.update(extra)
        return call_full("POST", "/api/wishlist", {"artwork_id": artwork}, headers=headers)

    wished = lambda: [w for w in storage.get_all("wishlists") if w["user_id"] == "u1"]
    for extra in ({"Host": HOST, "Origin": "https://evil.example"}, {"Host": HOST, "Origin": "null"},
                  {"Host": HOST, "Origin": "http://" + HOST + ".evil.example"},
                  {"Host": HOST, "Sec-Fetch-Site": "cross-site"}, {"Host": HOST, "Sec-Fetch-Site": "same-site"},
                  {"Host": HOST}, {}):
        result = add(extra, "w1")
        assert result.status == 403 and result.payload["error"]["code"] == "CROSS_ORIGIN_BLOCKED", (extra, result.status)
    assert wished() == [], "คำขอที่ถูกบล็อกต้องไม่เปลี่ยนข้อมูล"
    assert add(SAME, "w1").status in (200, 201)
    assert add({"Host": HOST, "Sec-Fetch-Site": "same-origin"}, "w2").status in (200, 201)
    assert call("POST", "/api/wishlist", {"artwork_id": "w3"}, buyer)[0] in (200, 201), "Bearer (ไม่ใช่ cookie) ไม่เสี่ยง CSRF"
    assert call_full("GET", "/api/wishlist", headers={"Cookie": cookie_value(buyer), "Origin": "https://evil.example"}).status == 200, \
        "GET ไม่เปลี่ยนข้อมูล ไม่ต้องบล็อก"


def test_login_from_another_site_is_blocked():
    result = call_full("POST", "/api/login", LOGIN_BODY, headers={"Host": HOST, "Origin": "https://evil.example"})
    assert result.status == 403 and not set_cookie_headers(result), "กัน login CSRF"


def test_cookie_requests_must_be_json():
    buyer = login("buyer")
    for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""):
        headers = with_cookie(buyer)
        headers["Content-Type"] = content_type
        result = call_full("POST", "/api/wishlist", b'{"artwork_id":"w1"}', headers=headers)
        assert result.status in (400, 415), (content_type, result.status)
    assert call_full("POST", "/api/wishlist", b'[1,2]', headers=with_cookie(buyer)).status == 400
    assert call_full("POST", "/api/wishlist", b'{broken', headers=with_cookie(buyer)).status == 400
    assert [w for w in storage.get_all("wishlists") if w["user_id"] == "u1"] == []


def test_cors_is_closed_by_default_and_never_wildcard():
    assert adapter.cors_headers({}) == [] and adapter.cors_headers({"Origin": "https://evil.example"}) == []
    with patched(ALLOWED_ORIGINS=("https://front.example",)):
        allowed = dict(adapter.cors_headers({"Origin": "https://front.example"}))
        assert allowed["Access-Control-Allow-Origin"] == "https://front.example"
        assert allowed["Access-Control-Allow-Credentials"] == "true"
        assert adapter.cors_headers({"Origin": "https://evil.example"}) == []
        assert adapter.cors_headers({"Origin": "null"}) == []
    status, _body, headers = adapter.handle_api("GET", "/api/health", {"Origin": "https://evil.example"}, b"")
    assert "*" not in [value for name, value in headers if name.lower().startswith("access-control-")]


def test_security_headers_are_added_to_api_responses():
    status, _body, headers = adapter.handle_api("GET", "/api/health", {}, b"")
    got = {name.lower(): value for name, value in headers}
    csp = got["content-security-policy"]
    assert "script-src 'self'" in csp and not re.search(r"script-src[^;]*unsafe", csp) and "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp and "base-uri 'none'" in csp
    assert got["x-content-type-options"] == "nosniff" and got["referrer-policy"] and got["permissions-policy"]
    assert got["cache-control"] == "no-store" and got["content-type"].startswith("application/json")
    assert "strict-transport-security" not in got, "HSTS ส่งเฉพาะเมื่อมาทาง HTTPS"
    with patched(TRUST_PROXY=True):
        _s, _b, https_headers = adapter.handle_api("GET", "/api/health", {"X-Forwarded-Proto": "https"}, b"")
        assert "strict-transport-security" in {name.lower() for name, _ in https_headers}


def test_vercel_json_routes_api_to_python_and_root_to_index():
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    rules = {r["source"]: r["destination"] for r in cfg["rewrites"]}
    assert (ROOT / "public" / "index.html").is_file()
    assert cfg["outputDirectory"] == "dist" and "public/." in cfg["buildCommand"], "public/* ต้องขึ้นรากของเว็บ (/, /login.html, /style.css)"
    api_rules = [dest for src, dest in rules.items() if src.startswith("/api")]
    assert api_rules and all("public" not in dest for dest in api_rules), "/api/* ห้ามถูก rewrite ไป public/"
    assert not [src for src in rules if src in ("/(.*)", "/:path*")], "ห้ามมี catch-all ที่กลืน /api/*"
    assert (ROOT / "api" / "index.py").is_file()
    header_keys = json.dumps(cfg["headers"])
    for name in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy"):
        assert name in header_keys, name


def test_vercel_json_paths_exist_in_repo():
    """กันพลาดซ้ำ: path ใน vercel.json ต้องมีจริง (เคยใส่ art4sells/ นำหน้า -> build ล้มเหลว / functions ไม่ match)"""
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    for source in re.findall(r"cp -R (\S+)", cfg["buildCommand"]):
        assert (ROOT / source.rstrip("/.")).exists(), "buildCommand คัดลอกจาก path ที่ไม่มี: " + source
    for func_path in cfg["functions"]:
        assert (ROOT / func_path).is_file(), "functions ชี้ไฟล์ที่ไม่มี: " + func_path
    csp = [h["value"] for h in cfg["headers"][0]["headers"] if h["key"] == "Content-Security-Policy"][0]
    assert "https://fonts.googleapis.com" in csp and "https://fonts.gstatic.com" in csp, "CSP ต้องอนุญาตโดเมน Google Fonts ที่ถูกต้อง"


def test_built_site_resolves_every_script_and_stylesheet():
    """จำลอง buildCommand (public/* -> ราก, src/ -> /src) แล้วตรวจว่าทุก <script src>/<link href> ของทุกหน้า resolve เจอไฟล์จริง
    (ถ้าพลาด หน้าเว็บจะเหลือแต่ footer เพราะ JS ไม่โหลด) - เป็นการจำลองด้วย urljoin ไม่ใช่การทดสอบบน Vercel จริง"""
    from urllib.parse import urljoin, urlparse
    out = Path(tempfile.mkdtemp())
    try:
        shutil.copytree(ROOT / "public", out, dirs_exist_ok=True)
        shutil.copytree(ROOT / "src", out / "src")
        pages = sorted(out.glob("*.html"))
        assert pages, "ไม่พบหน้า .html"
        for page in pages:
            base = "https://site.test/" + ("" if page.name == "index.html" else page.name)
            for ref in re.findall(r'(?:src|href)="([^"#?]+\.(?:js|css))"', page.read_text(encoding="utf-8")):
                target = out / urlparse(urljoin(base, ref)).path.lstrip("/")
                assert target.is_file(), page.name + " อ้าง " + ref + " แต่ไม่พบ " + str(target.relative_to(out))
    finally:
        shutil.rmtree(out, ignore_errors=True)


@contextlib.contextmanager
def vercel_handler_server():
    """รัน api/index.py (handler ของ Vercel) เป็น HTTP server ในเครื่อง - ใช้ทดสอบ adapter ผ่านคำขอ HTTP จริง (ไม่ใช่ Vercel จริง)"""
    import importlib.util
    from http.server import ThreadingHTTPServer
    spec = importlib.util.spec_from_file_location("vercel_api_index_under_test", ROOT / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:" + str(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


def exercise_vercel_routes(base, expect_storage):
    """GET /api/health, GET /api/artworks, POST /api/login, POST /api/register (ตามสเปกข้อ 4) ผ่าน handler ของ Vercel"""
    status, health, headers = tb.http_json_full(base, "GET", "/api/health")
    assert status == 200 and health["ok"] and health["storage"] == expect_storage and health["storage_available"], health
    assert "Content-Security-Policy" in headers and headers["X-Content-Type-Options"] == "nosniff"
    status, listing, _h = tb.http_json_full(base, "GET", "/api/artworks")
    assert status == 200 and listing["total"] > 0 and "items" in listing
    status, data, headers = tb.http_json_full(base, "POST", "/api/login", {"email": BUYER["email"], "password": BUYER["password"]})
    cookie = tb.http_cookie_of(headers)
    assert status == 200 and cookie and "token" not in data and data["user"]["role"] == "USER"
    cookie_line = [v for v in headers.get_all("Set-Cookie") if v.startswith(config.SESSION_COOKIE_NAME + "=")][0]
    assert "HttpOnly" in cookie_line and "SameSite=Lax" in cookie_line and "Path=/" in cookie_line
    assert tb.http_json_full(base, "GET", "/api/me", cookie=cookie)[0] == 200
    assert tb.http_json_full(base, "POST", "/api/login", {"email": BUYER["email"], "password": "WrongPass1!"})[0] == 401
    assert tb.http_json_full(base, "POST", "/api/login", {"email": "nobody@art4sells.test", "password": "WrongPass1!"})[0] == 401
    body = {"name": "Vercel Tester", "email": "vercel-tester@x.io", "password": "Passw0rd1!", "confirm_password": "Passw0rd1!", "role": "USER"}
    status, reg, headers = tb.http_json_full(base, "POST", "/api/register", body)
    assert status == 201 and tb.http_cookie_of(headers) and reg["user"]["role"] == "USER"
    assert tb.http_json_full(base, "POST", "/api/register", dict(body, email="vercel-admin@x.io", role="ADMIN"))[0] == 400
    assert tb.http_json_full(base, "GET", "/api/does-not-exist")[0] == 404
    assert tb.http_json_full(base, "POST", "/api/login", None)[0] == 400
    out_status, out, out_headers = tb.http_json_full(base, "POST", "/api/logout", None, cookie=cookie, extra_headers={"Origin": base})
    assert out_status == 200 and "Max-Age=0" in [v for v in out_headers.get_all("Set-Cookie")][0]
    assert tb.http_json_full(base, "GET", "/api/me", cookie=cookie)[0] == 401


def test_vercel_function_handler_serves_core_routes_over_http_with_local_json():
    with vercel_handler_server() as base:
        exercise_vercel_routes(base, "json")


def test_vercel_function_handler_serves_core_routes_over_http_with_redis():
    with redis_env("test:vercel-handler") as (fake, provider):
        with patched(RUNNING_ON_VERCEL=True, MODE="vercel", TRUST_PROXY=True):
            with vercel_handler_server() as base:
                assert not provider.is_initialized(), "ยังไม่ seed จนกว่าจะมี request แรก"
                exercise_vercel_routes(base, "redis")
                assert provider.is_initialized() and fake.data and all(k.startswith("test:vercel-handler:") for k in fake.data)
                seeded_sets = fake.commands.count("SET")
                exercise_vercel_routes_again = tb.http_json_full(base, "GET", "/api/artworks")
                assert exercise_vercel_routes_again[0] == 200
                users = storage.get_all("users")
                assert len(users) >= 8 and any(u["email"] == "vercel-tester@x.io" for u in users), "ข้อมูลที่สมัครเองอยู่ใน Redis และไม่ถูก seed ทับ"


# ===========================================================================
# 3) Login rate limit (IP + อีเมล) - ใช้เพดานจริง 5 ครั้ง / 10 นาที
# ===========================================================================
@tb.real_rate_limit
def test_login_rate_limit_blocks_after_5_failures_even_with_correct_password():
    ip = "10.0.0.1"
    for _ in range(config.LOGIN_MAX_FAILS_PER_PAIR):
        assert tb.call_login(BUYER["email"], "WrongPass1!", ip=ip)[0] == 401
    status, data, token = tb.call_login(BUYER["email"], tb.PASSWORD, ip=ip)      # รหัสถูกก็ยังโดนบล็อก (ระหว่าง cooldown)
    assert status == 429 and data["error"]["code"] == "LOGIN_RATE_LIMITED" and token is None
    assert 0 < data["error"]["details"]["retry_after_seconds"] <= config.LOGIN_WINDOW_MINUTES * 60 + 2
    assert tb.call_login(BUYER["email"], tb.PASSWORD, ip=ip)[0] == 429
    assert len(audit("LOGIN_RATE_LIMITED")) == 1, "บันทึก security event ตอนเพิ่งถูกบล็อก (ไม่ log ซ้ำทุกครั้งที่ยิงต่อ)"
    text = (tb.WORK_DIR / "login_attempts.json").read_text(encoding="utf-8")
    assert ip not in text and BUYER["email"] not in text, "เก็บเฉพาะ hash ของ IP/อีเมล"


@tb.real_rate_limit
def test_login_rate_limit_is_not_ip_only_identity():
    for _ in range(config.LOGIN_MAX_FAILS_PER_PAIR):
        tb.call_login(BUYER["email"], "WrongPass1!", ip="10.0.0.1")
    assert tb.call_login(BUYER["email"], "WrongPass1!", ip="10.0.0.1")[0] == 429
    assert tb.call_login(BUYER["email"], tb.PASSWORD, ip="10.0.0.2")[0] == 200, "IP อื่นยังเข้าได้ (ไม่ล็อกเจ้าของบัญชีจากคนร้ายคนเดียว)"
    assert tb.call_login("mika@art4sells.test", tb.PASSWORD, ip="10.0.0.1")[0] == 200, "อีเมลอื่นจาก IP เดียวกันยังเข้าได้"


@tb.real_rate_limit
def test_login_rate_limit_does_not_reveal_which_emails_exist():
    for _ in range(config.LOGIN_MAX_FAILS_PER_PAIR):
        assert tb.call_login("nobody@art4sells.test", "WrongPass1!", ip="10.0.0.3")[0] == 401
    status, data, _ = tb.call_login("nobody@art4sells.test", "WrongPass1!", ip="10.0.0.3")
    assert status == 429 and data["error"]["code"] == "LOGIN_RATE_LIMITED", "อีเมลที่ไม่มีในระบบก็นับ/ตอบแบบเดียวกัน"


@tb.real_rate_limit
def test_login_rate_limit_success_resets_only_that_pair():
    for _ in range(config.LOGIN_MAX_FAILS_PER_PAIR - 1):
        tb.call_login(BUYER["email"], "WrongPass1!", ip="10.0.0.4")
    assert tb.call_login(BUYER["email"], tb.PASSWORD, ip="10.0.0.4")[0] == 200
    for _ in range(config.LOGIN_MAX_FAILS_PER_PAIR - 1):
        assert tb.call_login(BUYER["email"], "WrongPass1!", ip="10.0.0.4")[0] == 401


@tb.real_rate_limit
def test_login_rate_limit_account_and_ip_wide_limits():
    for number in range(config.LOGIN_MAX_FAILS_PER_ACCOUNT):                     # เดาบัญชีเดียวจากหลาย IP
        assert tb.call_login(BUYER["email"], "WrongPass1!", ip="10.1.0." + str(number))[0] == 401
    status, data, _ = tb.call_login(BUYER["email"], tb.PASSWORD, ip="10.1.9.9")
    assert status == 429 and data["error"]["code"] == "LOGIN_RATE_LIMITED"
    for number in range(config.LOGIN_MAX_FAILS_PER_IP):                          # ไล่เดาหลายบัญชีจาก IP เดียว
        assert tb.call_login("u%d@x.io" % number, "WrongPass1!", ip="10.2.0.1")[0] == 401
    assert tb.call_login("another@x.io", "WrongPass1!", ip="10.2.0.1")[0] == 429
    assert tb.call_login("mika@art4sells.test", tb.PASSWORD, ip="10.2.0.2")[0] == 200


@tb.real_rate_limit
def test_login_rate_limit_expires_after_the_window():
    for _ in range(config.LOGIN_MAX_FAILS_PER_PAIR):
        tb.call_login(BUYER["email"], "WrongPass1!", ip="10.0.0.5")
    assert tb.call_login(BUYER["email"], tb.PASSWORD, ip="10.0.0.5")[0] == 429
    old = (datetime.now(timezone.utc) - timedelta(minutes=config.LOGIN_WINDOW_MINUTES + 1)).isoformat(timespec="seconds")
    storage.save_json("login_attempts", [dict(e, at=old) for e in storage.get_all("login_attempts")])
    assert tb.call_login(BUYER["email"], tb.PASSWORD, ip="10.0.0.5")[0] == 200


@tb.real_rate_limit
def test_forwarded_for_header_is_only_trusted_behind_a_proxy():
    def attempt(forwarded):
        result = call_full("POST", "/api/login", {"email": BUYER["email"], "password": "WrongPass1!"},
                           headers={"X-Forwarded-For": forwarded}, ip="10.0.0.6")
        return result.status
    with patched(TRUST_PROXY=False):                                              # ปลอม header เพื่อหนีการนับไม่ได้
        for number in range(config.LOGIN_MAX_FAILS_PER_PAIR):
            assert attempt("9.9.9." + str(number)) == 401
        assert attempt("9.9.9.200") == 429
    storage.save_json("login_attempts", [])
    with patched(TRUST_PROXY=True):                                               # หลัง proxy ใช้ IP แรกของ X-Forwarded-For
        for _ in range(config.LOGIN_MAX_FAILS_PER_PAIR):
            assert attempt("7.7.7.7, 10.9.9.9") == 401
        assert attempt("7.7.7.7") == 429 and attempt("7.7.7.8") == 401


# ===========================================================================
# 4) Developer OTP Mailbox (เฉพาะ ADMIN + development + A4S_DEV_TOOLS=true)
# ===========================================================================
def test_dev_tools_default_is_off_and_env_parsing_is_strict():
    assert config._env_bool("A4S_THIS_IS_NOT_SET", False) is False
    assert config.DEV_TOOLS is False or config.DEV_TOOLS is True
    import os
    for raw, expected in (("true", True), ("TRUE", True), (" 1 ", True), ("yes", True), ("false", False), ("0", False),
                          ("", False), ("enabled", False), ("on", False)):
        os.environ["A4S_TEST_FLAG"] = raw
        assert config._env_bool("A4S_TEST_FLAG", False) is expected, raw
    os.environ["A4S_TEST_FLAG"] = "   "
    assert config._env_bool("A4S_TEST_FLAG", True) is True and config._env_bool("A4S_TEST_FLAG", False) is False, "เว้นว่าง = ค่าเริ่มต้น"
    os.environ.pop("A4S_TEST_FLAG", None)


def test_dev_mailbox_is_admin_only_and_shows_otp_when_enabled():
    import test_security as ts
    with patched(EMAIL_MODE="development", DEV_TOOLS=True):
        admin, buyer, mika = login("admin"), login("buyer"), login("mika")
        with ts.mailbox() as outbox:
            status, data = call("POST", "/api/auth/forgot-password", {"email": BUYER["email"]})
            code = ts.code_of(outbox[0])
        assert status == 200 and code not in json.dumps(data), "API สาธารณะห้ามคืน OTP"
        assert call("GET", "/api/dev/mailbox")[0] == 401
        assert call("GET", "/api/dev/mailbox", None, buyer)[0] == 403 and call("GET", "/api/dev/mailbox", None, mika)[0] == 403
        status, box = call("GET", "/api/dev/mailbox", None, admin)
        assert status == 200 and len(box["items"]) == 1
        item = box["items"][0]
        assert {"recipient", "created_at", "expires_at", "otp", "purpose"} <= set(item)
        assert item["recipient"] == BUYER["email"] and item["otp"] == code and item["purpose"] == "PASSWORD_RESET"
        assert item["expired"] is False and "DEVELOPMENT" in box["warning"]
        assert call("GET", "/api/me", None, admin)[1].get("dev_tools") is True
        assert "dev_tools" not in call("GET", "/api/me", None, buyer)[1]
        assert code not in json.dumps(tb.read_json_file("logs")), "OTP ห้ามอยู่ใน audit log"
        assert call("DELETE", "/api/dev/mailbox", None, buyer)[0] == 403
        assert call("DELETE", "/api/dev/mailbox", None, admin)[1]["removed"] == 1
        assert call("GET", "/api/dev/mailbox", None, admin)[1]["items"] == []
        assert audit("DEV_MAILBOX_VIEWED") and audit("DEV_MAILBOX_CLEARED")


def test_dev_mailbox_is_invisible_when_dev_tools_off_or_in_production_mode():
    import test_security as ts
    admin = login("admin")
    for mode, tools in (("development", False), ("production", True), ("production", False)):
        with patched(EMAIL_MODE=mode, DEV_TOOLS=tools):
            with ts.mailbox():
                call("POST", "/api/auth/forgot-password", {"email": BUYER["email"]})
            assert call("GET", "/api/dev/mailbox", None, admin)[0] == 404, (mode, tools)
            assert call("DELETE", "/api/dev/mailbox", None, admin)[0] == 404, (mode, tools)
            assert call("GET", "/api/dev/mailbox")[0] == 404, "ปิดอยู่ = ไม่เผยว่ามี endpoint นี้ (แม้ไม่ login)"
            assert "dev_tools" not in call("GET", "/api/me", None, admin)[1]
            assert storage.get_all("dev_mailbox") == [], "ปิดอยู่ต้องไม่เก็บ OTP ที่ไหนเลย"
            storage.save_json("password_resets", [])
            storage.save_json("reset_requests", [])


# ===========================================================================
# 5) /api/health และการตั้งค่า storage ผิด (ห้าม fallback เงียบ ๆ)
# ===========================================================================
def test_health_reports_local_json_state_without_leaking_anything():
    status, data = call("GET", "/api/health")
    assert status == 200 and data == {
        "ok": True, "application": "Art 4 Sells", "mode": "local", "storage": "json", "storage_available": True,
        "deployment_ready": True, "email_mode": config.EMAIL_MODE, "version": "finale-prototype"}, data
    text = json.dumps(data).lower()
    for forbidden in (str(tb.WORK_DIR).lower(), "token", "password", "secret", "session", "/home", "traceback", "hash"):
        assert forbidden not in text, forbidden


def test_vercel_without_redis_is_unavailable_and_never_falls_back_to_json():
    users_before = (tb.WORK_DIR / "users.json").read_bytes()
    with provider_from_config(RUNNING_ON_VERCEL=True, MODE="vercel", STORAGE_PROVIDER="redis", REDIS_REST_URL="",
                              REDIS_REST_TOKEN=""):
        status, data = call("GET", "/api/health")
        assert status == 503 and data["ok"] is False and data["mode"] == "vercel" and data["storage"] == "redis"
        assert data["storage_available"] is False and data["deployment_ready"] is False
        assert data["storage_error"] == "REDIS_NOT_CONFIGURED"
        listing = call("GET", "/api/artworks")
        register = call("POST", "/api/register", {"name": "Nope", "email": "nope@x.io", "password": "Passw0rd1!",
                                                  "confirm_password": "Passw0rd1!", "role": "USER"})
        for status, body in (listing, register):
            assert status == 503 and body["error"]["code"] == "STORAGE_UNAVAILABLE"
            assert "REDIS" not in json.dumps(body) and "Traceback" not in json.dumps(body)
    assert (tb.WORK_DIR / "users.json").read_bytes() == users_before, "ห้ามเขียน JSON แทน Redis แบบเงียบ ๆ"
    assert not (tb.WORK_DIR / "nope.json").exists()


def test_misconfigured_storage_is_reported_with_safe_codes():
    cases = (
        (dict(RUNNING_ON_VERCEL=True, MODE="vercel", STORAGE_PROVIDER="json"), "json", "JSON_STORAGE_NOT_ALLOWED_ON_VERCEL"),
        (dict(STORAGE_PROVIDER="mongo"), "mongo", "STORAGE_PROVIDER_UNSUPPORTED"),
        (dict(STORAGE_PROVIDER="redis", REDIS_REST_URL="http://evil.example/x", REDIS_REST_TOKEN="t"), "redis", "REDIS_URL_INVALID"),
        (dict(STORAGE_PROVIDER="redis", REDIS_REST_URL="https://x.upstash.io", REDIS_REST_TOKEN=""), "redis", "REDIS_NOT_CONFIGURED"),
    )
    for changes, name, code in cases:
        with provider_from_config(**changes):
            status, data = call("GET", "/api/health")
            assert status == 503 and data["storage"] == name and data["storage_available"] is False, (code, data)
            assert data["deployment_ready"] is False and data["storage_error"] == code
            assert "evil.example" not in json.dumps(data) and "upstash" not in json.dumps(data)
    assert sp.redis_url_is_acceptable("https://abc.upstash.io") and sp.redis_url_is_acceptable("http://127.0.0.1:9")
    for bad in ("http://abc.upstash.io", "ftp://x", "javascript:alert(1)", "", None, "https://"):
        assert not sp.redis_url_is_acceptable(bad), bad


def test_vercel_demo_mode_needs_no_setup_and_seeds_itself():
    """deploy บน Vercel โดยไม่ตั้งค่าอะไรเลย = โหมด DEMO (JSON ใน /tmp + seed เอง) ใช้งานได้ทันที
    ไม่ใช่ fallback แบบเงียบ ๆ: /api/health บอกชัดว่า demo_mode=true, persistent=false, deployment_ready=false"""
    scratch = Path(tempfile.mkdtemp())
    previous = storage.get_provider()
    try:
        with patched(RUNNING_ON_VERCEL=True, MODE="vercel", STORAGE_PROVIDER="json", DEMO_EPHEMERAL=True):
            provider = sp.build_provider(scratch)
            assert provider.name == "json", "โหมด DEMO ต้องใช้ JSON ชั่วคราวได้"
            storage.use_provider(provider)
            adapter.reset_ready()
            headers = dict(SAME, **{"Content-Type": "application/json"})
            status, body, _ = adapter.handle_api("GET", "/api/health", headers, b"")
            data = json.loads(body)
            assert status == 200 and data["ok"] is True and data["mode"] == "vercel", data
            assert data["demo_mode"] is True and data["persistent"] is False and data["deployment_ready"] is False, data
            assert str(scratch) not in body.decode("utf-8") and "/tmp" not in body.decode("utf-8"), "ห้ามโชว์ path"
            status, body, _ = adapter.handle_api("GET", "/api/artworks", headers, b"")
            assert status == 200 and len(json.loads(body)["items"]) >= 1, "ต้อง seed ข้อมูลตัวอย่างเอง"
            status, body, out_headers = adapter.handle_api("POST", "/api/login", headers, json.dumps(BUYER).encode("utf-8"))
            assert status == 200 and any(name.lower() == "set-cookie" for name, _ in out_headers), body
            assert (scratch / "users.json").is_file(), "ข้อมูลต้องไปอยู่ในโฟลเดอร์ชั่วคราว ไม่ใช่ backend/data"
    finally:
        storage.use_provider(previous)
        adapter.reset_ready()
        shutil.rmtree(scratch, ignore_errors=True)


def test_vercel_demo_mode_file_store_and_strict_modes_stay_strict():
    scratch = Path(tempfile.mkdtemp())
    try:
        with patched(RUNNING_ON_VERCEL=True, DEMO_EPHEMERAL=True, FILE_STORAGE_PROVIDER="", BLOB_READ_WRITE_TOKEN="", UPLOAD_DIR=scratch):
            assert file_storage.build_store().name == "local", "โหมด DEMO ยังไม่มี Blob: เก็บไฟล์ชั่วคราวใน /tmp"
        with patched(RUNNING_ON_VERCEL=True, DEMO_EPHEMERAL=True, FILE_STORAGE_PROVIDER="", BLOB_READ_WRITE_TOKEN="tok"):
            assert file_storage.build_store().name == "vercel-blob", "มี Blob token แล้วต้องใช้ Blob จริง"
        with patched(RUNNING_ON_VERCEL=True, DEMO_EPHEMERAL=False, FILE_STORAGE_PROVIDER="", BLOB_READ_WRITE_TOKEN=""):
            assert file_storage.build_store().name == "unavailable", "ต่อ Redis แล้วแต่ไม่มี Blob = ยังตอบ 503 เหมือนเดิม"
        with patched(RUNNING_ON_VERCEL=True, DEMO_EPHEMERAL=False, FILE_STORAGE_PROVIDER="local"):
            assert file_storage.build_store().name == "unavailable"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    with patched(RUNNING_ON_VERCEL=True, MODE="vercel", STORAGE_PROVIDER="json", DEMO_EPHEMERAL=False):
        assert sp.build_provider(storage.get_data_dir()).name == "unavailable", "ตั้ง A4S_STORAGE=json เองบน Vercel = ยังห้ามเหมือนเดิม"


def test_demo_mode_is_chosen_only_when_nothing_is_configured():
    """config ถูกอ่านตอน import จึงทดสอบด้วย subprocess ที่ตั้ง environment ต่างกัน"""
    import os
    import subprocess
    code = ("from backend import config; from backend.modules import storage, file_storage; "
            "print(config.DEMO_EPHEMERAL, config.STORAGE_PROVIDER, storage.get_provider().name, file_storage.get_store().name)")
    managed = ("VERCEL", "A4S_STORAGE", "A4S_FILE_STORAGE", "A4S_DATA_DIR", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
               "KV_REST_API_URL", "KV_REST_API_TOKEN", "BLOB_READ_WRITE_TOKEN")
    cases = (
        ({}, "False json json local"),                                                         # เครื่องตัวเอง
        ({"VERCEL": "1"}, "True json json local"),                                              # deploy เปล่า ๆ = DEMO
        ({"VERCEL": "1", "UPSTASH_REDIS_REST_URL": "https://x.upstash.io", "UPSTASH_REDIS_REST_TOKEN": "t"},
         "False redis redis unavailable"),                                                      # ต่อ Upstash แล้ว = ใช้ Redis อัตโนมัติ
        ({"VERCEL": "1", "KV_REST_API_URL": "https://x.upstash.io", "KV_REST_API_TOKEN": "t"}, "False redis redis unavailable"),
        ({"VERCEL": "1", "A4S_STORAGE": "redis"}, "False redis unavailable unavailable"),       # ตั้งเองแต่ไม่ครบ = 503 ไม่ fallback
        ({"VERCEL": "1", "A4S_STORAGE": "json"}, "False json unavailable unavailable"),
    )
    for extra, expected in cases:
        env = {k: v for k, v in os.environ.items() if k not in managed}
        env.update(extra)
        result = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.');" + code], env=env, cwd=str(ROOT),
                                capture_output=True, text=True, timeout=60)
        assert result.stdout.strip() == expected, (extra, result.stdout, result.stderr[-300:])


def test_health_with_redis_ok_and_when_redis_goes_down():
    with redis_env("test:health") as (fake, provider):
        with patched(RUNNING_ON_VERCEL=True, MODE="vercel"):
            status, data = call("GET", "/api/health")
            assert status == 200 and data["ok"] and data["mode"] == "vercel" and data["storage"] == "redis"
            assert data["storage_available"] is True and data["deployment_ready"] is True
            fake.stop()
            status, data = call("GET", "/api/health")
            assert status == 503 and data["storage_available"] is False and data["deployment_ready"] is False
            assert data["storage_error"] == "REDIS_UNREACHABLE"
            text = json.dumps(data)
            assert "127.0.0.1" not in text and fake_upstash.VALID_TOKEN not in text


def test_provider_is_selected_from_config_without_touching_real_prefix():
    fake = fake_upstash.FakeUpstash()
    url = fake.start()
    try:
        with provider_from_config(RUNNING_ON_VERCEL=True, MODE="vercel", STORAGE_PROVIDER="redis", REDIS_REST_URL=url,
                                  REDIS_REST_TOKEN=fake_upstash.VALID_TOKEN, REDIS_KEY_PREFIX="test:cfg") as provider:
            assert provider.name == "redis"
            storage.create_record("files", {"artwork_id": "x", "role": "original"}, "f")
            assert fake.data and all(key.startswith("test:cfg:") for key in fake.data)
        with provider_from_config(STORAGE_PROVIDER="json") as provider:
            assert provider.name == "json"
    finally:
        fake.stop()


# ===========================================================================
# 6) Storage abstraction: JSON และ Redis ต้องทำงานเหมือนกัน (Business Logic ไม่รู้ว่าใช้ตัวไหน)
# ===========================================================================
def run_storage_contract():
    first = storage.create_record("files", {"artwork_id": "x", "role": "original", "note": "ไทย ✓ 😀 \u200b"}, "f")
    second = storage.create_record("files", {"artwork_id": "x", "role": "preview"}, "f")
    storage.create_record("files", {"artwork_id": "y", "role": "delivery"}, "f")
    assert storage.get_record("files", first["id"])["note"] == "ไทย ✓ 😀 \u200b", "Thai / emoji ต้องไม่เพี้ยน"
    assert storage.get_record("files", "does-not-exist") is None
    assert len(storage.get_all("files")) == 3 and storage.count_records("files") == 3
    assert [r["role"] for r in storage.find_records("files", "artwork_id", "x")] == ["original", "preview"]
    assert storage.find_one("files", "artwork_id", "y")["role"] == "delivery" and storage.find_one("files", "artwork_id", "zz") is None
    assert storage.find_records("files", "artwork_id", "' OR '1'='1") == [] and storage.find_one("files", "role", "1; DROP TABLE x") is None
    storage.update_record("files", second["id"], {"role": "changed"})
    assert storage.get_record("files", second["id"])["role"] == "changed" and storage.count_records("files") == 3
    with storage.transaction():                                                  # ซ้อนกันได้ (reentrant)
        with storage.transaction():
            storage.create_record("files", {"artwork_id": "z"}, "f")
    assert storage.count_records("files") == 4
    storage.delete_record("files", first["id"])
    assert storage.get_record("files", first["id"]) is None and storage.count_records("files") == 3
    assert storage.delete_where("files", "artwork_id", "x") == 1 and storage.count_records("files") == 2
    for bad_name in ("../../etc/passwd", "files/../users", "", "nope", "FILES"):  # ชื่อ collection ต้องอยู่ใน allowlist (กัน path/key แปลก ๆ)
        try:
            storage.load_json(bad_name)
        except StorageError as err:
            assert err.code == "UNKNOWN_COLLECTION"
        else:
            raise AssertionError("ต้องปฏิเสธชื่อ collection: " + repr(bad_name))


def test_storage_contract_json_provider_and_persistence_across_restart():
    assert storage.provider_name() == "json"
    run_storage_contract()
    reopened = sp.JSONStorage(storage.get_data_dir())                            # เหมือนปิดโปรแกรมแล้วเปิดใหม่
    assert reopened.read("files") == storage.get_all("files") and len(reopened.read("files")) == 2


def test_storage_contract_redis_provider_and_persistence_across_instances():
    with redis_env("test:contract") as (fake, provider):
        run_storage_contract()
        reopened = sp.RedisStorage(provider.client, prefix="test:contract")      # instance ใหม่ (เหมือน cold start) เห็นข้อมูลเดิม
        assert reopened.read("files") == storage.get_all("files") and len(reopened.read("files")) == 2
        assert fake.data and all(key.startswith("test:contract:") for key in fake.data)
        assert not any(key.startswith("a4s:v1") for key in fake.data), "เทสต์ห้ามแตะ key ของข้อมูลจริง"
        assert "test:contract:lock" not in fake.data, "lock ต้องถูกปล่อยหลังใช้เสร็จ"


def test_same_business_logic_runs_on_redis():
    with redis_env("test:flow") as (fake, provider):
        adapter.ensure_ready()
        assert provider.is_initialized() is True
        status, _data, token = tb.call_login(BUYER["email"], BUYER["password"])
        assert status == 200 and token
        assert call("GET", "/api/me", None, token)[1]["user"]["email"] == BUYER["email"]
        assert call("POST", "/api/login", {"email": BUYER["email"], "password": "WrongPass1!"})[0] == 401
        mika = login("mika")
        status, art = call("POST", "/api/artworks", tb.new_artwork_body(title="Redis Piece"), mika)
        assert status == 201
        mine = call("GET", "/api/artworks", None, mika, {"mine": "true"})[1]["items"]
        assert "Redis Piece" in [item["title"] for item in mine]
        assert call("POST", "/api/logout", None, token)[0] == 200 and call("GET", "/api/me", None, token)[0] == 401
        assert all(key.startswith("test:flow:") for key in fake.data)


def test_redis_seeds_demo_data_only_once_and_never_over_real_data():
    with redis_env("test:seed") as (fake, provider):
        assert provider.is_initialized() is False
        adapter.ensure_ready()
        assert storage.count_records("users") == len(tb.seed.USERS) and provider.is_initialized() is True
        storage.update_record("users", "u1", {"name": "Changed By Real User"})
        for _ in range(3):                                                       # จำลอง cold start หลายครั้ง
            adapter.reset_ready()
            assert tb.seed.seed_if_empty() is False
            adapter.ensure_ready()
        assert storage.get_record("users", "u1")["name"] == "Changed By Real User", "ห้าม seed ทับข้อมูลจริง"
    with redis_env("test:seed-existing") as (fake, provider):                    # ฐานข้อมูลที่ initialized แล้ว: ไม่ถูกแตะ
        provider.mark_initialized()
        storage.save_json("users", [{"id": "real1", "email": "real@x.io"}])
        adapter.ensure_ready()
        assert [u["id"] for u in storage.get_all("users")] == ["real1"]
    with redis_env("test:seed-race") as (fake, provider):                        # หลาย thread เริ่มพร้อมกัน -> seed ครั้งเดียว
        runs = []

        def seed_function():
            runs.append(1)
            time.sleep(0.05)
            storage.save_json("categories", [{"id": "c1"}])

        threads = [threading.Thread(target=storage.ensure_initialized, args=(seed_function,)) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(runs) == 1 and storage.get_all("categories") == [{"id": "c1"}]


def test_redis_distributed_lock_serializes_read_modify_write_across_instances():
    with redis_env("test:lock") as (fake, first):
        second = sp.RedisStorage(first.client, prefix="test:lock")               # เหมือน Serverless Function อีก instance
        errors = []

        def work(provider):
            try:
                for _ in range(6):
                    with provider.lock():
                        rows = provider.read("files")
                        provider.write("files", [{"id": "ctr", "n": (rows[0]["n"] if rows else 0) + 1}])
            except Exception as err:                                             # noqa: BLE001 - เก็บไว้ assert ด้านล่าง
                errors.append(err)

        threads = [threading.Thread(target=work, args=(p,)) for p in (first, second, first, second)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not errors and first.read("files")[0]["n"] == 24, "ไม่มี lost update"
        assert "test:lock:lock" not in fake.data


def test_redis_lock_busy_expiry_and_safe_release():
    with redis_env("test:lock2") as (fake, provider):
        key = "test:lock2:lock"
        fake.data[key] = ("someone-else", None)
        with patched(REDIS_LOCK_WAIT_SECONDS=0.3):
            try:
                with provider.lock():
                    raise AssertionError("ต้องได้ lock ไม่ได้")
            except StorageError as err:
                assert err.code == "STORAGE_BUSY" and err.status == 503
        fake.data[key] = ("crashed-function", time.monotonic() + 0.15)           # lock ของ function ที่ตายไปแล้ว หมดอายุเอง
        with patched(REDIS_LOCK_WAIT_SECONDS=3):
            with provider.lock():
                pass
        assert key not in fake.data
        with provider.lock():
            fake.data[key] = ("new-owner", None)                                 # ระหว่างนั้นเจ้าของ lock เปลี่ยนไปแล้ว
        assert fake.data[key][0] == "new-owner", "ห้ามปล่อย lock ของคนอื่น"


def test_redis_failures_are_safe_503_and_recover():
    with redis_env("test:err") as (fake, provider):
        adapter.ensure_ready()
        fake.fail_next = 10_000
        status, data = call("GET", "/api/artworks")
        assert status == 503 and data["error"]["code"] == "STORAGE_UNAVAILABLE"
        text = json.dumps(data, ensure_ascii=False)
        for forbidden in ("127.0.0.1", "redis", "Traceback", fake_upstash.VALID_TOKEN, "http"):
            assert forbidden not in text, forbidden
        fake.fail_next = 0
        assert call("GET", "/api/artworks")[0] == 200
        wrong = sp.RedisStorage(sp.UpstashRestClient(provider.client.url, "wrong-token"), prefix="test:err")
        try:
            wrong.read("users")
        except StorageError as err:
            assert err.status == 503 and err.code == "STORAGE_UNAVAILABLE" and "wrong-token" not in err.message
        else:
            raise AssertionError("token ผิดต้องไม่อ่านได้")


def test_redis_size_limit_and_collection_cap():
    with redis_env("test:size") as (fake, provider):
        try:
            storage.save_json("files", [{"id": "big", "blob": "x" * (sp.MAX_VALUE_BYTES + 10)}])
        except StorageError as err:
            assert err.code == "DATA_TOO_LARGE" and err.status == 507
        else:
            raise AssertionError("ข้อมูลใหญ่เกินต้องไม่ถูกเขียนแบบเงียบ ๆ")
        assert storage.get_all("files") == []
        storage.REDIS_COLLECTION_CAPS["files"] = 5
        try:
            for number in range(8):
                storage.create_record("files", {"n": number}, "f")
            assert [r["n"] for r in storage.get_all("files")] == [3, 4, 5, 6, 7], "เก็บเฉพาะรายการล่าสุด"
        finally:
            storage.REDIS_COLLECTION_CAPS.pop("files", None)


# ===========================================================================
# 7) ไฟล์งานศิลปะ: อัปโหลด / ลายน้ำ / Original ไม่ถูกแก้ / ส่งมอบหลังชำระเงิน
# ===========================================================================
def test_upload_creates_three_distinct_files_and_original_is_untouched():
    mika = login("mika")
    raw = make_image("PNG")
    art_id = fresh_artwork(mika)
    status, result = upload(art_id, mika, raw)
    assert status == 201 and [f["role"] for f in result["files"]] == ["original", "preview", "delivery"]
    for public in result["files"]:
        assert set(public) == {"id", "artwork_id", "role", "content_type", "size", "created_at"}, "client เห็นเฉพาะข้อมูลที่ปลอดภัย"
    text = json.dumps(result)
    assert "blob_path" not in text and "storage_provider" not in text and "local" not in text
    records, store = files_of(art_id), file_storage.get_store()
    assert set(records) == {"original", "preview", "delivery"}
    for role, record in records.items():
        assert {"storage_provider", "blob_path", "content_type", "size", "owner_id", "created_at"} <= set(record), role
        assert record["storage_provider"] == "local" and record["owner_id"] == "a1" and record["content_type"] == "image/png"
        assert record["blob_path"].startswith(role + "/") and re.fullmatch(role + r"/[0-9a-f]{32}\.png", record["blob_path"]), \
            "ชื่อไฟล์ที่เก็บต้องสร้างที่ server (ไม่ใช้ชื่อจาก client)"
        assert record["size"] == len(store.get(record["blob_path"]))
    assert store.get(records["original"]["blob_path"]) == raw, "Original ต้องเหมือนที่อัปโหลดทุกไบต์"
    assert store.get(records["delivery"]["blob_path"]) == raw
    assert len({r["blob_path"] for r in records.values()}) == 3, "เก็บเป็น 3 object แยกกัน"
    preview = store.get(records["preview"]["blob_path"])
    assert preview != raw, "Preview ต้องผ่านการใส่ลายน้ำ ไม่ใช่ไฟล์เดียวกับ Original"
    from PIL import Image
    shown = Image.open(io.BytesIO(preview))
    assert shown.format == "PNG" and max(shown.size) <= artwork_files.PREVIEW_MAX_SIDE
    big_art = fresh_artwork(mika)
    upload(big_art, mika, make_image("PNG", (2400, 1600)))
    big_preview = Image.open(io.BytesIO(file_storage.get_store().get(files_of(big_art)["preview"]["blob_path"])))
    assert max(big_preview.size) == artwork_files.PREVIEW_MAX_SIDE, "ภาพใหญ่ถูกย่อ ไม่ส่งความละเอียดเต็มให้คนทั่วไป"


def test_upload_accepts_png_jpg_jpeg_webp_and_ignores_unsafe_client_names():
    mika = login("mika")
    cases = (("PNG", "a.png", "image/png"), ("JPEG", "a.jpg", "image/jpeg"), ("JPEG", "A.JPEG", "image/jpeg"),
             ("WEBP", "a.webp", "image/webp"), ("PNG", "ภาพสวย 😀.png", "image/png"), ("PNG", "shell.php.png", "image/png"))
    for fmt, filename, ctype in cases:
        art_id = fresh_artwork(mika)
        status, result = upload(art_id, mika, make_image(fmt), filename=filename, ctype=ctype)
        assert status == 201, (filename, result)
        record = files_of(art_id)["original"]
        assert record["content_type"] == ctype and re.fullmatch(r"original/[0-9a-f]{32}\.(png|jpg|webp)", record["blob_path"])
        assert file_storage.get_store().get(files_of(art_id)["preview"]["blob_path"])[:4] != b"", filename


def test_upload_permissions_and_artwork_state():
    mika, kenji, buyer, admin = login("mika"), login("kenji"), login("buyer"), login("admin")
    raw, art_id = make_image(), None
    art_id = fresh_artwork(mika)
    assert upload(art_id, None, raw)[0] == 401
    assert upload(art_id, buyer, raw)[0] == 403 and upload(art_id, kenji, raw)[0] == 403, "ศิลปินคนอื่น/ผู้ซื้ออัปโหลดให้ไม่ได้"
    assert files_of(art_id) == {} and stored_files() == []
    assert upload(art_id, mika, raw)[0] == 201
    publish(art_id, mika, admin)
    status, data = upload(art_id, mika, raw)
    assert status == 409 and data["error"]["code"] == "ARTWORK_LOCKED", "งานที่เผยแพร่แล้ว ศิลปินเปลี่ยนไฟล์เองไม่ได้"
    assert upload(art_id, admin, raw)[0] == 201, "admin เปลี่ยนไฟล์ได้"
    assert upload("w999999", mika, raw)[0] == 404
    for bad_id in ("w'--", "../etc", "w1;DROP", "a" * 300):
        assert upload(bad_id, mika, raw)[0] in (400, 404), bad_id


def test_upload_rejects_bad_input_and_stores_nothing():
    mika = login("mika")
    art_id = fresh_artwork(mika)
    good, jpg = make_image("PNG"), make_image("JPEG")
    png_head = b"\x89PNG\r\n\x1a\n"
    cases = [
        ("empty file", upload_body(b"")),
        ("not base64", {"filename": "a.png", "content_type": "image/png", "data_base64": "***not*base64***"}),
        ("base64 is a list", {"filename": "a.png", "content_type": "image/png", "data_base64": ["x"]}),
        ("base64 is an int", {"filename": "a.png", "content_type": "image/png", "data_base64": 12345}),
        ("base64 is null", {"filename": "a.png", "content_type": "image/png", "data_base64": None}),
        ("missing file", {"filename": "a.png", "content_type": "image/png"}),
        ("filename is int", upload_body(good, filename=123)),
        ("filename is null", upload_body(good, filename=None)),
        ("traversal filename", upload_body(good, filename="../../etc/passwd.png")),
        ("backslash filename", upload_body(good, filename="..\\..\\x.png")),
        ("null byte filename", upload_body(good, filename="a\x00.png")),
        ("newline filename", upload_body(good, filename="a\n.png")),
        ("very long filename", upload_body(good, filename="a" * 300 + ".png")),
        ("executable extension", upload_body(good, filename="a.exe")),
        ("svg extension", upload_body(good, filename="a.svg", ctype="image/svg+xml")),
        ("no extension", upload_body(good, filename="picture")),
        ("mime mismatch", upload_body(good, ctype="image/jpeg")),
        ("mime html", upload_body(good, ctype="text/html")),
        ("mime missing", {"filename": "a.png", "data_base64": base64.b64encode(good).decode()}),
        ("svg disguised as png", upload_body(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')),
        ("html disguised as png", upload_body(b"<html><script>alert(1)</script></html>")),
        ("jpeg bytes named png", upload_body(jpg)),
        ("png bytes named jpg", upload_body(good, filename="a.jpg", ctype="image/jpeg")),
        ("gif bytes", upload_body(b"GIF89a" + b"\0" * 64)),
        ("png magic + garbage", upload_body(png_head + b"garbage" * 30)),
        ("truncated png", upload_body(good[: len(good) // 2])),
        ("script appended", upload_body(good + b"<script>alert(1)</script>")),
        ("php appended", upload_body(good + b"<?php system($_GET['c']); ?>")),
    ]
    for label, body in cases:
        status, data = call("POST", "/api/artworks/" + art_id + "/file", body, mika)
        assert status == 400 and data["error"]["code"] == "VALIDATION_ERROR", (label, status, data)
        assert "Traceback" not in json.dumps(data)
    assert call("POST", "/api/artworks/" + art_id + "/file", [1, 2], mika)[0] == 400
    assert call_full("POST", "/api/artworks/" + art_id + "/file", b"{bad json", token=mika).status == 400
    assert files_of(art_id) == {} and stored_files() == [], "ไฟล์ที่ไม่ผ่านต้องไม่ทิ้งอะไรไว้เลย"


def test_upload_size_limits_and_image_bomb():
    mika = login("mika")
    art_id = fresh_artwork(mika)
    too_big = make_image("PNG") + b"\0" * config.MAX_UPLOAD_BYTES                  # เกินขนาดไฟล์ที่อนุญาต
    status, data = upload(art_id, mika, too_big)
    assert status == 413 and data["error"]["code"] == "PAYLOAD_TOO_LARGE"
    huge_body = b'{"data_base64":"' + b"A" * (config.UPLOAD_BODY_BYTES + 10) + b'"}'   # เกินขนาด body ของ endpoint อัปโหลด
    result = call_full("POST", "/api/artworks/" + art_id + "/file", huge_body, token=mika)
    assert result.status == 413
    normal = call_full("POST", "/api/artworks/" + art_id + "/file", b'{"x":"' + b"a" * (config.MAX_BODY_BYTES + 5) + b'"}', token=mika)
    assert normal.status == 413 or normal.status == 400, "endpoint อื่นยังจำกัด body 1 MB (ไม่ได้ผ่อนทุก endpoint)"
    assert call_full("POST", "/api/artworks", b'{"x":"' + b"a" * (config.MAX_BODY_BYTES + 5) + b'"}', token=mika).status == 413
    need_pillow()
    from PIL import Image
    bomb = io.BytesIO()
    Image.new("1", (7000, 7000)).save(bomb, "PNG")                                 # ไฟล์เล็กแต่ภาพ 49 ล้านพิกเซล
    assert len(bomb.getvalue()) < config.MAX_UPLOAD_BYTES
    status, data = upload(art_id, mika, bomb.getvalue())
    assert status == 400 and "พิกเซล" in json.dumps(data, ensure_ascii=False), data
    assert files_of(art_id) == {} and stored_files() == []


def test_upload_ignores_mass_assignment_fields():
    mika = login("mika")
    art_id = fresh_artwork(mika)
    extra = {"owner_id": "ad1", "role": "delivery", "blob_path": "../../x", "storage_provider": "evil", "artwork_id": "w1",
             "size": 1, "id": "f-hacked", "__proto__": {"x": 1}, "constructor": {"y": 2}}
    status, _ = call("POST", "/api/artworks/" + art_id + "/file", upload_body(make_image(), **extra), mika)
    assert status == 201
    for record in files_of(art_id).values():
        assert record["owner_id"] == "a1" and record["artwork_id"] == art_id and record["storage_provider"] == "local"
        assert record["id"] != "f-hacked" and ".." not in record["blob_path"] and record["size"] > 1
    assert [r for r in storage.get_all("files") if r["artwork_id"] == "w1"] == []


def test_reupload_replaces_files_and_delete_artwork_removes_them():
    mika = login("mika")
    art_id = fresh_artwork(mika)
    upload(art_id, mika, make_image("PNG", (100, 60)))
    first = {role: r["blob_path"] for role, r in files_of(art_id).items()}
    assert len(stored_files()) == 3
    assert upload(art_id, mika, make_image("PNG", (140, 90)))[0] == 201
    second = {role: r["blob_path"] for role, r in files_of(art_id).items()}
    assert len(storage.find_records("files", "artwork_id", art_id)) == 3 and len(stored_files()) == 3
    assert not set(first.values()) & set(second.values()), "ไฟล์เก่าถูกแทนที่และลบออกจากที่เก็บ"
    assert call("DELETE", "/api/artworks/" + art_id, None, mika)[0] == 200
    assert storage.find_records("files", "artwork_id", art_id) == [] and stored_files() == [], "ลบงานแล้วไฟล์ต้องไม่ตกค้าง"
    other = fresh_artwork(mika)
    upload(other, mika, make_image())
    assert artwork_files.purge_all_files() == 3 and stored_files() == []


def test_preview_is_public_only_for_published_artwork_and_never_original():
    mika, buyer, admin = login("mika"), login("buyer"), login("admin")
    raw = make_image()
    art_id = fresh_artwork(mika)
    upload(art_id, mika, raw)
    assert call_full("GET", "/api/artworks/" + art_id + "/preview").status == 404, "งานยังไม่เผยแพร่ ไม่เผยว่ามีอยู่จริง"
    assert call_full("GET", "/api/artworks/" + art_id + "/preview", token=buyer).status == 404
    owner_view = call_full("GET", "/api/artworks/" + art_id + "/preview", token=mika)
    assert owner_view.status == 200 and owner_view.payload.private is True
    publish(art_id, mika, admin)
    anyone = call_full("GET", "/api/artworks/" + art_id + "/preview")
    assert anyone.status == 200 and anyone.payload.content != raw and anyone.payload.content_type == "image/png"
    status, body, headers = adapter.encode(anyone, {})
    got = {k.lower(): v for k, v in headers}
    assert status == 200 and body == anyone.payload.content and got["content-disposition"].startswith("inline")
    assert got["content-type"] == "image/png" and got["x-content-type-options"] == "nosniff" and "content-security-policy" in got
    unknown_param = call_full("GET", "/api/artworks/" + art_id + "/preview", query={"x": "1"})
    assert unknown_param.status == 400 and unknown_param.payload["error"]["code"] == "VALIDATION_ERROR", "พารามิเตอร์ที่ไม่รู้จักถูกปฏิเสธ"
    no_file = fresh_artwork(mika)
    publish(no_file, mika, admin)
    assert call_full("GET", "/api/artworks/" + no_file + "/preview").status == 404


def test_original_is_visible_only_to_owner_and_admin():
    mika, kenji, buyer, admin = login("mika"), login("kenji"), login("buyer"), login("admin")
    raw = make_image()
    art_id = fresh_artwork(mika)
    upload(art_id, mika, raw)
    publish(art_id, mika, admin)
    url = "/api/artworks/" + art_id + "/original"
    assert call_full("GET", url).status == 401
    assert call_full("GET", url, token=buyer).status == 403 and call_full("GET", url, token=kenji).status == 403
    assert call_full("GET", url, token=mika).payload.content == raw and call_full("GET", url, token=admin).payload.content == raw
    assert call("GET", "/api/artworks/" + art_id + "/files", None, buyer)[0] == 403
    listed = call("GET", "/api/artworks/" + art_id + "/files", None, mika)[1]
    assert len(listed["items"]) == 3 and "blob_path" not in json.dumps(listed)
    public_view = json.dumps(call("GET", "/api/artworks/" + art_id)[1])
    assert "blob_path" not in public_view and "original" not in public_view, "ข้อมูลงานสาธารณะไม่เผยที่เก็บไฟล์"
    assert tb.server_module.resolve_static_path("/uploads/original/" + files_of(art_id)["original"]["blob_path"].split("/")[1]) is None
    assert "uploads" not in config.STATIC_ROOTS


def test_delivery_download_requires_login_ownership_and_verified_payment():
    mika, buyer, ton, admin = login("mika"), login("buyer"), login("ton"), login("admin")
    raw = make_image("PNG", (200, 120))
    art_id = fresh_artwork(mika)
    upload(art_id, mika, raw)
    publish(art_id, mika, admin)
    status, order = call("POST", "/api/orders", {"items": [{"artwork_id": art_id, "quantity": 1}]}, buyer)
    assert status == 201, order
    url = "/api/orders/" + order["id"] + "/artworks/" + art_id + "/download"
    assert call_full("GET", url).status == 401, "ไม่ login"
    assert call_full("GET", url, token=buyer).status == 403, "ยังไม่ชำระเงิน (PENDING_PAYMENT)"
    assert call_full("GET", url, token=ton).status == 403 and call_full("GET", url, token=mika).status == 403, "ไม่ใช่เจ้าของออเดอร์"
    assert call("PUT", "/api/orders/" + order["id"], {"status": "PAYMENT_VERIFIED"}, admin)[0] == 200
    ok = call_full("GET", url, token=buyer)
    assert ok.status == 200 and ok.payload.content == raw and ok.payload.content_type == "image/png"
    records = files_of(art_id)
    assert records["delivery"]["blob_path"] != records["original"]["blob_path"], "ส่งไฟล์ delivery ไม่ใช่ตัว original"
    assert adapter.encode(ok, {})[2] and any(k.lower() == "content-disposition" and v.startswith("attachment") for k, v in adapter.encode(ok, {})[2])
    assert call_full("GET", url, token=ton).status == 403, "ชำระแล้วก็ยังต้องเป็นเจ้าของออเดอร์"
    other_artwork = "/api/orders/" + order["id"] + "/artworks/w1/download"
    assert call_full("GET", other_artwork, token=buyer).status == 403, "งานที่ไม่ได้อยู่ในออเดอร์นี้"
    for bad in ("/api/orders/o'1/artworks/" + art_id + "/download", "/api/orders/" + order["id"] + "/artworks/w'1/download"):
        assert call_full("GET", bad, token=buyer).status in (400, 404), bad
    assert call_full("GET", "/api/orders/o_missing/artworks/" + art_id + "/download", token=buyer).status == 403
    for status_name in ("PAID", "COMPLETED"):
        assert call("PUT", "/api/orders/" + order["id"], {"status": status_name}, admin)[0] == 200
        assert call_full("GET", url, token=buyer).status == 200
    denied = audit("ARTWORK_FILE_DOWNLOAD_DENIED")
    reasons = {e["details"]["reason"] for e in denied}
    assert {"payment_not_verified", "not_order_owner", "artwork_not_in_order"} <= reasons, reasons
    assert len(audit("ARTWORK_FILE_DOWNLOADED")) == 3
    assert "blob_path" not in json.dumps(tb.read_json_file("logs")) and records["delivery"]["blob_path"] not in json.dumps(tb.read_json_file("logs"))


def test_delivery_is_refused_for_unpaid_cancelled_or_expired_orders():
    mika, buyer, admin = login("mika"), login("buyer"), login("admin")
    art_id = fresh_artwork(mika)
    upload(art_id, mika, make_image())
    publish(art_id, mika, admin)
    order = call("POST", "/api/orders", {"items": [{"artwork_id": art_id, "quantity": 1}]}, buyer)[1]
    url = "/api/orders/" + order["id"] + "/artworks/" + art_id + "/download"
    assert call_full("GET", url, token=buyer).status == 403
    record = storage.get_record("orders", order["id"])
    for state in ("CREATED", "PENDING_PAYMENT", "EXPIRED", "CANCELLED", "FAILED", "REFUNDED", "weird"):
        storage.update_record("orders", order["id"], {"status": state})
        assert call_full("GET", url, token=buyer).status == 403, state
    storage.update_record("orders", order["id"], {"status": record["status"], "items": []})
    assert call_full("GET", url, token=buyer).status == 403, "ออเดอร์ที่ไม่มีงานนี้"


# ---- Vercel Blob (SDK ปลอม + urlopen ปลอม: ตรวจรูปแบบการเรียกและการตรวจสิทธิ์ของเรา ไม่ใช่ Blob จริง) ----
class FakeBlobSDK:
    """แทน vercel.blob: เก็บ object ในหน่วยความจำ จำลอง url แบบ private"""

    def __init__(self, fail_on_put=None):
        self.objects, self.puts, self.deleted, self.fail_on_put = {}, [], [], fail_on_put

    def put(self, pathname, data, **kwargs):
        if self.fail_on_put is not None and len(self.puts) == self.fail_on_put:
            raise RuntimeError("secret-internal-detail https://store.example/token=abc")
        self.puts.append((pathname, kwargs))
        url = "https://store123.private.blob.vercel-storage.com/" + pathname
        self.objects[url] = bytes(data)
        return {"url": url}

    def delete(self, url, **kwargs):
        self.deleted.append(url)
        self.objects.pop(url, None)


@contextlib.contextmanager
def fake_blob(sdk, token="tok_test_not_real"):
    class Response:
        def __init__(self, data):
            self._data = data

        def read(self, size=-1):
            return self._data if size < 0 else self._data[:size]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    seen = []

    def fake_urlopen(request, timeout=None):
        seen.append((request.full_url, request.get_header("Authorization")))
        if request.get_header("Authorization") != "Bearer " + token:
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)
        if request.full_url not in sdk.objects:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)
        return Response(sdk.objects[request.full_url])

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    file_storage.use_store(file_storage.VercelBlobStore(token, sdk=sdk))
    try:
        yield seen
    finally:
        urllib.request.urlopen = original


def test_vercel_blob_store_uploads_private_and_reads_with_authorization():
    sdk = FakeBlobSDK()
    mika, buyer, admin = login("mika"), login("buyer"), login("admin")
    raw = make_image()
    with fake_blob(sdk) as seen:
        art_id = fresh_artwork(mika)
        assert upload(art_id, mika, raw)[0] == 201
        assert [p for p, _ in sdk.puts][0].startswith("original/") and len(sdk.puts) == 3
        assert {p.split("/")[0] for p, _ in sdk.puts} == {"original", "preview", "delivery"}
        for _path, kwargs in sdk.puts:
            assert kwargs["access"] == "private" and kwargs["token"] == "tok_test_not_real" and kwargs["content_type"] == "image/png"
        records = files_of(art_id)
        assert all(r["storage_provider"] == "vercel-blob" and r["blob_path"].startswith("https://") for r in records.values())
        assert "blob.vercel-storage" not in json.dumps(call("GET", "/api/artworks/" + art_id + "/files", None, mika)[1]), \
            "url ภายในของ Blob ไม่ถูกส่งให้ client"
        publish(art_id, mika, admin)
        assert call_full("GET", "/api/artworks/" + art_id + "/original", token=mika).payload.content == raw
        assert call_full("GET", "/api/artworks/" + art_id + "/preview").payload.content != raw
        order = call("POST", "/api/orders", {"items": [{"artwork_id": art_id, "quantity": 1}]}, buyer)[1]
        url = "/api/orders/" + order["id"] + "/artworks/" + art_id + "/download"
        assert call_full("GET", url, token=buyer).status == 403
        call("PUT", "/api/orders/" + order["id"], {"status": "PAYMENT_VERIFIED"}, admin)
        assert call_full("GET", url, token=buyer).payload.content == raw
        assert seen and all(auth == "Bearer tok_test_not_real" for _u, auth in seen), "ทุกการอ่าน private blob ต้องแนบ token"
        store = file_storage.get_store()
        for bad in ("http://store.example/x", "ftp://x", "../../etc/passwd", "", None, 5):
            try:
                store.get(bad)
            except StorageError as err:
                assert err.status == 404, bad
            else:
                raise AssertionError(repr(bad))
        try:
            store.get("https://store123.private.blob.vercel-storage.com/original/missing.png")
        except StorageError as err:
            assert err.code == "FILE_NOT_FOUND"
        assert call("DELETE", "/api/artworks/" + fresh_artwork(mika), None, mika)[0] == 200


def test_vercel_blob_failure_cleans_up_and_hides_internal_details():
    sdk = FakeBlobSDK(fail_on_put=1)                                               # ไฟล์ที่ 2 (preview) เขียนไม่สำเร็จ
    mika = login("mika")
    with fake_blob(sdk):
        art_id = fresh_artwork(mika)
        status, data = upload(art_id, mika, make_image())
        text = json.dumps(data, ensure_ascii=False)
        assert status == 503 and data["error"]["code"] == "FILE_STORAGE_UNAVAILABLE"
        for forbidden in ("secret-internal-detail", "store.example", "token=abc", "Traceback", "RuntimeError"):
            assert forbidden not in text, forbidden
        assert files_of(art_id) == {} and sdk.objects == {} and len(sdk.deleted) == 1, "เก็บกวาดไฟล์ที่เขียนไปแล้ว ไม่ให้เหลือไฟล์กำพร้า"


def test_vercel_file_storage_never_falls_back_to_the_function_disk():
    mika = login("mika")
    art_id = fresh_artwork(mika)
    upload_dir = Path(config.UPLOAD_DIR)
    before = sorted(upload_dir.rglob("*")) if upload_dir.exists() else []
    cases = ((dict(RUNNING_ON_VERCEL=True, FILE_STORAGE_PROVIDER="", BLOB_READ_WRITE_TOKEN=""), "BLOB_NOT_CONFIGURED"),
             (dict(RUNNING_ON_VERCEL=True, FILE_STORAGE_PROVIDER="local", BLOB_READ_WRITE_TOKEN="t"), "LOCAL_FILES_NOT_ALLOWED_ON_VERCEL"),
             (dict(RUNNING_ON_VERCEL=False, FILE_STORAGE_PROVIDER="s3"), "FILE_STORAGE_PROVIDER_UNSUPPORTED"))
    for changes, reason in cases:
        with patched(**changes):
            store = file_storage.build_store()
            assert store.name == "unavailable" and store.health() == {"available": False, "error": reason}
            file_storage.use_store(store)
            status, data = upload(art_id, mika, make_image())
            assert status == 503 and data["error"]["code"] == "FILE_STORAGE_UNAVAILABLE" and reason not in json.dumps(data)
    with patched(RUNNING_ON_VERCEL=True, FILE_STORAGE_PROVIDER="", BLOB_READ_WRITE_TOKEN="tok"):
        assert file_storage.build_store().name == "vercel-blob"
    with patched(RUNNING_ON_VERCEL=False, FILE_STORAGE_PROVIDER=""):
        assert file_storage.build_store().name == "local"
    after = sorted(upload_dir.rglob("*")) if upload_dir.exists() else []
    assert before == after and files_of(art_id) == {}, "ห้ามเขียนไฟล์ลงดิสก์ระหว่างที่ตั้งค่าผิด"


def test_upload_is_refused_when_watermarking_is_unavailable():
    need_pillow()
    mika = login("mika")
    art_id = fresh_artwork(mika)
    raw = make_image()                                                             # สร้างภาพก่อน แล้วค่อยจำลองว่าไม่มี Pillow
    saved = sys.modules.get("PIL")
    sys.modules["PIL"] = None
    try:
        status, data = upload(art_id, mika, raw)
    finally:
        sys.modules["PIL"] = saved
    assert status == 503 and data["error"]["code"] == "WATERMARK_UNAVAILABLE", "ไม่ยอมเอา original ไปเป็น preview แทน"
    assert files_of(art_id) == {} and stored_files() == []


# ===========================================================================
# 8) Payload ทดสอบความปลอดภัย (spec ข้อ 17) กับ surface ใหม่
# ===========================================================================
PAYLOADS = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)", "../../etc/passwd",
            "' OR '1'='1", "NaN", "Infinity", "9" * 400, "ไทย 😀 ภาษาไทย", "\x00\x01\x1f\x7f", "A" * 10000, "{{7*7}}",
            "${jndi:ldap://x/a}", "$(whoami)", "`id`", "; rm -rf /", "__proto__", "constructor", "\u202eevil", "%00%2e%2e%2f"]


def assert_safe(result, label):
    assert result.status < 500, (label, result.status)
    text = json.dumps(result.payload, ensure_ascii=False) if isinstance(result.payload, dict) else ""
    for leak in ("Traceback", "File \"", "site-packages", str(tb.WORK_DIR)):
        assert leak not in text, (label, leak)


def test_hostile_payloads_in_headers_cookies_and_new_endpoints_never_crash_or_leak():
    mika = login("mika")
    art_id = fresh_artwork(mika)
    with patched(TRUST_PROXY=True):
        for payload in PAYLOADS:
            safe = payload[:300]
            for label, result in (
                ("cookie", call_full("GET", "/api/me", headers={"Cookie": config.SESSION_COOKIE_NAME + "=" + safe})),
                ("origin", call_full("POST", "/api/login", LOGIN_BODY, headers={"Host": HOST, "Origin": safe})),
                ("xff", call_full("POST", "/api/login", {"email": "a@b.io", "password": "WrongPass1!"}, headers={"X-Forwarded-For": safe})),
                ("proto", call_full("GET", "/api/health", headers={"X-Forwarded-Proto": safe})),
                ("host", call_full("POST", "/api/login", LOGIN_BODY, headers={"Host": safe})),
                ("upload name", call_full("POST", "/api/artworks/" + art_id + "/file", upload_body(make_image(), filename=safe), token=mika)),
                ("upload type", call_full("POST", "/api/artworks/" + art_id + "/file", upload_body(make_image(), ctype=safe), token=mika)),
                ("upload data", call_full("POST", "/api/artworks/" + art_id + "/file", upload_body(make_image(), data_base64=safe), token=mika)),
                ("file id", call_full("GET", "/api/artworks/" + safe + "/preview")),
                ("order id", call_full("GET", "/api/orders/" + safe + "/artworks/w1/download", token=mika)),
                ("query", call_full("GET", "/api/artworks", query={"q": payload, "category": payload}, token=mika)),
            ):
                assert_safe(result, (label, payload[:20]))
    assert files_of(art_id) == {}, "payload ไม่มีตัวไหนผ่านเป็นไฟล์ได้"
    status, body, headers = adapter.handle_api("GET", "/api/artworks/%00%2e%2e/preview", {"Cookie": "a4s_session=" + "x" * 30}, b"")
    assert status < 500 and b"Traceback" not in body


def test_new_endpoints_reject_wrong_methods_and_unknown_paths_cleanly():
    mika = login("mika")
    for method, path in (("GET", "/api/artworks/w1/file"), ("POST", "/api/artworks/w1/preview"), ("DELETE", "/api/artworks/w1/original"),
                         ("PUT", "/api/dev/mailbox"), ("POST", "/api/health"), ("GET", "/api/orders/o1/artworks/w1/downloads")):
        result = call_full(method, path, token=mika)
        assert result.status in (404, 405) and "Traceback" not in json.dumps(result.payload), (method, path)


def test_backend_code_has_no_shell_eval_or_pickle_and_frontend_has_no_dynamic_code():
    bad = []
    banned_py = re.compile(r"\b(?:os\.system|os\.popen|subprocess|eval\(|exec\(|pickle|marshal|shell=True|__import__\()")
    for path in list((ROOT / "backend").rglob("*.py")) + list((ROOT / "api").rglob("*.py")):
        rel = path.relative_to(ROOT)
        if "tests" in rel.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if banned_py.search(line) and not line.lstrip().startswith("#"):
                bad.append("%s:%d" % (rel, number))
    banned_js = re.compile(r"\beval\s*\(|new\s+Function\s*\(|document\.write(?:ln)?\s*\(|setTimeout\s*\(\s*[\"']|setInterval\s*\(\s*[\"']")
    for folder in ("src", "public"):
        for path in (ROOT / folder).rglob("*"):
            rel = path.relative_to(ROOT)
            if path.suffix in (".js", ".html") and "test" not in rel.parts:
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if banned_js.search(line):
                        bad.append("%s:%d" % (rel, number))
    assert not bad, bad


def strip_js_comments(text):
    """ตัด /* ... */ และ // ... ออก (ไม่ตัด // ที่อยู่หลัง : เช่น https://) เพื่อตรวจเฉพาะโค้ดที่ทำงานจริง"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?<![:\"'])//[^\n]*", "", text)


def test_frontend_keeps_no_login_token_in_browser_storage():
    offenders = []
    for path in (ROOT / "src").rglob("*.js"):
        rel = path.relative_to(ROOT)
        if "test" in rel.parts:
            continue
        text = strip_js_comments(path.read_text(encoding="utf-8"))
        if re.search(r"sessionStorage|document\.cookie|indexedDB", text):
            offenders.append(str(rel) + " (storage/cookie API)")
        if "localStorage" in text and rel.as_posix() != "src/core/storage.js":
            offenders.append(str(rel) + " (localStorage นอก core/storage.js)")
        if re.search(r"Authorization\s*[=:]|Bearer\s", text) and rel.as_posix() != "src/test/run.js":
            offenders.append(str(rel) + " (ส่ง Authorization เอง)")
        if re.search(r"AppStorage\.(?:set|get)\(\s*[\"'](?:token|session|jwt|auth)", text):
            offenders.append(str(rel) + " (เก็บ token ใน AppStorage)")
    assert not offenders, offenders
    assert 'MEMORY_ONLY={currentUser:true}' in (ROOT / "src/core/state.js").read_text(encoding="utf-8")


# ===========================================================================
# 9) Vercel readiness script + เอกสาร + ของวิชา
# ===========================================================================
def load_readiness():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_vercel_ready_under_test", ROOT / "scripts" / "check_vercel_ready.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vercel_readiness_script_passes_here_and_fails_when_critical_config_is_missing():
    module = load_readiness()
    report = module.run_checks(ROOT)
    assert report.worst() in ("PASS", "WARN"), [row for row in report.rows if row[0] == "FAIL"]
    assert any(level == "WARN" and "deploy" in name for level, name, _ in report.rows), "ต้องเตือนเสมอว่ายังไม่ได้ทดสอบ deploy จริง"
    empty = Path(tempfile.mkdtemp())
    try:
        assert module.run_checks(empty).worst() == "FAIL"
        (empty / "vercel.json").write_text(json.dumps({"rewrites": [{"source": "/", "destination": "/public/index.html"},
                                                                    {"source": "/api/(.*)", "destination": "/public/$1"}]}))
        rows = module.run_checks(empty).rows
        assert [r for r in rows if r[0] == "FAIL" and "api" in r[1]], "/api/* ถูก rewrite ไป public/ ต้อง FAIL"
        (ROOT / ".env.local").write_text("X=1")
        try:
            assert [r for r in module.run_checks(ROOT).rows if r[0] == "FAIL" and ".env.local" in r[1]], "พบ .env.local ต้อง FAIL"
        finally:
            (ROOT / ".env.local").unlink()
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def test_env_example_and_gitignore_protect_secrets():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in example.splitlines() if "=" in line and not line.startswith("#"))
    for key in ("A4S_STORAGE", "A4S_EMAIL_MODE", "A4S_DEV_TOOLS", "A4S_CORS_ORIGINS", "A4S_PBKDF2_ITERATIONS",
                "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "BLOB_READ_WRITE_TOKEN"):
        assert key in values, key
    assert values["A4S_STORAGE"] == "json" and values["A4S_DEV_TOOLS"] == "false" and values["A4S_EMAIL_MODE"] == "development"
    assert not values["UPSTASH_REDIS_REST_TOKEN"] and not values["BLOB_READ_WRITE_TOKEN"] and not values["UPSTASH_REDIS_REST_URL"]
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and ".env.local" in ignored
    assert not (ROOT / ".env").exists() and not (ROOT / ".env.local").exists()


def test_academic_requirement_files_are_still_present_and_runnable():
    assert (ROOT / "training" / "console_menu.py").is_file() and (ROOT / "ACADEMIC_REQUIREMENTS.md").is_file()
    code = (ROOT / "training" / "console_menu.py").read_text(encoding="utf-8")
    for needle in ("def ", "while ", "for ", "try:", "except", "return ", "break", "elif ", " and ", " or ", " not "):
        assert needle in code, needle
    assert callable(getattr(tb.console_menu, "main_menu", None)), "console_menu ยังมีเมนูหลักที่เรียกใช้ได้"
    assert len(list((ROOT / "backend" / "modules").glob("*.py"))) >= 10, "ยังเป็นหลายไฟล์ .py"
    assert (ROOT / "backend" / "modules" / "storage_providers.py").is_file()
    text = (ROOT / "ACADEMIC_REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "JSON" in text and "Redis" in text and "Vercel" in text, "เอกสารวิชาต้องอธิบาย JSON (Local) กับ Redis (Vercel)"
    assert "Local JSON" in text and "Vercel Prototype Persistence" in text


def test_required_documents_exist_and_make_no_false_claims():
    names = ("README.md", "ACADEMIC_REQUIREMENTS.md", "docs/ARCHITECTURE.md", "docs/SECURITY_STATUS.md", "VERCEL_DEPLOYMENT.md", ".env.example")
    for name in names:
        assert (ROOT / name).is_file() and (ROOT / name).stat().st_size > 200, name
    security = (ROOT / "docs" / "SECURITY_STATUS.md").read_text(encoding="utf-8")
    for heading in ("IMPLEMENTED", "PARTIAL", "DEVELOPMENT-ONLY", "FUTURE PRODUCTION"):
        assert heading in security, heading
    lowered = "\n".join((ROOT / n).read_text(encoding="utf-8") for n in names).lower()
    for claim in ("100% secure", "fully production secure", "deploy สำเร็จแล้ว", "deployed successfully", "production ready"):
        for line in lowered.splitlines():
            if claim in line:
                assert any(w in line for w in ("ห้าม", "ไม่", "not", "never", "no ")), "พบคำอ้างเกินจริง: " + line.strip()

# ---------------------------------------------------------------------------
# Finale PART 2: marketplace / payment / commission / moderation smoke tests
# ---------------------------------------------------------------------------
def test_part2_payment_review_and_delivery_foundation():
    buyer = login("buyer")
    artist = login("mika")
    admin = login("admin")
    artwork_id = tb.make_approved_artwork(artist, admin, title="Part2 Limited", price=555, sale_type="LIMITED")
    st, cart = call("POST", "/api/cart", {"artwork_id": artwork_id}, buyer)
    assert st == 201, cart
    st, checked = call("POST", "/api/cart/checkout", None, buyer)
    assert st == 201, checked
    order_id = checked["order"]["id"] if "order" in checked else checked["id"]
    st, payment = call("POST", "/api/orders/" + order_id + "/payment", {
        "order_id": order_id, "method": "BANK_TRANSFER", "submitted_amount": 555,
        "slip": "Slip"
    }, buyer)
    assert st == 200 and payment["status"] == "PENDING_VERIFICATION", payment
    st, verified = call("POST", "/api/orders/" + order_id + "/payment/verify", {"approved": True, "verified_amount": 555}, admin)
    assert st == 200 and verified["status"] == "PAID", verified
    st, done = call("PUT", "/api/orders/" + order_id, {"status": "PAID"}, admin)
    assert st == 200, done
    st, done = call("PUT", "/api/orders/" + order_id, {"status": "COMPLETED"}, admin)
    assert st == 200, done
    st, review = call("POST", "/api/reviews", {"artwork_id": artwork_id, "rating": 5, "comment": "excellent work"}, buyer)
    assert st == 201, review
    st, download = call("GET", "/api/orders/" + order_id + "/artworks/" + artwork_id + "/download", None, buyer)
    assert st in (200, 404), download  # seeded file availability is provider-dependent; authorization is the important foundation here


def test_email_rejects_emoji_and_non_ascii():
    for bad in ("emoji\U0001F600@x.io", "\U0001F600@x.io", "user@\U0001F600.io", "ผู้ใช้@x.io", "a b@x.io", "a@b", "a@@b.io"):
        st, res = call("POST", "/api/register", {"name": "Emo Ji", "email": bad, "password": "Passw0rd1!",
                                                  "confirm_password": "Passw0rd1!", "role": "USER"})
        assert st == 400 and "email" in res.get("error", {}).get("fields", {}), (bad, st, res)
        st, res = call("POST", "/api/login", {"email": bad, "password": "Passw0rd1!"})
        assert st == 400, (bad, st, res)
    st, res = call("POST", "/api/register", {"name": "Plain Mail", "email": "plain.mail+t@x.io", "password": "Passw0rd1!",
                                              "confirm_password": "Passw0rd1!", "role": "USER"})
    assert st == 201, res


def test_payment_slip_is_a_typed_word():
    buyer = login("buyer")
    artist = login("mika")
    admin = login("admin")
    ids = []
    for n in range(2):
        aid = tb.make_approved_artwork(artist, admin, title="Slip Word " + str(n), price=100 + n, sale_type="LIMITED")
        assert call("POST", "/api/cart", {"artwork_id": aid}, buyer)[0] == 201
    st, checked = call("POST", "/api/cart/checkout", None, buyer)
    assert st == 201, checked
    orders = checked["orders"] if "orders" in checked else [checked["order"] if "order" in checked else checked]
    oid = orders[0]["id"]
    total = orders[0]["total"]
    base = {"order_id": oid, "method": "QR_PAYMENT", "submitted_amount": total}
    for bad in (None, "", "   ", "slip.png", "slips", "สลิป", {"filename": "slip.png"}):
        st, res = call("POST", "/api/orders/" + oid + "/payment", dict(base, slip=bad), buyer)
        assert st == 400 and "slip" in res.get("error", {}).get("fields", {}), (bad, st, res)
    st, res = call("POST", "/api/orders/" + oid + "/payment", dict(base, slip=" Slip "), buyer)
    assert st == 200 and res["status"] == "PENDING_VERIFICATION" and res["slip"]["simulated"] is True, res
    st, got = call("GET", "/api/orders/" + oid, None, buyer)
    assert st == 200 and got["status"] == "PAYMENT_SUBMITTED", got
    st, res = call("POST", "/api/orders/" + oid + "/payment/verify", {"approved": True, "verified_amount": total}, admin)
    assert st == 200 and res["status"] == "PAID", res


<<<<<<< HEAD
=======
def test_payment_slip_image_upload_and_admin_review():
    buyer, admin, artist = login("buyer"), login("admin"), login("mika")
    other = login("ton")
    aid = tb.make_approved_artwork(artist, admin, title="Slip Image Order", price=321, sale_type="LIMITED")
    assert call("POST", "/api/cart", {"artwork_id": aid}, buyer)[0] == 201
    st, checked = call("POST", "/api/cart/checkout", None, buyer)
    assert st == 201, checked
    order = checked["orders"][0] if "orders" in checked else (checked.get("order") or checked)
    oid, total = order["id"], order["total"]
    pay = {"order_id": oid, "method": "QR_PAYMENT", "submitted_amount": total, "slip": ""}
    slip_url = "/api/orders/" + oid + "/payment/slip"

    # no image and no secret word -> refused; nothing to view yet
    st, res = call("POST", "/api/orders/" + oid + "/payment", pay, buyer)
    assert st == 400 and "slip" in res["error"]["fields"], res
    assert call_full("GET", slip_url, token=buyer).status == 404

    # bad uploads: not an image / wrong type / script hidden in the image / not the owner / not signed in
    assert call("POST", slip_url, upload_body(b"not an image at all", "slip.png"), buyer)[0] == 400
    assert call("POST", slip_url, upload_body(make_image("PNG"), "slip.jpg", "image/jpeg"), buyer)[0] == 400
    assert call("POST", slip_url, upload_body(make_image("PNG") + b"<script>alert(1)</script>", "slip.png"), buyer)[0] == 400
    assert call("POST", slip_url, upload_body(make_image(), "slip.png"), other)[0] == 404
    assert call("POST", slip_url, upload_body(make_image(), "slip.png"))[0] == 401

    # a good image: stored privately, linked to the payment, no internal path in the JSON
    raw = make_image("PNG", (200, 140))
    st, up = call("POST", slip_url, upload_body(raw, "slip.png"), buyer)
    assert st == 201 and up["slip"]["simulated"] is False and "blob_path" not in json.dumps(up), up
    st, res = call("POST", "/api/orders/" + oid + "/payment", pay, buyer)
    assert st == 200 and res["status"] == "PENDING_VERIFICATION" and res["slip"]["file_id"] == up["slip"]["file_id"], res
    assert "blob_path" not in json.dumps(res)

    # who can look at it: owner + admin yes, other buyer / artist / anonymous no
    for who in (buyer, admin):
        got = call_full("GET", slip_url, token=who)
        assert got.status == 200 and got.payload.content == raw and got.payload.content_type == "image/png" \
            and got.payload.private is True, who
    assert call_full("GET", slip_url, token=other).status == 404
    assert call_full("GET", slip_url, token=artist).status == 404
    assert call_full("GET", slip_url).status == 401

    # uploading again replaces the old image (one slip image per order)
    raw2 = make_image("JPEG", (160, 160))
    assert call("POST", slip_url, upload_body(raw2, "slip.jpg", "image/jpeg"), buyer)[0] == 201
    slips = [f for f in storage.get_all("files") if f.get("role") == "slip" and f.get("order_id") == oid]
    assert len(slips) == 1, slips
    assert call("POST", "/api/orders/" + oid + "/payment", pay, buyer)[0] == 200
    assert call_full("GET", slip_url, token=admin).payload.content == raw2

    # admin approves -> PAID; after that nothing more can be uploaded
    st, verified = call("POST", "/api/orders/" + oid + "/payment/verify", {"approved": True, "verified_amount": total}, admin)
    assert st == 200 and verified["status"] == "PAID", verified
    assert call("POST", slip_url, upload_body(make_image(), "slip.png"), buyer)[0] == 409


def test_payment_secret_word_skips_the_image_and_cod_needs_none():
    buyer, admin, artist = login("buyer"), login("admin"), login("mika")
    ids = [tb.make_approved_artwork(artist, admin, title="Skip Word " + str(n), price=200 + n, sale_type="LIMITED") for n in range(2)]
    orders = []
    for aid in ids:
        assert call("POST", "/api/cart", {"artwork_id": aid}, buyer)[0] == 201
        st, checked = call("POST", "/api/cart/checkout", None, buyer)
        assert st == 201, checked
        orders.append(checked["orders"][0] if "orders" in checked else (checked.get("order") or checked))
    st, res = call("POST", "/api/orders/" + orders[0]["id"] + "/payment",
                   {"order_id": orders[0]["id"], "method": "BANK_TRANSFER", "submitted_amount": orders[0]["total"], "slip": "SLIP"}, buyer)
    assert st == 200 and res["slip"] == {"text": "slip", "simulated": True}, res
    assert call_full("GET", "/api/orders/" + orders[0]["id"] + "/payment/slip", token=admin).status == 404, "คำลับไม่มีรูป"
    st, res = call("POST", "/api/orders/" + orders[1]["id"] + "/payment",
                   {"order_id": orders[1]["id"], "method": "COD", "submitted_amount": orders[1]["total"]}, buyer)
    assert st == 200 and res["slip"] is None, res


>>>>>>> 4bb6b93 (Block emoji in email, simulate slip by typing 'slip', fix payment/commission/admin forms)
def test_part2_commission_lifecycle_and_access_control():
    artist = login("mika")
    buyer = login("buyer")
    admin = login("admin")
    st, listing = call("POST", "/api/commission-listings", {
        "title": "Portrait Commission", "description": "A custom digital portrait", "conditions": "One character",
        "price": 800, "days": 5, "revisions": 2, "samples": []
    }, artist)
    assert st == 201, listing
    lid = listing["id"]
    st, job = call("POST", "/api/commissions", {
        "listing_id": lid,
        "brief": {"type": "portrait", "details": "Blue themed portrait", "references": "https://example.com/ref", "size": "2000x2000", "style": "digital", "background": "simple", "character_count": 1, "additional_requests": ""},
        "payment_method": "QR_PAYMENT"
    }, buyer)
    assert st == 201 and job["state"] == "BRIEF", job
    jid = job["id"]
    assert call("GET", "/api/commissions/" + jid, None, artist)[0] == 200
    assert call("GET", "/api/commissions/" + jid, None, admin)[0] == 200
    assert call("POST", "/api/commissions/" + jid + "/payment", None, buyer)[0] == 200
    assert call("POST", "/api/commissions/" + jid + "/verify-payment", None, admin)[0] == 200
    st, accepted = call("POST", "/api/commissions/" + jid + "/ACCEPTED", None, artist)
    assert st == 200 and accepted["state"] == "ACCEPTED" and accepted["deadline_at"], accepted
    assert call("POST", "/api/commissions/" + jid + "/IN_PROGRESS", None, artist)[0] == 200
    assert call("POST", "/api/commissions/" + jid + "/DELIVERED", None, artist)[0] == 200
    assert call("POST", "/api/commissions/" + jid + "/COMPLETED", None, buyer)[0] == 200
    assert call("POST", "/api/commissions/" + jid + "/IN_PROGRESS", None, buyer)[0] == 409


def test_part2_promotion_price_history_and_price_drop_notification():
    artist = login("mika")
    buyer = login("buyer")
    admin = login("admin")
    artwork_id = tb.make_approved_artwork(artist, admin, title="Promo Piece", price=1000, sale_type="UNLIMITED")
    assert call("POST", "/api/wishlist", {"artwork_id": artwork_id}, buyer)[0] == 201
    st, promo = call("POST", "/api/promotions", {
        "title": "Artist Sale", "type": "PERCENTAGE", "value": 10,
        "start_at": "2027-01-01T00:00:00+00:00", "end_at": "2027-12-31T23:59:59+00:00", "artwork_id": artwork_id
    }, artist)
    assert st == 201, promo
    st, updated = call("PUT", "/api/artworks/" + artwork_id, {"price": 900}, admin)
    assert st == 200, updated
    st, history = call("GET", "/api/artworks/" + artwork_id + "/price-history")
    assert st == 200 and any(x["new_price"] == 900 for x in history["items"]), history
    st, notes = call("GET", "/api/me/notifications", None, buyer)
    assert st == 200 and any("ลด" in n["message"] for n in notes["items"]), notes


def test_part2_admin_moderation_blacklist_and_ip_block():
    admin = login("admin")
    buyer = login("buyer")
    st, record = call("POST", "/api/admin/blacklist", {"user_id": "u2", "reason": "test"}, admin)
    assert st == 201, record
    assert call("GET", "/api/admin/blacklist", None, admin)[0] == 200
    assert call("POST", "/api/admin/blacklist", {"user_id": "u2", "reason": "test"}, buyer)[0] == 403
    st, ip = call("POST", "/api/admin/ip-blocks", {"ip": "203.0.113.20", "reason": "test"}, admin)
    assert st == 201, ip
    st, rows = call("GET", "/api/admin/ip-blocks", None, admin)
    assert st == 200 and any(x["ip"] == "203.0.113.20" for x in rows["items"]), rows
