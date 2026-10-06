# PHASE_3_5.md - Authentication, Per-User Data, Password Recovery, Admin Data Management, Input Security

> ต่อยอดจาก Phase 3 (ไม่ได้เขียนระบบ login / backend ใหม่) ผลทดสอบ: `python backend/tests/test_backend.py` → **109/109 ผ่าน**

## 1. สถาปัตยกรรมก่อนแก้ (ที่ตรวจพบ) และสิ่งที่ทำ

| หัวข้อที่ spec ให้ตรวจ | พบอะไร | การตัดสินใจ |
|---|---|---|
| Login / Session / Token | `auth.py`: token สุ่ม ส่งผ่าน `Authorization: Bearer`, เก็บเฉพาะ hash ใน `sessions.json`, อายุ 12 ชม. | **ใช้ต่อทั้งหมด** |
| Password hashing | PBKDF2-SHA256 + salt (`security.py`) | **ใช้ต่อ** (OTP, เปลี่ยนรหัส, รีเซ็ตใช้ตัวเดียวกัน ไม่มีอัลกอริทึมใหม่) |
| Cart / Wishlist / Follow | **เก็บใน `localStorage` ด้วย key กลาง ไม่ผูก user และไม่ต้อง login** (user คนที่ 2 บนเครื่องเดียวกันเห็นของคนแรก) | ย้ายไป backend ผูก `user_id` และต้อง login |
| Notification | ไม่มีเลย | เพิ่มโครงขั้นต่ำ (ของใคร คนนั้นดู) |
| Storage | `storage.py` ชั้นกลางเดียว | ใช้ต่อ เพิ่ม collection ใหม่ + `delete_where` + `transaction` |
| Routing / Admin permission / Audit | `api.py` route table, `permissions.py`, `logger.py` | ใช้ต่อ เพิ่ม route / สิทธิ์ / action ใหม่ และช่อง `result` ใน audit |
| Seed / Reset | `seed.py` มี `seed_all()` | **ใช้ซ้ำ** สำหรับ Reset Demo Data (เพิ่มพารามิเตอร์เก็บ admin/log/session) |
| Validation | `validation.py` (Phase 3) | ใช้ต่อ + เข้มขึ้น (ดูหัวข้อ 6) |
| Frontend state | `A4S.api` facade (remote / mock) | ใช้ต่อ เพิ่ม `A4S.priv` (หน่วยความจำเท่านั้น) |
| **ช่องโหว่ที่พบในโค้ด Phase 3 เอง** | (1) `admin.html?tab=<payload>` ถูกพิมพ์กลับลง HTML (reflected XSS) (2) `avatar()` ใส่อักษรแรกของชื่อโดยไม่ escape (3) ตรวจรูปแบบด้วย regex `$` ทำให้ id/อีเมลที่มี `\n` ต่อท้ายผ่านได้ (4) `title: 123` / `["a"]` ถูกแปลงเป็นข้อความเงียบ ๆ (5) JSON ซ้อนลึก/เลขใหญ่ → 500 | แก้ทั้งหมด + มี test กันย้อนกลับ |

## 2. ข้อมูลส่วนตัวรายผู้ใช้ (ข้อ 3-11)

กฎ: **ไม่ login = ทำอะไรกับข้อมูลส่วนตัวไม่ได้ (401) และไม่มีข้อมูลถูกสร้าง** ไม่มี anonymous cart/wishlist และไม่มี merge

| ข้อมูล | ไฟล์ | Endpoint | กติกาที่ backend บังคับ |
|---|---|---|---|
| Cart | `modules/cart.py` → `carts.json` | `GET/POST/DELETE /api/cart`, `PUT/DELETE /api/cart/:id`, `POST /api/cart/checkout` | งานต้องมีอยู่จริง/อนุมัติแล้ว/ยังซื้อได้/ไม่ใช่งานตัวเอง, LIMITED = 1 ชิ้น, ราคารวมคำนวณที่ server, checkout ใช้ตะกร้าบน server |
| Wishlist | `modules/wishlist.py` → `wishlists.json` | `GET/POST /api/wishlist`, `DELETE /api/wishlist/:id` | กัน record ซ้ำ `(user_id, artwork_id)` (เพิ่มซ้ำ = ไม่สร้างใหม่) |
| Follow | `modules/follow.py` → `follows.json` | `GET/POST /api/follows`, `DELETE /api/follows/:id` | กันซ้ำ `(user_id, artist_id)`, ติดตามตัวเองไม่ได้, ต้องเป็นศิลปินที่ใช้งานอยู่ |
| Notifications | `modules/notification.py` → `notifications.json` | `GET /api/me/notifications`, `PUT /api/me/notifications/:id`, `POST /api/me/notifications/read-all` | สร้างอัตโนมัติเมื่อ admin อนุมัติ/ปฏิเสธงาน และเมื่อสถานะ order เปลี่ยน |

