"""storage_providers.py - ผู้ให้บริการเก็บข้อมูลจริง (JSONStorage / RedisStorage)

storage.py (ชั้นกลาง) ไม่รู้ว่าข้อมูลอยู่ที่ไหน  มันเรียกเฉพาะ "คำสั่งพื้นฐาน" 5 อย่างของ provider:
    read(collection)            อ่านทั้ง collection (list ของ dict)
    write(collection, data)     เขียนทับทั้ง collection
    lock()                      ตัวล็อกสำหรับงาน "ตรวจแล้วค่อยเขียน" (ใช้ with)
    health()                    สถานะพร้อมใช้งาน (ไม่เปิดเผย secret / path)
    is_initialized() / mark_initialized()   ใช้กับ seed ข้อมูลตัวอย่างครั้งแรก

    Local   : JSONStorage   -> backend/data/<collection>.json   (งานวิชา: File Handling + JSON Persistence)
    Vercel  : RedisStorage  -> Upstash Redis ผ่าน REST          (ไม่พึ่ง filesystem ของ Serverless Function)
    ตั้งค่าไม่ครบ : UnavailableStorage -> ทุกคำสั่ง error 503 (ห้าม fallback ไปใช้ JSON แบบเงียบ ๆ)
ใช้เฉพาะ Python Standard Library (Redis ผ่าน urllib.request ไม่ต้องติดตั้งแพ็กเกจเพิ่ม)
"""
import contextlib
import json
import os
import random
import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from backend import config
from backend.modules.errors import StorageError
from backend.modules.utils import now_iso

UNAVAILABLE_MESSAGE = "ระบบเก็บข้อมูลยังไม่พร้อมใช้งาน กรุณาลองใหม่ภายหลัง"


class BaseProvider:
    """ตัวแม่ของ provider - กำหนดว่าทุกตัวต้องมีอะไรบ้าง (provider ลูกต้อง override ตัวที่ raise NotImplementedError)"""
    name = "base"

    def read(self, collection):
        raise NotImplementedError

    def write(self, collection, data):
        raise NotImplementedError

    def lock(self):
        raise NotImplementedError

    def health(self):
        """คืน dict {"available": bool, "error": รหัส error แบบปลอดภัย หรือ None}"""
        raise NotImplementedError

    def is_initialized(self):
        raise NotImplementedError

    def mark_initialized(self):
        raise NotImplementedError

    def begin_request(self):                           # ใช้กับ cache ต่อ request (เฉพาะ Redis) - provider อื่นไม่ต้องทำอะไร
        pass

    def end_request(self):
        pass


