"""security.py - ส่วนที่เกี่ยวกับความปลอดภัยโดยเฉพาะ (แยกไว้เพื่อให้ Phase Security ต่อยอดได้)

- เก็บรหัสผ่านแบบ hash (PBKDF2-HMAC-SHA256 + salt สุ่ม) ห้ามเก็บ plaintext
- session token สุ่มด้วย secrets และเก็บเฉพาะค่า hash ของ token ในไฟล์
ใช้เฉพาะ Python Standard Library
"""
import hashlib
import hmac
import secrets

from backend import config

HASH_NAME = "pbkdf2_sha256"
_dummy_hash_cache = []


def hash_password(password, iterations=None):
    """แปลงรหัสผ่านเป็นข้อความ hash
    รูปแบบ: pbkdf2_sha256$<รอบ>$<salt hex>$<hash hex>  (เก็บจำนวนรอบไว้ด้วย เพื่อปรับเพิ่มได้ในอนาคต)
    """
    rounds = iterations or config.PASSWORD_ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "$".join([HASH_NAME, str(rounds), salt.hex(), digest.hex()])


def verify_password(password, stored_hash):
    """ตรวจรหัสผ่านที่ผู้ใช้กรอก เทียบกับ hash ที่เก็บไว้ คืน True/False"""
    try:
        name, rounds_text, salt_hex, digest_hex = stored_hash.split("$")
        rounds = int(rounds_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False                                   # รูปแบบ hash เสีย -> ถือว่าไม่ผ่าน
    if name != HASH_NAME or not (1 <= rounds <= 10_000_000):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)       # เทียบแบบเวลาคงที่ กัน timing attack


def get_dummy_hash():
    """hash ปลอมไว้ใช้ตอนไม่พบอีเมล เพื่อให้เวลาตอบใกล้เคียงกับกรณีมีอีเมล (ไม่เผยว่าอีเมลมีในระบบหรือไม่)"""
    if not _dummy_hash_cache:
        _dummy_hash_cache.append(hash_password("not-a-real-password"))
    return _dummy_hash_cache[0]


def new_session_token():
    """สร้าง token สุ่มสำหรับ session (เดาไม่ได้)"""
    return secrets.token_urlsafe(32)


def hash_token(token):
    """hash ของ token - ในไฟล์ sessions.json เก็บค่านี้ ไม่เก็บ token จริง"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# OTP / token ใช้ครั้งเดียว (ใช้ hash เดิมของระบบ ไม่สร้างอัลกอริทึมใหม่)
# ---------------------------------------------------------------------------
def new_otp_code():
    """สร้างรหัส OTP ตัวเลข config.OTP_LENGTH หลัก ด้วย secrets (สุ่มแบบ cryptographic ทายไม่ได้)"""
    return "".join(str(secrets.randbelow(10)) for _ in range(config.OTP_LENGTH))


def hash_otp(code):
    """hash ของ OTP - ใช้ PBKDF2 เดียวกับรหัสผ่าน (OTP 5 หลักมีแค่ 100,000 ค่า จึงต้องมี salt + hash หนัก)"""
    return hash_password(code)


def verify_otp(code, stored_hash):
    return verify_password(code, stored_hash)


def new_secret_token():
    """token สุ่มสำหรับ reset authorization / ขั้นยืนยันของ admin (ส่งให้ client ครั้งเดียว เก็บเฉพาะ hash)"""
    return secrets.token_urlsafe(32)
