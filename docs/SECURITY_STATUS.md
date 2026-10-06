# SECURITY_STATUS.md - สถานะความปลอดภัยของ Art 4 Sells (Finale Prototype - PART 1)

> **ระบบนี้ไม่ได้ปลอดภัย 100% และเป็น Prototype ยังไม่พร้อมใช้งานจริง (ไม่ใช่ Production)** เอกสารนี้แยกให้ชัดว่าอะไรทำแล้ว (IMPLEMENTED) ทำบางส่วน (PARTIAL) ใช้ได้เฉพาะตอนพัฒนา/ทดสอบ (DEVELOPMENT-ONLY) และอะไรต้องเพิ่มก่อนขึ้นระบบจริง (FUTURE PRODUCTION)
> หลักฐาน = ชื่อ test ใน `backend/tests/` (รัน `python backend/tests/test_backend.py` → `183/183`) และ `src/test/run.js` (`node src/test/run.js` → `35 passed`)
> **สิ่งที่ยังไม่เคยทดสอบจริง:** การ deploy บน Vercel, Upstash Redis ตัวจริง, Vercel Blob ตัวจริง — เทสต์ใช้เซิร์ฟเวอร์/SDK จำลอง (ดูหัวข้อ 5)

## 1. IMPLEMENTED (ทำจริง มี test)

