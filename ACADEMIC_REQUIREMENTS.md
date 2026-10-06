# ACADEMIC_REQUIREMENTS.md - ตารางตรวจ Requirement (Traceability)

> วิธีใช้ตอนโชว์อาจารย์: เปิดไฟล์ในคอลัมน์ "ไฟล์" → ค้นหาชื่อฟังก์ชันในคอลัมน์ถัดไป → ทำตามคอลัมน์ "วิธีสาธิต"
> คำสั่งทุกอันรันจากโฟลเดอร์ `art4sells/` (Python 3 เท่านั้น ไม่ต้องติดตั้งอะไรเพิ่ม)
> บัญชีตัวอย่าง: `admin@art4sells.test`, `mika@art4sells.test` (ศิลปิน), `buyer@art4sells.test`  รหัสผ่านตัวอย่าง `Demo1234!`
> (ใช้เฉพาะเครื่อง development เปลี่ยนได้ด้วย `A4S_DEMO_PASSWORD`)

ตัวย่อ: **M** = `backend/modules/`, **C** = `training/console_menu.py`, **T** = `backend/tests/test_backend.py`

---

## 1. ระบบสมาชิก (Member System)

| Requirement | ไฟล์ | Function / Class | วิธีสาธิต |
|---|---|---|---|
| Register | `M/auth.py`, `M/user.py` | `register_user()`, `create_user()` | `POST /api/register` (ดู README ข้อ 6) หรือหน้า `register.html` / test `test_register_success_and_password_not_plaintext` |
| Login | `M/auth.py` | `login()` (ตรวจรหัสผ่านจริงทุกบัญชี) | หน้า `login.html` / `console_menu.py` ขึ้นให้ login ก่อนเข้าเมนู |
| Password policy | `M/validation.py` | `validate_password()` | สมัครด้วยรหัส `abcdef12` ได้ 400, `Abcdef12!` ได้ 201 (ดู docs/PHASE_3_5B.md) |
| Logout | `M/auth.py` | `logout()` | `POST /api/logout` แล้วเรียก `GET /api/me` จะได้ 401 (test `test_login_logout_and_current_user`) |
| Role: USER / ARTIST / ADMIN | `backend/config.py`, `M/permissions.py` | `ROLES` (tuple), `ROLE_PERMISSIONS` (dict ของ set) | เปิด `permissions.py` ดูสิทธิ์แต่ละ role |
| สมัครเองเป็น ADMIN ไม่ได้ | `backend/config.py`, `M/validation.py` | `SELF_REGISTER_ROLES`, `validate_user_data()` | test `test_register_cannot_choose_admin` |
| ตรวจอีเมล / รหัสผ่าน / อีเมลซ้ำ | `M/validation.py`, `M/user.py` | `validate_email()`, `validate_password()`, `create_user()` (เช็คซ้ำ → `EMAIL_EXISTS`) | tests `test_register_duplicate_email`, `test_register_invalid_email_and_passwords` |
| รหัสผ่านไม่เก็บ plaintext | `M/security.py` | `hash_password()`, `verify_password()` (PBKDF2-HMAC-SHA256 + salt สุ่ม) | เปิด `backend/data/users.json` จะเห็นเฉพาะ `password_hash` ขึ้นต้นด้วย `pbkdf2_sha256$` |
| Session / current user | `M/auth.py`, `M/security.py`, `M/session_cookie.py` | `authenticate()`, `new_session_token()`, `hash_token()`, `build_session_cookie()` | login แล้ว server ส่ง **HttpOnly cookie** `a4s_session` (ไม่มี token ใน JSON); `GET /api/me` ด้วย cookie จะได้ข้อมูลผู้ใช้ — โปรแกรมที่ไม่ใช่เบราว์เซอร์ใช้ `Authorization: Bearer <token จาก Set-Cookie>` ได้ · test `finale.cookie_authenticates_and_logout_invalidates_and_clears_it` |

## 2. CRUD (Artwork เป็นตัวหลัก + User, Category, Order, Review)

| Entity | Create | Read | Update | Delete | ไฟล์ |
|---|---|---|---|---|---|
| **Artwork** | `create_artwork()` | `get_artwork()`, `list_artworks()` | `update_artwork()` | `delete_artwork()` | `M/artwork.py` |
| User | `create_user()` | `get_user()`, `list_users()` | `update_user()` | `delete_user()` | `M/user.py` |
| Category | `create_category()` | `list_categories()` | `update_category()` | `delete_category()` | `M/category.py` |
| Order | `create_order()` | `get_order()`, `list_orders()` | `update_order_status()` | `delete_order()` | `M/order.py` |
| Review | `create_review()` | `list_reviews()` | `update_review()` | `delete_review()` | `M/review.py` |

- **Input validation**: `M/validation.py` → `validate_artwork()` (title ห้ามว่าง, price ≥ 0, category ต้องมีอยู่จริง, tags ถูกต้อง), `validate_review()`, `validate_order_items()`, `validate_category()`
- artist ต้องมีอยู่จริง: `artwork.ensure_artist_exists()`
- **วิธีสาธิต**: `python training/console_menu.py` → login `mika@art4sells.test` → เมนู 3 (Create) → 1 (Read) → 4 (Update) → 5 (Delete) หรือใช้ curl ตาม README ข้อ 7 / test `test_artwork_crud_full_cycle`, `test_artwork_validation_errors`
- ป้องกันการแอบแก้ field (mass assignment): `update_artwork()` รับเฉพาะ `EDITABLE_FIELDS` → test `test_artwork_mass_assignment_is_ignored`

## 3. Search / Filter / Sort / Pagination (ทำใน backend)

| Requirement | ไฟล์ | Function | วิธีสาธิต |
|---|---|---|---|
| Search (title / ศิลปิน / tag) | `M/artwork.py` | `search_artworks()` | `GET /api/artworks?q=koi` · test `test_search` |
| Filter (หมวด, ราคา, คะแนน, ประเภทขาย, ศิลปิน, ซื้อได้เลย) | `M/artwork.py` | `filter_artworks()` | `GET /api/artworks?category=3d-art&max_price=2000` · test `test_filter` |
| Sort | `M/artwork.py`, `backend/config.py` | `sort_artworks()`, `SORT_OPTIONS` | `GET /api/artworks?sort=price_asc` · test `test_sort` |
| Pagination + metadata | `M/utils.py` | `calculate_pagination()` (คืน tuple), `paginate()` | `GET /api/artworks?page=2&page_size=5` ได้ `items, page, page_size, total, total_pages` · test `test_pagination` |
| ตรวจ query ผิด (page=abc, page=0 ฯลฯ) | `M/validation.py` | `validate_page_params()`, `validate_artwork_filters()` | `GET /api/artworks?page=abc` → 400 พร้อมข้อความ |
| ตัวควบรวมทั้งหมด | `M/artwork.py` | `list_artworks()` | ใช้ฟังก์ชันเดียวกันทั้งใน API, หน้าเว็บ และ console เมนู 2 |

## 4. Dashboard / Summary Report

