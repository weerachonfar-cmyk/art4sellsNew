# ARCHITECTURE.md - Art 4 Sells (Phase 3 → Finale Prototype PART 1)

> **อ่านหัวข้อ 11 ก่อน** — สถาปัตยกรรมปัจจุบัน (Local vs Vercel, Storage, Auth, Upload) อยู่ที่นั่น หัวข้อ 1-10 เป็นเอกสารเดิมของ Phase 3/3.5 ที่ยังใช้ได้ ยกเว้นจุดที่ระบุว่า "เปลี่ยนใน Finale"

## 1. วิเคราะห์ Phase 2 (ก่อนแก้)

```
UI (src/ui, src/app.js)  ->  Services (src/services)  ->  Core (src/core)  ->  Data (src/data: mocks + registry)
                                                         state / storage / validation / rbac / stateMachine / audit / router
```

| จุดที่พบ | ผลต่อ Phase 3 |
|---|---|
| ข้อมูลทั้งหมดอยู่ใน `localStorage` ผ่าน `core/storage.js` และ `data/registry.js` | ย้าย "แหล่งความจริง" ไปที่ไฟล์ JSON ฝั่ง Python |
| Service เป็นฟังก์ชัน **synchronous** | HTTP เป็น async จึงต้องมีชั้นกลาง (`A4S.api`) ที่ทุกอย่างเป็น Promise |
| RBAC / validation / state machine / audit มีแล้วใน JS แต่เป็น "UX เท่านั้น" | เขียนซ้ำใน Python เป็นตัวจริง (ฝั่ง JS เหลือไว้สำหรับ MOCK mode) |
| Login เป็น mock (ไม่เก็บรหัสผ่าน) | ทำ register/login/session จริงด้วย hash |
| Test เดิมเป็น Node (`src/test/run.js`) | เก็บไว้ผ่านครบ 14/14 เพราะไม่แตะ `core/`, `data/`, `services/` |

### ไฟล์ที่เพิ่ม / แก้
- **เพิ่ม (Python)**: `backend/` ทั้งโฟลเดอร์, `training/console_menu.py`, `ACADEMIC_REQUIREMENTS.md`, `docs/ARCHITECTURE.md`
- **เพิ่ม (JS)**: `src/api/httpClient.js`, `remoteApi.js`, `mockApi.js`, `cart.js`, `index.js`
- **แก้**: `src/ui/pages/pages.js` (เขียนใหม่เป็น async อ่านผ่าน `A4S.api`), `src/app.js` (ปุ่ม/ฟอร์มเรียก `A4S.api`), `src/ui/components/ui.js` (card ใช้ `artistName`, แถบ MOCK MODE, ลิงก์ My Artwork/Admin ตาม role), `public/*.html` (เพิ่ม script `src/api/*`), `public/style.css` (ต่อท้ายไม่กี่บรรทัด)
- **ไม่แตะ**: `src/core`, `src/data`, `src/services`, `src/test`, `src/manifest.json`

## 2. Backend architecture

```
HTTP request
   │
backend/server.py ......... ส่งต่อ HTTP + ส่งไฟล์ static (ไม่มี business logic)
   │
modules/api.py ............ route table → ตรวจ token → แปลง JSON → เรียก handler → แปลง error เป็น JSON
   │
modules/{auth,user,artwork,order,review,category,admin}.py ... business logic + ตรวจสิทธิ์ซ้ำ
   │         ├── validation.py   ตรวจ/แปลงข้อมูล
   │         ├── permissions.py  RBAC            security.py  hash/token
   │         └── logger.py       audit log
   │
modules/storage.py ........ จุดเดียวที่อ่าน/เขียนข้อมูล
   │
backend/data/*.json
```

หลักการ: server / logic / validation / storage / logging แยกจากกัน · module บน "รู้จัก" module ล่างเท่านั้น (ไม่มี import วน) · `api.handle_request()` ไม่ผูกกับ HTTP จึงเทสต์ได้โดยไม่เปิด port

## 3. Request flow (ตัวอย่าง: ศิลปินสร้างงาน)

