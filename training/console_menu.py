"""console_menu.py - เมนู Console สำหรับทดสอบ/จัดการข้อมูล Art 4 Sells (ใช้สาธิตกับอาจารย์)

เมนูนี้เรียก "ฟังก์ชันเดียวกับระบบจริง" (backend/modules/*) ไม่ได้เขียนตรรกะแยก
ข้อมูลที่สร้าง/แก้ในเมนูนี้จึงไปปรากฏบนเว็บด้วย (ใช้ไฟล์ JSON ชุดเดียวกัน)

รัน (จากโฟลเดอร์ art4sells):
    python training/console_menu.py

จุดที่ใช้สาธิตตามโจทย์ (ดูตารางเต็มใน ACADEMIC_REQUIREMENTS.md):
    while + break ........ main_menu(), ask_float(), login_prompt()
    if / elif / else ..... main_menu() (เลือกเมนู), is_allowed()
    for .................. print_artwork_page(), export_artworks_csv()
    and / or / not ....... is_allowed(), ask_float(), main_menu()
    functions ............ ทุกฟังก์ชันในไฟล์นี้มี parameter และ return value
    dict / list / tuple / set .. MENU_ITEMS (tuple), ARTIST_ONLY (set), session (dict), artworks (list)
    try / except ......... run_action(), export_artworks_csv()
    file handling ........ export_artworks_csv() (เขียน CSV), และผ่าน storage.py ทุกครั้งที่บันทึกข้อมูล
    type conversion ...... ask_float() (str -> float), ask_int() (str -> int)
"""
import csv
import getpass
import sys
from pathlib import Path

if __package__ in (None, ""):                          # อนุญาตให้รัน "python training/console_menu.py" ตรง ๆ
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, seed
from backend.modules import admin, artwork, auth, category, validation
from backend.modules.errors import AppError, StorageError

# tuple ของ tuple: รายการเมนู (ค่าคงที่ แก้ไม่ได้ระหว่างรัน)
MENU_ITEMS = (
    ("1", "List artworks (แสดงรายการงาน)"),
    ("2", "Search artwork (ค้นหา/กรอง/เรียง)"),
    ("3", "Create artwork (สร้างงาน - ศิลปิน)"),
    ("4", "Update artwork (แก้ไขงาน)"),
    ("5", "Delete artwork (ลบงาน)"),
    ("6", "View summary (สรุป Dashboard - admin)"),
    ("7", "View audit logs (ดู Log - admin)"),
    ("8", "Export artworks to CSV (ส่งออกไฟล์)"),
    ("9", "Switch user (เข้าสู่ระบบใหม่)"),
    ("0", "Exit (ออกจากโปรแกรม)"),
)

# set ของเมนูที่ต้องเป็น role นั้น ๆ (ตรวจเร็ว และไม่มีค่าซ้ำ)
ARTIST_ONLY = {"3"}
ADMIN_ONLY = {"6", "7"}
MENU_KEYS = {key for key, _label in MENU_ITEMS}        # set comprehension

DEFAULT_EXPORT_PATH = Path(__file__).resolve().parent / "exports" / "artworks.csv"
LOGIN_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# รับข้อมูลจากผู้ใช้ (input validation ด้วย while + type conversion)
# ---------------------------------------------------------------------------
def ask_text(prompt, input_func=input, required=True):
    """ถามข้อความ  ถ้า required=True จะถามซ้ำจนกว่าจะกรอก (หรือพิมพ์ q เพื่อยกเลิก)
    คืนค่า: str  หรือ None ถ้าผู้ใช้ยกเลิก
    """
    while True:
        text = input_func(prompt).strip()
        if text.lower() == "q":
            return None
        if text or not required:
            return text
        print("  กรุณากรอกข้อมูล (หรือพิมพ์ q เพื่อยกเลิก)")


def ask_float(prompt, input_func=input):
    """ถามตัวเลขทศนิยม (เช่น ราคา) วนถามจนกว่าจะถูกต้อง  คืนค่า: float หรือ None ถ้ายกเลิก"""
    while True:
        text = input_func(prompt).strip()
        if text.lower() == "q":
            return None
        value, problem = validation.to_float(text)     # type conversion: str -> float
        if problem is None and value >= 0:             # and: ต้องแปลงได้ และไม่ติดลบ
            return value
        print("  ราคาต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป (หรือพิมพ์ q เพื่อยกเลิก)")