| Requirement | ไฟล์ | Function | วิธีสาธิต |
|---|---|---|---|
| คำนวณจากข้อมูลจริง (ไม่ hardcode) | `M/admin.py` | `get_dashboard_summary()`, `count_by_field()` | login admin → `admin.html` หรือ `GET /api/dashboard` หรือ console เมนู 6 |
| User / Artist / Artwork / รออนุมัติ / Order / ยอดขาย / Review | `M/admin.py` | `total_users`, `total_artists`, `total_artworks`, `pending_artworks`, `total_orders`, `total_sales`, `total_reviews` | test `test_dashboard_is_computed_from_real_data` (เพิ่มข้อมูลแล้วตัวเลขเปลี่ยนตาม) |

## 5. Important Data Logs (Audit Log)

| Requirement | ไฟล์ | Function | วิธีสาธิต |
|---|---|---|---|
| บันทึก log ลงไฟล์ | `M/logger.py` | `create_audit_log(actor_id, action, target_type, target_id, details)` | เปิด `backend/data/logs.json` |
| field: id, actor_id, action, target_type, target_id, timestamp, details | `M/logger.py` | (โครงสร้าง dict ใน `create_audit_log`) | test `test_audit_log_fields_and_filters` |
| action ที่ครอบคลุม | `M/logger.py` | `AUDIT_ACTIONS` (set) | USER_LOGIN, USER_CREATED, ARTWORK_CREATED/UPDATED/DELETED/SUBMITTED/APPROVED/REJECTED, ORDER_CREATED/UPDATED, REVIEW_CREATED, USER_BANNED ฯลฯ · test `test_all_required_audit_actions_are_written` |
| ดู log (admin เท่านั้น) | `M/admin.py`, `M/logger.py` | `get_audit_logs()`, `list_audit_logs()` | `GET /api/logs?action=ARTWORK_APPROVED` หรือแท็บ Audit Logs หรือ console เมนู 7 |

---

## 6. Python Requirements

### 6.1 Data types + type conversion (int / float / str / bool)

| ชนิด | ไฟล์ | Function | เกิดจาก logic จริงอย่างไร |
|---|---|---|---|
| `float` | `M/validation.py` | `to_float()` ใช้ใน `validate_artwork()` | ราคาจากฟอร์ม/JSON เป็นข้อความ `"1200.50"` → `float` ปฏิเสธ `abc`, `nan`, `inf`, `True` |
| `int` | `M/validation.py` | `to_int()` ใช้ใน `validate_page_params()`, `validate_order_items()`, `validate_review()` | `page=2` จาก URL เป็นข้อความ → `int`; จำนวนสินค้า; คะแนน 1-5 |
| `bool` | `M/validation.py` | `to_bool()` ใช้กับ `available=true`, `mine=true` | แปลง `"true"/"1"/"yes"` → `True` |
| `str` | `M/validation.py` | `check_text()`, `normalize_tags()` | `strip()`, `lower()`, ตรวจความยาว |
| int จาก env | `backend/config.py` | `_env_int()` | อ่านค่า `A4S_PORT` เป็นเลขพร้อม try/except |
| ใน console | `C` | `ask_float()`, `ask_int()` | `input()` เป็นข้อความเสมอ ต้องแปลงเป็นเลขก่อนใช้ |

### 6.2 Conditions

| ต้องมี | ตัวอย่างในโค้ด |
|---|---|
| `if / elif / else` | `validation.to_bool()` · `artwork.search_artworks()` (เลือกค้นตาม title/artist/tag/all) · `console.is_allowed()` · `console.main_menu()` (ตัวเลือกเมนู) |
| nested if | `order._create_order_locked()` (ถ้างาน LIMITED → ตรวจจำนวน → ตรวจว่าถูกล็อกไหม) · `artwork._select_visible()` |
| `and` | `order.expire_stale_orders()` (`waiting and is_expired(...)`) · `console.ask_float()` (`problem is None and value >= 0`) |
| `or` | `artwork.search_artworks()` (`title_hit or artist_hit or tag_hit`) · `admin.ban_user()` (`ตัวเอง or เป็น ADMIN`) |
| `not` | `user.get_user()` (`not (เจ้าของ or admin)`) · `console.main_menu()` (`choice not in MENU_KEYS`) · `artwork.update_artwork()` (`not (is_admin or is_own)`) |
| ตรวจสิทธิ์ user | `permissions.check_permission()`, `permissions.has_permission()` |
| ตรวจสถานะ artwork | `artwork.can_view_artwork()`, `artwork.compute_availability()`, `artwork._change_status()` |
| ตรวจว่าจ่ายเงินแล้ว | `order.is_order_paid()` |
| ตรวจว่า artwork ขายแล้ว/ถูกล็อก | `order._create_order_locked()` (`ARTWORK_SOLD`, `ARTWORK_LOCKED`) |
| ตรวจสิทธิ์รีวิว | `review.check_review_eligibility()` |

### 6.3 Loops

| ชนิด | ตัวอย่างในโค้ด | ใช้ทำอะไร |
|---|---|---|
| `for` | `artwork.search_artworks()`, `artwork.filter_artworks()` | วนรายการ artwork เพื่อค้น/กรอง |
| `for` | `admin.get_dashboard_summary()`, `review.calculate_average_rating()`, `order.get_locked_artwork_ids()` | วนสรุปยอด / คำนวณค่าเฉลี่ย / หาของที่ถูกล็อก |
| `for` | `logger.list_audit_logs()` | วนกรอง log (มี `break` ในลูปย่อย) |
| `for` | `console.print_artwork_page()`, `console.export_artworks_csv()` | พิมพ์รายการ / เขียน CSV ทีละแถว |
| `while` | `storage.create_record()` | วนสุ่ม id ใหม่ถ้าซ้ำ |
| `while` | `console.ask_text()`, `ask_float()`, `ask_int()` | validation loop: ถามซ้ำจนกว่าจะกรอกถูก |
| `while` | `console.login_prompt()` | ให้ลอง login สูงสุด 3 ครั้ง |
| `while` + `break` | `console.main_menu()`, `console.action_list()` | วงเมนูหลัก / เปลี่ยนหน้าที่ละหน้า |

### 6.4 Menu loop + exit

| Requirement | ไฟล์ | Function | วิธีสาธิต |
|---|---|---|---|
| เมนู `while` + `if/elif/else` + `break` | `training/console_menu.py` | `main_menu()` | `python training/console_menu.py` → login → เลือก `0` เพื่อออก (`break`) |
| เรียก logic เดียวกับระบบจริง | `training/console_menu.py` | `action_*()` เรียก `artwork.create_artwork()`, `artwork.list_artworks()`, `admin.get_dashboard_summary()` ฯลฯ | สร้างงานในเมนู แล้วเปิดเว็บ/`artworks.json` จะเห็นงานนั้นทันที |
| เมนูทดสอบได้อัตโนมัติ | `backend/tests/test_backend.py` | `test_console_*` | ใส่คำตอบสำเร็จรูปแทนการพิมพ์ (`input_func`) |

### 6.5 Functions (ผู้พัฒนาเขียนเอง มี parameter + return)

เกิน 6 ฟังก์ชันมาก (ทั้งโปรเจกต์ประมาณ 200 ฟังก์ชัน ไม่นับ test) ตัวอย่างที่ตรงกับโจทย์:

| ฟังก์ชัน | ไฟล์ | Parameter → Return |
|---|---|---|
| `validate_email(email)` | `M/validation.py` | `str` → `None` หรือข้อความ error |
| `validate_artwork(data, valid_categories, partial)` | `M/validation.py` | `dict, set, bool` → `tuple (clean, errors)` |
| `load_json(collection, default)` / `save_json(collection, data)` | `M/storage.py` | ชื่อ collection → `list` / เขียนไฟล์ |
| `search_artworks(artworks, text, search_in, artist_names)` | `M/artwork.py` | `list, str, str, dict` → `list` |
| `calculate_average_rating(reviews)` | `M/review.py` | `list` → `float` |
| `check_permission(user, permission)` | `M/permissions.py` | `dict, str` → ผ่านเงียบ ๆ หรือ raise 401/403 |
| `create_audit_log(actor_id, action, target_type, target_id, details)` | `M/logger.py` | → `dict` ของ log |
| `calculate_pagination(total, page, page_size)` | `M/utils.py` | `int, int, int` → `tuple (page, total_pages, start)` |

**ไม่มี God function**: ฟังก์ชันที่ยาวที่สุดในระบบประมาณ 50-60 บรรทัด (`validate_artwork`, `update_user`, `create_order`) และ `server.py` / `api.py` เป็นเพียงตัวส่งต่อ (ไม่มี business logic)

### 6.6 Data structures

| ชนิด | ตัวอย่าง |
|---|---|
| `list` | รายการ record ทุก collection (`storage.get_all()`), ผลค้นหา (`artwork.search_artworks()`) |
| `dict` | record ทุกชนิด, `config.ARTWORK_TRANSITIONS` / `ORDER_TRANSITIONS` (state machine), `permissions.ROLE_PERMISSIONS`, `console.ACTIONS` (เลขเมนู → ฟังก์ชัน) |
| `tuple` | `config.ROLES`, `config.PAGE_SIZE_RANGE`, `utils.calculate_pagination()` คืน tuple, `console.MENU_ITEMS` |
| `set` | `permissions.USER_PERMISSIONS`, `storage.COLLECTIONS`, `logger.AUDIT_ACTIONS`, `validation.normalize_tags()` (กัน tag ซ้ำ) |

### 6.7 Python modules แยกไฟล์

| หน้าที่ | ไฟล์ |
|---|---|
| server | `backend/server.py` (ส่งต่อ HTTP) + `M/api.py` (route + จัดการ error) |
| config | `backend/config.py` |
| logic | `M/auth.py`, `artwork.py`, `order.py`, `review.py`, `user.py`, `category.py`, `admin.py` |
| validation | `M/validation.py` |
| storage | `M/storage.py` |
| security | `M/security.py`, `M/permissions.py` |
| logging | `M/logger.py` |

### 6.8 Standard Library (ไม่มี package ภายนอกเลย)

`json`, `os`, `pathlib`, `datetime`, `uuid`, `hashlib`, `hmac`, `secrets`, `http.server`, `urllib.parse`, `csv`, `threading`, `logging`, `re`, `math`, `random`, `mimetypes` (ตัว test ใช้ `urllib.request`, `tempfile`, `shutil`, `contextlib` เพิ่ม)

### 6.9 File handling + Persistence

| ต้องทำได้ | ที่ไหน | วิธีสาธิต |
|---|---|---|
| read | `storage.load_json()` | ดู `backend/data/*.json` |
| write (แบบปลอดภัย: เขียนไฟล์ชั่วคราวแล้ว `os.replace`) | `storage.save_json()` | test `test_storage_crud_functions` (ไม่มีไฟล์ `.tmp` ค้าง) |
| create | `storage.create_record()` | สร้าง artwork แล้วเปิด `artworks.json` |
| update | `storage.update_record()` | แก้ราคาแล้วเปิด `artworks.json` |
| delete | `storage.delete_record()` | ลบ artwork แล้วเปิด `artworks.json` |
| CSV | `console.export_artworks_csv()` | เมนู 8 → `training/exports/artworks.csv` |
| **ข้อมูลอยู่หลังปิด-เปิดใหม่** | `storage.py` (ไม่มีข้อมูลหลักใน memory) | README ข้อ 10 · test `test_persistence_survives_server_restart` |

### 6.10 Error handling (try / except)

| จุด | ไฟล์ | Function |
|---|---|---|
| ไฟล์ไม่มี / JSON เสีย / อ่าน-เขียนไม่ได้ | `M/storage.py` | `load_json()`, `save_json()` → `StorageError` |
| แปลงชนิดข้อมูล | `M/validation.py` | `to_float()`, `to_int()` |
| แปลง JSON ของ request | `M/api.py` | `parse_json_body()` |
| ตัวดักสุดท้าย (ไม่ให้เห็น traceback) | `M/api.py` | `handle_request()` → ตอบ `INTERNAL_ERROR` ภาษาไทย, traceback ลง `backend/logs/server.log` |
| ตรวจ hash เสีย | `M/security.py` | `verify_password()` |
| อ่านเวลาไม่ได้ | `M/utils.py` | `is_expired()` |
| อ่าน env | `backend/config.py` | `_env_int()` |
| console | `C` | `run_action()`, `export_artworks_csv()` |

ข้อความที่ผู้ใช้เห็น: "ไม่สามารถบันทึกข้อมูลได้", "ข้อมูลไม่ถูกต้อง", "ไม่พบ Artwork", "ไม่มีสิทธิ์ดำเนินการ" (นิยามใน `M/errors.py`)

### 6.11 Storage abstraction

ทุก module เรียกข้อมูลผ่าน `M/storage.py` เท่านั้น (ค้นหา `open(` ใน `backend/` จะเจอเฉพาะ `storage.py`; นอกจากนั้นมี `console_menu.py` ที่เขียนไฟล์ CSV ส่งออก, `server.py` ที่อ่านไฟล์ static ของหน้าเว็บ และ `logger.py` ที่เขียน dev log ซึ่งไม่ใช่ข้อมูลระบบ)
อนาคตเปลี่ยนเป็น database: แก้ `storage.py` ให้ค่า `A4S_STORAGE` เลือก provider ใหม่ ส่วน business logic ไม่ต้องแก้

---

## 7. Backend / Auth / RBAC / Security by Design

