# Art 4 Sells - Finale Prototype (PART 1: Backend, Authentication, Security, Storage & Vercel Foundation)

ระบบ Art Marketplace ที่ตัว backend ใช้ **Python Standard Library ล้วน** (รันเว็บ + งานวิชาได้โดยไม่ต้อง `pip install` อะไร) + frontend เดิมจาก Phase 2 · เฉพาะส่วน **อัปโหลดภาพ/ลายน้ำ** ต้องมี `Pillow` (`pip install Pillow`) และส่วน Vercel Blob ใช้แพ็กเกจ `vercel` (ดู `requirements.txt`)

> **สถานะ:** Prototype ยังไม่ใช่ Production · ยังไม่เคยทดสอบ deploy บน Vercel / Upstash / Vercel Blob จริง (เทสต์ใช้ของจำลอง) — ดู `VERCEL_DEPLOYMENT.md` และ `docs/SECURITY_STATUS.md`

เอกสารที่ควรอ่าน:
- `ACADEMIC_REQUIREMENTS.md` - ตารางชี้ว่าแต่ละข้อของอาจารย์อยู่ที่ไฟล์/ฟังก์ชันไหน และสาธิตอย่างไร
- `docs/ARCHITECTURE.md` - สถาปัตยกรรม, request flow, data flow, data model, API ทั้งหมด
- `docs/SECURITY_STATUS.md` - สถานะความปลอดภัยแบบตรงไปตรงมา (Implemented / Partial / Not Implemented / Development-only / Future Production) **ระบบนี้ไม่ได้ปลอดภัย 100% และยังไม่พร้อมขึ้นระบบจริง**
- `VERCEL_DEPLOYMENT.md` - ขั้นตอน deploy ขึ้น Vercel + รายการตรวจหลัง deploy (**ยังไม่ได้ทดสอบจริง**)
- `docs/FINAL_REPORT_FINALE_PART1.md` - รายงานสรุป Finale PART 1 (ไฟล์ที่เพิ่ม/แก้, ผลเทสต์, ข้อจำกัด)
- `docs/FINAL_REPORT_PHASE_3_5.md` - รายงานสรุป Phase 3.5 ตามหัวข้อที่กำหนด
- `docs/PHASE_3_5.md` - สิ่งที่เพิ่มใน Phase 3.5: ข้อมูลส่วนตัว, เปลี่ยน/ลืมรหัสผ่าน (OTP), Data Management, input security, ข้อสมมติ และข้อจำกัด

## 1. ต้องมีอะไร
- Python 3.8 ขึ้นไป (ผมทดสอบกับ Python 3.12 เท่านั้น)
- Browser (Chrome / Safari ในมือถือก็ได้)
- Node.js **ไม่จำเป็น** (ใช้แค่รัน test ฝั่งหน้าเว็บ ถ้าต้องการ)
- `pip install Pillow` (เฉพาะถ้าจะใช้อัปโหลดภาพ/ลายน้ำ และรัน test ส่วนไฟล์ภาพ — ถ้าไม่มี ระบบปฏิเสธการอัปโหลดแทนที่จะเอาไฟล์ต้นฉบับไปแสดงโดยไม่มีลายน้ำ)

## 2. รัน backend + เว็บ (คำสั่งเดียว)
```
cd art4sells
python backend/server.py
```
แล้วเปิด `http://127.0.0.1:8000` ในเบราว์เซอร์ (server ส่งหน้าเว็บให้เองด้วย ไม่ต้องรัน frontend แยก)

- ครั้งแรกระบบสร้างข้อมูลตัวอย่างลง `backend/data/*.json` ให้อัตโนมัติ (ครั้งต่อไปใช้ข้อมูลเดิม)
- หยุด server: กด `Ctrl+C`
- เปลี่ยน port: `A4S_PORT=9000 python backend/server.py`
- ถ้ารันบนมือถือ (เช่น Termux) แล้วเปิดเบราว์เซอร์ในเครื่องเดียวกัน ใช้ `127.0.0.1` ได้เลย

**บัญชีตัวอย่าง** (รหัสผ่านตัวอย่างทุกบัญชี `Demo1234!` ใช้เฉพาะเครื่อง dev; ทุกบัญชีถูกตรวจรหัสผ่านจริงตอน login):

| อีเมล | Role |
|---|---|
| `admin@art4sells.test` | ADMIN |
| `mika@art4sells.test`, `kenji@art4sells.test`, `nara@art4sells.test`, `lumi@art4sells.test` | ARTIST |
| `buyer@art4sells.test`, `ton@art4sells.test` | USER |

