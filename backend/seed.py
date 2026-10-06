"""seed.py - สร้างข้อมูลตัวอย่างลงไฟล์ JSON (ครั้งแรกเท่านั้น)

- ใช้ข้อมูลชุดเดียวกับ mock ของ Phase 2 (id เดิม: a1-a4, u1, u2, ad1, w1-w16) เพื่อให้ UI เดิมใช้ต่อได้
- รหัสผ่านถูก hash ก่อนบันทึก (ไม่มี plaintext ในไฟล์ข้อมูล)
- รหัสผ่านตัวอย่างสำหรับ "เครื่อง development" เท่านั้น เปลี่ยนได้ด้วย  A4S_DEMO_PASSWORD=... python backend/seed.py --reset (ต้องผ่านนโยบายรหัสผ่านเดียวกับผู้ใช้จริง)

วิธีใช้:
    python backend/seed.py            # สร้างข้อมูลถ้ายังไม่มี (ถ้ามีแล้วจะไม่แตะ)
    python backend/seed.py --reset    # ลบข้อมูลเดิมทั้งหมดแล้วสร้างใหม่
"""
import os
import sys
from pathlib import Path

if __package__ in (None, ""):                          # อนุญาตให้รัน "python backend/seed.py" ตรง ๆ
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config
from backend.modules import review, security, storage, validation
from backend.modules.utils import minutes_from_now_iso, now_iso

DEMO_PASSWORD = os.environ.get("A4S_DEMO_PASSWORD", "Demo1234!")      # ต้องผ่านนโยบายรหัสผ่านเดียวกับผู้ใช้จริง (8+ ตัว มี a-z A-Z 0-9 และอักษรพิเศษ)

CATEGORIES = [
    ("illustration", "Illustration"), ("digital-painting", "Digital Painting"), ("3d-art", "3D Art"),
    ("character", "Character"), ("game-asset", "Game Asset"), ("concept-art", "Concept Art"),
    ("photography", "Photography"), ("other", "Other"),
]

# id, ชื่อ, อีเมล, role, headline, bio, accepts_commissions, followers
USERS = [
    ("a1", "Mika Sorn", "mika@art4sells.test", "ARTIST", "Illustrator & Digital Artist",
     "Bangkok-based illustrator painting quiet, ink-soaked night scenes and character portraits.", True, 1200),
    ("a2", "Kenji Aoi", "kenji@art4sells.test", "ARTIST", "3D Artist & Game Asset Designer",
     "Builds stylised low-poly worlds and production-ready game props for indie teams.", True, 3400),
    ("a3", "Nara Wong", "nara@art4sells.test", "ARTIST", "Concept Artist",
     "Environment and creature concepts for film, games and tabletop stories.", False, 860),
    ("a4", "Lumi Pranee", "lumi@art4sells.test", "ARTIST", "Photographer & Texture Artist",
     "Captures surfaces, light and weather, then turns them into seamless texture packs.", True, 540),
    ("u1", "Pim Buyer", "buyer@art4sells.test", "USER", "", "", False, 0),
    ("u2", "Ton Collector", "ton@art4sells.test", "USER", "", "", False, 0),
    ("ad1", "Site Admin", "admin@art4sells.test", "ADMIN", "", "", False, 0),
]