| Requirement | ไฟล์ | Function | วิธีสาธิต |
|---|---|---|---|
| API ที่ frontend เรียกได้จริง | `M/api.py` | `ROUTES` (38 เส้นทาง), `handle_request()` | `python backend/server.py` แล้วเปิดเว็บ |
| Backend ตรวจสิทธิ์ซ้ำ (ไม่เชื่อ frontend) | `M/permissions.py` + ทุก module | `check_permission()`, `is_owner()` | `curl -X POST .../api/artworks/w13/approve` โดยไม่มี token → 401; ด้วย token ศิลปิน → 403 · test `test_rbac_matrix` |
| อนุมัติงานเฉพาะ ADMIN | `M/artwork.py` | `approve_artwork()`, `reject_artwork()` | test `test_approval_workflow_approve`, `test_approval_workflow_reject_edit_resubmit` |
| Workflow DRAFT→PENDING_APPROVAL→APPROVED/REJECTED→(แก้)→PENDING | `backend/config.py`, `M/artwork.py` | `ARTWORK_TRANSITIONS`, `_change_status()` | ลองข้ามขั้น → 409 `INVALID_TRANSITION` |
| Order state + กันย้อนสถานะ | `backend/config.py`, `M/order.py` | `ORDER_TRANSITIONS`, `_apply_status()` | `PUT /api/orders/o2 {"status":"PENDING_PAYMENT"}` (COMPLETED → PENDING_PAYMENT) → 409 · test `test_order_state_transitions` |
| Review ผูกกับ order ที่ COMPLETED | `M/review.py` | `check_review_eligibility()`, `create_review()` | test `test_review_eligibility_and_creation` |
| Input validation | `M/validation.py` | ทั้งไฟล์ | ดูหัวข้อ CRUD |
| Safe file handling | `M/storage.py`, `backend/server.py` | `_path_for()` (whitelist ชื่อ collection), `resolve_static_path()` (กัน `../`) | tests `test_unknown_collection_and_provider_rejected`, `test_static_path_traversal_blocked` |
| ไม่ hardcode secret | `backend/config.py`, `M/security.py` | token สุ่มด้วย `secrets`, เก็บเฉพาะ hash ของ token, ค่าตั้งต่าง ๆ อ่านจาก environment variable | ใน source ไม่มี key/รหัสผ่านจริง ยกเว้นรหัสผ่านตัวอย่าง `Demo1234!` ใน `backend/seed.py` ซึ่งเป็นค่าเริ่มต้นสำหรับเครื่อง dev เท่านั้นและ override ได้ด้วย `A4S_DEMO_PASSWORD` |
| Controlled error messages | `M/errors.py`, `M/api.py` | `AppError`, `StorageError` | test `test_request_body_errors_and_unexpected_errors_are_safe` |
| Audit logging | `M/logger.py` | `create_audit_log()` | ดูหัวข้อ 5 |

## 8. Frontend integration + Mock fallback

| Requirement | ไฟล์ | หมายเหตุ |
|---|---|---|
| UI → Frontend Service → HTTP API → Python | `src/ui/pages/pages.js` → `src/api/remoteApi.js` → `src/api/httpClient.js` → `backend/` | `httpClient.js` เป็นไฟล์เดียวที่เรียก `fetch()` |
| Mock แยกชัดเจน | `src/api/mockApi.js` (ห่อ service Phase 2 เดิม) | ใช้เฉพาะเมื่อ backend ไม่ตอบ หรือเปิด `?mode=mock` ; ใน MOCK ไม่มี authentication — Login/Register ถูกปิด (Phase 3.5b) |
| ผู้ใช้เห็นว่าอยู่ mode ไหน | `src/api/index.js`, `src/ui/components/ui.js` | แถบเหลือง "MOCK MODE" ใต้หัวเว็บ + footer บอก `Mode: API/MOCK` |

## 9. Testing (ใช้ `assert` + Standard Library)

รัน: `python backend/tests/test_backend.py` (ทดสอบบนสำเนาข้อมูลชั่วคราว ไม่แตะข้อมูลจริง)

| หัวข้อที่โจทย์ขอ | Test |
|---|---|
| Register / Login / Duplicate / Invalid password | `test_register_*`, `test_login_*` |
| Role permissions | `test_rbac_matrix`, `test_user_cannot_escalate_own_role`, `test_admin_user_management` |
| Artwork CRUD / validation | `test_artwork_crud_full_cycle`, `test_artwork_validation_errors` |
| Search / Filter / Sort / Pagination | `test_search`, `test_filter`, `test_sort`, `test_pagination` |
| Approval | `test_approval_workflow_*` |
| Dashboard / Audit log | `test_dashboard_is_computed_from_real_data`, `test_audit_log_fields_and_filters` |
| Order state / Review eligibility | `test_order_state_transitions`, `test_review_eligibility_and_creation` |
| JSON persistence / Invalid JSON / File error / Missing file | `test_persistence_survives_server_restart`, `test_invalid_json_file_is_reported_not_overwritten`, `test_file_write_error_is_handled`, `test_missing_data_file_is_handled` |
| Error cases ตามข้อ 32 | invalid email → `test_register_invalid_email_and_passwords` · empty title / negative price / invalid numeric → `test_artwork_validation_errors` · unknown artwork id → `test_artwork_unknown_id_and_ownership` · unknown user id → `test_unknown_user_id` · unauthorized → `test_rbac_matrix` · duplicate register → `test_register_duplicate_email` · invalid JSON → `test_request_body_errors_and_unexpected_errors_are_safe` · invalid page → `test_pagination` · invalid state transition → `test_order_state_transitions` |
| Race condition (ตรวจแล้วเขียนพร้อมกัน) | `test_concurrent_*` |
| Console menu | `test_console_*` |

Prototype เดิม (Phase 2): `node src/test/run.js` (ต้องมี Node.js; ส่วนนี้ไม่จำเป็นต่อการรัน backend)

---

## 10. Phase 3.5 - ส่วนที่เพิ่ม (ยังคงชี้ requirement ของอาจารย์ไปที่โค้ดจริง)

ตัวย่อเพิ่ม: **S** = `backend/tests/test_security.py`