เริ่มข้อมูลใหม่ทั้งหมด: `python backend/seed.py --reset` (ลบข้อมูลเดิม!)

## 3. โหมดของ frontend (API / MOCK)
หน้าเว็บเลือกโหมดเองตอนโหลด:
- **API** - backend ตอบ `/api/health` → ใช้ข้อมูลจริงจาก Python (footer เขียน `Mode: API`)
- **MOCK** - backend ไม่ตอบ → ถอยไปใช้ข้อมูลจำลองของ Phase 2 และแสดงแถบเหลือง **MOCK MODE** (ข้อมูลอยู่ใน browser เท่านั้น) **ใน MOCK ไม่มี authentication: หน้า Login/Register จะแจ้งว่าต้องใช้ backend จริง (ไม่ยอม login ด้วยอีเมลอย่างเดียว)**  (**เปลี่ยนใน Finale:** ถอยไป MOCK ได้เฉพาะเมื่อเปิดจาก `localhost`/`127.0.0.1`; บนเว็บที่ deploy แล้ว backend ล่ม = แจ้งว่าใช้ไม่ได้ ไม่มีข้อมูลจำลอง/login ปลอม)
- บังคับ mock: `?mode=mock` · กลับ API: `?mode=api` · ชี้ backend ที่อื่น: `?api=http://host:8000/api`

## 4. ทดสอบ
```
python backend/tests/test_backend.py        # backend ทั้งหมด (183 tests: เดิม 122 + Finale 61 — auth/cookie/CSRF/rate limit/storage JSON+Redis/อัปโหลด/ดาวน์โหลด/security)
node src/test/run.js                        # prototype Phase 2 + auth ฝั่งหน้าเว็บ + cookie/XSS/no-fake-backend (35 tests, ต้องมี Node.js)
```
test ทำงานบนสำเนาข้อมูลชั่วคราว ไม่กระทบข้อมูลจริง (ส่วน Redis ใช้เซิร์ฟเวอร์จำลองในหน่วยความจำ ไม่แตะ Upstash จริง) ผลที่ถูกต้องคือบรรทัดสุดท้าย `183/183 tests passed`
ตรวจความพร้อมก่อน deploy: `python scripts/check_vercel_ready.py` (ผล PASS/WARN/FAIL — **WARN เสมอจนกว่าจะทดสอบ deploy จริง**)

## 5. Console menu (สำหรับสาธิตกับอาจารย์)
```
python training/console_menu.py
```
login แล้วใช้เมนู list / search / create / update / delete / summary / logs / export CSV
เมนูนี้เรียกฟังก์ชันเดียวกับระบบจริง ข้อมูลที่สร้างจะไปปรากฏบนเว็บด้วย

## 6. ลอง API ด้วย curl (ตัวอย่าง)
```
# login: server ส่ง session เป็น HttpOnly cookie (ไม่มี token ใน JSON) -> เก็บลงไฟล์ cookies.txt ด้วย -c
# คำขอที่เปลี่ยนข้อมูล (POST/PUT/DELETE) ที่ใช้ cookie ต้องแนบ Origin ของเว็บเราเอง (เหมือนที่เบราว์เซอร์ทำให้) - ระบบ CSRF ตรวจข้อนี้
curl -s -c cookies.txt -X POST localhost:8000/api/login -H "Content-Type: application/json" -H "Origin: http://localhost:8000" \
  -d '{"email":"mika@art4sells.test","password":"Demo1234!"}'

# คำขอถัดไปใช้ -b cookies.txt  (ถ้าไม่มี Origin จะได้ 403 CROSS_ORIGIN_BLOCKED)
curl -s -b cookies.txt localhost:8000/api/me

# ตรวจสถานะระบบ (ไม่มี secret)
curl -s localhost:8000/api/health

# อ่านรายการ (ค้นหา + กรอง + เรียง + แบ่งหน้า)
curl -s "localhost:8000/api/artworks?q=koi&sort=price_asc&page=1&page_size=5"

# สมัครสมาชิก
curl -s -X POST localhost:8000/api/register -H "Content-Type: application/json" \
  -H "Origin: http://localhost:8000" \
  -d '{"name":"New Artist","email":"new@x.io","password":"Passw0rd1!","confirm_password":"Passw0rd1!","role":"ARTIST"}'
```