| หัวข้อ | สิ่งที่ทำ | หลักฐาน (test) |
|---|---|---|
| รหัสผ่าน | PBKDF2-SHA256 + salt สุ่ม, เทียบแบบเวลาคงที่, ไม่ strip/sanitize, ไม่เก็บ/ไม่ log/ไม่ส่งกลับ plaintext หรือ hash | `password_hash_functions`, `passwords_with_special_characters_are_never_sanitized` |
| Login ตรวจจริงทุกบัญชี | บัญชี demo ผ่าน hash/verify ชุดเดียวกับผู้ใช้จริง: อีเมลถูก+รหัสถูก = ผ่าน, อีเมลถูก+รหัสผิด = ไม่ผ่าน, อีเมลไม่มี = ไม่ผ่าน (ข้อความเดียวกัน) | `login_requires_the_correct_password`, `demo_accounts_do_not_bypass_password_verification`, `no_email_based_authentication_bypass_in_backend_code` |
| **Session = HttpOnly cookie** | ตั้ง `HttpOnly; SameSite=Lax; Path=/; Max-Age=43200` (+`Secure` เมื่อมาทาง HTTPS); token ไม่อยู่ใน JSON; frontend ไม่เก็บ token ใน localStorage (user อยู่ในหน่วยความจำเท่านั้น); ลบ token เก่าจาก localStorage ของเวอร์ชันก่อนตอนเริ่ม | `finale.login_sets_httponly_cookie_and_token_is_never_in_json`, `finale.cookie_secure_flag_follows_https_and_ignores_spoofed_headers`, `finale.frontend_keeps_no_login_token_in_browser_storage`, Node: `Login uses the HttpOnly cookie...`, `A leftover login token...` |
| Session ฝั่ง server | เก็บเฉพาะ hash ของ token + user_id + created_at + expires_at (12 ชม.); ถูกลบเมื่อ logout / ban / เปลี่ยนรหัส / รีเซ็ตรหัส / ลบ user; cookie ที่เป็นขยะไม่ทำให้ระบบล้ม | `finale.sessions_store_only_token_hash_with_user_and_expiry`, `finale.cookie_authenticates_and_logout_invalidates_and_clears_it`, `finale.expired_cookie_session_is_rejected`, `finale.ban_invalidates_existing_cookie_sessions`, `finale.garbage_session_cookies_never_authenticate_or_crash` |
| **CSRF / Origin** | คำขอ POST/PUT/PATCH/DELETE: ตรวจ `Origin` (ต้องตรงกับ Host หรืออยู่ใน `A4S_CORS_ORIGINS`), `Sec-Fetch-Site`, ถ้าใช้ cookie แล้วไม่มี Origin เลย = 403, บังคับ `Content-Type: application/json` + body เป็น JSON object, ไม่เคยส่ง `Access-Control-Allow-Origin: *`, login CSRF ถูกบล็อก | `finale.cookie_requests_need_a_trustworthy_origin`, `finale.login_from_another_site_is_blocked`, `finale.cookie_requests_must_be_json`, `finale.cors_is_closed_by_default_and_never_wildcard` |
| **Login rate limit** | นับ 3 แบบพร้อมกัน: IP+อีเมล (5 ครั้งผิด/10 นาที), อีเมล (15), IP (30) → 429 + `retry_after_seconds`; อีเมลที่ไม่มีก็นับเหมือนกัน (ไม่เผยว่ามีบัญชี); เก็บเฉพาะ hash ของ IP/อีเมล; บันทึก security event `LOGIN_RATE_LIMITED`; `X-Forwarded-For` เชื่อเฉพาะเมื่อ `A4S_TRUST_PROXY` (บน Vercel เปิดให้อัตโนมัติ) | `finale.login_rate_limit_*` (7 tests) |
| Password policy กลาง | 8–128 ตัว + a-z A-Z 0-9 อักษรพิเศษ ตัว validator เดียวใช้ทั้ง register / change / reset / admin สร้าง user | `password_policy_table_through_validator_and_register`, `one_central_password_validator_is_used_by_every_entry_point` |
| Forgot password (OTP) | OTP 5 หลักสุ่ม เก็บเป็น hash, อายุ 10 นาที, ใช้ได้ครั้งเดียว, ผิดได้ 5 ครั้ง, rate limit ขอรหัส, อีเมลที่ไม่มีตอบแบบเดียวกัน, reset แล้วตัดทุก session, ลืมรหัสผ่านข้าม cooldown 30 วันได้, audit log | `otp_end_to_end_hashed_single_use_and_session_invalidation` และชุด `forgot_*` / `change_password_*` |
| Developer OTP Mailbox | เปิดได้เฉพาะ `A4S_EMAIL_MODE=development` **และ** `A4S_DEV_TOOLS=true` และเฉพาะ ADMIN (ปิดอยู่ = 404 ไม่เผยว่ามี endpoint, ไม่เก็บ OTP เลย); API สาธารณะไม่เคยคืน OTP; OTP ไม่อยู่ใน audit log | `finale.dev_mailbox_is_admin_only_and_shows_otp_when_enabled`, `finale.dev_mailbox_is_invisible_when_dev_tools_off_or_in_production_mode`, `finale.dev_tools_default_is_off_and_env_parsing_is_strict` |
| Authorization | RBAC ซ้ำที่ backend ทุก endpoint + ตรวจเจ้าของ record; ไม่เชื่อ `role/is_admin/user_id` จาก client | `rbac_matrix`, `mass_assignment_and_role_tampering_are_ignored` |
| Validation กลาง / Injection | ชนิด/ความยาว/ช่วง/allowlist ที่ `validation.py`; ชื่อ collection เป็น allowlist (กัน path/key แปลก ๆ ทั้ง JSON และ Redis); ไม่มี `os.system/subprocess/eval/exec/pickle` (test สแกนโค้ด) | `wrong_type_matrix_is_rejected_field_by_field`, `injection_style_payloads_on_every_text_entry_are_inert`, `finale.backend_code_has_no_shell_eval_or_pickle_and_frontend_has_no_dynamic_code`, `finale.storage_contract_*` |
| Payload ทดสอบ (XSS/SQLi/path traversal/NaN/Infinity/เลขใหญ่/ชนิดผิด/JSON เสีย/Unicode/ไทย/emoji/สตริงยาว/control chars) | ไม่ทำให้ server ล้ม ไม่มี traceback/path/secret รั่วใน response (ทดสอบกับ header, cookie, path, query, body ของ endpoint ใหม่ด้วย) | `finale.hostile_payloads_in_headers_cookies_and_new_endpoints_never_crash_or_leak`, `no_secrets_paths_or_internals_in_any_response`, `number_boundaries_and_json_edge_cases` |
| Security headers | `Content-Security-Policy` (`script-src 'self'`, ไม่มี unsafe-inline/eval สำหรับ script, `frame-ancestors 'none'`, `object-src 'none'`), `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`, COOP/CORP, HSTS เฉพาะเมื่อมาทาง HTTPS; ตั้งทั้งใน API และไฟล์ static บน Vercel (`vercel.json`) | `finale.security_headers_are_added_to_api_responses`, `finale.vercel_json_routes_api_to_python_and_root_to_index` |
| Storage Abstraction | business logic ไม่รู้ว่าเป็น JSON หรือ Redis: `get_all/get_record/find_records/find_one/count_records/create_record/update_record/delete_record/delete_where/transaction`; ผลเหมือนกันทั้งสอง provider (Thai/emoji ไม่เพี้ยน, ข้อมูลอยู่หลังเริ่มใหม่) | `finale.storage_contract_json_provider_and_persistence_across_restart`, `finale.storage_contract_redis_provider_and_persistence_across_instances`, `finale.same_business_logic_runs_on_redis` |
| ไม่ fallback เงียบ ๆ | บน Vercel ถ้าไม่มี Redis (หรือตั้ง `A4S_STORAGE=json`) → ทุก API ตอบ 503 + `/api/health` บอก `storage_available:false, deployment_ready:false` + รหัส error ที่ปลอดภัย; ไม่เขียน JSON ลง disk ของ Function; ไฟล์ภาพก็เช่นกัน (ไม่มี `BLOB_READ_WRITE_TOKEN` = 503 ไม่เขียนลง `uploads/`) | `finale.vercel_without_redis_is_unavailable_and_never_falls_back_to_json`, `finale.misconfigured_storage_is_reported_with_safe_codes`, `finale.vercel_file_storage_never_falls_back_to_the_function_disk` |
| `/api/health` | แสดงเฉพาะ ok/application/mode/storage/storage_available/deployment_ready/email_mode/version (+ `storage_error` จาก allowlist) — ไม่มี token/password/session/secret/path/URL ของ Redis | `finale.health_reports_local_json_state_without_leaking_anything`, `finale.health_with_redis_ok_and_when_redis_goes_down` |
| Demo seed ครั้งเดียว | Redis ว่างครั้งแรก: seed ภายใต้ lock แล้วตั้ง `initialized`; ไม่ seed ซ้ำทุก request/cold start; ไม่ทับข้อมูลจริง; หลาย instance เริ่มพร้อมกัน seed ครั้งเดียว | `finale.redis_seeds_demo_data_only_once_and_never_over_real_data` |
| Lock แบบกระจาย (Redis) | `SET NX PX` + token + ปลดเฉพาะของตัวเอง + หมดอายุเอง (กัน Function ตายค้าง); อัปเดตพร้อมกันจากหลาย instance ไม่เกิด lost update | `finale.redis_distributed_lock_serializes_read_modify_write_across_instances`, `finale.redis_lock_busy_expiry_and_safe_release` |
| Redis ล่ม/ผิดพลาด | ตอบ 503 ข้อความกลาง (ไม่มี URL/token/ชื่อ provider) แล้วกลับมาใช้ได้เมื่อ Redis คืนมา; ข้อมูลใหญ่เกิน ~900 KB/collection ถูกปฏิเสธ (507) ไม่เขียนพังเงียบ ๆ | `finale.redis_failures_are_safe_503_and_recover`, `finale.redis_size_limit_and_collection_cap` |
| อัปโหลดไฟล์งานศิลปะ | PNG/JPG/JPEG/WEBP: ตรวจนามสกุล + Content-Type + ขนาด (5 MB) + **magic bytes** + เครื่องหมายโค้ดแฝง + **ถอดรหัสด้วย Pillow จริง** + จำกัดจำนวนพิกเซลก่อนถอดรหัส (กัน image bomb) + ชื่อไฟล์ที่เก็บ server สร้างเอง (uuid) + กัน path traversal; ไฟล์เสียหาย/ปลอมถูกปฏิเสธและ **ไม่ทิ้งอะไรไว้** | `finale.upload_rejects_bad_input_and_stores_nothing` (27 กรณี), `finale.upload_size_limits_and_image_bomb`, `finale.upload_accepts_png_jpg_jpeg_webp_and_ignores_unsafe_client_names`, `finale.upload_ignores_mass_assignment_fields` |
| Original / Preview / Delivery | Original **ไม่ถูกแก้แม้ไบต์เดียว** (เทียบทุกไบต์); ลายน้ำใช้กับ Preview เท่านั้น (ย่อขนาด); เก็บเป็น 3 object แยก; ไม่มี Pillow = ปฏิเสธอัปโหลด (ไม่เอา original ไปเป็น preview); Preview เปิดได้เมื่องานเผยแพร่แล้ว; Original เฉพาะเจ้าของ/admin; ไม่มี public URL; metadata มี storage_provider/blob_path/content_type/size/owner_id/created_at (blob_path ไม่ส่งให้ client) | `finale.upload_creates_three_distinct_files_and_original_is_untouched`, `finale.preview_is_public_only_for_published_artwork_and_never_original`, `finale.original_is_visible_only_to_owner_and_admin`, `finale.upload_is_refused_when_watermarking_is_unavailable` |
| ดาวน์โหลดหลังชำระเงิน | ต้อง ล็อกอิน + เป็นเจ้าของออเดอร์ + ออเดอร์ `PAYMENT_VERIFIED/PAID/COMPLETED` + งานอยู่ในออเดอร์นั้น ไม่ผ่าน = 403 (ไม่ login = 401) + audit; ส่งไฟล์ delivery ไม่ใช่ original | `finale.delivery_download_requires_login_ownership_and_verified_payment`, `finale.delivery_is_refused_for_unpaid_cancelled_or_expired_orders` |
| Vercel Blob (ฝั่งโค้ดของเรา) | อัปโหลดแบบ `access="private"` + token; อ่านกลับพร้อม `Authorization: Bearer`; เขียนไม่สำเร็จกลางทาง = เก็บกวาดไฟล์ที่เขียนแล้ว + ไม่รั่วรายละเอียดภายใน | `finale.vercel_blob_store_uploads_private_and_reads_with_authorization`, `finale.vercel_blob_failure_cleans_up_and_hides_internal_details` (ใช้ SDK ปลอม - ดูหัวข้อ 5) |
| Frontend | ไม่มี `eval` / `new Function` / `document.write` / `sessionStorage` / `document.cookie`; `localStorage` ใช้เฉพาะ `core/storage.js` (ข้อมูลทั่วไป ไม่ใช่ login); ข้อความผู้ใช้ผ่าน `esc()`; test render payload แล้วไม่เพิ่ม tag แม้แต่ตัวเดียว; deploy จริง + backend ล่ม = ไม่ใช้ข้อมูลจำลอง/ไม่มี login ปลอม | Node tests ท้ายไฟล์ `src/test/run.js` |
| Audit log | actor / action / target / timestamp / result / details; ไม่มีรหัสผ่าน/OTP/blob_path | `audit_log_fields_and_filters` |

