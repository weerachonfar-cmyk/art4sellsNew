"""validation.py - ตรวจความถูกต้องของข้อมูล + แปลงชนิดข้อมูล (type conversion)

รูปแบบการคืนค่า (สม่ำเสมอทั้งไฟล์):
- to_xxx(raw)            -> tuple (ค่าที่แปลงแล้ว, error)   ถ้าแปลงไม่ได้ ค่า = None
- validate_field(value)  -> ข้อความ error (str) หรือ None ถ้าถูกต้อง
- validate_entity(data)  -> tuple (clean_data, errors)       errors = dict {ชื่อช่อง: ข้อความ}
"""
import math
import re
import string
import unicodedata
from urllib.parse import urlsplit

from backend import config

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?\.)+[A-Za-z0-9\-]{2,}", re.ASCII)   # อีเมลต้องเป็น ASCII เท่านั้น: ห้ามอีโมจิ/อักขระพิเศษอื่น           # ใช้กับ fullmatch เสมอ (ไม่ใช้ ^ $ เพราะ $ ยอมให้มี \n ต่อท้าย)
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")           # id ที่ระบบสร้างเอง: ตัวอักษร/ตัวเลข/_/- เท่านั้น
BIDI_CONTROLS = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")   # ตัวควบคุมทิศทางข้อความ (ใช้หลอกตาได้)
MULTILINE_OK = {"\n", "\r", "\t"}
TRUE_WORDS = {"true", "1", "yes", "on"}
FALSE_WORDS = {"false", "0", "no", "off"}
PASSWORD_LOWER = frozenset(string.ascii_lowercase)              # a-z   (ตรวจแบบ ASCII ตรง ๆ ไม่ใช้ isupper()/isdigit() เพราะรับอักขระ Unicode ที่ไม่ใช่ A-Z / 0-9)
PASSWORD_UPPER = frozenset(string.ascii_uppercase)              # A-Z
PASSWORD_DIGIT = frozenset(string.digits)                       # 0-9
PASSWORD_SPECIAL = frozenset(string.punctuation)                # อักษรพิเศษ = เครื่องหมายวรรคตอน ASCII เช่น ! @ # $ % ^ & * ( )  (ช่องว่างไม่นับ)


# ---------------------------------------------------------------------------
# แปลงชนิดข้อมูล (int / float / bool / str)
# ---------------------------------------------------------------------------
def to_float(raw):
    """แปลงเป็น float (เช่น ราคาที่มาจากฟอร์มเป็นข้อความ "1200.50")
    ปฏิเสธ: None, bool, ข้อความที่ไม่ใช่เลข, NaN และ Infinity
    """
    if raw is None or isinstance(raw, bool):
        return None, "ต้องเป็นตัวเลข"
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):        # OverflowError: จำนวนเต็มใหญ่เกินกว่าจะเป็น float (เช่น 10**400)
        return None, "ต้องเป็นตัวเลข"
    if not math.isfinite(value):
        return None, "ต้องเป็นตัวเลขที่ถูกต้อง"
    return value, None


def to_int(raw):
    """แปลงเป็น int (เช่น page=2 จาก URL เป็นข้อความ)
    ปฏิเสธ: None, bool, เลขทศนิยมที่ไม่ลงตัว (4.5), ข้อความที่ไม่ใช่เลข
    """
    if raw is None or isinstance(raw, bool):
        return None, "ต้องเป็นจำนวนเต็ม"
    if isinstance(raw, float):
        if not raw.is_integer():
            return None, "ต้องเป็นจำนวนเต็ม"
        return int(raw), None
    try:
        return int(str(raw).strip()), None
    except ValueError:
        return None, "ต้องเป็นจำนวนเต็ม"


def to_bool(raw):
    """แปลงเป็น bool: รับ True/False หรือข้อความ true/false/1/0/yes/no/on/off"""
    if isinstance(raw, bool):
        return raw, None
    word = str(raw).strip().lower()
    if word in TRUE_WORDS:
        return True, None
    elif word in FALSE_WORDS:
        return False, None
    else:
        return None, "ต้องเป็น true หรือ false"