# ---------------------------------------------------------------------------
# JSONStorage (Local / Academic Persistence)
# ---------------------------------------------------------------------------
class JSONStorage(BaseProvider):
    """เก็บเป็นไฟล์ <data_dir>/<collection>.json  เขียนแบบ "ไฟล์ชั่วคราวแล้วสลับชื่อ" (ไฟดับกลางคันไฟล์เดิมไม่เสีย)"""
    name = "json"

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()                 # กันหลาย thread เขียนไฟล์ชนกัน

    def _path(self, collection):
        return self.data_dir / (collection + ".json")

    def read(self, collection):
        path = self._path(collection)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []                                  # ไม่มีไฟล์ = ยังไม่มีข้อมูล
        except json.JSONDecodeError as err:
            raise StorageError("DATA_CORRUPT", "ไม่สามารถอ่านข้อมูลได้ (ไฟล์ข้อมูลเสียหาย)", detail=str(err))
        except OSError as err:
            raise StorageError("DATA_READ_FAILED", "ไม่สามารถอ่านข้อมูลได้", detail=str(err))
        if not isinstance(data, list):
            raise StorageError("DATA_CORRUPT", "ไม่สามารถอ่านข้อมูลได้ (รูปแบบข้อมูลไม่ถูกต้อง)",
                               detail=str(path) + " is not a JSON list")
        return data

    def write(self, collection, data):
        path = self._path(collection)
        tmp_path = path.with_name(path.name + ".tmp")
        try:
            with self._lock:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
        except (OSError, TypeError, ValueError) as err:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise StorageError("DATA_WRITE_FAILED", "ไม่สามารถบันทึกข้อมูลได้", detail=str(err))

    def lock(self):
        return self._lock

    def health(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            writable = os.access(self.data_dir, os.W_OK)
        except OSError:
            writable = False
        return {"available": writable, "error": None if writable else "DATA_DIR_NOT_WRITABLE"}

    def is_initialized(self):
        return self._path("users").exists()            # พฤติกรรมเดิมของโปรเจกต์: มี users.json = เคยสร้างข้อมูลแล้ว

    def mark_initialized(self):
        pass                                           # ไฟล์ข้อมูลที่ seed เขียนไว้ คือหลักฐานว่า initialized แล้ว


# ---------------------------------------------------------------------------
# UnavailableStorage (ตั้งค่าไม่ครบ -> ไม่ fallback)
# ---------------------------------------------------------------------------
class UnavailableStorage(BaseProvider):
    """ใช้เมื่อค่าตั้งไม่ถูกต้อง เช่น รันบน Vercel แต่ไม่มี Redis  ทุกคำสั่ง error 503 และ health บอกตรง ๆ ว่าใช้ไม่ได้"""
    name = "unavailable"

    def __init__(self, requested, reason_code):
        self.requested = requested
        self.reason_code = reason_code
        self._lock = threading.RLock()

    def _fail(self):
        raise StorageError("STORAGE_UNAVAILABLE", UNAVAILABLE_MESSAGE, detail=self.reason_code, status=503)

    def read(self, collection):
        self._fail()

    def write(self, collection, data):
        self._fail()

    def lock(self):
        return self._lock

    def health(self):
        return {"available": False, "error": self.reason_code}

    def is_initialized(self):
        self._fail()

    def mark_initialized(self):
        self._fail()


# ---------------------------------------------------------------------------
# RedisStorage (Vercel Prototype Persistence) - Upstash REST API
# ---------------------------------------------------------------------------
class UpstashRestClient:
    """ไคลเอนต์เล็ก ๆ สำหรับ Upstash Redis REST: POST [คำสั่ง, อาร์กิวเมนต์...] -> {"result": ...}"""

    def __init__(self, url, token, timeout=None):
        self.url = url
        self.token = token
        self.timeout = timeout or config.REDIS_TIMEOUT_SECONDS

    def command(self, *args):
        body = json.dumps(list(args), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise StorageError("STORAGE_UNAVAILABLE", UNAVAILABLE_MESSAGE, detail="redis http " + str(err.code), status=503)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
            raise StorageError("STORAGE_UNAVAILABLE", UNAVAILABLE_MESSAGE, detail="redis " + type(err).__name__, status=503)
        if not isinstance(payload, dict) or payload.get("error"):
            detail = str(payload.get("error"))[:120] if isinstance(payload, dict) else "bad response"
            raise StorageError("STORAGE_UNAVAILABLE", UNAVAILABLE_MESSAGE, detail="redis error: " + detail, status=503)
        return payload.get("result")


# ลบ lock ได้เฉพาะเมื่อ token ตรงกับของเรา (กันไปลบ lock ของคนอื่นที่ได้ต่อจากเรา)
_UNLOCK_SCRIPT = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
MAX_VALUE_BYTES = 900_000                              # Upstash จำกัดขนาด request ราว 1 MB - เกินแล้วบอกตรง ๆ ไม่ปล่อยให้เขียนพัง


def redis_url_is_acceptable(url):
    """รับเฉพาะ https (หรือ http ที่ชี้เครื่องตัวเอง ใช้ตอนเทสต์กับ emulator) - กันตั้งค่า URL แปลก ๆ"""
    parts = urlsplit(url or "")
    if parts.scheme == "https" and parts.netloc:
        return True
    return parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")


class RedisStorage(BaseProvider):
    """เก็บแต่ละ collection เป็น JSON text 1 ค่า ที่ key  <prefix>:c:<collection>

    - lock()   : ล็อกแบบกระจาย (SET NX PX) ให้ "ตรวจแล้วค่อยเขียน" ถูกต้องแม้มีหลาย instance ของ Serverless Function
    - cache    : อ่านซ้ำใน request เดียวกันไม่ยิง Redis ซ้ำ (ปิดเมื่ออยู่ใน lock และล้างเมื่อมีการเขียน)
    - ข้อจำกัด : collection ใหญ่เกิน ~900 KB เขียนไม่ได้ (ดู docs/SECURITY_STATUS.md / VERCEL_DEPLOYMENT.md)
    """
    name = "redis"

    def __init__(self, client, prefix=None):
        self.client = client
        self.prefix = prefix or config.REDIS_KEY_PREFIX
        self._rlock = threading.RLock()
        self._tl = threading.local()                   # depth ของ lock และ cache ของ request ปัจจุบัน (แยกตาม thread)

    # ---- key ----
    def _key(self, collection):
        return self.prefix + ":c:" + collection

    def _lock_key(self):
        return self.prefix + ":lock"

    def _init_key(self):
        return self.prefix + ":meta:initialized"

    # ---- cache ต่อ request ----
    def begin_request(self):
        self._tl.cache = {}

    def end_request(self):
        self._tl.cache = None

    def _depth(self):
        return getattr(self._tl, "depth", 0)

    # ---- อ่าน / เขียน ----
    def read(self, collection):
        cache = getattr(self._tl, "cache", None)
        use_cache = cache is not None and self._depth() == 0     # ใน lock ต้องอ่านของสดเสมอ
        if use_cache and collection in cache:
            raw = cache[collection]
        else:
            raw = self.client.command("GET", self._key(collection))
            if use_cache:
                cache[collection] = raw
        if raw is None:
            return []
        try:
            data = json.loads(raw)                     # parse ใหม่ทุกครั้ง: ผู้เรียกแก้ dict ได้โดยไม่ทำให้ cache เพี้ยน
        except (ValueError, TypeError) as err:
            raise StorageError("DATA_CORRUPT", "ไม่สามารถอ่านข้อมูลได้ (ข้อมูลเสียหาย)", detail=type(err).__name__)
        if not isinstance(data, list):
            raise StorageError("DATA_CORRUPT", "ไม่สามารถอ่านข้อมูลได้ (รูปแบบข้อมูลไม่ถูกต้อง)", detail="not a list")
        return data

    def write(self, collection, data):
        try:
            text = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError) as err:
            raise StorageError("DATA_WRITE_FAILED", "ไม่สามารถบันทึกข้อมูลได้", detail=str(err))
        if len(text.encode("utf-8")) > MAX_VALUE_BYTES:
            raise StorageError("DATA_TOO_LARGE", "ข้อมูลมีขนาดใหญ่เกินกว่าที่ระบบเก็บข้อมูลบน Vercel รองรับ",
                               detail=collection + " exceeds " + str(MAX_VALUE_BYTES) + " bytes", status=507)
        with self.lock():
            self.client.command("SET", self._key(collection), text)
            cache = getattr(self._tl, "cache", None)
            if cache is not None:
                cache.pop(collection, None)

    # ---- lock แบบกระจาย (reentrant ภายใน thread เดียว) ----
    @contextlib.contextmanager
    def lock(self):
        self._rlock.acquire()
        try:
            if self._depth() == 0:
                self._tl.lock_token = self._acquire_remote()
            self._tl.depth = self._depth() + 1
            try:
                yield
            finally:
                self._tl.depth = self._depth() - 1
                if self._depth() == 0:
                    self._release_remote(self._tl.lock_token)
        finally:
            self._rlock.release()

    def _acquire_remote(self):
        token = secrets.token_hex(12)
        deadline = time.monotonic() + config.REDIS_LOCK_WAIT_SECONDS
        while True:
            got = self.client.command("SET", self._lock_key(), token, "NX", "PX", str(config.REDIS_LOCK_SECONDS * 1000))
            if got == "OK":
                return token
            if time.monotonic() >= deadline:
                raise StorageError("STORAGE_BUSY", "ระบบกำลังประมวลผลคำขออื่นอยู่ กรุณาลองใหม่อีกครั้ง",
                                   detail="redis lock wait timeout", status=503)
            time.sleep(0.05 + random.random() * 0.05)

    def _release_remote(self, token):
        try:
            self.client.command("EVAL", _UNLOCK_SCRIPT, "1", self._lock_key(), token)
        except StorageError:
            pass                                       # lock จะหมดอายุเอง (REDIS_LOCK_SECONDS) ไม่ทำให้ request ล้ม

    # ---- health / initialized ----
    def health(self):
        try:
            ok = self.client.command("PING") == "PONG"
        except StorageError:
            return {"available": False, "error": "REDIS_UNREACHABLE"}
        return {"available": ok, "error": None if ok else "REDIS_UNEXPECTED_RESPONSE"}

    def is_initialized(self):
        return bool(self.client.command("EXISTS", self._init_key()))

    def mark_initialized(self):
        self.client.command("SET", self._init_key(), now_iso())


# ---------------------------------------------------------------------------
# เลือก provider ตาม config (เรียกจาก storage.py)
# ---------------------------------------------------------------------------
def build_provider(data_dir):
    """สร้าง provider ตามค่าใน config  ไม่ fallback: ถ้าตั้งไม่ครบจะได้ UnavailableStorage ที่บอกสาเหตุตรง ๆ"""
    wanted = config.STORAGE_PROVIDER
    if wanted not in config.STORAGE_PROVIDERS:
        return UnavailableStorage(wanted, "STORAGE_PROVIDER_UNSUPPORTED")
    if wanted == "json":
        if config.RUNNING_ON_VERCEL and not config.DEMO_EPHEMERAL:   # filesystem ของ Serverless Function ไม่ถาวร - ห้ามใช้เป็น database
            return UnavailableStorage(wanted, "JSON_STORAGE_NOT_ALLOWED_ON_VERCEL")   # (ยกเว้นโหมด DEMO ที่เปิดเองเมื่อไม่ได้ตั้งค่าอะไรเลย - ดู config.DEMO_EPHEMERAL)
        return JSONStorage(data_dir)
    if not config.REDIS_REST_URL or not config.REDIS_REST_TOKEN:
        return UnavailableStorage(wanted, "REDIS_NOT_CONFIGURED")
    if not redis_url_is_acceptable(config.REDIS_REST_URL):
        return UnavailableStorage(wanted, "REDIS_URL_INVALID")
    return RedisStorage(UpstashRestClient(config.REDIS_REST_URL, config.REDIS_REST_TOKEN))