- **เจ้าของมาจาก session เสมอ**: `user_id`, `role`, `is_admin`, `price` ที่ client ส่งมาถูกทิ้ง (`validation.pick_fields`)
- **ของคนอื่น**: `permissions.get_owned_record()` → ไม่มี record = 404, เป็นของคนอื่น = **403**, id รูปแบบผิด = 400
- **Race condition**: ตรวจ+เขียนอยู่ใน `storage.transaction()` (ทดสอบแล้ว: ซื้องาน LIMITED พร้อมกัน 8 request ได้ 1 คน)
- **Dependency**: ลบงาน → ล้างตะกร้า/wishlist ที่ชี้งานนั้น, ลบ user → ล้างข้อมูลส่วนตัวทั้งหมดของเขา (`references.py`)

### ฝั่ง frontend (ข้อ 8-9)
```
Login สำเร็จ → A4S.priv.load() → โหลด cart / wishlist / follows / unread จาก server (ตาม token)
Logout / 401 / เปลี่ยน user → A4S.priv.clear()
```
- `A4S.priv` อยู่ใน **หน่วยความจำอย่างเดียว** ไม่เขียน localStorage/sessionStorage (มี test ตรวจ)
- ทุกหน้าโหลดใหม่ → ถามจาก server ตาม token ปัจจุบัน จึงไม่มีข้อมูล user ก่อนหน้าค้าง
- กดปุ่ม private ตอนยังไม่ login → แจ้ง "กรุณาเข้าสู่ระบบก่อนจึงสามารถใช้ฟังก์ชันนี้ได้" แล้วพาไป `login.html?next=<หน้าเดิม>` (รับเฉพาะชื่อหน้า `*.html` ของเว็บเอง กัน open redirect) **ไม่จดจำ action ที่ค้างไว้**
- หน้า Cart / Wishlist / Notifications / Settings ตอนยังไม่ login แสดงข้อความให้ login (ไม่สร้างอะไร)
- โหมด MOCK (backend ไม่ตอบ): เก็บข้อมูลส่วนตัวแยกตาม user id (`mock_cart_u1`) และไม่เก็บอะไรให้ผู้เยี่ยมชม

## 3. เปลี่ยนรหัสผ่าน (ข้อ 12-14, 22-23) `modules/password.py`

`POST /api/auth/change-password` `{current_password, new_password, confirm_password}` (ต้อง login)

ลำดับการตรวจ: **cooldown → ชนิดข้อมูล/นโยบาย/ยืนยัน → รหัสเดิมถูก → รหัสใหม่ไม่ซ้ำรหัสเดิม**
- cooldown 30 วัน (`config.PASSWORD_CHANGE_COOLDOWN_DAYS`) คำนวณจาก `password_changed_at` จริง → ตอบ 429 + ข้อความ "สามารถเปลี่ยนรหัสผ่านได้อีกครั้ง: 2 November 2026" (วันที่ UTC ไม่ hard-code) และมี `details.available_at`
- ตรวจ cooldown ก่อนตรวจรหัสเดิม: session ที่ถูกขโมยจะลองเดารหัสเดิมผ่าน endpoint นี้ไม่ได้ในช่วง cooldown
- สำเร็จ: ตัด session อื่นของ user (session ที่ใช้เปลี่ยนยังอยู่), บันทึก `PASSWORD_CHANGE_SUCCESS`
- รหัสผ่านไม่ถูก strip / sanitize (ช่องว่างและอักขระพิเศษเป็นส่วนหนึ่งของรหัส) มี test

## 4. ลืมรหัสผ่านด้วย OTP (ข้อ 15-23)

```
POST /api/auth/forgot-password  {email}              → OTP_PENDING   (อีเมลเดียวกันขอซ้ำ = POST /api/auth/resend-reset-code)
POST /api/auth/verify-reset-code {email, code}       → OTP_VERIFIED  → ได้ reset_token (RESET_AUTHORIZED)
POST /api/auth/reset-password    {reset_token, new_password, confirm_password}  → PASSWORD_RESET
```

