# VERCEL_DEPLOYMENT.md - วิธี deploy Art 4 Sells (Finale Prototype) ขึ้น Vercel

> **สถานะตรงไปตรงมา:** ขั้นตอนนี้ **ยังไม่เคยถูกทดสอบบน Vercel จริง** — ผมทดสอบเฉพาะในเครื่อง (backend + เทสต์ที่ใช้ Redis/Blob จำลอง) เอกสารนี้จึงเป็น "วิธีที่ออกแบบไว้ + รายการตรวจหลัง deploy" ห้ามอ้างว่า deploy สำเร็จจนกว่าคุณจะทำ **รายการตรวจหลัง deploy (หัวข้อ 4) ผ่านครบด้วยตัวเอง** ระบบนี้เป็น Prototype ไม่ใช่ Production

## 00. Deploy ทันที (ไม่ต้องตั้งค่าอะไรเลย) - โหมด DEMO
1. อัปโหลดโฟลเดอร์นี้ขึ้น GitHub (ตัวไฟล์ `.gitignore` กันข้อมูล/ความลับให้แล้ว)
2. Vercel → **Add New Project** → เลือก repo → กด **Deploy** (Framework Preset: **Other**, ไม่ต้องกรอก Environment Variables)
3. เปิด `https://<โปรเจกต์>.vercel.app` → ล็อกอินด้วยบัญชีตัวอย่างใน README ได้ทันที

**โหมด DEMO ทำงานเมื่อ:** รันบน Vercel + ไม่ได้ตั้ง `A4S_STORAGE` + ยังไม่ได้ต่อ Upstash Redis  
- ข้อมูล (ผู้ใช้ ออเดอร์ session ฯลฯ) เก็บเป็น JSON ใน `/tmp` ของ Function และ seed ข้อมูลตัวอย่างให้เอง ตอน cold start ครั้งแรก
- **ข้อมูลชั่วคราว:** หายเมื่อ Vercel รีสตาร์ท/สลับ instance (เช่น ไม่มีคนใช้สักพัก) และอาจเห็นข้อมูลไม่ตรงกันถ้ามีหลาย instance — ใช้สาธิต/ส่งงานได้ ไม่เหมาะกับข้อมูลจริง
- ไฟล์ภาพที่อัปโหลดอยู่ใน `/tmp` ด้วย (ชั่วคราวเช่นกัน)
- `/api/health` จะแสดง `"demo_mode": true, "persistent": false, "deployment_ready": false` ให้รู้ว่าอยู่ในโหมดนี้
- **อยากให้ข้อมูลถาวร:** Project → Storage → เพิ่ม **Upstash Redis** แล้ว Redeploy — ระบบสลับไปใช้ Redis เองอัตโนมัติ (ดูหัวข้อ 0) และเพิ่ม Vercel Blob + `BLOB_READ_WRITE_TOKEN` ถ้าต้องการให้ไฟล์ภาพถาวร
- ถ้าตั้ง `A4S_STORAGE` เองแล้วตั้งค่าไม่ครบ ระบบยังตอบ 503 เหมือนเดิม (ไม่ถอยมาใช้ DEMO เงียบ ๆ)
- รหัสผ่านบัญชีตัวอย่างเป็นค่าสาธารณะ (อยู่ใน README) — ตั้ง `A4S_DEMO_PASSWORD` ได้ถ้าไม่ต้องการให้คนอื่นล็อกอินเป็น admin

## 0. ทางลัด (ให้ข้อมูลถาวร: ต่อ Upstash Redis)
1. Import repo เข้า Vercel (Framework Preset: **Other**, Root Directory: ว่าง = ราก repo ที่มีโฟลเดอร์ `public/`, `src/`, `api/`)
2. Project → **Storage** → เพิ่ม **Upstash Redis** แล้วผูกกับโปรเจกต์ (Vercel จะใส่ตัวแปรให้เอง)
3. (แนะนำ) ตั้ง `A4S_DEMO_PASSWORD` เป็นรหัสของคุณเอง แล้ว **Redeploy**
- บน Vercel **ไม่ต้องตั้ง `A4S_STORAGE` เอง** (เมื่อต่อ Upstash แล้ว ค่าเริ่มต้นคือ `redis`; ถ้ายังไม่ต่อ = โหมด DEMO ด้านบน)
- ไม่มี Blob ก็เปิดเว็บ/ล็อกอิน/ซื้อขายได้ (อัปโหลดภาพงานเท่านั้นที่ยังไม่ได้ จนกว่าจะตั้ง `BLOB_READ_WRITE_TOKEN`)
- เปิด `https://<โปรเจกต์>.vercel.app/api/health` ต้องเห็น `"ok": true`; ถ้าเป็น 503 ดู `storage_error` ในหัวข้อ 5