def ask_int(prompt, input_func=input, minimum=1):
    """ถามจำนวนเต็ม (เช่น เลขหน้า) วนถามจนกว่าจะถูกต้อง  คืนค่า: int"""
    while True:
        value, problem = validation.to_int(input_func(prompt).strip())    # str -> int
        if problem is None and value >= minimum:
            return value
        print("  กรุณากรอกจำนวนเต็มตั้งแต่ " + str(minimum) + " ขึ้นไป")


# ---------------------------------------------------------------------------
# แสดงผล
# ---------------------------------------------------------------------------
def format_artwork_line(art):
    """สร้างข้อความ 1 บรรทัดของงาน เช่น  w1 | Moonlit Koi | ฿1,200.00 | APPROVED | Mika Sorn"""
    price_text = "{:,.2f}".format(art["price"])
    return " | ".join([art["id"], art["title"], "฿" + price_text, art["status"], art.get("artist_name", "")])


def print_artwork_page(result):
    """พิมพ์ผลลัพธ์แบบแบ่งหน้า (dict จาก artwork.list_artworks)  คืนจำนวนแถวที่พิมพ์"""
    items = result["items"]
    if not items:
        print("  (ไม่พบงาน)")
        return 0
    for number, art in enumerate(items, start=1):      # for: วนพิมพ์ทีละงาน
        print("  " + str(number) + ". " + format_artwork_line(art))
    print("  หน้า " + str(result["page"]) + "/" + str(result["total_pages"])
          + "  (ทั้งหมด " + str(result["total"]) + " ชิ้น)")
    return len(items)


# ---------------------------------------------------------------------------
# สิทธิ์ของเมนู
# ---------------------------------------------------------------------------
def is_allowed(choice, actor):
    """ตรวจว่า actor ใช้เมนูนี้ได้หรือไม่ คืน tuple (allowed, ข้อความอธิบาย)"""
    role = actor["role"] if actor else None
    if choice in ARTIST_ONLY and role != "ARTIST":
        return False, "เมนูนี้สำหรับศิลปิน (ARTIST) เท่านั้น"
    elif choice in ADMIN_ONLY and role != "ADMIN":
        return False, "เมนูนี้สำหรับผู้ดูแลระบบ (ADMIN) เท่านั้น"
    elif choice in {"4", "5"} and not (role == "ARTIST" or role == "ADMIN"):
        return False, "เมนูนี้สำหรับศิลปินหรือผู้ดูแลระบบเท่านั้น"
    else:
        return True, ""


# ---------------------------------------------------------------------------
# แต่ละเมนู (เรียก backend/modules จริง)
# ---------------------------------------------------------------------------
def action_list(actor, input_func):
    """เมนู 1: แสดงรายการงาน (แบ่งหน้า) - ศิลปินเลือกดูเฉพาะงานของตัวเองได้"""
    query = {"page_size": "5"}
    if actor["role"] == "ARTIST" and input_func("ดูเฉพาะงานของฉัน (ทุกสถานะ)? (y/n): ").strip().lower() == "y":
        query["mine"] = "true"
    page = 1
    while True:                                        # while: วนดูทีละหน้าจนกว่าจะพิมพ์ q
        query["page"] = str(page)
        result = artwork.list_artworks(query, actor)
        print_artwork_page(result)
        if page >= result["total_pages"]:
            break
        answer = input_func("  Enter = หน้าถัดไป, q = กลับเมนู: ").strip().lower()
        if answer == "q":
            break
        page += 1


def action_search(actor, input_func):
    """เมนู 2: ค้นหา + กรอง + เรียง (ใช้ฟังก์ชันเดียวกับ GET /api/artworks)"""
    query = {}
    text = ask_text("คำค้น (ชื่อ/ศิลปิน/tag, เว้นว่างได้): ", input_func, required=False)
    if text is None:
        return
    if text:
        query["q"] = text
    category_ids = sorted(category.get_category_ids())         # list ที่เรียงแล้ว
    chosen = input_func("หมวดหมู่ [" + ", ".join(category_ids) + "] (เว้นว่าง = ทุกหมวด): ").strip()
    if chosen:
        query["category"] = chosen
    max_price = input_func("ราคาสูงสุด (เว้นว่าง = ไม่จำกัด): ").strip()
    if max_price:
        query["max_price"] = max_price
    query["sort"] = input_func("เรียงตาม [" + ", ".join(config.SORT_OPTIONS) + "] (เว้นว่าง = newest): ").strip() or "newest"
    query["page_size"] = "10"
    print_artwork_page(artwork.list_artworks(query, actor))