## 2. PARTIAL (ทำบางส่วน — พูดตรง ๆ ว่าขาดอะไร)

| หัวข้อ | ทำแล้ว | ยังขาด / ข้อจำกัด |
|---|---|---|
| **CSRF** | Origin + Sec-Fetch-Site + SameSite=Lax + บังคับ JSON + ไม่ใช้ CORS wildcard | **ไม่มี CSRF token** (ใช้การตรวจ Origin เป็นหลัก) — เบราว์เซอร์รุ่นเก่ามากที่ไม่ส่ง Origin/Sec-Fetch-Site กับคำขอ cookie จะถูกปฏิเสธ (403) ไม่ใช่ผ่านเงียบ ๆ |
| **XSS** | ข้อความผู้ใช้เป็น plain text, `esc()` ทุกจุด, CSP `script-src 'self'`, test render + test สแกนโค้ด | `innerHTML` **ยังใช้กับ template** ใน `ui.js`/`pages.js` (ไม่ได้เปลี่ยนเป็น `textContent` ทั้งระบบ) — ความปลอดภัยพึ่งวินัยของโค้ด `esc()`; `style-src` ต้องมี `'unsafe-inline'` |
| **Rate limit** | login (IP+อีเมล), ขอ OTP (ต่ออีเมล) | ไม่มีสำหรับ API ทั่วไป / change-password / verify OTP ต่อ IP; ไม่ใช่ WAF; ตัวนับบน Redis เป็น read-modify-write ภายใต้ lock เดียวทั้งระบบ (ช้าลงเมื่อคนใช้มาก); IP บน Vercel อ่านจาก `X-Forwarded-For` (ต้องเชื่อ proxy ของ Vercel) |
| **Concurrency** | JSON: lock ใน process เดียว / Redis: lock กลางทั้งระบบ (1 lock ต่อ deployment) | JSON ไม่ปลอดภัยถ้ารันหลาย process; Redis lock เป็นแบบ best-effort (ไม่ใช่ Redlock) และเขียนหลาย collection ไม่ atomic (ถ้า Function ตายกลางทางอาจเหลือข้อมูลครึ่งทาง) |
| **ขนาดข้อมูลบน Redis** | แต่ละ collection เก็บเป็นค่าเดียว (JSON) | จำกัด ~900 KB ต่อ collection (logs/login_attempts/dev_mailbox ถูกตัดเหลือรายการล่าสุด) — เหมาะ prototype/เดโม ไม่เหมาะข้อมูลจำนวนมาก; อ่านทั้ง collection ทุกครั้ง |
| **File upload** | ตรวจเนื้อไฟล์ + Pillow decode + จำกัดพิกเซล + ลายน้ำ | ไม่ใช่การสแกนมัลแวร์; original/delivery ยังเป็นไฟล์เดิมของผู้ใช้ (ไม่ re-encode, EXIF ไม่ถูกลบ); ส่งไฟล์เป็น base64 ใน JSON จึงผ่านขนาดจริงได้ราว 3 MB บน Vercel (จำกัด request ~4.5 MB) แม้ระบบรับ 5 MB ในเครื่อง; **ส่วนที่คุยกับ Vercel Blob จริงยังไม่เคยรัน** |
| **Email/User enumeration** | login / forgot / verify / reset ตอบเหมือนกัน; rate limit นับอีเมลที่ไม่มีด้วย | สมัครด้วยอีเมลซ้ำตอบ `EMAIL_EXISTS` (แลกกับ UX) |
| **Session** | cookie HttpOnly, อายุ 12 ชม., ตัดเมื่อ logout/ban/reset | ไม่มี idle timeout, ไม่มีรายการอุปกรณ์/ออกจากระบบทุกเครื่องด้วยตัวเอง, ไม่แจ้งเตือน login ใหม่ |
| **Blocked IP (บล็อก IP โดย admin)** | มีเฉพาะ rate limit ต่อ IP | **ยังไม่มีระบบบล็อก IP** (แท็บ IP Block ยังว่าง — อยู่ใน PART 2 Admin Finalization) |

