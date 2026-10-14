"""Security probes against a NON-production copy (default http://127.0.0.1:8775). Usage:
   GAC_BASE=http://127.0.0.1:8775 python audits/scripts/security_probe.py <admin> <adminpw> <reviewer> <reviewerpw>"""
import os, sys, io, json, re, http.client, urllib.parse
from PIL import Image
B = os.environ.get("GAC_BASE", "http://127.0.0.1:8775"); U = urllib.parse.urlsplit(B)
def req(method, path, body=None, headers=None, cookie=None):
    c = http.client.HTTPConnection(U.hostname, U.port, timeout=120); h = dict(headers or {})
    if cookie: h["Cookie"] = "gac_session=" + cookie
    if isinstance(body, (dict, list)): body = json.dumps(body); h.setdefault("Content-Type", "application/json")
    h.setdefault("Origin", B) if method != "GET" and "Origin" not in h and "_noorigin" not in h else None
    h.pop("_noorigin", None)
    c.request(method, path, body=body, headers=h); r = c.getresponse(); d = r.read(); return r.status, dict(r.getheaders()), d
def login(u, p):
    s, h, d = req("POST", "/api/auth/login", {"username": u, "password": p})
    m = re.search(r"gac_session=([^;]+)", h.get("set-cookie", "")); return m.group(1) if m else None, h.get("set-cookie", "")
def mp(fields, fname, data, ctype="image/jpeg"):
    bd = "----x"; out = b""
    for k, v in fields.items(): out += f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += f'--{bd}\r\nContent-Disposition: form-data; name="image"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + f"\r\n--{bd}--\r\n".encode()
    return out, {"Content-Type": "multipart/form-data; boundary=" + bd}
res = []
def chk(ok, name, detail=""): res.append((bool(ok), name, detail)); print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

adm, cookie_hdr = login(sys.argv[1], sys.argv[2]); rev, _ = login(sys.argv[3], sys.argv[4])
chk(adm and rev, "logins work")
chk("httponly" in cookie_hdr.lower() and "samesite=lax" in cookie_hdr.lower(), "session cookie HttpOnly + SameSite=Lax", cookie_hdr)
chk("secure" not in cookie_hdr.lower().replace("samesite", ""), "cookie not Secure over plain http (expected; Secure is set under https)", "")

# ---- authz matrix over every registered route
sys.path.insert(0, os.getcwd()); from app.main import app
def _flat(rs):
    for r in rs:
        if hasattr(r, 'original_router'): yield from _flat(r.original_router.routes)
        else: yield r
matrix = []
for r in _flat(app.routes):
    path = getattr(r, "path", ""); methods = sorted(getattr(r, "methods", None) or [])
    if not path or path.startswith("/static") or path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"): continue
    p = path.replace("{cid}", "1").replace("{uid}", "999").replace("{eid}", "1").replace("{name}", "x.jpg").replace("{kind}", "csv")
    for m in methods:
        if m == "HEAD": continue
        body = {} if m == "POST" else None
        if p == "/api/auth/logout": continue   # would kill our sessions
        row = {"route": f"{m} {path}"}
        for who, ck in (("anon", None), ("reviewer", rev), ("admin", adm)):
            if m == "POST" and who == "admin" and p in ("/api/admin/retention/run", "/api/batches/archive", "/api/undo", "/api/admin/settings", "/api/me/password"): row[who] = "skipped(destructive)"; continue
            if m == "POST" and who == "reviewer" and p in ("/api/batches/archive", "/api/undo", "/api/me/password"): row[who] = "skipped(destructive)"; continue
            s, h, d = req(m, p, body, cookie=ck); row[who] = s
        matrix.append(row)
for row in matrix: print(json.dumps(row))
open_anon = [r for r in matrix if isinstance(r["anon"], int) and r["anon"] < 300 and not any(r["route"].endswith(x) for x in ("/login", "/setup", "/health", "/privacy", "/api/auth/state", "/api/auth/policy"))]
chk(not open_anon, "no data route open to anonymous (except /api/scan from loopback)", json.dumps(open_anon))
adm_routes = [r for r in matrix if "/api/admin/" in r["route"]]
chk(all(r["reviewer"] in (403, "skipped(destructive)") for r in adm_routes), "reviewer gets 403 on every /api/admin/* route")
s, *_ = req("GET", "/api/admin/users", cookie=rev); chk(s == 403, "reviewer cannot list users")
s, *_ = req("POST", "/api/admin/users", {"username": "evil", "display": "e", "password": "xxxxxxxxxxxx", "role": "admin"}, cookie=rev); chk(s == 403, "reviewer cannot create an admin")
s, *_ = req("POST", "/api/batches/archive", {"batch": "__all__"}, cookie=rev); chk(s == 403, "reviewer cannot clear all data")
s, *_ = req("POST", "/api/auth/setup", {"username": "x2", "display": "x", "password": "yyyyyyyyyyyy"}); chk(s == 409, "setup refused once an admin exists")