## 1. สถาปัตยกรรมที่ deploy
```
GitHub Repository
      ↓
Vercel
  ├── Frontend (public/ + src/ เป็นไฟล์ static)      /  →  dist/index.html (buildCommand คัดลอกเนื้อหา public/ ไปราก dist/ และคัดลอก src/ ไป dist/src/)
  └── Python Function  api/index.py                  /api/*
            ↓
      backend/modules/adapter.py → api.dispatch() → Business Logic เดิม (backend/modules/)
            ↓
      Storage Abstraction ── A4S_STORAGE=redis ──→ Upstash Redis (ข้อมูล)
      File Storage        ── (อัตโนมัติบน Vercel) → Vercel Blob แบบ Private (ไฟล์ภาพ)
```
`backend/server.py` ใช้เฉพาะตอนพัฒนาในเครื่อง — Vercel ไม่เรียกไฟล์นี้ ไม่มีการเขียน disk ของ Function เป็นที่เก็บถาวร (ถ้า config ผิด ระบบตอบ 503 แทนที่จะถอยไปใช้ JSON/disk เงียบ ๆ)

## 2. เตรียมก่อน deploy
1. `python scripts/check_vercel_ready.py` ต้องไม่มี `FAIL` (ผลสุดท้าย `WARN` เป็นปกติ เพราะสคริปต์ตรวจได้แค่ไฟล์ในเครื่อง)
2. `python backend/tests/test_backend.py` และ `node src/test/run.js` ผ่านทั้งหมด (ต้องติดตั้ง `Pillow` ก่อนสำหรับเทสต์ส่วนไฟล์ภาพ: `pip install Pillow`)
3. push ขึ้น GitHub — **ห้ามมี** `.env`, `.env.local`, token, รหัสผ่านจริงใน repo (`.gitignore` กันไว้แล้ว และสคริปต์ตรวจให้)

## 3. ตั้งค่าบน Vercel
1. **Import** repository เป็น Project ใหม่ (Framework Preset: Other) — `vercel.json` กำหนด build/route ให้แล้ว
2. **Redis**: Storage / Marketplace → เพิ่ม **Upstash Redis** แล้วผูกกับ Project → จะได้ตัวแปร `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` (ถ้า integration ตั้งชื่อ `KV_REST_API_URL` / `KV_REST_API_TOKEN` ระบบรองรับให้ด้วย)
3. **Blob**: Storage → สร้าง **Blob store ชนิด Private** → ได้ `BLOB_READ_WRITE_TOKEN`
4. **Environment Variables** (Project Settings → Environment Variables):

| ตัวแปร | ค่า | หมายเหตุ |
|---|---|---|
| `A4S_STORAGE` | `redis` | ไม่ต้องตั้งบน Vercel (ค่าเริ่มต้นคือ `redis`) — ถ้าตั้งเป็น `json` บน Vercel ระบบจะตอบ 503 (ตั้งใจ) |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | จาก Upstash | **จำเป็น** (ห้ามใส่ในโค้ด) |
| `BLOB_READ_WRITE_TOKEN` | จาก Blob store | จำเป็นถ้าจะอัปโหลดภาพ (ไม่มี = อัปโหลดตอบ 503) |
| `A4S_DEMO_PASSWORD` | รหัสของคุณเอง (ผ่าน Password Policy) | **ตั้งก่อน deploy ครั้งแรก** — seed จะใช้รหัสนี้กับบัญชี demo ทุกตัว; ถ้าไม่ตั้ง รหัสคือ `Demo1234!` ซึ่งเป็นความรู้สาธารณะ (ใครก็ login เป็น admin ได้) |
| `A4S_EMAIL_MODE` | `development` | ยังไม่มี provider อีเมลจริง |
| `A4S_DEV_TOOLS` | `true` เฉพาะตอนทดสอบ Forgot Password | เปิด Developer OTP Mailbox (admin เท่านั้น) — **ทดสอบเสร็จตั้งกลับเป็น `false`** |
| `A4S_CORS_ORIGINS` | เว้นว่าง | frontend/API อยู่โดเมนเดียวกัน ไม่ต้องเปิด CORS |
| `A4S_PBKDF2_ITERATIONS` | เว้นว่าง (ค่าเริ่มต้น 600000) | อย่าลดบนระบบที่ใช้จริง |

หลังแก้ env ต้อง **Redeploy** ให้มีผล

## 4. รายการตรวจหลัง deploy (ทำเองตามลำดับ — ผ่านครบจึงบอกได้ว่า "ทดสอบแล้ว")
ใช้ `https://<โปรเจกต์ของคุณ>.vercel.app` แทน `$URL`