## 3. DEVELOPMENT-ONLY (ใช้เฉพาะพัฒนา/ทดสอบ ห้ามขึ้นระบบจริง)
- `A4S_EMAIL_MODE=development`: ยังไม่ส่งอีเมลจริง — พิมพ์ข้อความ (รวม OTP) ลง console ของ server (บน Vercel = **Function Logs ของโปรเจกต์**); ไม่ส่งใน API
- **Developer OTP Mailbox** (`A4S_DEV_TOOLS=true`): แสดง OTP จริงให้ ADMIN — เปิดเฉพาะตอนทดสอบ Prototype แล้วปิดทันที (ค่าเริ่มต้นและ `.env.example` = `false`)
- บัญชี demo + รหัสผ่านตัวอย่าง `Demo1234!` เป็นข้อมูลสาธารณะ (อยู่ในเอกสาร/โค้ด) — **บน Vercel ต้องตั้ง `A4S_DEMO_PASSWORD` เองก่อน seed ครั้งแรก** (ถ้าไม่ตั้ง ใครก็ login เป็น admin ได้)
- ที่เก็บข้อมูล JSON ในเครื่อง; `A4S_PBKDF2_ITERATIONS` ที่ลดได้ (เทสต์ใช้ 1000 — ค่าเริ่มต้น 600,000)
- HTTP ธรรมดา `127.0.0.1` (ไม่มี TLS)
- โหมด MOCK ของ frontend: ใช้ได้เฉพาะเมื่อเปิดจาก `localhost/127.0.0.1` — ไม่มี authentication; บนเว็บที่ deploy แล้ว backend ล่ม = แจ้งว่าใช้ไม่ได้ (ไม่ใช้ข้อมูลจำลอง)
- Upstash/Vercel Blob ในเทสต์เป็นของจำลอง (ไม่แตะข้อมูลจริง)