1. หน้า My Artwork → `app.js` (submit ฟอร์ม) → `A4S.api.artworks.create()` (`remoteApi.js`)
2. `httpClient.js` ส่ง `POST /api/artworks` พร้อม header `Authorization: Bearer <token>`
3. `server.py` อ่าน body → `api.handle_request()`
4. `auth.authenticate(token)` → ได้ `actor` (หรือ `None`)
5. `artwork.create_artwork(body, actor)`
   - `permissions.check_permission(actor, "artwork.create")` → 401 / 403
   - `validation.validate_artwork()` → 400 พร้อมบอกช่องที่ผิด
   - `storage.create_record("artworks", ...)` → เขียนไฟล์
   - `logger.create_audit_log(... "ARTWORK_CREATED" ...)` → เขียน `logs.json`
6. ตอบ `201` + JSON · ถ้า error ใด ๆ → JSON `{"error": {"code","message","fields"}}` (ไม่มี traceback)

## 4. Data flow

```
ฟอร์ม (string) ─► JSON ─► validation.to_float / to_int (แปลงชนิด) ─► dict (clean)
   ─► storage.create_record ─► artworks.json (list ของ dict)
   ─► (อ่านกลับ) storage.get_all ─► search → filter → sort → paginate ─► JSON ─► remoteApi.toArtwork ─► หน้าจอ
```
- ราคา/สถานะ/ศิลปินเจ้าของ ถูกตัดสินที่ backend เสมอ (ราคาที่ client ส่งมาตอนสั่งซื้อไม่ถูกใช้)
- Dashboard ไม่มีที่เก็บตัวเลข: `admin.get_dashboard_summary()` วนอ่านข้อมูลจริงทุกครั้ง

## 5. Data model (ไฟล์ใน `backend/data/`)

| ไฟล์ | field หลัก |
|---|---|
| `users.json` | id, name, email, **password_hash**, role (USER/ARTIST/ADMIN), status (ACTIVE/BANNED), headline, bio, rating, followers, accepts_commissions, created_at, updated_at |
| `artworks.json` | id, title, description, artist_id, category, tags[], price (float), rating, sale_type (LIMITED/UNLIMITED), status, preview_seed, created_at, updated_at, submitted_at, reviewed_by, reject_reason |
| `categories.json` | id (slug), name, description, created_at, updated_at |
| `orders.json` | id, user_id, items[{artwork_id, title, artist_id, sale_type, quantity, unit_price}], total, status, created_at, updated_at, expires_at, paid_at |
| `reviews.json` | id, **order_id**, artwork_id, artist_id, user_id, rating (1-5), comment, status (PUBLISHED/HIDDEN), created_at, updated_at |
| `logs.json` | id, actor_id, action, target_type, target_id, timestamp, details |
| `carts.json` / `wishlists.json` / `follows.json` / `notifications.json` | id, **user_id**, artwork_id / artist_id, ... (ข้อมูลส่วนตัว ทุก record มีเจ้าของ) |
| `password_resets.json` / `reset_requests.json` / `confirmations.json` | OTP (เก็บเฉพาะ hash) + reset authorization, บันทึกการขอรหัส (hash ของอีเมล), ขั้นยืนยันของ admin (เก็บ hash ของ token) |
| `sessions.json` | id, token_hash, user_id, created_at, expires_at (เก็บเฉพาะ hash ของ token) |

### State machine (นิยามที่ `backend/config.py`)
- Artwork: `DRAFT → PENDING_APPROVAL → APPROVED → SOLD` และ `PENDING_APPROVAL → REJECTED → PENDING_APPROVAL`
- Order: `CREATED → PENDING_PAYMENT → PAYMENT_VERIFIED → PAID → COMPLETED` และ `CREATED/PENDING_PAYMENT → CANCELLED`, `PENDING_PAYMENT → EXPIRED` (ย้อนกลับ/ข้ามขั้นไม่ได้)

## 6. API endpoints (62 เส้นทาง: 38 จาก Phase 3 + 24 ของ Phase 3.5) - รูปแบบ response ของรายการ: `{items, page, page_size, total, total_pages}`