# id, ชื่อ, artist, category id, ราคา, sale_type, status, tags, คำอธิบาย, วันที่ส่งอนุมัติ
ARTWORKS = [
    ("w1", "Moonlit Koi", "a1", "illustration", 1200, "LIMITED", "APPROVED", ["koi", "night", "ink"],
     "Ink and gouache koi drifting under a paper-white moon. One edition only.", None),
    ("w2", "Lantern Street", "a1", "digital-painting", 900, "LIMITED", "APPROVED", ["city", "lantern", "night"],
     "A rain-soaked alley glowing with hand-painted lanterns.", None),
    ("w3", "Fox Ranger", "a1", "character", 650, "UNLIMITED", "APPROVED", ["fox", "fantasy", "character"],
     "Forest ranger character sheet with full-colour and line-art layers.", None),
    ("w4", "Stone Golem Kit", "a2", "3d-art", 1490, "UNLIMITED", "APPROVED", ["golem", "lowpoly", "rigged"],
     "Rigged low-poly golem with three texture sets. Commercial licence included.", None),
    ("w5", "Dungeon Prop Pack", "a2", "game-asset", 990, "UNLIMITED", "APPROVED", ["dungeon", "props", "modular"],
     "48 modular dungeon props with game-ready FBX files and PNG atlases.", None),
    ("w6", "Floating Isles", "a2", "3d-art", 2200, "LIMITED", "APPROVED", ["island", "sky", "render"],
     "A cinematic render of drifting islands at dawn.", None),
    ("w7", "Ashen Citadel", "a3", "concept-art", 1800, "LIMITED", "APPROVED", ["castle", "environment", "matte"],
     "Matte-painted fortress rising from volcanic plains.", None),
    ("w8", "Tide Wraith", "a3", "concept-art", 1350, "LIMITED", "SOLD", ["creature", "sea", "design"],
     "Creature study with silhouette exploration and colour keys.", None),
    ("w9", "Wet Stone Textures", "a4", "game-asset", 450, "UNLIMITED", "APPROVED", ["texture", "stone", "seamless"],
     "12 seamless 4K PBR stone textures shot after monsoon rain.", None),
    ("w10", "Golden Hour, Ayutthaya", "a4", "photography", 800, "LIMITED", "APPROVED", ["photo", "temple", "sunset"],
     "Fine-art print file of ancient brick stupas at last light.", None),
    ("w11", "Paper Garden", "a1", "illustration", 700, "UNLIMITED", "APPROVED", ["flowers", "paper", "pastel"],
     "Layered paper-cut botanicals in a soft pastel palette.", None),
    ("w12", "Neon Courier", "a3", "character", 1100, "LIMITED", "APPROVED", ["cyberpunk", "neon", "character"],
     "Motorbike courier in a neon-soaked megacity, with full concept breakdown.", None),
    ("w13", "Sakura Mech", "a2", "3d-art", 1600, "LIMITED", "PENDING_APPROVAL", ["mech", "sakura", "render"],
     "Cherry-blossom battle mech, high-poly render.", "2026-09-28"),
    ("w14", "Salt Flat Dreams", "a4", "photography", 600, "UNLIMITED", "PENDING_APPROVAL", ["salt", "desert", "photo"],
     "Mirror-like salt flats at blue hour.", "2026-09-29"),
    ("w15", "Ember Fox", "a1", "character", 750, "UNLIMITED", "PENDING_APPROVAL", ["fox", "fire", "character"],
     "Fire-spirit fox in a layered PSD.", "2026-09-30"),
    ("w16", "Glass Harbour", "a3", "concept-art", 1400, "LIMITED", "PENDING_APPROVAL", ["harbour", "glass", "environment"],
     "A crystalline port city concept.", "2026-09-30"),
]


def _timestamp(day_text):
    """แปลงวันที่แบบ 2026-09-28 เป็นข้อความเวลา ISO"""
    return day_text + "T09:00:00+00:00"


def build_users():
    """สร้างรายการ user (hash รหัสผ่านทีละคน) - คืน list ของ dict
    บัญชีตัวอย่างมีรหัสผ่านจริง (เก็บเป็น hash) ตรวจตอน login เหมือนบัญชีอื่นทุกประการ - ไม่มีทางผ่านด้วยอีเมลอย่างเดียว
    """
    problem = validation.validate_password(DEMO_PASSWORD)
    if problem:                                                   # กันตั้ง A4S_DEMO_PASSWORD เป็นรหัสอ่อนจนมีบัญชีตัวอย่างที่ผิดนโยบาย
        raise SystemExit("A4S_DEMO_PASSWORD ไม่ผ่านนโยบายรหัสผ่าน: " + problem)
    records = []
    for uid, name, email, role, headline, bio, commission, followers in USERS:
        records.append({
            "id": uid, "name": name, "email": email,
            "password_hash": security.hash_password(DEMO_PASSWORD),
            "role": role, "status": "ACTIVE", "headline": headline, "bio": bio,
            "rating": 0.0, "followers": followers, "accepts_commissions": commission, "password_changed_at": None,
            "created_at": _timestamp("2026-09-01"), "updated_at": _timestamp("2026-09-01"),
        })
    return records