## 4. FUTURE PRODUCTION (ต้องเพิ่มก่อนขึ้นระบบจริง)
- ผู้ให้บริการอีเมลจริง (secret เก็บใน environment) แล้วปิด Developer Mailbox และไม่พิมพ์ OTP ลง log
- ฐานข้อมูลจริง (เช่น Postgres) + parameterized queries + transaction แทนการเก็บ JSON ก้อนเดียวต่อ collection
- Rate limit / WAF ที่ชั้น edge สำหรับทุก endpoint, lockout/แจ้งเตือนกิจกรรมผิดปกติ, ระบบบล็อก IP
- สแกนมัลแวร์ + re-encode ภาพ + ลบ EXIF; อัปโหลดตรงไป Blob (client upload) เพื่อไม่ติดเพดาน request 4.5 MB
- CSRF token (ถ้าต้องการชั้นป้องกันเพิ่ม), ย้าย template จาก `innerHTML` เป็น DOM API/framework ที่ escape ให้, ตัด `'unsafe-inline'` ของ style
- MFA, idle timeout, จัดการอุปกรณ์/session, ตรวจรหัสผ่านรั่ว
- Monitoring/alerting, backup/restore ของข้อมูล, ตรวจ dependency, penetration test โดยผู้ที่ไม่ใช่ผู้เขียนโค้ด
- Payment จริง (ตอนนี้ admin กดยืนยันเอง — ตั้งใจให้อยู่ PART 2)