| Method | Path | ใครเรียกได้ |
|---|---|---|
| GET | `/api/health` | ทุกคน |
| POST | `/api/register` | ทุกคน (role: USER/ARTIST) |
| POST | `/api/login` | ทุกคน |
| POST | `/api/logout` | ผู้ที่ login |
| GET | `/api/me` | ผู้ที่ login |
| GET | `/api/categories` | ทุกคน |
| POST | `/api/categories` | ADMIN |
| PUT | `/api/categories/:id` | ADMIN |
| DELETE | `/api/categories/:id` | ADMIN |
| GET | `/api/artworks` | ทุกคน (เห็นเฉพาะ APPROVED/SOLD; `mine=true` ต้อง login; `submitted`/สถานะอื่น = ADMIN) |
| POST | `/api/artworks` | ARTIST |
| GET | `/api/artworks/:id` | ทุกคน (งานที่เผยแพร่) · เจ้าของ/ADMIN (งานอื่น) |
| PUT | `/api/artworks/:id` | เจ้าของ (เฉพาะ DRAFT/REJECTED) · ADMIN |
| DELETE | `/api/artworks/:id` | เจ้าของ · ADMIN (ลบไม่ได้ถ้ามี order) |
| POST | `/api/artworks/:id/submit` | ARTIST เจ้าของงาน |
| POST | `/api/artworks/:id/approve` | ADMIN |
| POST | `/api/artworks/:id/reject` | ADMIN |
| GET | `/api/artworks/:id/review-eligibility` | ทุกคน (ไม่ login = ไม่มีสิทธิ์) |
| GET | `/api/artists` | ทุกคน |
| GET | `/api/artists/:id` | ทุกคน |
| GET | `/api/orders` | ผู้ที่ login (`scope=mine|sales|all`) |
| POST | `/api/orders` | USER · ARTIST (ซื้องานตัวเองไม่ได้) |
| GET | `/api/orders/:id` | เจ้าของ order · ADMIN |
| PUT | `/api/orders/:id` | ผู้ซื้อ (CANCELLED/COMPLETED) · ADMIN (ตามตาราง state) |
| DELETE | `/api/orders/:id` | ADMIN (เฉพาะ CANCELLED/EXPIRED) |
| GET | `/api/reviews` | ทุกคน (เห็นเฉพาะ PUBLISHED; ADMIN เห็นทั้งหมด) |
| POST | `/api/reviews` | ผู้ซื้อที่ order COMPLETED (รีวิวงานละ 1 ครั้ง) |
| PUT | `/api/reviews/:id` | เจ้าของ (แก้เนื้อหา) · ADMIN (ซ่อน/แสดง) |
| DELETE | `/api/reviews/:id` | เจ้าของ · ADMIN |
| GET | `/api/users` | ADMIN |
| POST | `/api/users` | ADMIN (กำหนด role ได้ทุกแบบ) |
| GET | `/api/users/:id` | เจ้าของ · ADMIN |
| PUT | `/api/users/:id` | เจ้าของ (โปรไฟล์) · ADMIN (เปลี่ยน role ได้) |
| DELETE | `/api/users/:id` | ADMIN |
| POST | `/api/users/:id/ban` | ADMIN |
| POST | `/api/users/:id/unban` | ADMIN |
| GET | `/api/dashboard` | ADMIN |
| GET | `/api/logs` | ADMIN |


### เพิ่มใน Phase 3.5 (รายละเอียดเต็มใน `docs/PHASE_3_5.md`)

| Method | Path | ใครเรียกได้ |
|---|---|---|
| POST | `/api/auth/change-password` | ผู้ที่ login (cooldown 30 วัน) |
| POST | `/api/auth/forgot-password` | ทุกคน (ตอบข้อความกลางเสมอ จำกัดจำนวนครั้ง) |
| POST | `/api/auth/resend-reset-code` | ทุกคน (ตอบข้อความกลางเสมอ จำกัดจำนวนครั้ง) |
| POST | `/api/auth/verify-reset-code` | ทุกคน (ต้องมี OTP ที่ถูกต้อง) |
| POST | `/api/auth/reset-password` | ผู้ถือ reset token (ใช้ครั้งเดียว) |
| GET | `/api/cart` | ผู้ที่ login (ของตัวเอง) |
| POST | `/api/cart` | USER · ARTIST |
| DELETE | `/api/cart` | USER · ARTIST (ของตัวเอง) |
| POST | `/api/cart/checkout` | USER · ARTIST |
| PUT | `/api/cart/:id` | เจ้าของรายการ |
| DELETE | `/api/cart/:id` | เจ้าของรายการ |
| GET | `/api/wishlist` | ผู้ที่ login (ของตัวเอง) |
| POST | `/api/wishlist` | ผู้ที่ login |
| DELETE | `/api/wishlist/:id` | เจ้าของรายการ |
| GET | `/api/follows` | ผู้ที่ login (ของตัวเอง) |
| POST | `/api/follows` | ผู้ที่ login |
| DELETE | `/api/follows/:id` | เจ้าของรายการ |
| GET | `/api/me/notifications` | ผู้ที่ login (ของตัวเอง) |
| POST | `/api/me/notifications/read-all` | ผู้ที่ login (ของตัวเอง) |
| PUT | `/api/me/notifications/:id` | เจ้าของ |
| POST | `/api/admin/data/clear/preview` | ADMIN (ขั้นที่ 1: ดูสรุป + ขอ confirm token) |
| POST | `/api/admin/data/clear` | ADMIN (ขั้นที่ 2: token + พิมพ์ CLEAR) |
| POST | `/api/admin/data/reset/preview` | ADMIN (ขั้นที่ 1) |
| POST | `/api/admin/data/reset` | ADMIN (ขั้นที่ 2: token + พิมพ์ RESET) |