def has_control_chars(text, allow_newlines=False):
    """True ถ้ามีอักขระควบคุม (Cc) หรือตัวควบคุมทิศทางข้อความ
    allow_newlines=True (ช่องหลายบรรทัด เช่น คำอธิบาย) อนุญาตเฉพาะ ขึ้นบรรทัดใหม่/tab
    """
    for ch in text:
        if ch in BIDI_CONTROLS:
            return True
        if ch in MULTILINE_OK and allow_newlines:
            continue
        if unicodedata.category(ch) == "Cc":
            return True
    return False


def clean_text(value):
    """ทำให้ข้อความเป็นรูปแบบมาตรฐาน: Unicode NFC + ตัดช่องว่างหัวท้าย (ใช้กับช่องข้อความทั่วไปเท่านั้น ไม่ใช้กับรหัสผ่าน)
    ไม่ลบ/แก้อักขระอื่น เพราะผู้ใช้อาจตั้งใจใช้ (ภาษาไทย, emoji, เครื่องหมายพิเศษ)
    """
    return unicodedata.normalize("NFC", str(value)).strip()


def validate_required(value, label):
    """ช่องบังคับกรอก: None / ข้อความว่าง / มีแต่ช่องว่าง -> error  (ไม่ใช่ -> None)"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "กรุณากรอก" + label
    return None


def validate_length(text, label, min_len, max_len):
    """ตรวจความยาวข้อความ (นับหลัง normalize แล้ว) -> error หรือ None"""
    if len(text) < min_len:
        if min_len <= 1:
            return "กรุณากรอก" + label
        return label + "ต้องมีอย่างน้อย " + str(min_len) + " ตัวอักษร"
    if len(text) > max_len:
        return label + "ยาวเกินไป (ไม่เกิน " + str(max_len) + " ตัวอักษร)"
    return None


def validate_string(value, label, min_len=0, max_len=100, single_line=True):
    """ตรวจข้อความทั่วไป คืนข้อความ error หรือ None
    ชนิดต้องเป็น str จริง (หรือ None = ว่าง) - ตัวเลข/list/dict จะไม่ถูกแปลงเป็นข้อความเงียบ ๆ
    """
    if value is not None and not isinstance(value, str):
        return label + "ต้องเป็นข้อความ"
    text = "" if value is None else clean_text(value)
    problem = validate_length(text, label, min_len, max_len)
    if problem:
        return problem
    if has_control_chars(text, allow_newlines=not single_line):
        return label + "มีอักขระที่ไม่อนุญาต"
    return None


check_text = validate_string          # ชื่อเดิมที่ module อื่นเรียกใช้อยู่ (ตัวเดียวกัน ไม่ใช่โค้ดซ้ำ)


def validate_integer(value, label, minimum=None, maximum=None):
    """ตรวจจำนวนเต็มและช่วงค่า  คืน tuple (ค่า int, error)  ปฏิเสธ bool / 1.5 / ข้อความที่ไม่ใช่เลข"""
    number, problem = to_int(value)
    if problem:
        return None, label + "ต้องเป็นจำนวนเต็ม"
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        return None, label + "ต้องอยู่ระหว่าง " + str(minimum) + " ถึง " + str(maximum)
    return number, None


def validate_float(value, label, minimum=None, maximum=None):
    """ตรวจเลขทศนิยมและช่วงค่า  คืน tuple (ค่า float, error)  ปฏิเสธ NaN / Infinity / bool"""
    number, problem = to_float(value)
    if problem:
        return None, label + "ต้องเป็นตัวเลข"
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        return None, label + "ต้องอยู่ระหว่าง " + str(minimum) + " ถึง " + str(maximum)
    return number, None


def validate_boolean(value, label, from_query=False):
    """ตรวจค่า true/false  คืน tuple (bool, error)
    - JSON body: ต้องเป็น true/false จริง ๆ เท่านั้น ("true", 1, "1", null, [], {} ไม่ถือเป็น boolean โดยอัตโนมัติ)
    - query string (from_query=True): ทุกค่าเป็นข้อความอยู่แล้ว จึงรับ true/false/1/0/yes/no
    """
    if isinstance(value, bool):
        return value, None
    if from_query and isinstance(value, str):
        converted, problem = to_bool(value)
        if not problem:
            return converted, None
    return None, label + " ต้องเป็น true หรือ false"


def validate_price(value):
    """ราคา: ตัวเลข finite (ไม่ NaN/Infinity), 0 ถึง PRICE_MAX, ปัดทศนิยม 2 ตำแหน่ง  คืน tuple (price, error)"""
    price, problem = to_float(value)
    if problem:
        return None, "ราคาต้องเป็นตัวเลข"
    if price < 0:
        return None, "ราคาต้องไม่ต่ำกว่า 0"
    if price > config.PRICE_MAX:
        return None, "ราคาสูงเกินไป (ไม่เกิน " + str(config.PRICE_MAX) + ")"
    return round(price, 2), None


def validate_username(value):
    """ชื่อที่แสดง: ข้อความ 2-50 ตัวอักษร รองรับภาษาไทย/Unicode  แสดงผลเป็น plain text เสมอ -> error หรือ None"""
    low, high = config.DISPLAY_NAME_RANGE
    return validate_string(value, "ชื่อที่แสดง", min_len=low, max_len=high)


def validate_artwork_title(value):
    """ชื่องาน: 1-80 ตัวอักษร บรรทัดเดียว -> error หรือ None"""
    return validate_string(value, "ชื่องาน", min_len=1, max_len=80)


def validate_review_text(value):
    """ความเห็นรีวิว: 5-1000 ตัวอักษร ขึ้นบรรทัดใหม่ได้ เป็น plain text -> error หรือ None"""
    return validate_string(value, "ความเห็น", min_len=5, max_len=1000, single_line=False)


def validate_rating(value):
    """คะแนนรีวิว: จำนวนเต็ม 1-5  คืน tuple (rating, error)"""
    rating, problem = validate_integer(value, "คะแนน", 1, 5)
    return rating, ("คะแนนต้องเป็นจำนวนเต็ม 1 ถึง 5" if problem else None)


def validate_quantity(value):
    """จำนวนสินค้า: จำนวนเต็ม 1..MAX_ORDER_QUANTITY  คืน tuple (quantity, error)"""
    quantity, problem = validate_integer(value, "จำนวนสินค้า", 1, config.MAX_ORDER_QUANTITY)
    return quantity, ("จำนวนสินค้าต้องเป็นจำนวนเต็ม 1 ถึง " + str(config.MAX_ORDER_QUANTITY) if problem else None)


def validate_id(value, label="id"):
    """ตรวจรูปแบบ id ที่มาจาก client (ก่อนเอาไปค้นข้อมูล) -> error หรือ None"""
    if not isinstance(value, str) or not value:
        return label + " ไม่ถูกต้อง"
    if len(value) > config.ID_MAX_LENGTH or not ID_PATTERN.fullmatch(value):
        return label + " ไม่ถูกต้อง"
    return None


def validate_choice(value, allowed, label):
    """ค่าต้องอยู่ในรายการที่อนุญาต (allowlist) -> error หรือ None"""
    if not isinstance(value, str) or value not in allowed:
        return label + " ต้องเป็นหนึ่งใน " + ", ".join(sorted(allowed))
    return None


def validate_url(value, label="URL", allowed_schemes=("http", "https"), max_len=2048):
    """ตรวจ URL: ต้องเป็น str, ไม่เกินความยาว, scheme อยู่ใน allowlist (กัน javascript: / data:), ต้องมี host"""
    if not isinstance(value, str) or not value or len(value) > max_len or has_control_chars(value):
        return label + " ไม่ถูกต้อง"
    try:
        parts = urlsplit(value)
    except ValueError:
        return label + " ไม่ถูกต้อง"
    if parts.scheme.lower() not in allowed_schemes or not parts.netloc:
        return label + " ต้องขึ้นต้นด้วย " + " หรือ ".join(s + "://" for s in allowed_schemes)
    return None


def pick_fields(data, allowed):
    """เลือกเฉพาะ field ที่อนุญาต (allowlist) จาก dict ที่ client ส่งมา - field อื่น (role, user_id, is_admin ฯลฯ) ถูกทิ้งทั้งหมด"""
    return {key: data[key] for key in allowed if key in data}


def check_allowed_params(query, allowed):
    """query string ต้องมีเฉพาะพารามิเตอร์ที่ endpoint รู้จัก  คืน dict ของ error (ว่าง = ผ่าน)"""
    return {name: "ไม่รู้จักพารามิเตอร์นี้" for name in query if name not in allowed}


def check_query_values(query):
    """ทุกค่าใน query string: ความยาวไม่เกิน 200 และไม่มีอักขระควบคุม  คืน dict ของ error"""
    errors = {}
    for name, value in query.items():
        if len(str(name)) > 40 or len(str(value)) > 200 or has_control_chars(str(value)):
            errors[str(name)[:40]] = "ค่าไม่ถูกต้อง"
    return errors


# ---------------------------------------------------------------------------
# ตรวจรายช่อง
# ---------------------------------------------------------------------------
def validate_email(email):
    """ตรวจรูปแบบอีเมล -> error หรือ None"""
    if email is not None and not isinstance(email, str):
        return "รูปแบบอีเมลไม่ถูกต้อง"
    text = (email or "").strip()
    if not text:
        return "กรุณากรอกอีเมล"
    if not text.isascii():
        return "อีเมลใช้ได้เฉพาะตัวอักษรภาษาอังกฤษ ตัวเลข และสัญลักษณ์ . _ % + - เท่านั้น (ห้ามใช้อีโมจิ)"
    if len(text) > 254 or not EMAIL_PATTERN.fullmatch(text):
        return "รูปแบบอีเมลไม่ถูกต้อง"
    return None


def _is_utf8_safe(text):
    """True ถ้าข้อความเข้ารหัส UTF-8 ได้ (hash รหัสผ่านต้องใช้ UTF-8; \\ud800 เดี่ยว ๆ จาก JSON เข้ารหัสไม่ได้)"""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def password_problems(password):
    """รายการข้อความ error ของรหัสผ่านที่ไม่ผ่านนโยบาย (ว่าง = ผ่านทุกข้อ)  - นโยบายเดียวของทั้งระบบ

    ข้อกำหนด: 8-128 ตัว + มี a-z, A-Z, 0-9 และอักษรพิเศษอย่างละ 1 ตัวขึ้นไป
    รหัสผ่านเป็นค่าลับ: ห้าม strip/lower/upper/ลบอักขระ - ช่องว่างและทุกอักขระเป็นส่วนหนึ่งของรหัสผ่าน
    """
    if password is not None and not isinstance(password, str):
        return ["รหัสผ่านต้องเป็นข้อความ"]
    text = "" if password is None else password
    if not _is_utf8_safe(text):                           # เข้ารหัสไม่ได้ -> hash ล้ม จึงปฏิเสธตั้งแต่ตรงนี้
        return ["รหัสผ่านมีอักขระที่ไม่รองรับ"]
    problems = []
    if len(text) < config.PASSWORD_MIN_LENGTH:
        problems.append("รหัสผ่านต้องมีอย่างน้อย " + str(config.PASSWORD_MIN_LENGTH) + " ตัวอักษร")
    if len(text) > config.PASSWORD_MAX_LENGTH:
        problems.append("รหัสผ่านต้องไม่เกิน " + str(config.PASSWORD_MAX_LENGTH) + " ตัวอักษร")
    chars = set(text)
    if not chars & PASSWORD_LOWER:
        problems.append("รหัสผ่านต้องมีตัวพิมพ์เล็ก (a-z) อย่างน้อย 1 ตัว")
    if not chars & PASSWORD_UPPER:
        problems.append("รหัสผ่านต้องมีตัวพิมพ์ใหญ่ (A-Z) อย่างน้อย 1 ตัว")
    if not chars & PASSWORD_DIGIT:
        problems.append("รหัสผ่านต้องมีตัวเลข (0-9) อย่างน้อย 1 ตัว")
    if not chars & PASSWORD_SPECIAL:
        problems.append("รหัสผ่านต้องมีอักษรพิเศษ เช่น ! @ # $ % อย่างน้อย 1 ตัว")
    return problems


def validate_password(password):
    """ตรวจรหัสผ่านตามนโยบายกลาง คืนข้อความ error ข้อแรกที่พบ หรือ None ถ้าผ่าน
    (register_user / create_user ของ admin / change_password / reset_password เรียกฟังก์ชันนี้ตัวเดียวกันทั้งหมด)
    """
    problems = password_problems(password)
    return problems[0] if problems else None


def normalize_tags(raw):
    """แปลง tags เป็น list ของข้อความ (ตัวพิมพ์เล็ก ไม่ซ้ำ) รับได้ทั้ง list และข้อความคั่นด้วย ,
    คืนค่า: tuple (tags, error)
    """
    if raw is None or raw == "":
        return [], None
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        return None, "tags ต้องเป็นรายการ"
    tags, seen = [], set()
    for item in raw:
        if not isinstance(item, str):
            return None, "tag ต้องเป็นข้อความ"
        tag = clean_text(item).lower()
        if not tag or tag in seen:
            continue                                   # ข้ามค่าว่างและค่าซ้ำ
        if len(tag) > 30 or has_control_chars(tag) or "," in tag:
            return None, "tag ไม่ถูกต้อง (ยาวไม่เกิน 30 ตัวอักษร)"
        seen.add(tag)
        tags.append(tag)
    if len(tags) > config.MAX_TAGS:
        return None, "ใส่ tag ได้ไม่เกิน " + str(config.MAX_TAGS) + " รายการ"
    return tags, None


# ---------------------------------------------------------------------------
# ตรวจทั้ง entity
# ---------------------------------------------------------------------------
def validate_artwork(data, valid_categories, partial=False):
    """ตรวจข้อมูล Artwork
    พารามิเตอร์: data (dict), valid_categories (set ของ category id ที่มีจริง),
                partial (True = ตรวจเฉพาะช่องที่ส่งมา ใช้ตอนแก้ไข)
    คืนค่า: tuple (clean, errors)
    """
    clean, errors = {}, {}

    def wanted(field):
        return (not partial) or (field in data)

    if wanted("title"):
        problem = validate_artwork_title(data.get("title"))
        if problem:
            errors["title"] = problem
        else:
            clean["title"] = clean_text(data["title"])

    if wanted("description"):
        problem = check_text(data.get("description"), "คำอธิบาย", max_len=2000, single_line=False)
        if problem:
            errors["description"] = problem
        else:
            clean["description"] = clean_text(data.get("description") or "")

    if wanted("category"):
        category = data.get("category")
        if validate_id(category, "หมวดหมู่") or category not in valid_categories:
            errors["category"] = "หมวดหมู่ไม่ถูกต้อง"
        else:
            clean["category"] = category

    if wanted("price"):
        price, problem = validate_price(data.get("price"))
        if problem:
            errors["price"] = problem
        else:
            clean["price"] = price

    if wanted("sale_type"):
        sale_type = data.get("sale_type")
        sale_type = sale_type.strip().upper() if isinstance(sale_type, str) else None
        if sale_type not in config.SALE_TYPES:
            errors["sale_type"] = "ประเภทการขายต้องเป็น LIMITED หรือ UNLIMITED"
        else:
            clean["sale_type"] = sale_type

    if wanted("tags"):
        tags, problem = normalize_tags(data.get("tags"))
        if problem:
            errors["tags"] = problem
        else:
            clean["tags"] = tags

    return clean, errors


def validate_user_data(data, allowed_roles, require_confirm=False):
    """ตรวจข้อมูลสมัครสมาชิก/สร้าง user  คืน (clean, errors)
    allowed_roles = tuple ของ role ที่ยอมให้กำหนด (สมัครเองได้เฉพาะ USER/ARTIST)
    require_confirm = True ตอนสมัครเอง: ต้องมี confirm_password ที่ตรงกับ password ทุกตัวอักษร
    """
    clean, errors = {}, {}

    problem = validate_username(data.get("name"))
    if problem:
        errors["name"] = problem
    else:
        clean["name"] = clean_text(data["name"])

    problem = validate_email(data.get("email"))
    if problem:
        errors["email"] = problem
    else:
        clean["email"] = data["email"].strip().lower()

    problem = validate_password(data.get("password"))
    if problem:
        errors["password"] = problem
    else:
        clean["password"] = data["password"]          # ไม่แก้ไขรหัสผ่านใด ๆ
    if require_confirm and (not isinstance(data.get("confirm_password"), str)
                            or data.get("confirm_password") != data.get("password")):
        errors["confirm_password"] = "รหัสผ่านยืนยันไม่ตรงกัน"       # เทียบตรง ๆ ไม่ strip: "Abcd1234!" กับ "Abcd1234! " คือคนละรหัส

    role = data.get("role", "USER")                    # ไม่ส่งมา = USER  แต่ถ้าส่งมาต้องเป็นข้อความที่อยู่ใน allowlist
    role = role.strip().upper() if isinstance(role, str) else None
    if role not in allowed_roles:
        errors["role"] = "role ต้องเป็นหนึ่งใน " + ", ".join(allowed_roles)
    else:
        clean["role"] = role

    return clean, errors


def validate_login(data):
    """ตรวจข้อมูล login (ไม่ตรวจความซับซ้อนของรหัสผ่านตอน login)"""
    clean, errors = {}, {}
    problem = validate_email(data.get("email"))
    if problem:
        errors["email"] = problem
    else:
        clean["email"] = data["email"].strip().lower()
    password = data.get("password")
    if not password or not isinstance(password, str):
        errors["password"] = "กรุณากรอกรหัสผ่าน"
    elif len(password) > config.PASSWORD_MAX_LENGTH:
        errors["password"] = "รหัสผ่านยาวเกินไป"
    elif not _is_utf8_safe(password):
        errors["password"] = "รหัสผ่านมีอักขระที่ไม่รองรับ"      # กัน hash ล้ม (ไม่ใช่การตรวจนโยบายความซับซ้อน)
    else:
        clean["password"] = password                           # ส่งต่อตามที่ผู้ใช้พิมพ์ ไม่ strip ไม่แปลง ไม่ตรวจความซับซ้อน
    return clean, errors


def validate_review(data, partial=False):
    """ตรวจรีวิว: รองรับคะแนนรวมเดิม และคะแนน Artwork/Artist แยก 1-5"""
    clean, errors = {}, {}
    for field in ("rating", "artwork_rating", "artist_rating"):
        if (not partial) and field == "rating":
            required = True
        else:
            required = field in data
        if required:
            value, problem = validate_rating(data.get(field))
            if problem:
                errors[field] = problem
            else:
                clean[field] = value
    if (not partial) or ("comment" in data):
        problem = validate_review_text(data.get("comment"))
        if problem:
            errors["comment"] = problem
        else:
            clean["comment"] = clean_text(data["comment"])
    if "rating" in clean:
        clean.setdefault("artwork_rating", clean["rating"])
        clean.setdefault("artist_rating", clean["rating"])
    return clean, errors


def validate_order_items(raw_items):
    """ตรวจรายการสินค้าในคำสั่งซื้อ  รูปแบบ [{"artwork_id": "w1", "quantity": 1}, ...]
    คืน (items, errors)
    """
    if not isinstance(raw_items, list) or not raw_items:
        return [], {"items": "ต้องมีสินค้าอย่างน้อย 1 รายการ"}
    items, seen = [], set()
    for position, entry in enumerate(raw_items):
        if not isinstance(entry, dict):
            return [], {"items": "รายการที่ " + str(position + 1) + " ไม่ถูกต้อง"}
        artwork_id = entry.get("artwork_id")
        quantity, problem = validate_quantity(entry.get("quantity", 1))
        if validate_id(artwork_id, "artwork_id"):
            return [], {"items": "รายการที่ " + str(position + 1) + " มี artwork_id ไม่ถูกต้อง"}
        if problem:
            return [], {"items": problem}
        if artwork_id in seen:
            return [], {"items": "มีสินค้าซ้ำในรายการ"}
        seen.add(artwork_id)
        items.append({"artwork_id": artwork_id, "quantity": quantity})
    return items, {}


def validate_category(data, partial=False):
    """ตรวจข้อมูลหมวดหมู่ (name 2-40, description ไม่เกิน 200)"""
    clean, errors = {}, {}
    if (not partial) or ("name" in data):
        problem = check_text(data.get("name"), "ชื่อหมวดหมู่", min_len=2, max_len=40)
        if problem:
            errors["name"] = problem
        else:
            clean["name"] = clean_text(data["name"])
    if (not partial) or ("description" in data):
        problem = check_text(data.get("description"), "คำอธิบาย", max_len=200)
        if problem:
            errors["description"] = problem
        else:
            clean["description"] = clean_text(data.get("description") or "")
    return clean, errors


def validate_page_params(query):
    """ตรวจ page / page_size จาก query string
    คืนค่า: tuple (page, page_size, errors)
    """
    errors = {}
    page = 1
    page_size = config.PAGE_SIZE_DEFAULT
    if "page" in query:
        value, problem = to_int(query["page"])
        if problem or value < 1:
            errors["page"] = "หมายเลขหน้าต้องเป็นจำนวนเต็มตั้งแต่ 1 ขึ้นไป"
        else:
            page = value
    if "page_size" in query:
        low, high = config.PAGE_SIZE_RANGE             # แกะ tuple เป็นสองตัวแปร
        value, problem = to_int(query["page_size"])
        if problem or not (low <= value <= high):
            errors["page_size"] = "page_size ต้องเป็นจำนวนเต็ม " + str(low) + " ถึง " + str(high)
        else:
            page_size = value
    return page, page_size, errors


ARTWORK_QUERY_PARAMS = {"q", "search_in", "category", "artist_id", "sale_type", "status", "min_price", "max_price",
                        "min_rating", "available", "mine", "submitted", "sort", "page", "page_size"}


def validate_artwork_filters(query):
    """ตรวจเงื่อนไขค้นหา/กรอง/เรียงของ GET /api/artworks  คืน (filters, errors)"""
    errors = check_allowed_params(query, ARTWORK_QUERY_PARAMS)
    errors.update(check_query_values(query))
    search_text = query.get("q", "")
    problem = check_text(search_text, "คำค้น", max_len=config.SEARCH_MAX_LENGTH)
    if problem:
        errors["q"] = problem
    filters = {"q": clean_text(search_text) if not problem else "", "search_in": "all", "sort": "newest"}

    search_in = query.get("search_in", "all")
    if search_in not in config.SEARCH_FIELDS:
        errors["search_in"] = "search_in ต้องเป็น " + ", ".join(config.SEARCH_FIELDS)
    else:
        filters["search_in"] = search_in

    sort = query.get("sort", "newest")
    if sort not in config.SORT_OPTIONS:
        errors["sort"] = "sort ต้องเป็น " + ", ".join(config.SORT_OPTIONS)
    else:
        filters["sort"] = sort

    for name in ("category", "artist_id"):
        if query.get(name):
            problem = validate_id(query[name], name)
            if problem:
                errors[name] = problem
            else:
                filters[name] = query[name]

    if query.get("sale_type"):
        sale_type = query["sale_type"].strip().upper()
        if sale_type not in config.SALE_TYPES:
            errors["sale_type"] = "sale_type ต้องเป็น LIMITED หรือ UNLIMITED"
        else:
            filters["sale_type"] = sale_type

    if query.get("status"):
        status = query["status"].strip().upper()
        if status not in config.ARTWORK_STATUSES:
            errors["status"] = "status ไม่ถูกต้อง"
        else:
            filters["status"] = status

    for name in ("min_price", "max_price", "min_rating"):
        if name in query:
            value, problem = to_float(query[name])
            if problem or value < 0:
                errors[name] = name + " ต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป"
            else:
                filters[name] = value

    if "min_price" in filters and "max_price" in filters and filters["min_price"] > filters["max_price"]:
        errors["min_price"] = "min_price ต้องไม่มากกว่า max_price"

    for name in ("available", "mine", "submitted"):
        if name in query:
            value, problem = validate_boolean(query[name], name, from_query=True)
            if problem:
                errors[name] = problem
            else:
                filters[name] = value

    return filters, errors


def can_transition(current, new, rules):
    """True ถ้าเปลี่ยนสถานะจาก current ไป new ได้ตามตารางกติกา rules (dict)"""
    return new in rules.get(current, ())