## 5. สิ่งที่ยัง "ไม่ได้พิสูจน์" (อย่าเข้าใจผิดจากเลขเทสต์)
| เรื่อง | สถานะ |
|---|---|
| Deploy บน Vercel สำเร็จ | **ยังไม่ได้ทดสอบ** — รูปแบบ `api/index.py` (BaseHTTPRequestHandler), `vercel.json` (`rewrites`, `includeFiles`, `buildCommand`) เขียนตามเอกสาร แต่ยังไม่เคยรันบน Vercel |
| Upstash Redis ตัวจริง | **ยังไม่ได้ทดสอบ** — เทสต์ใช้เซิร์ฟเวอร์จำลอง REST (`fake_upstash.py`) ที่รองรับเฉพาะคำสั่งที่เราใช้ (PING/GET/SET NX PX/DEL/EXISTS/EVAL) |
| Vercel Blob ตัวจริง | **ยังไม่ได้ทดสอบ** — เทสต์ใช้ SDK ปลอม; ลายเซ็นของ `vercel.blob.put/delete` และการอ่าน private blob ด้วย `Authorization: Bearer` ตามเอกสารที่อ่านตอนเขียน ต้องยืนยันตอน deploy จริง |
| `scripts/check_vercel_ready.py` | ตรวจไฟล์/โครงสร้างในเครื่องเท่านั้น (ผล WARN เสมอจนกว่าจะทดสอบ deploy จริง) |