| # | คำสั่ง / การกระทำ | ผลที่ถูกต้อง |
|---|---|---|
| 1 | เปิด `$URL/` | เห็นหน้าแรก (ไม่ใช่ 404 / ไม่ใช่ JSON) |
| 2 | `curl -i $URL/api/health` | 200, `"storage":"redis"`, `"storage_available":true`, `"deployment_ready":true`, `"mode":"vercel"`, **ไม่มี** token/URL/path ใน body; มี header `Content-Security-Policy` |
| 3 | `curl $URL/api/artworks` | 200 + รายการงาน (ครั้งแรกอาจช้า: ระบบ seed ข้อมูลตัวอย่างลง Redis ครั้งเดียว) |
| 4 | `curl -i -X POST $URL/api/login -H "Content-Type: application/json" -H "Origin: $URL" -d '{"email":"buyer@art4sells.test","password":"<A4S_DEMO_PASSWORD>"}'` | 200, มี `Set-Cookie: a4s_session=...; HttpOnly; Secure; SameSite=Lax; Path=/` และ **ไม่มี** `token` ใน JSON |
| 5 | login ด้วยรหัสผิด | 401 ข้อความเดียวกับอีเมลที่ไม่มีในระบบ; ผิดซ้ำ 5 ครั้ง → 429 |
| 6 | `curl -i -X POST $URL/api/register ...` (JSON ถูกต้อง, role USER/ARTIST) | 201 + cookie; role `ADMIN` ถูกปฏิเสธ |
| 7 | ในเบราว์เซอร์: login แล้ว reload หน้า | ยังล็อกอินอยู่ (ถามจาก `/api/me` ด้วย cookie); DevTools → Application → Local Storage **ไม่มี** token |
| 8 | Logout แล้ว reload | ไม่ล็อกอิน; cookie ถูกล้าง |
| 9 | Forgot password (ตั้ง `A4S_DEV_TOOLS=true` ชั่วคราว): ขอรหัส → login เป็น admin → แท็บ **Dev Mailbox** | เห็น OTP ของอีเมลนั้น; ใช้ตั้งรหัสใหม่ได้; ใช้ซ้ำไม่ได้ |
| 10 | ตั้ง `A4S_DEV_TOOLS=false` แล้ว redeploy → `GET /api/dev/mailbox` | 404 |
| 11 | ศิลปิน login → สร้างงาน → อัปโหลดภาพ (`POST /api/artworks/:id/file`) | 201; `GET /api/artworks/:id/preview` เห็นภาพมีลายน้ำ; `/original` ใช้ได้เฉพาะเจ้าของ/admin |
| 12 | ผู้ซื้อสั่งงาน → ยังไม่ชำระ → `GET /api/orders/:oid/artworks/:aid/download` | 403; admin ยืนยัน `PAYMENT_VERIFIED` แล้วดาวน์โหลดได้ |
| 13 | ลบ env `UPSTASH_REDIS_REST_URL` (ทดสอบ) แล้ว redeploy → `GET /api/health` | 503, `"storage_available":false`, `"deployment_ready":false`, `"storage_error":"REDIS_NOT_CONFIGURED"` (แล้วใส่คืน) |

## 5. อ่านผล `/api/health` เมื่อมีปัญหา
| `storage_error` | ความหมาย | แก้ |
|---|---|---|
| `REDIS_NOT_CONFIGURED` | ไม่มี URL/token | ตั้ง env แล้ว redeploy |
| `REDIS_URL_INVALID` | URL ไม่ใช่ `https://` | ตรวจ `UPSTASH_REDIS_REST_URL` |
| `REDIS_UNREACHABLE` | ต่อ Redis ไม่ได้ / token ผิด | ตรวจ token และสถานะ Upstash |
| `JSON_STORAGE_NOT_ALLOWED_ON_VERCEL` | `A4S_STORAGE` ไม่ใช่ `redis` บน Vercel | ตั้ง `A4S_STORAGE=redis` |
| `STORAGE_PROVIDER_UNSUPPORTED` | ค่า `A4S_STORAGE` ผิด | ใช้ `json` หรือ `redis` |

## 6. ข้อจำกัดที่ต้องรู้ก่อนใช้งาน
- **ขนาดข้อมูล**: แต่ละ collection บน Redis จำกัด ~900 KB (ระบบปฏิเสธการเขียนที่เกินด้วย 507 แทนที่จะเขียนพัง); เหมาะเดโม/prototype
- **อัปโหลดภาพ**: Vercel จำกัดขนาด request ราว 4.5 MB และระบบส่งไฟล์เป็น base64 ใน JSON → ภาพจริงควรไม่เกิน ~3 MB
- **Cold start ครั้งแรก**: seed ข้อมูลตัวอย่างต้อง hash รหัสผ่านหลายบัญชี (PBKDF2 600,000 รอบ) อาจใช้เวลาหลายวินาที และ login ทุกครั้งใช้เวลาประมาณหนึ่งในห้าวินาทีบนเครื่องที่ผมวัด (ยังไม่ได้วัดบน Vercel)
- **ไม่ได้ทดสอบ**: Vercel runtime, Upstash ตัวจริง, Vercel Blob ตัวจริง — ลายเซ็นของ `vercel.blob.put` (`access="private"`, `token=`) และการอ่าน private blob ด้วย `Authorization: Bearer` อ้างจากเอกสารตอนเขียน ถ้าข้อ 11 ใน checklist ล้มเหลว ให้ดู Function Logs ก่อน (ปัญหาน่าจะอยู่ที่ `backend/modules/file_storage.py` ส่วน `VercelBlobStore`)
- OTP ในโหมด development ถูกพิมพ์ลง **Function Logs** ของ Vercel (ผู้มีสิทธิ์ดู log ของโปรเจกต์เห็นได้) — ใช้เฉพาะทดสอบ