ทุก endpoint ที่มีข้อมูลส่วนตัว ตัดสินเจ้าของจาก session ฝั่ง server (ไม่เชื่อ `user_id` ที่ client ส่งมา)

Query ของ `GET /api/artworks`: `q`, `search_in` (all/title/artist/tag), `category`, `artist_id`, `sale_type`, `min_price`, `max_price`, `min_rating`, `available`, `sort` (newest/oldest/price_asc/price_desc/rating), `page`, `page_size` (1-50)

## 7. Requirement mapping
ดูตารางเต็มที่ `ACADEMIC_REQUIREMENTS.md`

## 8. แนวทาง Vercel / production (เปลี่ยนใน Finale - ดูหัวข้อ 11)
- Local development: `A4S_STORAGE=json` ผ่าน `storage.py` → `JSONStorage` (งานวิชา File Handling)
- Vercel: `A4S_STORAGE=redis` → `RedisStorage` (Upstash REST) และไฟล์ภาพไป Vercel Blob; `api/index.py` เป็น adapter ที่เรียก `adapter.handle_api()` → `api.dispatch()` (เขียนแล้ว แต่ **ยังไม่ได้ทดสอบ deploy บน Vercel จริง**)
- ถ้าตั้งค่า Vercel ไม่ครบ ระบบ **ไม่ fallback ไป JSON เงียบ ๆ** แต่ตอบ 503 และ `/api/health` บอกสาเหตุ
## 9. ข้อจำกัดของ Phase นี้ (ตรงไปตรงมา)
- (แก้แล้วใน Phase 3.5) cart / wishlist / follow ย้ายมาเก็บที่ backend ผูกกับ user_id แล้ว
- **Commission** (ราคา/ขั้นตอน) ยังเป็นข้อมูลจำลองจาก Phase 2 ในหน้าศิลปิน ไม่ผ่าน backend
- แท็บ Admin: Reviews / Reports / Blacklist / IP Block ยังเป็นที่ว่างสำหรับ Phase ถัดไป (backend มีสิทธิ์ซ่อน/ลบรีวิวแล้ว แต่ยังไม่มีหน้าจอ)
- ยังไม่มี payment จริง: admin เป็นคนกดเปลี่ยนสถานะ PAYMENT_VERIFIED/PAID ผ่าน API เพื่อจำลอง
- (เปลี่ยนใน Finale) มี endpoint อัปโหลดภาพจริงแล้ว (original / preview ลายน้ำ / delivery); งานตัวอย่างจาก seed ยังเป็นภาพ SVG ที่สร้างจาก `preview_seed` และไม่มีไฟล์ในระบบอัปโหลด
- (เปลี่ยนใน Finale) rate limit ของ login / cookie HttpOnly / CSRF-Origin / security headers ทำแล้ว; **ยังไม่มี**: บล็อก IP โดย admin, CSRF token, HTTPS ที่ควบคุมเอง (Vercel ให้ HTTPS) — ดู `docs/SECURITY_STATUS.md`
- ความเร็ว: อ่านทั้งไฟล์ JSON ทุก request และล็อกด้วย `threading.RLock` ใน process เดียว เหมาะกับ prototype/เดโม ไม่เหมาะกับหลาย process หรือข้อมูลจำนวนมาก
- hash รหัสผ่านใช้ PBKDF2 600,000 รอบ: การ hash/ตรวจรหัสผ่านหนึ่งครั้งวัดได้ราว 0.18 วินาทีบนเครื่องที่ผมทดสอบ (ยังไม่ได้วัดบนมือถือ อาจช้ากว่านั้น) (ปรับด้วย `A4S_PBKDF2_ITERATIONS` ได้ แต่ไม่ควรลดในระบบจริง)

