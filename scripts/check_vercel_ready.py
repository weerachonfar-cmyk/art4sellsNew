"""check_vercel_ready.py - ตรวจว่าโปรเจกต์ "ตั้งค่าครบพอจะ deploy ขึ้น Vercel" หรือยัง (ตรวจไฟล์/โครงสร้างในเครื่องเท่านั้น)

รัน:   python scripts/check_vercel_ready.py            (ตรวจโฟลเดอร์โปรเจกต์นี้)
       python scripts/check_vercel_ready.py --root DIR (ตรวจโฟลเดอร์อื่น เช่นสำเนาที่ใช้ทดสอบสคริปต์)
ผลลัพธ์รายข้อ: PASS / WARN / FAIL   และสรุปท้ายสุดเป็น PASS / WARN / FAIL (exit code 1 เมื่อมี FAIL)
- FAIL = ขาดของที่ "จำเป็น" (config/ไฟล์/ความปลอดภัย)   WARN = ใช้ได้แต่ควรรู้ / ตรวจเองไม่ได้   PASS = ผ่านการตรวจแบบที่สคริปต์ทำได้
- สคริปต์นี้ "ไม่ได้ deploy และไม่ได้ต่อ network" จึงยืนยันไม่ได้ว่า deploy สำเร็จจริง  (ผลสุดท้ายจะบอกเรื่องนี้เสมอ)
ใช้เฉพาะ Python Standard Library
"""
import ast
import importlib
import json
import re
import sys
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
REQUIRED_ENV_KEYS = ("A4S_STORAGE", "A4S_EMAIL_MODE", "A4S_DEV_TOOLS", "A4S_CORS_ORIGINS", "A4S_PBKDF2_ITERATIONS",
                     "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "BLOB_READ_WRITE_TOKEN")
SECRET_ENV_KEYS = ("UPSTASH_REDIS_REST_TOKEN", "BLOB_READ_WRITE_TOKEN", "A4S_DEMO_PASSWORD")
SECRET_PATTERNS = (                                    # (ชื่อ, regex)  ตรวจเฉพาะรูปแบบที่ "ดูเป็นความลับจริง"
    ("Vercel Blob token", re.compile(r"vercel_blob_rw_[A-Za-z0-9_]{10,}")),
    ("Bearer JWT", re.compile(r"Bearer\s+eyJ[A-Za-z0-9_-]{20,}")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Upstash REST URL with token", re.compile(r"https://[a-z0-9-]+\.upstash\.io")),
    ("generic API key", re.compile(r"(?i)\b(?:api[_-]?key|secret|token)\s*=\s*[\"'][A-Za-z0-9_\-]{24,}[\"']")),
)
LOCAL_PATH_PATTERN = re.compile(r"(?:/home/[A-Za-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/|[A-Za-z]:\\\\Users\\\\|[A-Za-z]:\\Users\\|/mnt/(?:user-data|skills))")
SCAN_DIRS = ("api", "backend", "src", "scripts", "public", "training")
SKIP_PARTS = ("tests", "test", "__pycache__", "data", "logs", "exports")


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, name, detail=""):
        self.rows.append((level, name, detail))

    def worst(self):
        levels = [row[0] for row in self.rows]
        return FAIL if FAIL in levels else (WARN if WARN in levels else PASS)


def source_files(root, suffixes=(".py", ".js", ".html", ".json", ".md")):
    for folder in SCAN_DIRS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in suffixes and not any(part in SKIP_PARTS for part in path.relative_to(root).parts):
                yield path


def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def check_vercel_json(root, report):
    path = root / "vercel.json"
    if not path.is_file():
        return report.add(FAIL, "vercel.json", "ไม่พบไฟล์")
    try:
        config = json.loads(read(path))
    except ValueError as err:
        return report.add(FAIL, "vercel.json", "JSON ผิดรูปแบบ: " + str(err))
    rewrites = config.get("rewrites", [])
    by_source = {r.get("source"): r.get("destination", "") for r in rewrites if isinstance(r, dict)}
    build_cmd = str(config.get("buildCommand", ""))
    if "public/." in build_cmd:
        report.add(PASS, "static root  /  ->  public/*", "buildCommand คัดลอกเนื้อหา public/ ไปไว้ราก dist/ (/, /login.html, /style.css ใช้ได้)")
    elif by_source.get("/") == "/public/index.html":
        report.add(WARN, "static root  /  ->  public/index.html", "ใช้ rewrite เดิม: ตรวจให้ดีว่า style.css และลิงก์ *.html เปิดได้จาก / ")
    else:
        report.add(FAIL, "static root  /  ->  public/*", "buildCommand ไม่ได้คัดลอก public/ ไปราก dist/ และไม่มี rewrite ของ /")
    # path ใน vercel.json ต้องมีอยู่จริงใน repo (เคยพลาด: ใส่ prefix art4sells/ ทั้งที่ไม่มีโฟลเดอร์นี้ -> build ล้มเหลว)
    for source in re.findall(r"cp -R (\S+)", build_cmd):
        if not (root / source.rstrip("/.")).exists():
            report.add(FAIL, "buildCommand path", "คัดลอกจาก '" + source + "' แต่ไม่พบใน repo")
    for func_path in (config.get("functions") or {}):
        if (root / func_path).is_file():
            report.add(PASS, "functions['" + func_path + "']", "ตรงกับไฟล์จริง")
        else:
            report.add(FAIL, "functions['" + func_path + "']", "ไม่พบไฟล์นี้ใน repo (Vercel จะ build ไม่ผ่าน)")
    api_rules = [r for r in rewrites if isinstance(r, dict) and str(r.get("source", "")).startswith("/api")]
    if not api_rules:
        report.add(FAIL, "route /api/*  ->  Python Function", "ไม่มี rewrite สำหรับ /api/*")
    elif any("public" in str(r.get("destination", "")) for r in api_rules):
        report.add(FAIL, "route /api/*  ->  Python Function", "/api/* ถูก rewrite ไปที่ public/ (ต้องไปที่ฟังก์ชัน)")
    else:
        report.add(PASS, "route /api/*  ->  Python Function", "ไม่ถูก rewrite ไป public/")
    catch_all = [r for r in rewrites if isinstance(r, dict) and r.get("source") in ("/(.*)", "/:path*", "/:path(.*)")
                 and "api" not in str(r.get("destination", ""))]
    if catch_all:
        report.add(FAIL, "catch-all rewrite", "rewrite แบบ /(.*) อาจกลืน /api/* (ต้องไม่มี หรืออยู่หลังกฎ /api)")
    if config.get("outputDirectory") and config.get("buildCommand"):
        report.add(PASS, "frontend static output", "buildCommand + outputDirectory ตั้งไว้ (คัดลอก public/ และ src/)")
        if "src" not in str(config.get("buildCommand")) or "public" not in str(config.get("buildCommand")):
            report.add(FAIL, "frontend build", "buildCommand ต้องคัดลอกทั้ง public/ และ src/ (หน้าเว็บอ้าง ../src/...)")
    else:
        report.add(WARN, "frontend static output", "ไม่ได้ตั้ง buildCommand/outputDirectory - ตรวจว่า /public/* และ /src/* เปิดได้บน Vercel")
    headers = json.dumps(config.get("headers", []))
    missing = [h for h in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy") if h not in headers]
    report.add(PASS if not missing else WARN, "security headers (static files)", "ครบ" if not missing else "ขาด " + ", ".join(missing))


def check_api_function(root, report):
    path = root / "api" / "index.py"
    if not path.is_file():
        return report.add(FAIL, "api/index.py", "ไม่พบไฟล์")
    text = read(path)
    try:
        tree = ast.parse(text)
    except SyntaxError as err:
        return report.add(FAIL, "api/index.py", "syntax error: " + str(err))
    has_handler = any(isinstance(n, ast.ClassDef) and n.name == "handler" for n in tree.body) or any(
        isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "app" for t in n.targets) for n in tree.body)
    report.add(PASS if has_handler else FAIL, "api/index.py มี handler / app", "" if has_handler else "ไม่พบ class handler หรือตัวแปร app")
    imports_server = any(                              # เจาะจง backend/server.py เท่านั้น (http.server ของ stdlib ไม่นับ)
        (isinstance(n, ast.ImportFrom) and ((n.module or "") == "backend.server"
                                            or ((n.module or "") == "backend" and any(a.name == "server" for a in n.names))))
        or (isinstance(n, ast.Import) and any(a.name == "backend.server" for a in n.names)) for n in ast.walk(tree))
    report.add(FAIL if imports_server else PASS, "api/index.py ไม่พึ่ง backend/server.py", "import server อยู่" if imports_server else "")
    lines = len([ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")])
    report.add(PASS if lines <= 80 else WARN, "api/index.py เป็นแค่ adapter", str(lines) + " บรรทัดโค้ด" + ("" if lines <= 80 else " (มาก - ตรวจว่าไม่มี business logic)"))


def check_env_example(root, report):
    path = root / ".env.example"
    if not path.is_file():
        return report.add(FAIL, ".env.example", "ไม่พบไฟล์")
    values = {}
    for line in read(path).splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    missing = [k for k in REQUIRED_ENV_KEYS if k not in values]
    report.add(PASS if not missing else FAIL, ".env.example มี key ครบ", "ขาด " + ", ".join(missing) if missing else "")
    leaked = [k for k in SECRET_ENV_KEYS if values.get(k)]
    report.add(PASS if not leaked else FAIL, ".env.example ไม่มีค่าความลับจริง", "มีค่าใน " + ", ".join(leaked) if leaked else "")
    if values.get("A4S_DEV_TOOLS", "false").lower() == "true":
        report.add(FAIL, ".env.example A4S_DEV_TOOLS", "ค่าตัวอย่างต้องเป็น false")
    for name in (".env", ".env.local"):
        if (root / name).exists():
            report.add(FAIL, "ไม่มี " + name + " ในโปรเจกต์", "พบไฟล์ " + name + " (ห้าม commit ค่าจริง)")
    gitignore = read(root / ".gitignore")
    missing_ignore = [n for n in (".env", ".env.local") if not re.search(r"(?m)^" + re.escape(n) + r"\s*$", gitignore)]
    report.add(PASS if not missing_ignore else FAIL, ".gitignore กัน .env / .env.local", "ขาด " + ", ".join(missing_ignore) if missing_ignore else "")


def check_requirements(root, report):
    text = read(root / "requirements.txt")
    if not text:
        return report.add(FAIL, "requirements.txt", "ไม่พบไฟล์หรือว่างเปล่า")
    names = {re.split(r"[<>=!~\[ ;]", ln.strip(), maxsplit=1)[0].lower() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")}
    report.add(PASS if {"pillow", "vercel"} <= names else FAIL, "requirements.txt", "มี Pillow + vercel" if {"pillow", "vercel"} <= names else "ต้องมี Pillow และ vercel (ได้ " + ", ".join(sorted(names)) + ")")


def check_frontend(root, report):
    ok_pages = (root / "public" / "index.html").is_file() and (root / "src" / "app.js").is_file()
    report.add(PASS if ok_pages else FAIL, "frontend (public/ + src/)", "" if ok_pages else "ไม่พบ public/index.html หรือ src/app.js")


def check_backend_imports(root, report):
    sys.path.insert(0, str(root))
    for name in [m for m in list(sys.modules) if m == "backend" or m.startswith("backend.")]:
        del sys.modules[name]                          # import จาก --root ที่ระบุ ไม่ใช่ตัวที่ cache ไว้
    bad, modules_dir = [], root / "backend" / "modules"
    if not modules_dir.is_dir():
        sys.path.pop(0)
        return report.add(FAIL, "backend imports", "ไม่พบ backend/modules/")
    for path in sorted(modules_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            importlib.import_module("backend.modules." + path.stem)
        except Exception as err:                       # import ล้มด้วยเหตุใดก็ตาม = deploy ไม่ได้
            bad.append(path.stem + ": " + type(err).__name__ + ": " + str(err)[:80])
    sys.path.pop(0)
    report.add(PASS if not bad else FAIL, "backend modules import ได้ทุกตัว", "; ".join(bad))


def check_storage_adapters(root, report):
    text = read(root / "backend" / "modules" / "storage_providers.py")
    needed = ("class JSONStorage", "class RedisStorage", "def build_provider", "class UnavailableStorage")
    missing = [n for n in needed if n not in text]
    report.add(PASS if not missing else FAIL, "storage adapters (JSON / Redis / ไม่ fallback เงียบ)", "ขาด " + ", ".join(missing) if missing else "")
    report.add(PASS if (root / "backend" / "modules" / "file_storage.py").is_file() else FAIL, "file storage adapter (Local / Vercel Blob)")


def check_secrets_and_paths(root, report):
    secrets_found, paths_found, server_imports = [], [], []
    for path in source_files(root):
        text, rel = read(path), str(path.relative_to(root))
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                secrets_found.append(rel + " (" + label + ")")
        if LOCAL_PATH_PATTERN.search(text):
            paths_found.append(rel)
        if path.suffix == ".py" and rel.startswith("backend/modules/") and re.search(r"(?m)^\s*(?:from|import)\s+backend\.server\b|^\s*from backend import .*\bserver\b", text):
            server_imports.append(rel)
    report.add(PASS if not secrets_found else FAIL, "ไม่มี secret ที่ฝังในโค้ด", "; ".join(secrets_found[:5]))
    report.add(PASS if not paths_found else FAIL, "ไม่มี absolute path ของเครื่องตัวเอง", "; ".join(paths_found[:5]))
    report.add(PASS if not server_imports else FAIL, "backend/modules ไม่ import server.py", "; ".join(server_imports))
    demo = re.search(r"A4S_DEMO_PASSWORD\"\s*,\s*\"[^\"]+\"", read(root / "backend" / "seed.py"))
    if demo:
        report.add(WARN, "รหัสผ่าน demo มีค่าเริ่มต้นใน seed.py", "เป็นรหัสตัวอย่างสาธารณะ - บน Vercel ควรตั้ง A4S_DEMO_PASSWORD เอง")


def run_checks(root):
    root = Path(root).resolve()
    report = Report()
    check_vercel_json(root, report)
    check_api_function(root, report)
    check_env_example(root, report)
    check_requirements(root, report)
    check_frontend(root, report)
    check_backend_imports(root, report)
    check_storage_adapters(root, report)
    check_secrets_and_paths(root, report)
    report.add(WARN, "การ deploy จริงบน Vercel", "สคริปต์นี้ตรวจเฉพาะไฟล์ในเครื่อง - ยังไม่ได้ทดสอบ deploy / Redis / Blob จริง (ดู VERCEL_DEPLOYMENT.md)")
    return report


def main(argv):
    root = Path(__file__).resolve().parent.parent
    if "--root" in argv:
        root = Path(argv[argv.index("--root") + 1])
    report = run_checks(root)
    for level, name, detail in report.rows:
        print("[" + level + "] " + name + ((" - " + detail) if detail else ""))
    print("\nVercel readiness: " + report.worst())
    return 1 if report.worst() == FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