def build_artworks():
    records = []
    for index, row in enumerate(ARTWORKS):
        wid, title, artist, category, price, sale_type, status, tags, desc, submitted = row
        day = "2026-09-" + ("0" + str(index + 1))[-2:]
        records.append({
            "id": wid, "title": title, "description": desc, "artist_id": artist, "category": category,
            "tags": tags, "price": float(price), "rating": 0.0, "sale_type": sale_type, "status": status,
            "preview_seed": index % 8, "created_at": _timestamp(day), "updated_at": _timestamp(day),
            "submitted_at": _timestamp(submitted) if submitted else (_timestamp(day) if status != "DRAFT" else None),
            "reviewed_by": "ad1" if status in ("APPROVED", "SOLD") else None, "reject_reason": None,
        })
    return records


def build_orders():
    """ออเดอร์ตัวอย่าง: o1 รอจ่ายเงิน (ล็อกงาน LIMITED w6), o2/o3 เสร็จสมบูรณ์ (ใช้เป็นหลักฐานให้รีวิวได้)"""
    def item(art_id, title, artist, sale_type, price):
        return {"artwork_id": art_id, "title": title, "artist_id": artist, "sale_type": sale_type,
                "quantity": 1, "unit_price": float(price)}
    return [
        {"id": "o1", "user_id": "u1", "items": [item("w6", "Floating Isles", "a2", "LIMITED", 2200)],
         "total": 2200.0, "status": "PENDING_PAYMENT", "created_at": now_iso(), "updated_at": now_iso(),
         "expires_at": minutes_from_now_iso(24 * 60), "paid_at": None},
        {"id": "o2", "user_id": "u1", "items": [item("w8", "Tide Wraith", "a3", "LIMITED", 1350)],
         "total": 1350.0, "status": "COMPLETED", "created_at": _timestamp("2026-09-12"),
         "updated_at": _timestamp("2026-09-13"), "expires_at": _timestamp("2026-09-12"),
         "paid_at": _timestamp("2026-09-12")},
        {"id": "o3", "user_id": "u2", "items": [item("w3", "Fox Ranger", "a1", "UNLIMITED", 650)],
         "total": 650.0, "status": "COMPLETED", "created_at": _timestamp("2026-09-15"),
         "updated_at": _timestamp("2026-09-16"), "expires_at": _timestamp("2026-09-15"),
         "paid_at": _timestamp("2026-09-15")},
    ]


def build_reviews():
    return [
        {"id": "r1", "order_id": "o2", "artwork_id": "w8", "artist_id": "a3", "user_id": "u1", "rating": 5,
         "comment": "Beautiful silhouettes and colour keys.", "status": "PUBLISHED",
         "created_at": _timestamp("2026-09-20"), "updated_at": _timestamp("2026-09-20")},
        {"id": "r2", "order_id": "o3", "artwork_id": "w3", "artist_id": "a1", "user_id": "u2", "rating": 4,
         "comment": "Lovely line art, very clean layers.", "status": "PUBLISHED",
         "created_at": _timestamp("2026-09-22"), "updated_at": _timestamp("2026-09-22")},
    ]



def build_payments():
    return [
        {"id": "pay1", "order_id": "o1", "user_id": "u1", "method": "QR_PAYMENT", "expected_amount": 2200.0, "submitted_amount": None, "verified_amount": None, "status": "UNPAID", "slip": None, "submitted_at": None, "verified_at": None, "verified_by": None, "rejection_reason": None, "created_at": now_iso(), "updated_at": now_iso()},
        {"id": "pay2", "order_id": "o2", "user_id": "u1", "method": "BANK_TRANSFER", "expected_amount": 1350.0, "submitted_amount": 1350.0, "verified_amount": 1350.0, "status": "PAID", "slip": None, "submitted_at": _timestamp("2026-09-12"), "verified_at": _timestamp("2026-09-12"), "verified_by": "ad1", "rejection_reason": None, "created_at": _timestamp("2026-09-12"), "updated_at": _timestamp("2026-09-12")},
        {"id": "pay3", "order_id": "o3", "user_id": "u2", "method": "COD", "expected_amount": 650.0, "submitted_amount": 650.0, "verified_amount": 650.0, "status": "PAID", "slip": None, "submitted_at": _timestamp("2026-09-15"), "verified_at": _timestamp("2026-09-15"), "verified_by": "ad1", "rejection_reason": None, "created_at": _timestamp("2026-09-15"), "updated_at": _timestamp("2026-09-15")},
    ]

def build_promotions():
    return [{"id": "pr1", "artist_id": "a1", "title": "Fox Ranger Week", "type": "PERCENTAGE", "value": 10.0, "start_at": "2027-01-01T00:00:00+00:00", "end_at": "2027-03-31T23:59:59+00:00", "artwork_id": "w3", "category_id": None, "store_id": None, "status": "SCHEDULED", "created_at": _timestamp("2026-10-01"), "updated_at": _timestamp("2026-10-01")} ]