| ข้อกำหนด | ทำอย่างไร |
|---|---|
| ไม่ติด cooldown | cooldown อยู่ใน `change_password()` เท่านั้น (test: เพิ่งเปลี่ยนรหัส แล้วกู้บัญชีได้) |
| กัน email enumeration | `forgot`/`resend` ตอบ **ข้อความเดียวกันทุกตัวอักษร** ไม่ว่ามีบัญชีหรือไม่ (มี test เทียบตรง ๆ); ขอบ่อยเกิน = 429 เหมือนกันทั้งสองกรณี; อีเมลที่ไม่มีก็ hash dummy ให้เวลาใกล้เคียง; verify ผิดทุกกรณีตอบข้อความเดียวกัน |
| OTP | 5 หลัก, `secrets.randbelow` (cryptographic), อายุ 10 นาที, ใช้ครั้งเดียว, ผิดได้ 5 ครั้งแล้วยกเลิก |
| เก็บ OTP | เก็บเฉพาะ `otp_hash` (PBKDF2 ตัวเดียวกับรหัสผ่าน + salt) ไม่ส่งใน API ไม่อยู่ใน log ไม่อยู่ในไฟล์ข้อมูล ไม่อยู่ใน localStorage (มี test ไล่ตรวจ) |
| Rate limit | ขอรหัสได้ทุก 60 วินาที และไม่เกิน 5 ครั้ง/ชั่วโมง ต่ออีเมล (นับจาก hash ของอีเมล) ค่าอยู่ใน `config.py` |
| Reset authorization | token สุ่ม ใช้ครั้งเดียว อายุ 15 นาที เก็บเฉพาะ hash; เรียก `reset-password` โดยไม่ผ่าน OTP ไม่ได้; รหัสใหม่ไม่ผ่านนโยบายยังไม่ใช้ token |
| หลัง reset | ทุก session ของ user ถูกลบ (ต้อง login ใหม่), OTP/token ที่เหลือถูกยกเลิก |
| Email abstraction | `modules/email_service.py` → `send_password_reset_code()`; `EMAIL_MODE="development"` พิมพ์อีเมลลง **หน้าจอ server** พร้อมป้าย `[DEV ONLY - EMAIL NOT SENT]` (ไม่ผ่าน logger จึงไม่เข้า `server.log`); โหมดอื่นที่ยังไม่มี provider จะไม่ส่งและไม่ crash; ไม่มี SMTP password/API key ในโค้ด |

**ลองเอง:** รัน `python backend/server.py` → เปิด `forgot.html` → กรอก `buyer@art4sells.test` → ดูรหัส 5 หลักในหน้าจอที่รัน server → กรอกรหัส → ตั้งรหัสใหม่

Audit log: `PASSWORD_CHANGE_SUCCESS`, `PASSWORD_CHANGE_FAILED`, `PASSWORD_CHANGE_REJECTED_COOLDOWN`, `PASSWORD_RESET_REQUESTED`, `PASSWORD_RESET_OTP_VERIFIED`, `PASSWORD_RESET_SUCCESS`, `PASSWORD_RESET_FAILED`, `OTP_INVALID`, `OTP_EXPIRED`, `OTP_RATE_LIMITED` (ทุกรายการมีช่อง `result`; ไม่มีรหัสผ่าน/OTP ใน log)

## 5. Admin Data Management (ข้อ 24-29) `modules/data_management.py`

แท็บ **Data Management** ในหน้า Admin (ADMIN เท่านั้น สิทธิ์ `data.manage`)

**สองขั้นตอนที่ server บังคับเอง** (ไม่ใช่แค่หน้าเว็บ):
1. `POST /api/admin/data/clear/preview` `{scopes, preserve_admins}` → สรุปจำนวนที่จะลบ + scope ที่ต้องลบตามกัน + `confirm_token` (ใช้ครั้งเดียว อายุ 5 นาที ผูกกับ admin คนนั้น + รายการที่เลือกพอดี)
2. `POST /api/admin/data/clear` ต้องส่ง `confirm_token` + `confirm_text: "CLEAR"` (ตรงเป๊ะ); ถ้าเลือก Audit Logs ต้องพิมพ์ `CLEAR AUDIT LOGS` เพิ่ม
(Reset Demo Data: `.../reset/preview` และ `.../reset` พิมพ์ `RESET`)