## 10. Security architecture (Phase 3.5) - สะท้อนระบบจริงหลังแก้ไข

> สถานะเต็มของแต่ละหัวข้อ (Implemented / Partial / Not Implemented / Development-only / Future Production) อยู่ใน `docs/SECURITY_STATUS.md` ระบบนี้ **ไม่ได้ปลอดภัย 100%** และยังไม่พร้อม production

### 10.1 เส้นทางของ request (Untrusted Input → Safe Output)
```
Untrusted Input  (JSON body / query string / path / headers จาก client ทั้งหมด)
   │  server.py     จำกัดขนาด body, ตัด request ผิดรูปแบบ (ตอบ JSON กลาง ๆ), ส่งไฟล์ static เฉพาะ public/ และ src/
   │  api.py        check_origin()          ตรวจ Origin ของคำขอที่เปลี่ยนข้อมูล (CSRF ชั้นเสริม)
   │                check_request_inputs()  id ใน path/query เป็นรูปแบบที่ถูกต้อง, query ที่ไม่รู้จักถูกปฏิเสธ, ค่า ≤ 200 ตัวอักษร
   │                parse_json_body()       ต้องเป็น application/json + JSON object ที่ถูกต้อง (ไม่มี NaN/Infinity/ซ้อนลึก/เลขใหญ่เกิน)
   ▼
Authentication     auth.authenticate(token)  → actor (dict ของ user จาก session ฝั่ง server) หรือ None
   ▼
Authorization      permissions.check_permission(actor, สิทธิ์)   และ   permissions.get_owned_record()  (ต้องเป็นเจ้าของ record)
   ▼
Validation (ราย field)   validation.py: validate_string/integer/float/boolean/price/id/choice/... (ชนิดจริง ความยาว ช่วง allowlist)
   ▼
Business Logic     modules/{artwork,order,cart,review,password,data_management,...}.py
   ▼
Persistence        storage.py: storage.transaction() (ล็อก), เขียนไฟล์ชั่วคราวแล้ว os.replace, ชื่อ collection เป็น allowlist
   ▼
Safe Output        JSON → remoteApi.js (แปลงรูป) → A4S.ui.esc() / textContent → CSP ('script-src self') ในเบราว์เซอร์
```
หมายเหตุตรงตามโค้ด: การตรวจ "รูปร่าง" ของ input (id, query, JSON) เกิดก่อน authentication ส่วนการตรวจ **ค่าของแต่ละ field** เกิดใน module หลังตรวจสิทธิ์แล้ว (เพื่อไม่ให้ผู้ที่ไม่มีสิทธิ์รู้ว่าข้อมูลถูกหรือผิดอย่างไร)

### 10.2 ข้อมูลส่วนตัวของผู้ใช้ (User-Owned Data)
```
Public Browsing (ดู/ค้นหา/กรอง/เรียง ไม่ต้อง login)
   ▼  กดฟังก์ชันส่วนตัว (cart / wishlist / follow / notifications / settings)
Authentication Gate   ไม่ login → แจ้ง "กรุณาเข้าสู่ระบบ..." → หน้า login (ไม่สร้างข้อมูล ไม่จำ action) ; backend ตอบ 401 ซ้ำอีกชั้น
   ▼
Authenticated User    ตัดสินจาก token → session ฝั่ง server (ไม่ใช่ user_id จาก client)
   ▼
User-Owned Data       ทุก record มี user_id ; อ่าน/แก้/ลบได้เฉพาะของตัวเอง (ของคนอื่น → 403)
   ▼
Backend Persistence   carts.json / wishlists.json / follows.json / notifications.json
   ▼  Frontend: A4S.priv (หน่วยความจำเท่านั้น) โหลดหลัง login ล้างตอน logout / 401 / เปลี่ยน user
```