def build_price_history():
    return [{"id": "ph1", "artwork_id": "w3", "old_price": 800.0, "new_price": 650.0, "changed_at": _timestamp("2026-09-25"), "changed_by": "a1"}]

def build_commission_listings():
    return [{"id": "cl1", "artist_id": "a1", "title": "Character Illustration", "description": "Custom character illustration with clean line art and colour.", "conditions": "One character. Extra revisions are negotiated before acceptance.", "price": 1500.0, "days": 7, "revisions": 2, "samples": [], "status": "LISTING", "created_at": _timestamp("2026-09-20"), "updated_at": _timestamp("2026-09-20")}]

def build_commissions():
    return []

def build_categories():
    return [{"id": cid, "name": name, "description": "", "created_at": _timestamp("2026-09-01"),
             "updated_at": _timestamp("2026-09-01")} for cid, name in CATEGORIES]


def seed_all(keep_users=(), keep_sessions=(), keep_logs=()):
    """เขียนข้อมูลตัวอย่างทุก collection ลงไฟล์ แล้วคำนวณคะแนนเฉลี่ยจากรีวิวจริง

    พารามิเตอร์ (ใช้ตอน "Reset Demo Data" ของ admin; ตอนสร้างครั้งแรกไม่ต้องใส่):
        keep_users    record ของ user ที่ต้องเก็บไว้ (เช่น admin) - ถ้า id ซ้ำกับ demo จะใช้ record ที่เก็บไว้แทน
        keep_sessions session ที่ต้องเก็บไว้ (admin ที่กำลังใช้งานจะไม่ถูกเตะออก)
        keep_logs     audit log เดิม (ไม่หายตอน reset)
    """
    users = {u["id"]: u for u in build_users()}
    for kept in keep_users:
        users[kept["id"]] = kept
    storage.save_json("users", list(users.values()))
    storage.save_json("categories", build_categories())
    storage.save_json("artworks", build_artworks())
    storage.save_json("orders", build_orders())
    storage.save_json("reviews", build_reviews())
    storage.save_json("payments", build_payments())
    storage.save_json("promotions", build_promotions())
    storage.save_json("price_history", build_price_history())
    storage.save_json("commission_listings", build_commission_listings())
    storage.save_json("commissions", build_commissions())
    storage.save_json("sessions", list(keep_sessions))
    storage.save_json("logs", list(keep_logs))
    for empty in ("carts", "wishlists", "follows", "notifications", "password_resets", "reset_requests", "confirmations", "files", "commission_messages", "blacklist", "blocked_ips"):
        storage.save_json(empty, [])
    for item in storage.get_all("reviews"):
        review.refresh_ratings(item["artwork_id"])


def seed_if_empty():
    """สร้างข้อมูลตัวอย่างเฉพาะ "ครั้งแรกที่ระบบยังว่าง" แล้วทำเครื่องหมาย initialized  คืน True ถ้าเพิ่งสร้าง
    - JSON : มี users.json แล้ว = เคยสร้างแล้ว (พฤติกรรมเดิมของโปรเจกต์)
    - Redis: ใช้ key meta:initialized + lock  จึงไม่ seed ทุก request / ทุก cold start และไม่ทับข้อมูลจริง
    """
    return storage.ensure_initialized(seed_all)


def main(argv):
    if "--reset" in argv:
        if storage.provider_name() != "json":
            raise SystemExit("--reset ใช้ได้กับ A4S_STORAGE=json (ข้อมูลในเครื่อง) เท่านั้น - "
                             "ข้อมูลบน Redis ให้รีเซ็ตผ่านหน้า Admin > Data Management เพื่อไม่ลบข้อมูลจริงโดยไม่ตั้งใจ")
        for name in sorted(storage.COLLECTIONS):
            target = Path(storage.get_data_dir()) / (name + ".json")
            if target.exists():
                target.unlink()
    created = seed_if_empty()
    print("สร้างข้อมูลตัวอย่างแล้วที่ " + str(storage.get_data_dir()) if created
          else "มีข้อมูลอยู่แล้ว ไม่แก้ไข (ใช้ --reset เพื่อสร้างใหม่)")


if __name__ == "__main__":
    main(sys.argv[1:])