**Dependency** (ล้าง scope ซ้าย ต้องล้างขวาตาม แสดงใน preview ว่า "ถูกเพิ่มอัตโนมัติ"):
```
users      → artworks, orders, reviews, cart, wishlist, follows, notifications
categories → artworks
artworks   → orders, reviews, cart, wishlist        orders → reviews
```
ลำดับการเขียนไฟล์: ข้อมูลที่อ้างอิงคนอื่นก่อน (ถ้าหยุดกลางคันก็ไม่เกิด orphan)

**ความปลอดภัย:** Preserve Admin Accounts เปิดไว้เป็นค่าเริ่มต้น · ปิดได้ แต่ **admin ที่กำลังใช้งานไม่ถูกลบเด็ดขาด** (กันล็อกตัวเองออก) · Preserve System Configuration เป็นสถานะคงที่ (การตั้งค่าอยู่ใน `config.py` ไม่ใช่ข้อมูล) · บันทึก `ADMIN_DATA_CLEAR` / `ADMIN_DATA_RESET` **ก่อนลบ** และ log ของการกระทำนี้ไม่ถูกลบแม้เลือกล้าง Audit Logs · เขียน log ไม่ได้ = ไม่ลบ

**Reset Demo Data** ใช้ `seed.seed_all()` ตัวเดิม (ไม่คัดลอกข้อมูลตัวอย่างซ้ำ) เก็บ Audit Log, admin (ตาม preserve) และ session ของ admin ไว้

## 6. Input validation / Security ทั่วทั้งระบบ (ข้อ 31-50)

ทุกอย่างจาก client = untrusted; frontend ตรวจเพื่อ UX, **backend ตรวจเป็นด่านความปลอดภัย** (`modules/validation.py` ที่เดียว)

| หัวข้อใน spec | ที่อยู่ในโค้ด |
|---|---|
| validate_string / required / length | `check_text()` (ชนิดต้องเป็น str จริง ตัวเลข/list/dict ไม่ถูกแปลงเงียบ ๆ, จำกัดความยาว, ห้ามอักขระควบคุมและตัวควบคุมทิศทางข้อความ, ช่องหลายบรรทัดอนุญาตเฉพาะ `\n \r \t`) |
| normalization (เฉพาะช่อง) | `clean_text()` = Unicode NFC + trim ใช้กับชื่อ/ชื่องาน/คำอธิบาย/รีวิว **ไม่แก้สัญลักษณ์/HTML/ภาษาไทย/emoji ที่ผู้ใช้พิมพ์** และ **ไม่แตะรหัสผ่าน** |
| validate_integer / float / boolean / price | `to_int()`, `to_float()`, `to_bool()`, `validate_artwork()` (finite, ไม่ NaN/Infinity/ติดลบ, ≤ 1,000,000, ปัด 2 ตำแหน่ง); JSON `NaN`/`Infinity` ถูกปฏิเสธตั้งแต่ตอน parse |
| validate_email / password | `validate_email()`, `validate_password()` (ตรวจความยาว/ชนิด; ใช้ `fullmatch` เพราะ `$` ยอมให้มี `\n` ต่อท้าย) |
| validate_choice / allowlist | `validate_choice()`, `config.SORT_OPTIONS`, `SEARCH_FIELDS`, `ROLES`... (ไม่ใช้ blacklist เป็นด่านหลัก) |
| validate_id | `validate_id()` ใช้กับ **ทุก id ใน path / query (`*_id`) / body** ก่อนค้นข้อมูล (`api.check_request_inputs`) |
| validate_url | `validate_url()` (http/https เท่านั้น กัน `javascript:` `data:`) เตรียมไว้ใช้ภายหลัง |
| query / search / pagination | endpoint ที่ไม่รับ query ปฏิเสธพารามิเตอร์แปลก ๆ; `q` ≤ 100 ตัวอักษร; ค่าใน query ≤ 200 ตัวอักษรและไม่มีอักขระควบคุม; `page_size` ≤ 50; `sort` เป็น allowlist |
| Mass assignment | `pick_fields()` (allowlist ต่อ endpoint) + `update_artwork` ใช้ `EDITABLE_FIELDS`; `role/is_admin/permissions/user_id/status` ที่ client ส่งมาถูกทิ้ง (ส่ง `"true"` เป็นข้อความก็ไม่มีผล) |
| JSON / injection | ไม่ต่อ string เป็น JSON (ใช้ `json.dump`); อ่านไฟล์แล้วตรวจโครงสร้าง; ไม่มี `os.system / subprocess / eval / exec / pickle` (test สแกนโค้ดให้อัตโนมัติ); JSON ซ้อนลึก/เลขใหญ่/ไม่ใช่ UTF-8 = 400 |
| Path traversal / upload | `server.resolve_static_path()` (ให้เปิดได้แค่ `public/`, `src/`), `modules/uploads.py`: `validate_upload_metadata()` (นามสกุล+Content-Type+ขนาดจาก allowlist), `safe_server_filename()` (ชื่อสุ่มเอง), `safe_join()` — เป็น **foundation** ยังไม่มี endpoint อัปโหลดจริง |
| Error leakage | `AppError` ข้อความภาษาไทย, `INTERNAL_ERROR` ข้อความกลาง (traceback อยู่ใน `backend/logs/server.log`), หน้า error ของ `http.server` ถูกแทนด้วย JSON กลาง ๆ (test ยิง request พัง 6 แบบ) |

