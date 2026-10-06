"""fake_upstash.py - เซิร์ฟเวอร์จำลอง Upstash Redis REST (ใช้ในเทสต์เท่านั้น ไม่ใช่ Redis จริง)

รองรับเฉพาะคำสั่งที่ RedisStorage ใช้: PING, GET, SET (NX / PX), DEL, EXISTS, EVAL (สคริปต์ปลดล็อกเฉพาะที่ระบบใช้)
เก็บข้อมูลในหน่วยความจำ จึงเทสต์ provider ได้โดย "ไม่แตะ production data" และไม่ต้องมี network

ข้อจำกัด: จำลองพฤติกรรมของคำสั่งพวกนี้เท่านั้น - ไม่ได้พิสูจน์ว่า Upstash ของจริงตอบเหมือนกันทุกกรณี
(การทดสอบกับ Upstash จริงต้องทำเองด้วย credential ของตัวเอง ดู VERCEL_DEPLOYMENT.md)
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VALID_TOKEN = "test-token-not-a-secret"


class FakeUpstash:
    def __init__(self):
        self.data = {}                                 # key -> (value, หมดอายุเมื่อ monotonic เท่าไร หรือ None)
        self.commands = []                             # เก็บชื่อคำสั่งที่ถูกเรียก (ใช้ตรวจในเทสต์)
        self.fail_next = 0                             # >0 = ตอบ 500 กี่ครั้งถัดไป (ทดสอบ Redis ล่ม)
        self._guard = threading.Lock()
        self._server = None

    # ---- ตัวคำสั่ง ----
    def _alive(self, key):
        item = self.data.get(key)
        if item is None:
            return None
        if item[1] is not None and item[1] <= time.monotonic():
            del self.data[key]
            return None
        return item

    def execute(self, args):
        name = str(args[0]).upper()
        with self._guard:
            self.commands.append(name)
            if name == "PING":
                return "PONG"
            if name == "GET":
                item = self._alive(args[1])
                return item[0] if item else None
            if name == "MGET":
                values = []
                for key in args[1:]:
                    item = self._alive(key)
                    values.append(item[0] if item else None)
                return values
            if name == "EXISTS":
                return 1 if self._alive(args[1]) else 0
            if name == "DEL":
                return 1 if self.data.pop(args[1], None) is not None else 0
            if name == "SET":
                key, value, options = args[1], args[2], [str(a).upper() for a in args[3:]]
                if "NX" in options and self._alive(key):
                    return None
                expires = None
                if "PX" in options:
                    expires = time.monotonic() + int(args[3 + options.index("PX") + 1]) / 1000.0
                self.data[key] = (value, expires)
                return "OK"
            if name == "EVAL":
                if "redis.call('get',KEYS[1])==ARGV[1]" not in args[1]:
                    raise ValueError("ERR unsupported script")
                key, token = args[3], args[4]
                item = self._alive(key)
                if item and item[0] == token:
                    del self.data[key]
                    return 1
                return 0
        raise ValueError("ERR unknown command " + name)

    # ---- HTTP ----
    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                if outer.fail_next > 0:
                    outer.fail_next -= 1
                    return self._reply(500, {"error": "simulated outage"})
                if self.headers.get("Authorization") != "Bearer " + VALID_TOKEN:
                    return self._reply(401, {"error": "Unauthorized"})
                try:
                    result = outer.execute(json.loads(raw.decode("utf-8")))
                except ValueError as err:
                    return self._reply(400, {"error": str(err)})
                self._reply(200, {"result": result})

            def _reply(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return "http://127.0.0.1:" + str(self._server.server_address[1])

    def stop(self):
        if self._server:
            server, self._server = self._server, None      # เรียกซ้ำได้ (ปลอดภัย)
            server.shutdown()
            server.server_close()