| หัวข้อ | ไฟล์ | Function | วิธีสาธิต |
|---|---|---|---|
| CRUD ข้อมูลส่วนตัว (Cart / Wishlist / Follow) พร้อม validation | `M/cart.py`, `M/wishlist.py`, `M/follow.py` | `add_to_cart()`, `update_item()`, `remove_item()`, `clear_cart()`, `list_wishlist()`, `add_to_wishlist()`, `remove_from_wishlist()`, `follow_artist()`, `unfollow()` | login แล้วใช้หน้า Cart / Wishlist · tests `test_cart_*`, `test_wishlist_*`, `test_follow_*` |
| ตรวจเจ้าของ (RBAC ระดับ record) | `M/permissions.py` | `get_owned_record()`, `check_permission()` | `DELETE /api/cart/<id ของคนอื่น>` → 403 · test `test_cart_isolation_between_users` |
| เปลี่ยนรหัสผ่าน + cooldown (วันที่คำนวณจาก timestamp) | `M/password.py` | `change_password()`, `next_change_allowed_at()` | หน้า Settings · test `test_change_password_rules_success_and_cooldown` |
| ลืมรหัสผ่าน OTP (random, hash, หมดอายุ, จำกัดครั้ง) | `M/password.py`, `M/security.py`, `M/email_service.py` | `request_password_reset()`, `verify_reset_code()`, `reset_password()`, `new_otp_code()`, `hash_otp()` | หน้า `forgot.html` · tests `test_otp_*`, `test_reset_password_*` |
| try / except ใหม่ | `M/email_service.py`, `M/notification.py`, `M/api.py` | `send_password_reset_code()`, `notify()`, `parse_json_body()` | transport พัง → request ไม่ล้ม (test `test_email_service_modes_never_leak_or_crash`) |
| `while` ใหม่ | `M/data_management.py` | `expand_scopes()` | วนจนไม่มี scope ใหม่ถูกเพิ่ม (ล้าง `orders` → เพิ่ม `reviews` อัตโนมัติ) |
| `for` ใหม่ | `M/data_management.py`, `M/cart.py`, `M/password.py` | `build_plan()`, `build_cart_view()`, `_check_request_rate()` | วนคำนวณแผนการลบ / ยอดตะกร้า / จำนวนครั้งที่ขอรหัส |
| set / dict / tuple ใหม่ | `M/data_management.py` | `SCOPE_COLLECTIONS` (dict), `DEPENDENTS` (dict ของ set), `kept_admin_ids()` (set) | อ่านโค้ดส่วนต้นไฟล์ |
| Admin ล้างข้อมูล / รีเซ็ต + ยืนยัน 2 ชั้น + audit | `M/data_management.py`, `backend/seed.py` | `preview_clear()`, `clear_data()`, `preview_reset()`, `reset_demo_data()`, `seed_all()` | แท็บ Data Management · tests `test_data_management_*`, `test_clear_*`, `test_reset_demo_data_*` |
| ล้าง reference ไม่ให้เหลือ orphan | `M/references.py`, `M/storage.py` | `purge_artwork_references()`, `purge_user_references()`, `delete_where()` | test `test_deleting_artwork_or_user_removes_private_references` |
| Input validation กลาง + ชนิดข้อมูลจริง | `M/validation.py` | `check_text()`, `validate_id()`, `validate_choice()`, `validate_url()`, `pick_fields()`, `check_allowed_params()`, `check_query_values()`, `clean_text()` | tests `test_text_fields_require_real_strings`, `test_id_and_query_validation`, `test_query_parameter_limits_and_allowlists`, `test_unicode_control_chars_and_normalization` |
| ขอบเขตตัวเลข / JSON | `M/validation.py`, `M/api.py` | `to_float()`, `to_int()`, `parse_json_body()` | tests `test_number_boundaries_and_json_edge_cases`, `test_review_value_boundaries` |
| Mass assignment / role tampering | `M/validation.py`, ทุก module | `pick_fields()` | test `test_mass_assignment_and_role_tampering_are_ignored` |
| Path traversal / upload foundation | `M/uploads.py`, `backend/server.py` | `validate_upload_metadata()`, `safe_server_filename()`, `safe_join()`, `resolve_static_path()` | tests `test_validation_helpers_and_upload_foundation`, `test_static_path_traversal_blocked` |
| Safe output / XSS / CSP | `src/ui/components/ui.js`, `src/ui/pages/pages.js`, `backend/server.py` | `A4S.ui.esc()`, `build_csp()` | tests `test_frontend_source_has_no_dangerous_sinks`, `test_http_security_headers_and_error_pages_are_safe` |
| ไม่มี command injection | ทั้ง `backend/` | (สแกนโค้ดอัตโนมัติ) | test `test_backend_has_no_command_or_code_execution_calls` |
| Fuzz (ข้อมูลสุ่ม + mutation) | `S` | `test_fuzz_endpoints_never_crash_or_leak` | ต้องไม่มี 500 / traceback และไฟล์ข้อมูลไม่เสีย |

รัน test ทั้งหมด: `python backend/tests/test_backend.py` (รวม `test_security.py` และ `test_finale.py` อัตโนมัติ; ต้องติดตั้ง `pip install Pillow` สำหรับเทสต์ไฟล์ภาพ) → `183/183 tests passed` · `node src/test/run.js` → `35 passed, 0 failed`

---

## 11. Master Traceability Matrix (Requirement → File → Function/Class → API → Test → Demo)

ตารางรวมของ **requirement เดิมของอาจารย์ทั้งหมด** + ส่วนที่เพิ่มใน Phase 3.5 (ไม่มี requirement ใดหายไปจากการเพิ่ม security)
ตัวย่อ: **M** = `backend/modules/` · **C** = `training/console_menu.py` · **T** = ชื่อ test ใน `backend/tests/` (ต้องมีคำนำหน้า `test_`; ของ `test_security.py` ขึ้นต้น `security.` ตอนรัน)

### 11.1 ระบบสมาชิก / สิทธิ์ / ความเป็นเจ้าของ
| Requirement | File | Function / Class | API | Test | Demo |
|---|---|---|---|---|---|
| Register | `M/auth.py`, `M/user.py` | `register_user()`, `create_user()` | `POST /api/register` | `test_register_success_and_password_not_plaintext`, `test_register_duplicate_email`, `test_register_invalid_email_and_passwords` | หน้า `register.html` |
| Login / Logout | `M/auth.py` | `login()`, `logout()` | `POST /api/login`, `POST /api/logout` | `test_login_logout_and_current_user`, `test_login_failures_do_not_reveal_which_part_is_wrong` | หน้า `login.html`, console login |
| Password policy + login ไม่ bypass (Phase 3.5b) | `M/validation.py`, `M/auth.py`, `seed.py` | `validate_password()`, `login()` | `POST /api/register`, `POST /api/login` | `test_password_policy_table_through_validator_and_register`, `test_login_requires_the_correct_password`, `test_demo_accounts_do_not_bypass_password_verification`, `test_one_central_password_validator_is_used_by_every_entry_point` | หน้า `login.html`, `register.html` |
| Authentication (ใครกำลังเรียก) | `M/auth.py`, `M/security.py` | `authenticate()`, `hash_token()` | `GET /api/me` (cookie `a4s_session` หรือ header `Authorization: Bearer`) | `test_authorization_header_edge_cases_and_session_handling`, `test_expired_session_is_rejected` | `curl /api/me` ด้วย/ไม่ด้วย token |
| Role separation (USER/ARTIST/ADMIN) | `M/permissions.py`, `backend/config.py` | `ROLE_PERMISSIONS`, `check_permission()`, `has_permission()` | ทุก endpoint (ตัวอย่าง `POST /api/artworks/:id/approve`) | `test_rbac_matrix`, `test_user_cannot_escalate_own_role`, `test_mass_assignment_and_role_tampering_are_ignored` | login 3 role แล้วลองกดฟังก์ชันเดียวกัน |
| Authorization (ตรวจที่ backend ไม่ใช่ซ่อนปุ่ม) | `M/permissions.py` | `check_permission()` | `GET /api/dashboard` ไม่มี token → 401, USER → 403 | `test_rbac_matrix`, `test_private_endpoints_require_login_and_create_nothing` | README ข้อ 8 |
| User ownership / isolation | `M/permissions.py`, `M/cart.py`, `M/wishlist.py`, `M/follow.py`, `M/notification.py` | `get_owned_record()`, `add_to_cart()`, `add_to_wishlist()`, `follow_artist()`, `list_notifications()` | `GET/POST /api/cart`, `/api/wishlist`, `/api/follows`, `GET /api/me/notifications` | `test_cart_isolation_between_users`, `test_wishlist_prevents_duplicates_and_isolation`, `test_follow_artists_per_user`, `test_notifications_are_private_and_created_by_events` | login สลับ 2 บัญชี (README ข้อ 9.1) |
| Admin protected account | `M/admin.py`, `M/user.py`, `M/data_management.py` | `ban_user()`, `delete_user()`, `kept_admin_ids()` | `POST /api/users/:id/ban` | `test_protected_admin_account_rules`, `test_preserve_admin_flag_and_current_admin_is_never_deleted` | ลองระงับ `ad1` → 409 |