def action_create(actor, input_func):
    """เมนู 3: สร้างงานใหม่ (สถานะ DRAFT) ผ่าน artwork.create_artwork"""
    title = ask_text("ชื่องาน: ", input_func)
    if title is None:
        return
    price = ask_float("ราคา (บาท): ", input_func)
    if price is None:
        return
    print("หมวดหมู่ที่มี: " + ", ".join(sorted(category.get_category_ids())))
    data = {
        "title": title,
        "price": price,
        "category": input_func("หมวดหมู่: ").strip(),
        "sale_type": input_func("ประเภทการขาย (LIMITED/UNLIMITED): ").strip().upper(),
        "tags": input_func("tags (คั่นด้วย ,): ").strip(),
        "description": input_func("คำอธิบาย: ").strip(),
    }
    created = artwork.create_artwork(data, actor)
    print("  สร้างงานสำเร็จ id=" + created["id"] + " สถานะ " + created["status"])


def action_update(actor, input_func):
    """เมนู 4: แก้ไขงาน (ชื่อ/ราคา) ผ่าน artwork.update_artwork"""
    artwork_id = ask_text("id ของงานที่ต้องการแก้: ", input_func)
    if artwork_id is None:
        return
    changes = {}
    new_title = input_func("ชื่อใหม่ (เว้นว่าง = ไม่แก้): ").strip()
    if new_title:
        changes["title"] = new_title
    new_price = input_func("ราคาใหม่ (เว้นว่าง = ไม่แก้): ").strip()
    if new_price:
        changes["price"] = new_price
    updated = artwork.update_artwork(artwork_id, changes, actor)
    print("  แก้ไขสำเร็จ: " + updated["title"] + " ราคา " + str(updated["price"]))


def action_delete(actor, input_func):
    """เมนู 5: ลบงาน (ต้องยืนยันก่อน)"""
    artwork_id = ask_text("id ของงานที่ต้องการลบ: ", input_func)
    if artwork_id is None:
        return
    if input_func("ยืนยันลบ " + artwork_id + "? (yes/no): ").strip().lower() != "yes":
        print("  ยกเลิกการลบ")
        return
    artwork.delete_artwork(artwork_id, actor)
    print("  ลบงานแล้ว")


def action_summary(actor, input_func):
    """เมนู 6: สรุป Dashboard (คำนวณจากข้อมูลจริง)"""
    summary = admin.get_dashboard_summary(actor)
    labels = (("total_users", "ผู้ใช้ทั้งหมด"), ("total_artists", "ศิลปิน"), ("total_artworks", "งานทั้งหมด"),
              ("pending_artworks", "งานรออนุมัติ"), ("total_orders", "คำสั่งซื้อ"),
              ("total_sales", "ยอดขายรวม (บาท)"), ("total_reviews", "รีวิว"))
    for key, label in labels:
        print("  " + label.ljust(18) + str(summary[key]))


def action_logs(actor, input_func):
    """เมนู 7: ดู Audit Log ล่าสุด 10 รายการ"""
    result = admin.get_audit_logs({"page_size": "10"}, actor)
    for entry in result["items"]:
        print("  " + entry["timestamp"] + " | " + entry["actor_id"] + " | " + entry["action"]
              + " | " + str(entry["target_type"]) + ":" + str(entry["target_id"]))
    print("  (ทั้งหมด " + str(result["total"]) + " รายการ)")


def export_artworks_csv(artworks, path):
    """เขียนรายการงานลงไฟล์ CSV  พารามิเตอร์: artworks (list ของ dict), path (ที่อยู่ไฟล์)
    คืนค่า: tuple (สำเร็จหรือไม่, จำนวนแถวหรือข้อความ error)
    """
    columns = ("id", "title", "artist_name", "category_name", "price", "sale_type", "status")
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as file:     # utf-8-sig ให้ Excel อ่านภาษาไทยได้
            writer = csv.writer(file)
            writer.writerow(columns)
            count = 0
            for art in artworks:                                           # for: เขียนทีละแถว
                writer.writerow([art.get(column, "") for column in columns])
                count += 1
        return True, count
    except OSError as err:
        return False, "ไม่สามารถบันทึกไฟล์ได้: " + str(err)


def action_export(actor, input_func, export_path=DEFAULT_EXPORT_PATH):
    """เมนู 8: ส่งออกงานที่เผยแพร่แล้วทั้งหมดเป็น CSV"""
    result = artwork.list_artworks({"page_size": str(config.PAGE_SIZE_RANGE[1])}, actor)
    items = list(result["items"])
    page = 2
    while page <= result["total_pages"]:                                   # ดึงทุกหน้า
        more = artwork.list_artworks({"page_size": str(config.PAGE_SIZE_RANGE[1]), "page": str(page)}, actor)
        items.extend(more["items"])
        page += 1
    ok, info = export_artworks_csv(items, export_path)
    if ok:
        print("  ส่งออก " + str(info) + " แถว ไปที่ " + str(export_path))
    else:
        print("  " + str(info))