### XSS (ข้อ 36-37)
- ข้อความจากผู้ใช้เป็น **plain text** เสมอ (Artwork / Review / ชื่อศิลปิน / คำอธิบาย) ไม่รับ HTML
- ข้อความ error/toast ใช้ `textContent`; หน้าที่ประกอบ HTML เป็น string ทุกค่าที่มาจากผู้ใช้ผ่าน `A4S.ui.esc()` (escape `& < > " '`) และ `U.cls()` สำหรับ class
- **Reflected XSS**: `?tab=` ของหน้า Admin เป็น allowlist, `?id=`/`?artist=` ส่งเข้า API เท่านั้นไม่ถูกพิมพ์กลับ, `?next=` รับเฉพาะชื่อหน้าในเว็บ
- **CSP** (ทุก response): `script-src 'self'` ไม่มี inline script / eval → ถ้ามีช่องโหว่หลุด เบราว์เซอร์ก็ไม่รัน script แทรก (ทดสอบในเบราว์เซอร์จริงว่าไม่มี violation)
- **test อัตโนมัติ** (`test_frontend_source_has_no_dangerous_sinks`): ห้ามมี `eval`, `new Function`, `document.write`, `insertAdjacentHTML`, `outerHTML`, `javascript:`, inline `onclick=`, `<script>` แทรกใน HTML; `innerHTML` ใช้ได้เฉพาะ 3 ไฟล์ที่ผ่านการ escape
- ผมยังทดสอบด้วยเบราว์เซอร์จริงว่า payload `<img onerror>`, `<svg onload>`, `<script>` ในชื่องาน/ชื่อผู้ใช้/คำอธิบาย/tag ไม่ทำงานและแสดงเป็นข้อความ (ชุดทดสอบนี้ใช้ headless Chrome จึงไม่ได้ใส่ใน zip)

### CSRF (ข้อ 51) - สถานะ: Partially Implemented
- **ตรวจแล้ว**: การยืนยันตัวตนใช้ header `Authorization: Bearer` (ไม่ใช่ cookie / session cookie) → เบราว์เซอร์ไม่แนบ credential ให้เองเมื่อเว็บอื่นยิงมา จึงไม่เสี่ยง CSRF แบบคลาสสิก และ **ไม่ได้เพิ่ม CSRF token** (ไม่จำเป็นกับสถาปัตยกรรมนี้ และไม่ทำให้ระบบ login เดิมเสีย)
- **ชั้นเสริมที่ทำแล้ว**: (1) POST/PUT ที่มี body ต้อง `Content-Type: application/json` (ไม่งั้น 415) (2) `api.check_origin()` ปฏิเสธคำขอที่เปลี่ยนข้อมูลซึ่ง `Origin` ไม่ใช่เว็บเดียวกับ `Host` และไม่อยู่ใน `A4S_CORS_ORIGINS` (403) ; ไม่มี Origin (curl/โปรแกรมอื่น) ผ่านตามปกติ (3) CORS ปิดเป็นค่าเริ่มต้น (4) CSP `form-action 'self'`, `frame-ancestors 'none'`
- **CORS ไม่ใช่ CSRF protection** (CORS ควบคุมว่าเว็บอื่น "อ่านคำตอบ" ได้หรือไม่ ไม่ได้ป้องกันการ "ส่งคำขอ")
- **ยังไม่ใช่ production-ready**: ถ้าเปลี่ยนไปใช้ cookie session ต้องเพิ่ม CSRF token + `SameSite` + `HttpOnly` + `Secure` ก่อน (ดู `docs/SECURITY_STATUS.md`)