### 11.2 CRUD / Validation / Type conversion
| Requirement | File | Function / Class | API | Test | Demo |
|---|---|---|---|---|---|
| CRUD Artwork | `M/artwork.py` | `create_artwork()`, `get_artwork()`, `list_artworks()`, `update_artwork()`, `delete_artwork()` | `POST/GET/PUT/DELETE /api/artworks[/:id]` | `test_artwork_crud_full_cycle` | console เมนู 3/1/4/5, หน้า My Artwork |
| CRUD User / Category / Order / Review | `M/user.py`, `M/category.py`, `M/order.py`, `M/review.py` | `create_user()`/`update_user()`/`delete_user()`, `create_category()`..., `create_order()`/`update_order_status()`..., `create_review()`... | `/api/users`, `/api/categories`, `/api/orders`, `/api/reviews` | `test_admin_user_management`, `test_category_crud_and_rules`, `test_order_state_transitions`, `test_review_eligibility_and_creation` | README ข้อ 7 |
| Input validation (กลาง) | `M/validation.py` | `validate_string()`, `validate_integer()`, `validate_float()`, `validate_boolean()`, `validate_price()`, `validate_username()`, `validate_artwork_title()`, `validate_review_text()`, `validate_rating()`, `validate_quantity()`, `validate_email()`, `validate_password()`, `validate_id()`, `validate_choice()`, `validate_url()`, `validate_required()` | ทุก `POST/PUT` | `test_artwork_validation_errors`, `test_wrong_type_matrix_is_rejected_field_by_field`, `test_missing_required_fields_are_rejected`, `test_length_boundaries_min_max_and_plus_one` | ส่ง `"price": -5` → 400 บอกช่องที่ผิด |
| Type conversion **float** | `M/validation.py` | `to_float()` (ใช้ใน `validate_price()`) | `POST /api/artworks` `"price":"1200.50"` | `test_validation_and_conversion_functions`, `test_number_boundaries_and_json_edge_cases` | ราคาจากฟอร์มเป็นข้อความ → float |
| Type conversion **int** | `M/validation.py` | `to_int()` (ใช้ใน `validate_page_params()`, `validate_quantity()`, `validate_rating()`) | `GET /api/artworks?page=2` | `test_pagination`, `test_validation_and_conversion_functions` | `page=abc` → 400 |
| Type conversion **bool** | `M/validation.py` | `to_bool()`, `validate_boolean()` | `GET /api/artworks?available=true` | `test_boolean_type_confusion_is_rejected` | `available=maybe` → 400 |
| Type / **str** handling | `M/validation.py` | `clean_text()`, `validate_string()`, `normalize_tags()` | ทุกช่องข้อความ | `test_text_fields_require_real_strings`, `test_unicode_control_chars_and_normalization` | ชื่อไทย/emoji เก็บตามเดิม (NFC) |

### 11.3 โครงสร้างภาษา Python (ตามโจทย์)
| Requirement | File | Function / Class | API | Test | Demo |
|---|---|---|---|---|---|
| `if / elif / else` | `M/validation.py`, `M/artwork.py`, `C` | `to_bool()`, `search_artworks()` (เลือก title/artist/tag/all), `is_allowed()`, `main_menu()` | `GET /api/artworks?search_in=tag` | `test_search`, `test_console_helpers`, `test_boolean_type_confusion_is_rejected` | console เลือกเมนูผิด/ไม่มีสิทธิ์ |
| nested condition | `M/order.py`, `M/artwork.py` | `_create_order_locked()` (LIMITED → จำนวน → ถูกล็อก), `_select_visible()` | `POST /api/orders` | `test_order_validation_and_rules`, `test_order_create_locks_limited_artwork_and_uses_server_price` | สั่งงาน LIMITED ซ้ำ → 409 |
| `and` | `M/order.py`, `C` | `expire_stale_orders()`, `ask_float()` | `GET /api/orders/:id` | `test_order_expiry` | ออเดอร์เกินเวลา → EXPIRED |
| `or` | `M/artwork.py`, `M/admin.py` | `search_artworks()` (`title_hit or artist_hit or tag_hit`), `ban_user()` | `GET /api/artworks?q=` | `test_search` | ค้นหา "kenji" |
| `not` | `M/user.py`, `M/artwork.py`, `C` | `get_user()` (`not (เจ้าของ or admin)`), `update_artwork()`, `main_menu()` (`choice not in MENU_KEYS`) | `GET /api/users/:id` | `test_user_cannot_escalate_own_role`, `test_artwork_unknown_id_and_ownership` | ดู user คนอื่น → 403 |
| `for` loop | `M/artwork.py`, `M/admin.py`, `M/data_management.py`, `M/cart.py` | `filter_artworks()`, `get_dashboard_summary()`, `build_plan()`, `build_cart_view()` | `GET /api/dashboard` | `test_filter`, `test_dashboard_is_computed_from_real_data` | เพิ่มข้อมูลแล้วตัวเลข dashboard เปลี่ยน |
| `while` loop | `M/storage.py`, `M/data_management.py`, `C` | `create_record()` (สุ่ม id ซ้ำ), `expand_scopes()`, `ask_text()` / `ask_float()` / `ask_int()` / `login_prompt()` | `POST /api/admin/data/clear/preview` | `test_clear_data_follows_dependencies_and_keeps_integrity`, `test_console_helpers` | console กรอกราคาผิดแล้วถามซ้ำ |
| Looped menu + proper exit (`break`) | `C` | `main_menu()` | (ไม่ใช้ API: เรียก module ตรง) | `test_console_artist_session_create_update_delete_export`, `test_console_admin_session_and_login_limit` | `python training/console_menu.py` → เลือก `0` |
| Functions (parameters + return) | ทุกไฟล์ | เช่น `validate_email(email)`, `calculate_average_rating(reviews)`, `calculate_pagination(total, page, page_size)`, `check_permission(user, permission)` | - | `test_average_rating_function`, `test_validation_and_conversion_functions`, `test_pagination_helpers` | เปิดไฟล์ในตารางหัวข้อ 6.5 |
| `list` | `M/storage.py`, `M/artwork.py` | `get_all()`, `search_artworks()` | `GET /api/artworks` | `test_default_list_shows_only_public_artworks` | `backend/data/artworks.json` |
| `dict` | `M/permissions.py`, `backend/config.py`, `C` | `ROLE_PERMISSIONS`, `ARTWORK_TRANSITIONS`, `ACTIONS` | - | `test_approval_workflow_approve` | state machine ใน `config.py` |
| `set` | `M/permissions.py`, `M/storage.py`, `M/data_management.py` | `USER_PERMISSIONS`, `COLLECTIONS`, `kept_admin_ids()` | - | `test_rbac_matrix`, `test_unknown_collection_and_provider_rejected` | `permissions.py` ต้นไฟล์ |
| `tuple` | `backend/config.py`, `M/utils.py`, `C` | `ROLES`, `PAGE_SIZE_RANGE`, `calculate_pagination()` (คืน tuple), `MENU_ITEMS` | `GET /api/artworks?page=` | `test_pagination_helpers` | อ่าน `config.py` |
| `try / except` | `M/storage.py`, `M/api.py`, `M/validation.py`, `M/email_service.py`, `C` | `load_json()`, `save_json()`, `parse_json_body()`, `to_float()`, `send_password_reset_code()`, `run_action()` | ทุก endpoint (ตัวดักสุดท้ายใน `handle_request()`) | `test_invalid_json_file_is_reported_not_overwritten`, `test_request_body_errors_and_unexpected_errors_are_safe`, `test_email_service_modes_never_leak_or_crash` | แก้ `artworks.json` ให้เสียแล้วเปิดเว็บ |

