# Phase 3.5b — Login Authentication Hardening + Password Policy

ต่อยอดจาก Phase 3.5 โดยไม่เปลี่ยน architecture ลำดับความสำคัญ: Authentication Correctness > Security > Password Policy > UX > Academic Traceability

## ปัญหาที่พบ
| ที่ | ปัญหา |
|---|---|
| `src/services/authService.js` (MOCK) | `login()` เช็คแค่ว่าอีเมลมีอยู่ ใส่รหัสอะไรก็เข้าได้ (บัญชี demo ด้วย) และหน้า Login เขียนว่า "Any 8+ character password" |
| `backend/modules/validation.py` | policy เดิมขอแค่ตัวอักษร + ตัวเลข; register ไม่เช็ค confirm password |
| `login.html` | ไม่มีทางเข้า Forgot Password |
Backend (`auth.login()`) ตรวจ PBKDF2 จริงอยู่แล้ว ไม่มี logic ที่ใช้อีเมลเป็นเงื่อนไขผ่าน

## สิ่งที่ทำ
1. **Mock auth ปิด** — secure mock ต้องเก็บ hash ใน browser จึงเลือกทางที่ spec อนุญาต: `AuthService.login()/register()` คืน error "ต้องใช้ backend จริง", หน้า Login/Register ใน MOCK แสดงข้อความนี้แทนฟอร์ม, และเมื่อเข้า MOCK จะล้าง session เก่าทิ้ง ไม่มี fallback จาก backend ไม่ตอบ → login แบบไม่ปลอดภัย
2. **Password policy กลาง** `validation.validate_password()` (ตัวเดียว): 8–128 ตัว + a-z, A-Z, 0-9, อักษรพิเศษ ASCII ใช้ใน register, admin สร้าง user, change password, reset password (ฝั่ง JS มี `Validation.PASSWORD_RULES` ไว้ช่วย UX; backend ตรวจซ้ำ)
3. **Confirm password** — register ส่ง `confirm_password` และต้องตรงทุกตัวอักษร (change/reset มีอยู่แล้ว)
4. **รหัสผ่านเป็นค่าลับ** — ไม่ strip / lower / upper ทั้งตอนตั้งและตอน login (`"Abcd1234!"` กับ `"Abcd1234! "` เป็นคนละรหัส); login ไม่ใช้ policy และตอบข้อความกลาง "อีเมลหรือรหัสผ่านไม่ถูกต้อง"
5. **บัญชีตัวอย่าง** — รหัส `Demo1234!` (seed, เก็บเป็น hash); seed ปฏิเสธรหัสตัวอย่างที่ผิด policy; หน้า Login แสดง demo credential เฉพาะ localhost
6. **UI** — ลิงก์ "Forgot password?" ใต้ช่อง Password → `forgot.html`; Register / Forgot / Settings แสดงเงื่อนไขรหัสผ่านชุดเดียวกัน

## ไฟล์ / function หลัก
- Backend: `modules/validation.py` (`password_problems`, `validate_password`, `validate_user_data`, `validate_login`), `modules/user.py` (`create_user`), `modules/auth.py` (`register_user`), `seed.py` (`build_users`)
- Frontend: `src/core/validation.js`, `src/services/authService.js`, `src/api/index.js`, `src/api/remoteApi.js`, `src/ui/pages/pages.js`
- Tests: `backend/tests/test_security.py` (ส่วน Phase 3.5b), `backend/tests/test_backend.py`, `src/test/run.js`

## ผลทดสอบ
| ชุด | ก่อน | หลัง |
|---|---|---|
| `python backend/tests/test_backend.py` (รวม security) | 109/109 | 122/122 |
| `node src/test/run.js` | 14/14 | 27/27 |

test เดิมที่แก้ (ไม่ได้ลบ): ใช้รหัสเก่าที่ไม่มีอักษรพิเศษ / register ไม่ส่ง `confirm_password` จึงเปลี่ยนเป็นรหัสที่ผ่าน policy และเติม confirm ; test frontend 2 ตัว (Auth, Audit log) เคย login แบบไม่ตรวจรหัสเพื่อสวมบทบาท จึงเปลี่ยนเป็นดึง fixture ตรง ๆ

## ข้อจำกัดที่ทราบ
- `backend/data/` เก่าที่ seed ด้วย `Demo1234` ต้องรัน `python backend/seed.py --reset` ใหม่
- บัญชีเก่าที่รหัสอ่อนยัง login ได้จนกว่าจะเปลี่ยนรหัส (login ไม่ใช้ policy ตาม spec)
- "อักษรพิเศษ" นับเฉพาะเครื่องหมาย ASCII ; ยังไม่มี rate limit ของ login ; ยังไม่ได้ทดสอบหน้าเว็บในเบราว์เซอร์จริงสำหรับรอบนี้ (ใช้ Node + DOM จำลอง)
