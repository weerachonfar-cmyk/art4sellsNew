"""file_storage.py - ที่เก็บ "ตัวไฟล์" ของงานศิลปะ (File Storage Abstraction)  แยกจาก storage.py ที่เก็บข้อมูล JSON/Redis

    Business Logic (artwork_files.py) -> file_storage.py -> LocalFileStore   uploads/<original|preview|delivery>/   (Local เท่านั้น)
                                                         -> VercelBlobStore  Vercel Blob แบบ PRIVATE              (Vercel)
                                                         -> UnavailableFileStore  ตั้งค่าไม่ครบ -> 503 (ห้าม fallback ไปเก็บลง disk ของ Function)

หลักการ:
  - ไฟล์ "ไม่เคยมี public URL"  ทุกการอ่านต้องผ่าน API ของเราที่ตรวจสิทธิ์ก่อน (Original / Delivery) - ไฟล์ Preview ที่ใส่ลายน้ำแล้วเท่านั้นที่เปิดให้คนทั่วไปเห็น
  - blob_path (ตำแหน่งที่เก็บจริง) อยู่ในฐานข้อมูลฝั่ง server เท่านั้น ไม่ส่งให้ client
  - ชื่อไฟล์ที่เก็บจริงสร้างที่ server (uuid สุ่ม) ไม่ใช้ชื่อจาก client
ข้อจำกัด: VercelBlobStore ใช้ Vercel Python SDK (แพ็กเกจ "vercel") และยัง "ไม่ได้ทดสอบกับ Blob จริง" ในสภาพแวดล้อมที่พัฒนา - ดู VERCEL_DEPLOYMENT.md
"""
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from backend import config
from backend.modules import uploads
from backend.modules.errors import StorageError

UNAVAILABLE_MESSAGE = "ระบบเก็บไฟล์ยังไม่พร้อมใช้งาน กรุณาลองใหม่ภายหลัง"
ROLE_PREFIX = {"original": "original", "preview": "preview", "delivery": "delivery"}


def _unavailable(detail):
    return StorageError("FILE_STORAGE_UNAVAILABLE", UNAVAILABLE_MESSAGE, detail=detail, status=503)


def _check_role(role):
    if role not in ROLE_PREFIX:
        raise ValueError("unknown file role")


class LocalFileStore:
    """เก็บเป็นไฟล์ในโฟลเดอร์ uploads/<role>/ (Local Development / งานวิชา File Handling เท่านั้น)"""
    name = "local"

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)

    def put(self, role, data, extension, content_type):
        """เก็บไฟล์ คืน blob_path แบบ "<role>/<ชื่อสุ่ม>.<นามสกุล>" (ไม่ใช่ path เต็มของเครื่อง)"""
        _check_role(role)
        try:
            name = uploads.save_upload(self.base_dir / ROLE_PREFIX[role], data, extension)
        except (OSError, ValueError) as err:
            raise StorageError("FILE_WRITE_FAILED", "ไม่สามารถบันทึกไฟล์ได้", detail=str(err))
        return ROLE_PREFIX[role] + "/" + name

    def _resolve(self, blob_path):
        role, _, name = str(blob_path).partition("/")
        if role not in ROLE_PREFIX:
            return None
        return uploads.safe_join(self.base_dir / ROLE_PREFIX[role], name)   # กัน path traversal ซ้ำอีกชั้นแม้ข้อมูลใน DB เสีย

    def get(self, blob_path):
        """อ่านไฟล์ คืน bytes (ไม่พบ -> raise StorageError 404)"""
        target = self._resolve(blob_path)
        try:
            if target is None:
                raise FileNotFoundError(blob_path)
            return target.read_bytes()
        except FileNotFoundError:
            raise StorageError("FILE_NOT_FOUND", "ไม่พบไฟล์", detail=str(blob_path), status=404)
        except OSError as err:
            raise StorageError("FILE_READ_FAILED", "ไม่สามารถอ่านไฟล์ได้", detail=str(err))

    def delete(self, blob_path):
        target = self._resolve(blob_path)
        try:
            if target is not None:
                target.unlink()
        except OSError:
            pass

    def health(self):
        return {"available": True, "error": None}