### 11.4 ข้อมูล / ค้นหา / รายงาน / Log
| Requirement | File | Function / Class | API | Test | Demo |
|---|---|---|---|---|---|
| File persistence | `M/storage.py` | `load_json()`, `save_json()`, `create_record()`, `update_record()`, `delete_record()` | ทุก endpoint ที่เขียนข้อมูล | `test_persistence_survives_server_restart`, `test_storage_crud_functions` | README ข้อ 10 (ปิด-เปิด server) |
| Search | `M/artwork.py` | `search_artworks()` | `GET /api/artworks?q=&search_in=` | `test_search` | ช่องค้นหาหน้าแรก |
| Filter | `M/artwork.py` | `filter_artworks()` | `GET /api/artworks?category=&max_price=&min_rating=` | `test_filter` | ตัวกรองหน้าแรก |
| Sort | `M/artwork.py`, `backend/config.py` | `sort_artworks()`, `SORT_OPTIONS` | `GET /api/artworks?sort=price_asc` | `test_sort`, `test_query_parameter_limits_and_allowlists` (sort แปลกถูกปฏิเสธ) | ตัวเรียงหน้าแรก |
| Pagination | `M/utils.py`, `M/validation.py` | `paginate()`, `calculate_pagination()`, `validate_page_params()` | `GET /api/artworks?page=&page_size=` | `test_pagination`, `test_pagination_helpers` | ปุ่ม Next/Previous |
| Dashboard / Summary | `M/admin.py` | `get_dashboard_summary()` | `GET /api/dashboard` | `test_dashboard_is_computed_from_real_data` | แท็บ Dashboard, console เมนู 6 |
| Audit log | `M/logger.py`, `M/admin.py` | `create_audit_log()`, `list_audit_logs()`, `get_audit_logs()` | `GET /api/logs` | `test_audit_log_fields_and_filters`, `test_all_required_audit_actions_are_written` | แท็บ Audit Logs, console เมนู 7 |

### 11.5 Phase 3.5 (รหัสผ่าน / ข้อมูล admin / security)
| Requirement | File | Function / Class | API | Test | Demo |
|---|---|---|---|---|---|
| Change password + cooldown 30 วัน | `M/password.py` | `change_password()`, `next_change_allowed_at()` | `POST /api/auth/change-password` | `test_change_password_rules_success_and_cooldown` | หน้า Settings |
| Forgot / OTP / Reset | `M/password.py`, `M/email_service.py`, `M/security.py` | `request_password_reset()`, `verify_reset_code()`, `reset_password()`, `new_otp_code()` | `POST /api/auth/forgot-password`, `/verify-reset-code`, `/reset-password`, `/resend-reset-code` | `test_otp_end_to_end_hashed_single_use_and_session_invalidation`, `test_otp_wrong_attempts_invalidate_the_code`, `test_otp_expired_and_malformed_codes`, `test_otp_request_rate_limit_is_identical_for_known_and_unknown_emails`, `test_forgot_password_response_is_generic_for_known_and_unknown_email` | หน้า `forgot.html` (รหัสอยู่ในหน้าจอ server) |
| Admin Data Management | `M/data_management.py`, `backend/seed.py` | `preview_clear()`, `clear_data()`, `preview_reset()`, `reset_demo_data()` | `POST /api/admin/data/clear[/preview]`, `/reset[/preview]` | `test_data_management_is_admin_only_and_needs_two_steps`, `test_clear_data_follows_dependencies_and_keeps_integrity`, `test_reset_demo_data_restores_dataset_and_keeps_logs_and_admins` | แท็บ Data Management |
| XSS / safe output / CSP | `src/ui/components/ui.js`, `src/ui/pages/pages.js`, `backend/server.py` | `A4S.ui.esc()`, `build_csp()` | ทุกหน้า | `test_frontend_source_has_no_dangerous_sinks`, `test_pages_have_no_inline_scripts_so_strict_csp_is_safe`, `test_security_headers_present_on_api_and_static` | ใส่ชื่องาน `<img onerror>` แล้วดูหน้าเว็บ |
| CSRF foundation | `M/api.py` | `check_origin()`, `parse_json_body()` (บังคับ `application/json`) | ทุก `POST/PUT/DELETE` | `test_origin_check_blocks_cross_site_state_changes_only` | `curl -H "Origin: https://evil.example" -X POST ...` → 403 |
| Injection / path traversal / command | `M/validation.py`, `M/storage.py`, `backend/server.py` | `validate_id()`, `resolve_static_path()`, `COLLECTIONS` | ทุก endpoint | `test_injection_style_payloads_on_every_text_entry_are_inert`, `test_static_path_traversal_blocked`, `test_backend_has_no_command_or_code_execution_calls` | เปิด `/public/../backend/config.py` → 404 |
| File upload foundation | `M/uploads.py` | `validate_upload()`, `sniff_image_type()`, `save_upload()`, `safe_join()` | (ยังไม่มี endpoint) | `test_upload_content_checks_and_safe_storage` | ดู test |
| Error / information leakage | `M/errors.py`, `M/api.py`, `backend/server.py` | `AppError`, `handle_request()`, `send_error()` | ทุก endpoint | `test_no_secrets_paths_or_internals_in_any_response`, `test_http_security_headers_and_error_pages_are_safe` | ดู test |
| Fuzz / boundary / Thai / emoji | `backend/tests/test_security.py` | - | ทุก endpoint | `test_fuzz_endpoints_never_crash_or_leak`, `test_length_boundaries_min_max_and_plus_one`, `test_thai_emoji_and_special_text_roundtrip_and_search` | `python backend/tests/test_backend.py` |


---

## 12. Finale Prototype PART 1 - Persistence แบบ 2 ชั้น + Requirement ที่ยังรักษาไว้

> **Local JSON = Academic / Local Persistence** (ใช้ตอนทำงานวิชา/สาธิตกับอาจารย์: `A4S_STORAGE=json` ข้อมูลอยู่ใน `backend/data/*.json` ปิดโปรแกรมแล้วเปิดใหม่ข้อมูลยังอยู่)
> **Redis = Vercel Prototype Persistence** (ใช้เฉพาะตอน deploy ทดลองบน Vercel: `A4S_STORAGE=redis` เพราะ disk ของ Serverless Function ไม่ถาวร)
> ทั้งสองอย่างอยู่หลัง `storage.py` ตัวเดียวกัน — business logic ไม่รู้ว่าใช้ตัวไหน และ **งานวิชา (console menu, JSON, File Handling) ทำงานด้วย Local JSON เหมือนเดิมทุกประการ** ไม่ต้องมี Redis/Vercel/Internet เพื่อสาธิต

ตัวย่อ: **M** = `backend/modules/`, **F** = `backend/tests/test_finale.py`, **T** = `backend/tests/test_backend.py`