### 10.3 สถาปัตยกรรมย่อย
| หัวข้อ | ที่อยู่ในโค้ด | สรุป |
|---|---|---|
| **Auth** | `auth.py`, `security.py` | login ตรวจ PBKDF2 (มี dummy hash เมื่อไม่พบอีเมล), ตอบข้อความเดียวกันทั้งอีเมลผิด/รหัสผิด, บัญชีถูกระงับ login ไม่ได้ ; **Phase 3.5b:** ไม่มีทางผ่านด้วยอีเมลอย่างเดียว (บัญชีตัวอย่างก็ตรวจ hash), login ไม่ strip/แปลงรหัสผ่านและไม่ใช้ policy ความซับซ้อน |
| **Password policy** | `validation.py` | `password_problems()` / `validate_password()` ตัวเดียว (8–128 ตัว + a-z A-Z 0-9 อักษรพิเศษ) ถูกเรียกจาก `validate_user_data()` (register + admin สร้าง user), `change_password()`, `reset_password()` ; register ต้องมี `confirm_password` ; ฝั่ง JS (`Validation.PASSWORD_RULES`) มีไว้ช่วย UX เท่านั้น backend ตรวจซ้ำเสมอ |
| **Frontend MOCK mode** | `authService.js`, `api/index.js` | MOCK ไม่มี authentication: `login()`/`register()` คืน error "ต้องใช้ backend จริง" และล้าง session เก่าเมื่อเข้าโหมดนี้ ; ไม่มีการ fallback จาก backend ไม่ตอบ → login แบบไม่ปลอดภัย |
| **Session** | `auth.py`, `session_cookie.py`, `sessions` | (เปลี่ยนใน Finale) token สุ่มส่งเป็น **HttpOnly cookie** `a4s_session` (`SameSite=Lax; Path=/`, `Secure` เมื่อ HTTPS) — ไม่อยู่ใน JSON และ frontend ไม่เก็บใน localStorage; เก็บเฉพาะ hash + user_id + created_at + expires_at (12 ชม.); ถูกลบเมื่อ logout / ban / เปลี่ยนรหัส / รีเซ็ตรหัส / ลบ user ; `Authorization: Bearer` ยังใช้ได้สำหรับโปรแกรมที่ไม่ใช่เบราว์เซอร์ |
| **Ownership** | `permissions.get_owned_record()` | id ผิดรูปแบบ 400 · ไม่มี 404 · ของคนอื่น 403 · ไม่ login 401 |
| **Admin authorization** | `permissions.py` (`ADMIN_PERMISSIONS`), `data_management.py` | สิทธิ์ `data.manage` เฉพาะ ADMIN, งานอันตรายต้องยืนยัน 2 ขั้นที่ server (`confirm_token` ใช้ครั้งเดียว + พิมพ์ข้อความ), admin ที่ใช้งานอยู่ไม่ถูกลบ |
| **Validation** | `validation.py` | ที่เดียวทั้งระบบ; ชนิดต้องตรงจริง; allowlist; ดูหัวข้อ 3 ของ `PHASE_3_5.md` |
| **Password recovery** | `password.py`, `email_service.py` | OTP 5 หลัก (hash) → reset token ใช้ครั้งเดียว → ตั้งรหัสใหม่ → ตัดทุก session ; ดู `PHASE_3_5.md` หัวข้อ 4 |
| **Audit logging** | `logger.py` | actor / action / target / timestamp / result / details ; ห้ามมีรหัสผ่านหรือ OTP ; เขียน log ก่อนลงมือลบข้อมูล |
| **Storage** | `storage.py`, `storage_providers.py` | (เปลี่ยนใน Finale) จุดเดียวที่อ่าน/เขียนข้อมูล แบ่ง provider: `JSONStorage` (ไฟล์, lock ใน process, เขียน atomic) / `RedisStorage` (Upstash REST, lock กลาง) / `UnavailableStorage` (ตั้งค่าผิด = 503) ; ชื่อ collection เป็น allowlist ; ไฟล์เสียหาย = รายงานและไม่เขียนทับ |
| **Error handling** | `errors.py`, `api.handle_request()` | `AppError` = ข้อความไทยที่ตั้งใจให้ผู้ใช้เห็น ; อย่างอื่น = "เกิดข้อผิดพลาดภายในระบบ" ; รายละเอียด/traceback อยู่ใน `backend/logs/server.log` เท่านั้น |
| **Security limitations** | `docs/SECURITY_STATUS.md` | รายการเต็มแยก IMPLEMENTED / PARTIAL / DEVELOPMENT-ONLY / FUTURE PRODUCTION (เช่น ยังไม่มีบล็อก IP, ไม่มี CSRF token, `innerHTML` ยังใช้กับ template, ยังไม่ได้ทดสอบกับ Vercel/Upstash/Blob จริง) |