### Security headers (ข้อ 52)
ตรวจแล้วว่าทุกหน้า HTML **ไม่มี inline script** (มี test) จึงใช้ CSP `script-src 'self'` ได้โดยไม่ทำให้ระบบพัง ; `style-src` ยังต้องมี `'unsafe-inline'` (หน้าเว็บใช้ `style="..."`) = Partial ; มี `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy` ; HSTS ยังไม่ใส่เพราะยังไม่มี HTTPS (Future Production Requirement)

### File upload (ข้อ 53) - สถานะ: Partially Implemented (foundation)
ระบบยังไม่มีการอัปโหลดไฟล์จริง จึงเตรียม `modules/uploads.py` ไว้และมี test: ไม่เชื่อชื่อไฟล์/นามสกุล/Content-Type ที่ client ส่งมา → ตรวจนามสกุลจาก allowlist + Content-Type ต้องตรงนามสกุล + ขนาด + **ไบต์จริงของไฟล์** (PNG/JPEG/WEBP) ต้องตรงกับนามสกุล + ไม่มีเครื่องหมายโค้ดแฝง (`<?php`, `<script`, `#!/` ฯลฯ) ; ชื่อไฟล์ที่เก็บ server สร้างเอง ; เปิดไฟล์แบบสร้างใหม่และปิดสิทธิ์ execute ; **ไม่ใช่การสแกนมัลแวร์** และไม่ได้อ้างว่าอัปโหลดปลอดภัย 100%

## 7. ข้อสมมติ / การตัดสินใจที่ spec ไม่ได้ระบุ (โปรดยืนยัน)
1. **Reset password ไม่เริ่มนับ cooldown 30 วัน** (ใช้ `password_reset_at` แยก) — cooldown นับเฉพาะ "เปลี่ยนรหัสผ่าน"
2. **Wishlist**: เพิ่มได้เฉพาะงาน APPROVED ที่ยังไม่ SOLD (งานที่มีคนกำลังจ่ายเงินยังกดโปรดได้); **Cart**: ต้องซื้อได้จริง ณ ตอนนั้น (ไม่ SOLD ไม่ถูกล็อก)
3. Admin ไม่มีตะกร้า (ไม่มีสิทธิ์ `cart.use`) แต่มี wishlist/follow/notification
4. ของคนอื่นตอบ **403** (ตาม spec) ส่วน order/review เดิมยังตอบ 404 เพื่อไม่เผยว่ามี id นั้น
5. ปิด Preserve Admin Accounts ได้ แต่ admin ที่ใช้งานอยู่ถูกกันไว้เสมอ
6. Rate limit การขอ OTP นับต่ออีเมล (ยังไม่นับต่อ IP เพราะชั้น `api.handle_request` ไม่รับ IP; ทำใน Phase Security)

## 8. ยังไม่ได้ทำ / ข้อจำกัด
- ไม่มี rate limit/lockout ของ **login** และ **change-password** (spec ขอเฉพาะการส่งรหัส) → Phase Security
- ไม่มีผู้ให้บริการอีเมลจริง (dev mode เท่านั้น) และยังไม่มี endpoint อัปโหลดไฟล์จริง (มีแต่ foundation + test)
- JSON ไม่มี multi-file transaction: การล้างข้อมูลหลายไฟล์ถ้าไฟดับกลางคันอาจเหลือบางไฟล์ลบแล้ว (ลำดับการลบออกแบบให้ไม่เกิด orphan แต่ไม่ใช่ atomic)
- ล็อกอยู่ใน process เดียว (หลาย process/หลายเครื่องไม่ปลอดภัย) จนกว่าจะเปลี่ยนเป็น database
- token ยังอยู่ใน `localStorage` (เสี่ยงถ้ามี XSS ในอนาคต; CSP ช่วยลดความเสี่ยง)
- ยังไม่ได้ลองบน Vercel และบนมือถือจริง
- Notification เป็นโครงขั้นต่ำ (3 เหตุการณ์) ยังไม่มีระบบเต็ม
