"""email_service.py - ชั้นส่งอีเมล (Email abstraction)

Business logic เรียกเฉพาะ send_password_reset_code() - ไม่รู้ว่าส่งอย่างไร
    วันนี้ : EMAIL_MODE = "development"  -> พิมพ์อีเมลลงหน้าจอ server (DEV ONLY ไม่ได้ส่งออกจริง)
    อนาคต : เพิ่ม transport ของผู้ให้บริการจริง แล้วตั้ง config.EMAIL_MODE  (ไม่ต้องแก้ logic การกู้รหัสผ่าน)

Developer OTP Mailbox: ถ้า A4S_EMAIL_MODE=development และ A4S_DEV_TOOLS=true จะเก็บสำเนา "อีเมลจำลอง" ไว้ใน collection dev_mailbox
ให้ ADMIN เปิดดูผ่าน /api/dev/mailbox (เพื่อทดสอบ Forgot Password บน Vercel Prototype ที่ไม่มีหน้าจอ server ให้ดู)
โหมด production ไม่เก็บ OTP ที่ไหนเลย และไม่ส่งอีเมลจนกว่าจะเพิ่ม provider จริง

ข้อกำหนด: ห้ามใส่ SMTP password / API key ในโค้ด (ให้อ่านจาก environment variable ใน Phase ที่ทำ provider จริง)
ห้ามส่ง OTP กลับทาง API และห้ามเขียน OTP ลง audit log / server.log
"""
import sys

from backend import config
from backend.modules import logger, storage
from backend.modules.utils import minutes_from_now_iso, now_iso

_transport = None          # ฟังก์ชัน(message: dict) ที่ตั้งจากภายนอก (ใช้ในเทสต์ หรือ provider จริงในอนาคต)


def set_transport(func):
    """ตั้งวิธีส่งอีเมล (None = กลับไปใช้ค่าตาม EMAIL_MODE)"""
    global _transport
    _transport = func


def _dev_transport(message):
    """DEV ONLY: พิมพ์อีเมลลง stderr (ไม่ผ่าน logger เพื่อไม่ให้ OTP ไปอยู่ในไฟล์ server.log)"""
    lines = ["", "=" * 60, "[DEV ONLY - EMAIL NOT SENT]  To: " + message["to"], "Subject: " + message["subject"],
             message["body"], "=" * 60, ""]
    print("\n".join(lines), file=sys.stderr, flush=True)


def build_reset_code_message(to_email, code, lifetime_minutes):
    """สร้างอีเมลแบบ plain text (ไม่ใช้ HTML จึงไม่มีเรื่อง escape ค่าที่ผู้ใช้กรอก)"""
    return {
        "to": to_email,
        "subject": "Art 4 Sells - รหัสยืนยันสำหรับตั้งรหัสผ่านใหม่",
        "body": "รหัสยืนยันของคุณคือ " + code + "\nรหัสนี้ใช้ได้ " + str(lifetime_minutes)
                + " นาที และใช้ได้ครั้งเดียว\nหากคุณไม่ได้ขอรหัสนี้ ให้เพิกเฉยต่ออีเมลฉบับนี้",
    }


def _store_dev_mail(to_email, code, lifetime_minutes, purpose):
    """DEV ONLY: เก็บสำเนาอีเมลจำลองให้ admin ดู (เรียกเฉพาะเมื่อ config.dev_mailbox_enabled() เท่านั้น)"""
    storage.create_record("dev_mailbox", {
        "recipient": to_email, "created_at": now_iso(), "expires_at": minutes_from_now_iso(lifetime_minutes),
        "otp": code, "purpose": purpose}, "mb")


def send_password_reset_code(to_email, code, lifetime_minutes):
    """ส่งรหัส OTP ไปยังอีเมล  คืน True ถ้าส่งต่อให้ transport สำเร็จ / False ถ้าส่งไม่ได้ (ไม่ raise)"""
    message = build_reset_code_message(to_email, code, lifetime_minutes)
    try:
        if config.dev_mailbox_enabled():                   # ปิดอยู่เป็นค่าเริ่มต้น และไม่มีทางเปิดในโหมด production
            _store_dev_mail(to_email, code, lifetime_minutes, "PASSWORD_RESET")
        if _transport is not None:
            _transport(message)
        elif config.EMAIL_MODE == "development":
            _dev_transport(message)
        else:
            logger.log_info("EMAIL_MODE=" + str(config.EMAIL_MODE) + " ยังไม่มี provider จริง - ไม่ได้ส่งอีเมล")
            return False
        return True
    except Exception as err:                               # ส่งอีเมลไม่ได้ต้องไม่ทำให้ request ล้ม
        logger.log_exception("send_password_reset_code failed", err)
        return False