### 10.4 Architecture Notes (จุดที่สถาปัตยกรรมเดิมจำกัด requirement - ยังไม่ได้เขียนทับ)
| Problem | Source | Affected requirement | ทำไมสถาปัตยกรรมเดิมขัด | แก้เล็กที่สุดที่สมเหตุสมผล | ขอบเขต |
|---|---|---|---|---|---|
| ล้างข้อมูลหลายไฟล์ไม่ atomic | `storage.py` (JSON หนึ่งไฟล์ต่อ collection) | Clear Data / dependency-aware deletion | ไม่มี transaction ข้ามไฟล์ | ย้ายไปฐานข้อมูล (SQLite ก่อน) แล้วใช้ transaction ผ่าน `storage.py` | `storage.py` + provider ใหม่ (logic ธุรกิจไม่ต้องแก้) |
| ~~Rate limit ต่อ IP ทำไม่ได้~~ (แก้แล้วใน Finale) | `api.dispatch()` รับ `peer_ip` จาก transport แล้ว | login rate limit | ส่ง IP เข้าไปนับใน `rate_limit.py` (IP+อีเมล) | แก้แล้ว | — |
| ~~token ใน localStorage~~ (แก้แล้วใน Finale) | ใช้ HttpOnly cookie + ตรวจ Origin/Content-Type/SameSite | Session security | ไม่ใช้ CSRF token — พึ่ง Origin check (ดู PARTIAL ใน SECURITY_STATUS) | แก้แล้ว | `auth.py`, `api.py`, `session_cookie.py` |
| CSP ต้องอนุญาต `style-src 'unsafe-inline'` | template ใช้ `style="..."` | CSP เข้มงวด | สไตล์แบบ inline กระจายอยู่ใน `pages.js`/`ui.js` | ย้ายเป็น class ใน `style.css` | `pages.js`, `ui.js`, `style.css` |
| `innerHTML` + `esc()` อาศัยวินัยของโค้ด | frontend render เป็น string | XSS safe output | ไม่มี framework ที่ escape อัตโนมัติ | เขียน helper สร้าง DOM ด้วย `textContent` | `ui.js`, `pages.js` |

## 11. Finale Prototype PART 1 - สถาปัตยกรรมปัจจุบัน

### 11.1 เส้นทางของ request (ใช้โค้ดชุดเดียวกันทั้ง Local และ Vercel)
```
Frontend (public/ + src/)  ── fetch /api/... (same-origin, cookie a4s_session อัตโนมัติ) ──┐
                                                                                         ▼
Transport      Local : backend/server.py  (http.server)      Vercel : api/index.py (Python Function)
               └───────────── ทั้งคู่เรียก backend/modules/adapter.py : handle_api() ─────────────┘
                              (จำกัดขนาด body, เตรียม storage/seed ครั้งแรก, แปลงผลเป็น bytes + header)
                                                                 ▼
API            api.dispatch(): route → หา token (cookie / Bearer) → check_origin (CSRF) → ตรวจรูปร่าง input → JSON body
                                                                 ▼
Authentication auth.authenticate(token) → actor ;  login: rate_limit (IP+อีเมล) → ตรวจ PBKDF2 → สร้าง session → Set-Cookie
                                                                 ▼
Authorization  permissions.check_permission / get_owned_record (RBAC + เจ้าของ record)
                                                                 ▼
Validation     validation.py (ชนิด/ความยาว/ช่วง/allowlist/normalize) + uploads.py (ไฟล์)
                                                                 ▼
Business Logic modules/{artwork, order, cart, review, password, artwork_files, data_management, ...}.py
                                                                 ▼
Storage        storage.py (API เดียว) ── เลือก provider ตาม A4S_STORAGE ──┬── JSONStorage  → backend/data/*.json   (Local / งานวิชา)
                                                                         └── RedisStorage → Upstash Redis (REST)  (Vercel Prototype)
                                       ตั้งค่าไม่ครบ → UnavailableStorage → 503 (ไม่ fallback)
```