class VercelBlobStore:
    """เก็บใน Vercel Blob แบบ private (ต้องสร้าง Blob store ชนิด Private และตั้ง BLOB_READ_WRITE_TOKEN)

    เขียน/ลบ : ผ่าน Vercel Python SDK (vercel.blob)  อ่าน: GET <url ของ blob> พร้อม Authorization: Bearer <token> ตามเอกสาร Private Storage
    ข้อสำคัญ: เก็บ "url ภายใน" ไว้ใน blob_path ของฐานข้อมูลเท่านั้น (private blob เปิดตรงจากเบราว์เซอร์ไม่ได้อยู่แล้ว เพราะต้องมี token)
    """
    name = "vercel-blob"

    def __init__(self, token, sdk=None):
        self.token = token
        self._sdk = sdk                                # ใส่ SDK ปลอมได้ในเทสต์ ไม่ต้องต่อ network

    def _blob_module(self):
        if self._sdk is not None:
            return self._sdk
        try:
            from vercel import blob                    # import ตอนใช้งานจริงเท่านั้น (Local ไม่ต้องติดตั้งแพ็กเกจนี้)
        except ImportError:
            raise _unavailable("vercel sdk not installed")
        return blob

    def put(self, role, data, extension, content_type):
        _check_role(role)
        pathname = ROLE_PREFIX[role] + "/" + uuid.uuid4().hex + "." + extension
        try:
            result = self._blob_module().put(pathname, data, access="private", content_type=content_type,
                                             add_random_suffix=False, token=self.token)
        except StorageError:
            raise
        except Exception as err:                       # SDK / network ผิดพลาด: เก็บรายละเอียดไว้ใน log เท่านั้น
            raise _unavailable("blob put failed: " + type(err).__name__)
        url = result.get("url") if isinstance(result, dict) else getattr(result, "url", None)
        if not isinstance(url, str) or not url.startswith("https://"):
            raise _unavailable("blob put returned no url")
        return url

    def get(self, blob_path):
        if not isinstance(blob_path, str) or not blob_path.startswith("https://"):
            raise StorageError("FILE_NOT_FOUND", "ไม่พบไฟล์", detail="bad blob path", status=404)
        request = urllib.request.Request(blob_path, headers={"Authorization": "Bearer " + self.token})
        try:
            with urllib.request.urlopen(request, timeout=config.REDIS_TIMEOUT_SECONDS * 2) as response:
                return response.read(config.MAX_UPLOAD_BYTES * 2)
        except urllib.error.HTTPError as err:
            if err.code == 404:
                raise StorageError("FILE_NOT_FOUND", "ไม่พบไฟล์", detail="blob 404", status=404)
            raise _unavailable("blob get http " + str(err.code))
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise _unavailable("blob get " + type(err).__name__)

    def delete(self, blob_path):
        try:
            self._blob_module().delete(blob_path, token=self.token)
        except Exception:
            pass                                       # ลบไม่สำเร็จไม่ทำให้ request ล้ม (ไฟล์กำพร้าเก็บไว้ใน log ได้)

    def health(self):
        return {"available": True, "error": None}


class UnavailableFileStore:
    """ตั้งค่าไม่ครบ (เช่น Vercel แต่ไม่มี BLOB_READ_WRITE_TOKEN) - ทุกคำสั่ง 503 และไม่เขียนลง disk ของ Function"""
    name = "unavailable"

    def __init__(self, reason):
        self.reason = reason

    def put(self, *args, **kwargs):
        raise _unavailable(self.reason)

    get = delete = put

    def health(self):
        return {"available": False, "error": self.reason}


_store = None


def build_store():
    """เลือก file store ตาม config  Vercel -> Blob (ไม่มี token = Unavailable)  Local -> โฟลเดอร์ uploads/"""
    use_blob = config.RUNNING_ON_VERCEL and (not config.DEMO_EPHEMERAL or bool(config.BLOB_READ_WRITE_TOKEN))   # โหมด DEMO ที่ยังไม่มี Blob token -> เก็บไฟล์ชั่วคราวใน /tmp
    wanted = config.FILE_STORAGE_PROVIDER or ("blob" if use_blob else "local")
    if wanted == "local":
        if config.RUNNING_ON_VERCEL and not config.DEMO_EPHEMERAL:
            return UnavailableFileStore("LOCAL_FILES_NOT_ALLOWED_ON_VERCEL")   # filesystem ของ Function ไม่ถาวร
        return LocalFileStore(config.UPLOAD_DIR)
    if wanted == "blob":
        if not config.BLOB_READ_WRITE_TOKEN:
            return UnavailableFileStore("BLOB_NOT_CONFIGURED")
        return VercelBlobStore(config.BLOB_READ_WRITE_TOKEN)
    return UnavailableFileStore("FILE_STORAGE_PROVIDER_UNSUPPORTED")


def get_store():
    global _store
    if _store is None:
        _store = build_store()
    return _store


def use_store(store):
    """กำหนด file store เอง (ใช้ในเทสต์ เช่น โฟลเดอร์ชั่วคราว หรือ Blob ปลอม)"""
    global _store
    _store = store


def reset_store():
    global _store
    _store = None