| Requirement (วิชา) | ไฟล์ | Function / Class | Test | วิธีสาธิต |
|---|---|---|---|---|
| **File handling + JSON persistence** | `M/storage_providers.py` | `JSONStorage.read()` (`open`, `json.load`), `JSONStorage.write()` (ไฟล์ชั่วคราว + `os.replace`) | `finale.storage_contract_json_provider_and_persistence_across_restart`, `persistence_survives_server_restart` | `python backend/server.py` → สร้างงาน → `Ctrl+C` → รันใหม่ → งานยังอยู่ และเปิดดู `backend/data/artworks.json` ได้ |
| **try / except** | `M/storage_providers.py` | `JSONStorage.read()` (จับ `FileNotFoundError`, `JSONDecodeError`, `OSError`), `UpstashRestClient.command()` (จับ `HTTPError`, `URLError`, `TimeoutError`) | `finale.redis_failures_are_safe_503_and_recover`, `invalid_json_file_is_reported_not_overwritten` | แก้ `backend/data/artworks.json` ให้เป็น `{เสีย` → ระบบแจ้งข้อความกลาง ไม่ crash ไม่เขียนทับไฟล์ |
| **int / float / str / bool + type conversion + validation** | `backend/config.py`, `M/validation.py` | `_env_bool()` (แปลงข้อความ → `bool` แบบเข้มงวด: เฉพาะ `true/1/yes` เป็นจริง), `_env_int()`, `to_float()`, `to_int()` | `finale.dev_tools_default_is_off_and_env_parsing_is_strict`, `wrong_type_matrix_is_rejected_field_by_field` | `A4S_DEV_TOOLS=enabled` (ไม่ใช่ `true`) → ยังปิดอยู่ |
| **if / elif / else + nested conditions** | `M/storage_providers.py`, `M/api.py` | `build_provider()` (เลือก provider ด้วย `if/elif` ซ้อนเงื่อนไข Vercel/Redis), `check_origin()` (ตรวจ Origin → Sec-Fetch-Site → cookie เป็นชั้น ๆ) | `finale.misconfigured_storage_is_reported_with_safe_codes`, `finale.cookie_requests_need_a_trustworthy_origin` | ตั้ง `A4S_STORAGE=redis` โดยไม่ใส่ URL → `GET /api/health` บอก `REDIS_NOT_CONFIGURED` |
| **and / or / not** | `M/session_cookie.py`, `M/health.py`, `M/config` | `is_https()`, `build_health()` (`ready = available and (...) and ...`), `dev_mailbox_enabled()` (`EMAIL_MODE == "development" and DEV_TOOLS is True`) | `finale.cookie_secure_flag_follows_https_and_ignores_spoofed_headers`, `finale.dev_mailbox_is_invisible_when_dev_tools_off_or_in_production_mode` | เปิด/ปิด `A4S_DEV_TOOLS` แล้วดูว่า `/api/dev/mailbox` เป็น 200 หรือ 404 |
| **for / while / break** | `M/rate_limit.py`, `M/storage_providers.py`, `M/artwork_files.py` | `_blocked_scope()` (`for` ไล่ทีละ scope), `RedisStorage._acquire_remote()` (`while True` + `return`/`raise` เมื่อได้ lock หรือหมดเวลา), `make_watermarked_preview()` (`for` ซ้อน `for` วางลายน้ำ) | `finale.login_rate_limit_blocks_after_5_failures_even_with_correct_password`, `finale.redis_lock_busy_expiry_and_safe_release`, `finale.upload_creates_three_distinct_files_and_original_is_untouched` | login รหัสผิด 5 ครั้งติด → ครั้งที่ 6 ได้ 429 |
| **Functions + parameters + return values (รวมคืนหลายค่า)** | `M/rate_limit.py`, `M/health.py`, `M/api.py` | `_blocked_scope()` คืน **tuple** `(scope, วินาทีที่ต้องรอ)`, `build_health()` คืน tuple `(status, dict)`, `dispatch()` คืน `namedtuple Response` | `finale.health_reports_local_json_state_without_leaking_anything` | อ่านโค้ดทีละฟังก์ชัน (แต่ละตัวมี docstring ภาษาไทยบอกพารามิเตอร์/ค่าที่คืน) |
| **dict / list / tuple / set** | `backend/config.py`, `M/storage.py`, `M/http_headers.py`, `M/health.py` | `BASE_HEADERS` (dict), `COLLECTIONS` (**set** ชื่อ collection ที่อนุญาต), `STORAGE_PROVIDERS` / `FILE_ROLES` (**tuple**), `SAFE_ERRORS` (set), ผลลัพธ์ `list_mailbox()` (list ของ dict) | `finale.storage_contract_*` (ชื่อ collection นอก set ถูกปฏิเสธ) | `storage.load_json("../../etc/passwd")` → `UNKNOWN_COLLECTION` |
| **หลายไฟล์ `.py`** | `backend/modules/*.py` (30+ ไฟล์), `api/index.py`, `scripts/check_vercel_ready.py` | แยกหน้าที่: storage / providers / auth / rate_limit / session_cookie / artwork_files / file_storage / health / adapter ฯลฯ | `finale.academic_requirement_files_are_still_present_and_runnable` | `ls backend/modules` |
| **Console menu ใช้ logic จริง** | `training/console_menu.py` | `main_menu()` เรียก `auth.login()`, `artwork.*` ตัวเดียวกับเว็บ (ผ่าน rate limit และ Local JSON เหมือนกัน) | `console_menu_*` ใน T | `python training/console_menu.py` |

**Requirement ใหม่ของ Part 1 → อยู่ตรงไหน**

| หัวข้อ | ไฟล์หลัก | Test | วิธีสาธิต |
|---|---|---|---|
| Storage Abstraction (JSON/Redis) | `M/storage.py`, `M/storage_providers.py` | `finale.storage_contract_*`, `finale.same_business_logic_runs_on_redis` | `A4S_STORAGE=json python backend/server.py` |
| Cookie session / CSRF | `M/session_cookie.py`, `M/api.py` (`check_origin`) | `finale.login_sets_httponly_cookie_*`, `finale.cookie_requests_need_a_trustworthy_origin` | DevTools → Network → ดู `Set-Cookie: ...HttpOnly` และ Application → Local Storage ไม่มี token |
| Login rate limit | `M/rate_limit.py` | `finale.login_rate_limit_*` | login รหัสผิด 5 ครั้ง |
| Forgot password + Developer Mailbox | `M/password.py`, `M/email_service.py`, `M/dev_tools.py` | `otp_end_to_end_*`, `finale.dev_mailbox_*` | ตั้ง `A4S_DEV_TOOLS=true` → admin → แท็บ Dev Mailbox |
| `/api/health` | `M/health.py` | `finale.health_*` | `curl localhost:8000/api/health` |
| อัปโหลด + ลายน้ำ + ส่งมอบหลังชำระเงิน | `M/artwork_files.py`, `M/file_storage.py`, `M/uploads.py` | `finale.upload_*`, `finale.preview_*`, `finale.original_*`, `finale.delivery_*` | อ่านหัวข้อ "อัปโหลดภาพ" ใน README |
| Vercel (adapter + routing) | `api/index.py`, `M/adapter.py`, `vercel.json`, `scripts/check_vercel_ready.py` | `finale.vercel_json_routes_api_to_python_and_root_to_index`, `finale.vercel_readiness_script_*` | `python scripts/check_vercel_ready.py` (**ยังไม่ได้ทดสอบ deploy จริง** - ดู VERCEL_DEPLOYMENT.md) |