## 7. ทดสอบ CRUD (ศิลปิน mika)
```
# Create (ได้ id กลับมา สถานะ DRAFT)
curl -s -b cookies.txt -X POST localhost:8000/api/artworks -H "Origin: http://localhost:8000" -H "Content-Type: application/json" \
  -d '{"title":"My Piece","price":"350.50","category":"illustration","sale_type":"UNLIMITED","tags":["demo"]}'
# Read / Update / Delete (แทน ID ด้วย id ที่ได้)
curl -s -b cookies.txt localhost:8000/api/artworks/ID
curl -s -b cookies.txt -X PUT localhost:8000/api/artworks/ID -H "Origin: http://localhost:8000" -H "Content-Type: application/json" -d '{"price":400}'
curl -s -b cookies.txt -X DELETE localhost:8000/api/artworks/ID -H "Origin: http://localhost:8000"
```
ผ่านหน้าเว็บ: login เป็น mika → ไปที่หน้า **My Artwork** (ลิงก์ในเมนูมุมบนซ้าย) มีฟอร์มสร้าง/แก้ไข/ส่งอนุมัติ/ลบ

ลองข้อมูลผิดเพื่อดู error: `"price": -5` หรือ `"title": ""` → ได้ 400 พร้อมบอกว่าช่องไหนผิด

## 8. ทดสอบ login / RBAC
1. ไม่ login: `curl -i -X POST localhost:8000/api/artworks -H "Content-Type: application/json" -d '{}'` → **401** (POST/PUT ที่มี body ต้องส่ง `Content-Type: application/json` ไม่งั้นได้ 415)
2. login เป็น `buyer@...` (USER) แล้วสร้างงาน → **403**
3. login เป็น `mika@...` (ARTIST) แล้ว `POST /api/artworks/w13/approve` → **403** (ARTIST อนุมัติไม่ได้)
4. login เป็น `admin@...` แล้วเรียกอันเดียวกัน → **200**
5. ในหน้าเว็บ เปิด `admin.html` โดยไม่ login จะเห็น "Admins only" และการเรียก `/api/dashboard` ตรง ๆ ก็ยังได้ 401 (backend ตรวจเอง ไม่ใช่แค่ซ่อนปุ่ม)

