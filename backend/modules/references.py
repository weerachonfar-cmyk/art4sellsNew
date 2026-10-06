"""references.py - ล้างข้อมูลที่ "อ้างถึง" record ที่กำลังถูกลบ (ไม่ให้เหลือ orphan data)

ใช้โดย artwork.delete_artwork() และ user.delete_user()  (การล้างข้อมูลทีละหลายชุดของ admin อยู่ใน data_management.py)
"""
from backend.modules import storage


def purge_artwork_references(artwork_id):
    """ลบตะกร้า/wishlist ที่ชี้ไปยังงานที่ถูกลบ  คืน dict จำนวนที่ลบ"""
    return {
        "carts": storage.delete_where("carts", "artwork_id", artwork_id),
        "wishlists": storage.delete_where("wishlists", "artwork_id", artwork_id),
    }


def purge_user_references(user_id):
    """ลบข้อมูลส่วนตัวทั้งหมดของ user และ follow ที่ชี้มาหาเขา  คืน dict จำนวนที่ลบ"""
    removed = {}
    for collection in ("carts", "wishlists", "follows", "notifications", "sessions", "password_resets"):
        removed[collection] = storage.delete_where(collection, "user_id", user_id)
    removed["followers"] = storage.delete_where("follows", "artist_id", user_id)
    return removed


def purge_artwork_files(artwork_id):
    """ลบไฟล์ภาพของงาน (ตัวไฟล์ใน file storage + metadata)  คืนจำนวน record ที่ลบ  (import ในฟังก์ชัน เพื่อไม่ให้ module วนกลับหากัน)"""
    from backend.modules import artwork_files
    return artwork_files.delete_files_of_artwork(artwork_id)