# ---- CSRF
s, *_ = req("POST", "/api/cards-bulk", {"ids": [], "status": "rejected"}, headers={"Origin": "http://evil.example"}, cookie=rev); chk(s == 403, "cross-origin POST refused (Origin check)", s)
s, *_ = req("POST", "/api/cards-bulk", {"ids": [], "status": "rejected"}, headers={"Origin": "http://127.0.0.1:1339"}, cookie=rev); chk(s == 403, "same-host other-port POST refused", s)
s, *_ = req("POST", "/api/cards-bulk", {"ids": [], "status": "rejected"}, headers={"Origin": "null"}, cookie=rev); chk(s == 403, "Origin: null refused", s)
s, *_ = req("POST", "/api/cards-bulk", {"ids": [], "status": "rejected"}, headers={"_noorigin": "1"}, cookie=rev); chk(s == 200, "no-Origin JSON client (scripts) still works", s)
s, *_ = req("POST", "/api/cards-bulk", "ids=1&status=rejected", headers={"Content-Type": "application/x-www-form-urlencoded"}, cookie=rev); chk(s == 422, "form-encoded body (classic CSRF form) rejected by JSON body parser", s)

# ---- headers
s, h, _ = req("GET", "/ui", cookie=rev)
chk("frame-ancestors 'none'" in h.get("content-security-policy", "") and h.get("x-frame-options") == "DENY", "CSP + anti-framing headers on /ui")
s, h, _ = req("GET", "/api/cards", cookie=rev); chk(h.get("cache-control") == "no-store", "API responses no-store")

# ---- path traversal
for p in ("/img/..%2f..%2fapp%2fauth.py", "/img/%2e%2e%2fcards.db", "/img/..%5c..%5cdata%5ccards.db", "/static/..%2f..%2fdata%2fcards.db", "/static/ui/..%2f..%2f..%2fdata%2fcards.db"):
    s, h, d = req("GET", p, cookie=rev); chk(b"SQLite" not in d and b"import" not in d[:200], f"traversal blocked {p}", f"{s} {h.get('content-type')}")
s, *_ = req("GET", "/api/exports/1%20OR%201=1/download", cookie=rev); chk(s == 422, "export id is typed int", s)

# ---- SQL injection probes (all queries are parameterised; these must not error or leak)
for p in ("/api/cards?status=pending'%20OR%20'1'='1", "/api/cards?batch=x'%3B--", "/api/admin/audit?q=%27%20UNION%20SELECT%20pw%20FROM%20users--&limit=5"):
    s, h, d = req("GET", p, cookie=adm); chk(s == 200 and b"pbkdf2" not in d, f"SQLi probe harmless {p}", s)
s, _, d = req("POST", "/api/auth/login", {"username": "' OR 1=1 --", "password": "x"}); chk(s == 401, "SQLi in login username fails", s)

# ---- uploads
def jpg(w=800, h=500):
    im = Image.new("RGB", (w, h), "white"); from PIL import ImageDraw; dr = ImageDraw.Draw(im)
    for i in range(0, w, 40): dr.line((i, 0, w - i, h), fill=(i % 255, 0, 0))
    b = io.BytesIO(); im.save(b, "JPEG"); return b.getvalue()
bomb = io.BytesIO(); Image.new("1", (20000, 20000)).save(bomb, "PNG"); bomb = bomb.getvalue()   # ~400 MP, ~60 KB file
body, h = mp({"batch_label": "sec"}, "bomb.png", bomb, "image/png"); s, _, d = req("POST", "/api/jobs", body, h, cookie=rev)
chk(s == 422 and b"too large" in d, f"decompression bomb ({len(bomb)//1024} KB -> 400 MP) refused before decode", d[:120])
eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 800 500\nshowpage\n"
body, h = mp({}, "card.jpg", eps); s, _, d = req("POST", "/api/jobs", body, h, cookie=rev); chk(s == 422, "EPS disguised as .jpg refused (no Ghostscript decode)", d[:100])
html_ = b"<html><script>alert(1)</script></html>" + b" " * 2000
body, h = mp({}, "card.png", html_, "image/png"); s, _, d = req("POST", "/api/jobs", body, h, cookie=rev); chk(s == 422, "HTML disguised as .png refused", d[:100])
body, h = mp({}, "../../../../tmp/evil.jpg", jpg()); s, _, d = req("POST", "/api/jobs", body, h, cookie=rev)
chk(s in (200, 409) and not os.path.exists("/tmp/evil.jpg"), "path-traversal filename ignored (server names files by uuid)", d[:100])
big = b"\xff\xd8" + b"0" * (27 * 1024 * 1024)
body, h = mp({}, "big.jpg", big); s, _, d = req("POST", "/api/jobs", body, h, cookie=rev); chk(s == 413, "27 MB upload refused before body is read", s)
body, h = mp({}, "x.jpg", eps); s, _, d = req("POST", "/api/scan", body, h); chk(s == 422, "/api/scan (loopback) also validates the image now", s)

# ---- XSS: OCR/field text containing markup is stored verbatim and must be escaped by the UI (see a11y/xss playwright check)
s, _, d = req("GET", "/api/cards", cookie=rev); cards = json.loads(d)
if cards:
    cid = cards[0]["id"]; pay = '<img src=x onerror="window.__xss=1">"><script>window.__xss=1</script>'
    s, _, d = req("POST", f"/api/cards/{cid}", {"fields": {"company": pay, "title": pay}, "note": pay}, cookie=rev)
    chk(s == 200, "stored XSS payload in card fields (for the browser check)", cid); print("XSS_CARD", cid)
print(f"\n{sum(r[0] for r in res)}/{len(res)} probes passed")
json.dump({"probes": res, "matrix": matrix}, open(os.environ.get("OUT", "audits/raw/security_probe.json"), "w"), indent=1, default=str)