### 11.2 ไฟล์ภาพ (Upload)
```
POST /api/artworks/:id/file  (JSON: filename, content_type, data_base64)
   → ตรวจสิทธิ์ (เจ้าของ/admin) → ตรวจ metadata + magic bytes + โค้ดแฝง → Pillow ถอดรหัสจริง + จำกัดพิกเซล
   → สร้าง 3 object:  original (ไบต์เดิม) · preview (ย่อ + ลายน้ำ) · delivery (สำเนา original)
                                                                 ▼
file_storage.py ──┬── LocalFileStore   → uploads/<role>/<uuid>.<ext>   (Local เท่านั้น)
                  ├── VercelBlobStore  → Vercel Blob แบบ Private       (Vercel)
                  └── UnavailableFileStore → 503 (ไม่เขียนลง disk ของ Function)
metadata (collection "files"): storage_provider, blob_path (ภายใน), content_type, size, owner_id, created_at

อ่านไฟล์: GET /preview (งานเผยแพร่แล้ว/เจ้าของ) · GET /original (เจ้าของ/admin) ·
          GET /api/orders/:oid/artworks/:aid/download (ล็อกอิน + เป็นเจ้าของออเดอร์ + PAYMENT_VERIFIED/PAID/COMPLETED + งานอยู่ในออเดอร์)
ทุกการอ่านผ่าน API ที่ตรวจสิทธิ์ — ไม่มี public URL ของ original/delivery
```

### 11.3 Local Development vs Vercel Deployment
| | Local Development | Vercel Deployment |
|---|---|---|
| คำสั่ง | `python backend/server.py` | push GitHub → Vercel (`vercel.json`) |
| Transport | `backend/server.py` (http.server) | `api/index.py` (BaseHTTPRequestHandler) |
| ข้อมูล | `A4S_STORAGE=json` → `backend/data/*.json` | `A4S_STORAGE=redis` → Upstash Redis |
| ไฟล์ภาพ | `uploads/` (LocalFileStore) | Vercel Blob (Private) |
| Frontend | server.py ส่ง `public/`+`src/` | Vercel static (`buildCommand` คัดลอกไป `dist/`) |
| อีเมล | `development` (พิมพ์ลง console) | `development` + Developer Mailbox (เฉพาะทดสอบ) |
| MOCK fallback | อนุญาตเมื่อเปิดจาก localhost | **ปิด** — backend ล่ม = แจ้งว่าใช้ไม่ได้ |
| สถานะการทดสอบ | เทสต์อัตโนมัติ + รัน server จริงด้วย curl แล้ว | **ยังไม่ได้ทดสอบบน Vercel/Upstash/Blob จริง** |

### 11.4 ข้อจำกัดของสถาปัตยกรรม Redis (พูดตรง ๆ)
- แต่ละ collection เก็บเป็นค่าเดียว (JSON) → จำกัด ~900 KB และอ่านทั้งก้อนทุกครั้ง (เหมาะ prototype ไม่เหมาะข้อมูลมาก)
- lock เดียวทั้งระบบสำหรับงาน "ตรวจแล้วเขียน" → ถูกต้องแต่ช้าลงเมื่อคนใช้พร้อมกันมาก
- เขียนหลาย collection ไม่ atomic (เหมือน JSON เดิม) → ทางแก้ระยะยาวคือฐานข้อมูลจริง (ดู SECURITY_STATUS → FUTURE PRODUCTION)

## Finale PART 2 — Commerce / Commission / Moderation

PART 2 extends the existing architecture without replacing the core. New backend modules are separated by responsibility:

- `payment.py` — payment method/status, amount verification and slip metadata.
- `promotion.py` — promotions, active price calculation and price history.
- `commission.py` — commission listing/job state machine, payment gate and deadline foundation.
- `moderation.py` — user blacklist and IP-block administration.

The frontend continues to access these features through `src/api/remoteApi.js` and the existing page/action layer. The system still uses the same authentication, RBAC, validation, audit logging and storage abstraction from PART 1.