ACTIONS = {                                            # dict: เลขเมนู -> ฟังก์ชันที่ทำงาน
    "1": action_list, "2": action_search, "3": action_create, "4": action_update,
    "5": action_delete, "6": action_summary, "7": action_logs, "8": action_export,
}


def run_action(handler, actor, input_func):
    """รันเมนูหนึ่งรายการ โดยจับ error ไว้ไม่ให้โปรแกรมหยุดหรือโชว์ traceback
    คืนค่า True ถ้าทำงานสำเร็จ / False ถ้ามี error
    """
    try:
        handler(actor, input_func)
        return True
    except AppError as err:                            # error ที่ระบบรู้จัก (ไม่มีสิทธิ์, ข้อมูลไม่ถูกต้อง, ไม่พบข้อมูล)
        print("  ไม่สำเร็จ: " + err.message)
        for field, message in err.fields.items():
            print("    - " + field + ": " + message)
    except StorageError as err:
        print("  " + err.message)
    except (EOFError, KeyboardInterrupt):
        raise
    except Exception:                                  # bug ที่คาดไม่ถึง: ไม่โชว์ traceback ให้ผู้ใช้
        print("  เกิดข้อผิดพลาดภายในระบบ")
    return False


# ---------------------------------------------------------------------------
# login + เมนูหลัก
# ---------------------------------------------------------------------------
def login_prompt(input_func=input, password_func=getpass.getpass):
    """ให้ผู้ใช้ login (ผ่าน auth.login จริง) ได้สูงสุด 3 ครั้ง  คืนค่า dict ของ user หรือ None"""
    attempts = 0
    while attempts < LOGIN_ATTEMPTS:
        email = input_func("อีเมล: ").strip()
        password = password_func("รหัสผ่าน: ")
        try:
            return auth.login({"email": email, "password": password})["user"]
        except AppError as err:
            attempts += 1
            print("  เข้าสู่ระบบไม่สำเร็จ: " + err.message + " (" + str(attempts) + "/" + str(LOGIN_ATTEMPTS) + ")")
    return None


def print_menu(actor):
    print("\n========== Art 4 Sells Console ==========")
    print("ผู้ใช้: " + actor["name"] + " (" + actor["role"] + ")")
    for key, label in MENU_ITEMS:                      # for: วนพิมพ์รายการเมนูจาก tuple
        print(key + ". " + label)


def main_menu(input_func=input, password_func=getpass.getpass, export_path=DEFAULT_EXPORT_PATH):
    """วงวนเมนูหลัก: แสดงเมนู -> รับตัวเลือก -> ทำงาน -> วนกลับ  จนกว่าจะเลือก 0 (break)
    พารามิเตอร์ input_func / password_func ไว้ให้เทสต์ส่งคำตอบสำเร็จรูปแทนการพิมพ์
    """
    seed.seed_if_empty()                               # ถ้ายังไม่มีข้อมูล สร้างข้อมูลตัวอย่างให้
    session = {"actor": login_prompt(input_func, password_func)}      # dict เก็บผู้ใช้ที่ login อยู่
    if session["actor"] is None:
        print("เข้าสู่ระบบไม่สำเร็จเกินกำหนด ปิดโปรแกรม")
        return 1

    while True:                                        # while: วงวนเมนู
        print_menu(session["actor"])
        choice = input_func("เลือกเมนู: ").strip()

        if choice == "0":
            print("ออกจากโปรแกรม ขอบคุณที่ใช้งาน")
            break                                      # break: ออกจากวง while
        elif choice not in MENU_KEYS:                  # not: เลือกเลขที่ไม่มีในเมนู
            print("  ไม่มีเมนูนี้ กรุณาเลือกใหม่")
        elif choice == "9":
            new_actor = login_prompt(input_func, password_func)
            if new_actor is not None:
                session["actor"] = new_actor
        else:
            allowed, reason = is_allowed(choice, session["actor"])
            if not allowed:
                print("  " + reason)
            elif choice == "8":
                run_action(lambda a, i: action_export(a, i, export_path), session["actor"], input_func)
            else:
                run_action(ACTIONS[choice], session["actor"], input_func)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main_menu())
    except (EOFError, KeyboardInterrupt):
        print("\nออกจากโปรแกรม")
        sys.exit(0)