## 9. ดู Audit Log / Dashboard
- เว็บ: login เป็น admin → `admin.html` → แท็บ **Dashboard** และ **Audit Logs**
- API: `curl -s -b admin_cookies.txt "localhost:8000/api/logs?action=ARTWORK_APPROVED"` (login เป็น admin ด้วย `-c admin_cookies.txt` ก่อน)` และ `/api/dashboard`
- ไฟล์จริง: `backend/data/logs.json`
- Console: เมนู 6 (summary) และ 7 (logs)

## 9.1 ข้อมูลส่วนตัวรายผู้ใช้ (Phase 3.5)
- ยังไม่ login: เปิดดู/ค้นหา/กรองได้ตามปกติ แต่กด Add to Cart / หัวใจ / Follow จะขึ้น "กรุณาเข้าสู่ระบบก่อนจึงสามารถใช้ฟังก์ชันนี้ได้" แล้วพาไปหน้า Login (ไม่มีข้อมูลถูกสร้าง)
- ตะกร้า / รายการโปรด / ติดตามศิลปิน / แจ้งเตือน เก็บที่ backend ผูกกับบัญชี (`carts.json`, `wishlists.json`, `follows.json`, `notifications.json`) สลับบัญชีแล้วเห็นเฉพาะของตัวเอง
- ลองสลับ user: login `buyer@...` เพิ่มของลงตะกร้า → Logout → login `ton@art4sells.test` จะเห็นตะกร้าว่าง → กลับมา login `buyer@...` ของเดิมยังอยู่

## 9.2 เปลี่ยนรหัสผ่าน / ลืมรหัสผ่าน
- **เปลี่ยนรหัสผ่าน**: login แล้วเมนูมุมบนซ้าย → **Settings** (เปลี่ยนซ้ำได้ทุก 30 วัน หน้านั้นบอกวันที่เปลี่ยนได้อีกครั้ง)
- **ลืมรหัสผ่าน**: หน้า Login → **Forgot password?** → กรอกอีเมล → **รหัส 5 หลักจะพิมพ์ในหน้าจอที่รัน `python backend/server.py`** (โหมดพัฒนา `EMAIL_MODE=development` ยังไม่ส่งอีเมลจริง และไม่ส่งรหัสกลับทาง API) → กรอกรหัส → ตั้งรหัสใหม่

## 9.3 Admin: Data Management
login เป็น admin → `admin.html` → แท็บ **Data Management**: เลือกสิ่งที่จะล้าง → Review & continue (ดูสรุป) → Continue → พิมพ์ `CLEAR` → Confirm  ·  **Reset Demo Data** พิมพ์ `RESET`
(เก็บบัญชี admin ไว้เป็นค่าเริ่มต้น และ admin ที่ใช้งานอยู่ไม่ถูกลบเด็ดขาด; ถ้าทำพลาด `python backend/seed.py --reset` กู้ข้อมูลตัวอย่างได้)

## 9.4 Finale PART 1: ตั้งค่า / Health / Dev Mailbox / อัปโหลดภาพ / Rate limit
**ตัวแปรสภาพแวดล้อม** (ดูครบใน `.env.example`; ห้าม commit `.env` / `.env.local`):

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `A4S_STORAGE` | `json` (บน Vercel: ไม่ตั้ง = `redis` ถ้าต่อ Upstash แล้ว ไม่งั้น = โหมด DEMO) | `json` = `backend/data/*.json` (Local/งานวิชา) · `redis` = Upstash (Vercel) · **Deploy ขึ้น Vercel ได้ทันทีโดยไม่ตั้งค่า** (ข้อมูลชั่วคราว) ดู `VERCEL_DEPLOYMENT.md` หัวข้อ 00 |
| `A4S_EMAIL_MODE` | `development` | ยังไม่มี provider อีเมลจริง |
| `A4S_DEV_TOOLS` | `false` | `true` = เปิด Developer OTP Mailbox (เฉพาะ admin + development) |
| `A4S_CORS_ORIGINS` | ว่าง | origin ของ frontend ถ้าแยกโดเมน (ว่าง = same-origin เท่านั้น ไม่เปิด CORS) |
| `A4S_PBKDF2_ITERATIONS` | `600000` | รอบ hash รหัสผ่าน |
| `UPSTASH_REDIS_REST_URL/TOKEN` | ว่าง | ใช้เมื่อ `A4S_STORAGE=redis` |
| `BLOB_READ_WRITE_TOKEN` | ว่าง | Vercel Blob (ไฟล์ภาพบน Vercel) |

- **Health:** `curl localhost:8000/api/health` → `{"ok":true,"application":"Art 4 Sells","mode":"local","storage":"json","storage_available":true,"deployment_ready":true,"email_mode":"development","version":"finale-prototype"}` (ไม่มี token/path/secret)
- **Developer OTP Mailbox:** `A4S_DEV_TOOLS=true python backend/server.py` → ขอรหัสที่หน้า Forgot password → login เป็น admin → `admin.html` → แท็บ **Dev Mailbox** เห็น recipient / created_at / expires_at / OTP / purpose · ปิด (`false`) แล้ว endpoint จะเป็น 404 · **ห้ามเปิดในระบบจริง**
- **อัปโหลดภาพงาน** (ศิลปินเจ้าของงาน/admin): `POST /api/artworks/ID/file` ด้วย JSON `{"filename":"a.png","content_type":"image/png","data_base64":"..."}` (PNG/JPG/JPEG/WEBP ไม่เกิน 5 MB) → เก็บ 3 ไฟล์: **original** (ไม่แก้) · **preview** (ย่อ + ลายน้ำ) · **delivery** · ดู preview: `GET /api/artworks/ID/preview` · original: `GET /api/artworks/ID/original` (เจ้าของ/admin เท่านั้น) · ผู้ซื้อโหลด delivery ได้เมื่อออเดอร์ `PAYMENT_VERIFIED/PAID/COMPLETED`: `GET /api/orders/OID/artworks/ID/download`
- **Rate limit login:** รหัสผิด 5 ครั้ง/10 นาที (นับ IP+อีเมล) → `429` พร้อม `retry_after_seconds`
- **Session:** cookie `a4s_session` (HttpOnly, SameSite=Lax, 12 ชม.) — ในเบราว์เซอร์จะไม่เห็น token ใน Local Storage
- **Deploy Vercel:** อ่าน `VERCEL_DEPLOYMENT.md` (ยังไม่ได้ทดสอบจริง — ต้องทำรายการตรวจหลัง deploy ด้วยตัวเอง)

## 10. ตรวจ persistence
1. สร้างงานชื่อ `Artwork A` (หน้า My Artwork หรือ console เมนู 3)
2. กด `Ctrl+C` หยุด server
3. รัน `python backend/server.py` ใหม่ → ค้นหา `Artwork A` ยังอยู่ (และเห็นใน `backend/data/artworks.json`)

## 11. ตรวจ error handling
- JSON เสีย: แก้ `backend/data/artworks.json` ให้เป็น `{เสีย` แล้วเปิดหน้าแรก → เห็นข้อความ "ไม่สามารถอ่านข้อมูลได้ (ไฟล์ข้อมูลเสียหาย)" ไม่มี traceback และไฟล์ไม่ถูกเขียนทับ (รายละเอียดสำหรับ developer อยู่ที่ `backend/logs/server.log`)
- ไฟล์หาย: ลบ `backend/data/reviews.json` → ระบบถือว่ายังไม่มีรีวิว ไม่ crash
- ครบทั้ง 12 กรณีตามข้อ 32 อยู่ใน test (ดู `ACADEMIC_REQUIREMENTS.md` หัวข้อ 9)

## 12. โครงสร้างไฟล์
```
art4sells/
├── README.md, ACADEMIC_REQUIREMENTS.md, VERCEL_DEPLOYMENT.md, vercel.json, requirements.txt, .env.example, .gitignore, .vercelignore
├── api/index.py               Vercel Python Function (adapter เท่านั้น ไม่มี business logic)
├── scripts/check_vercel_ready.py   ตรวจความพร้อม deploy (PASS/WARN/FAIL)
├── backend/
│   ├── server.py              HTTP server (ส่งต่ออย่างเดียว ไม่มี business logic)
│   ├── config.py              ค่าตั้งต้น + ตารางสถานะ (state machine)
│   ├── seed.py                สร้างข้อมูลตัวอย่าง
│   ├── modules/
│   │   ├── api.py             route table + จัดการ error + แปลง JSON
│   │   ├── auth.py            register / login / logout / session
│   │   ├── user.py  artwork.py  order.py  review.py  category.py  admin.py
│   │   ├── cart.py  wishlist.py  follow.py  notification.py      (Phase 3.5: ข้อมูลส่วนตัวรายผู้ใช้)
│   │   ├── password.py  email_service.py                         (เปลี่ยน/ลืมรหัสผ่าน + OTP)
│   │   ├── data_management.py  references.py  uploads.py         (admin ล้าง/รีเซ็ตข้อมูล, ล้าง reference, รากฐานอัปโหลด)
│   │   ├── validation.py      ตรวจข้อมูล + แปลงชนิดข้อมูล
│   │   ├── permissions.py     RBAC        security.py   hash รหัสผ่าน/token
│   │   ├── storage.py + storage_providers.py   ชั้นเก็บข้อมูลกลาง: JSONStorage / RedisStorage / UnavailableStorage
│   │   ├── adapter.py  http_headers.py  session_cookie.py  rate_limit.py  health.py  dev_tools.py   (Finale: transport กลาง, header, cookie, rate limit, health, dev mailbox)
│   │   ├── artwork_files.py  file_storage.py                      (Finale: อัปโหลด/ลายน้ำ/ส่งมอบ + Local/Vercel Blob)
│   │   ├── logger.py          audit log + dev log
│   │   └── errors.py  utils.py
│   ├── data/                  *.json (สร้างอัตโนมัติ ไม่ commit)
│   └── tests/test_backend.py  test_security.py  test_finale.py  fake_upstash.py
├── training/console_menu.py   เมนู console สำหรับสาธิต
├── public/                    หน้า HTML + style.css
├── src/                       frontend
│   ├── api/                   httpClient / remoteApi / mockApi / index (ตัวเลือกโหมด) / cart
│   ├── ui/ app.js             หน้าจอ + ปุ่มต่าง ๆ
│   └── services/ core/ data/  prototype Phase 2 เดิม (ใช้เป็น MOCK fallback)
└── docs/ARCHITECTURE.md, SECURITY_STATUS.md, FINAL_REPORT_FINALE_PART1.md, PHASE_3_5.md, FINAL_REPORT_PHASE_3_5.md
```

## 13. ข้อจำกัดที่ควรรู้
ดูรายการเต็มใน `docs/ARCHITECTURE.md` หัวข้อ "ข้อจำกัดของ Phase นี้" และ `docs/PHASE_3_5.md` หัวข้อ 7-8 (เช่น commission ยังเป็นข้อมูลจำลอง, ยังไม่มี rate limit ของ login, ยังไม่ได้ลองบน Vercel/มือถือจริง)
