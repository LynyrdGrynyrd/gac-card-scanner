"""Local logins for the pilot: named reviewers, PBKDF2-hashed passwords, admin role, cookie sessions.
No external identity provider; everything lives in the same SQLite DB (tables users, sessions, settings, auth_log)."""
import os, re, time, hmac, hashlib, secrets, threading
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from . import store, demo

router = APIRouter()
STATIC = os.path.join(os.path.dirname(__file__), "static")
COOKIE = "gac_session"; SESSION_HOURS = 12; ITER = 310_000
SESSION_MAX_HOURS = float(os.environ.get("GAC_SESSION_MAX_HOURS", str(7 * 24)))   # absolute limit, sliding expiry or not
PUBLIC_PREFIX = ("/static/", "/api/auth/")
PUBLIC = {"/login", "/setup", "/health", "/favicon.ico", "/privacy", "/api/demo", "/help", "/ui/help"}   # v0.4.2 #10: public help
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

def _init_auth(c):
    c.execute("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, display TEXT,
      initials TEXT, role TEXT DEFAULT 'reviewer', pw TEXT, active INTEGER DEFAULT 1, created REAL, must_change INTEGER DEFAULT 0)""")
    c.execute("CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created REAL, expires REAL, ip TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS auth_log(id INTEGER PRIMARY KEY, ts REAL, username TEXT, event TEXT, ip TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id)")
    _dedupe_initials(c)
def db():
    c = store.db(); store.once("auth", _init_auth)
    return c

# ---------------- settings
DEFAULTS = {"image_retention_days": "30", "export_retention_days": "30", "retention_enabled": "1", "ai_check_enabled": "1", "corrections_enabled": "0", "mctrade_affcode": "CardScan-Pilot", "phone_format": "gac", "mctrade_updates_enabled": "0", "phone_mode_allowed": "1", "update_check_enabled": "1"}
def get_setting(k):
    r = db().execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r[0] if r else DEFAULTS.get(k)
def set_setting(k, v):
    with db() as c: c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, str(v)))

# ---------------- passwords
def hash_pw(pw):
    salt = secrets.token_bytes(16)
    return f"pbkdf2_sha256${ITER}${salt.hex()}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, ITER).hex()}"
def check_pw(pw, stored):
    try:
        _, it, salt, h = stored.split("$")
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex(), h)
    except Exception: return False
def pw_problem(pw):
    if not isinstance(pw, (str, type(None))): return "The password must be text."   # fuzz 2026-10: password: true was a 500
    if len(pw or "") < 10: return "Password must be at least 10 characters."
    return None

def _unique_initials(ini, taken):
    k = 2
    while f"{ini[:6 - len(str(k))]}{k}" in taken: k += 1
    return f"{ini[:6 - len(str(k))]}{k}"
def _dedupe_initials(c):
    """Audit 2026-10 F11: older versions allowed two people with the same initials (Alex Brown and Amy Baker = AB), which
    mixed up whose batches and uploads were whose. The later account gets a number (AB2). Earlier history rows keep the
    shared initials (they can't be told apart afterwards)."""
    seen = set()
    for uid, un, ini in c.execute("SELECT id, username, UPPER(initials) FROM users ORDER BY id").fetchall():
        if ini in seen:
            new = _unique_initials(ini, seen | {r[0].upper() for r in c.execute("SELECT initials FROM users")})
            c.execute("UPDATE users SET initials=? WHERE id=?", (new, uid))
            c.execute("INSERT INTO auth_log(ts,username,event,ip) VALUES(?,?,?,?)", (time.time(), un, f"initials changed from {ini} to {new}: another person already used {ini}", None))
            ini = new
        seen.add(ini)
def _initials(display):
    return "".join(p[0] for p in display.split()[:3]).upper() or "?"

def create_user(username, display, password, role="reviewer", initials=None, must_change=False):
    if not all(isinstance(x, (str, type(None))) for x in (username, display, initials)):   # fuzz 2026-10: username: null was a 500
        raise ValueError("Username, name and initials must be text.")
    username = (username or "").strip().lower()
    if not username or not username.replace(".", "").replace("-", "").replace("_", "").isalnum(): raise ValueError("Username: letters, numbers, . - _ only.")
    p = pw_problem(password)
    if p: raise ValueError(p)
    if role not in ("admin", "reviewer"): raise ValueError("Role must be admin or reviewer.")
    ini = (initials or _initials(display or username)).upper()[:6]
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone(): raise ValueError("That username already exists.")
        # audit 2026-10 P1 (F11): initials are how cards, batches and uploads are attributed ("mine", Cancel, history), so
        # two people must never share them: chosen initials that are taken are refused, derived ones get a number
        taken = {(r[0] or "").upper() for r in c.execute("SELECT initials FROM users")}
        if ini in taken:
            if initials: raise ValueError(f"The initials {ini} are already used by another person. Choose different initials.")
            ini = _unique_initials(ini, taken)
        return c.execute("INSERT INTO users(username,display,initials,role,pw,created,must_change) VALUES(?,?,?,?,?,?,?)",
                         (username, display or username, ini, role, hash_pw(password), time.time(), int(must_change))).lastrowid

def user_count(): return db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
def pub(u): return {k: u[k] for k in ("id", "username", "display", "initials", "role", "active", "created", "must_change")}

def alog(username, event, ip=None):
    if demo.enabled(): ip = None   # public demo: no record of visitors' addresses
    with db() as c: c.execute("INSERT INTO auth_log(ts,username,event,ip) VALUES(?,?,?,?)", (time.time(), username, event, ip))

def current_user(request: Request):
    tok = request.cookies.get(COOKIE)
    if not tok: return None
    now = time.time(); h = hashlib.sha256(tok.encode()).hexdigest()
    c = db(); r = c.execute("SELECT u.*, s.expires AS _s_exp FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? "
                            "AND s.created>? AND u.active=1", (h, now, now - SESSION_MAX_HOURS * 3600)).fetchone()
    if not r: return None
    # audit 2026-10 P1: the sliding expiry is written at most every 5 minutes (it was a database write on EVERY request,
    # polling included), and a session ends SESSION_MAX_HOURS after sign-in however active it is
    if r["_s_exp"] < now + SESSION_HOURS * 3600 - 300:
        with c: c.execute("UPDATE sessions SET expires=? WHERE token=?", (now + SESSION_HOURS * 3600, h))
    d = dict(r); d.pop("_s_exp", None); return d

def _client(request): return request.client.host if request.client else ""
def trusted_host(request):
    """Audit 2026-10 P0-11 (DNS rebinding): a page on attacker.example can re-point its own name at 127.0.0.1 and then talk
    to the scanner from the user's browser; the request comes from loopback and its Origin matches its Host, so neither
    check notices. Such a request always names the attacker's DOMAIN in Host. Anything that trusts loopback (first-admin
    setup, the open /api/scan) therefore also needs Host to be an IP address, localhost, this computer's own name, or a
    name listed in GAC_ALLOWED_HOSTS (comma-separated, for a reverse proxy or a fixed office name)."""
    import ipaddress, socket
    h = (request.headers.get("host") or "").strip().lower()
    h = h[1:h.index("]")] if h.startswith("[") and "]" in h else h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if not h: return False
    try: ipaddress.ip_address(h); return True
    except ValueError: pass
    me = socket.gethostname().lower()
    extra = {x.strip().lower() for x in os.getenv("GAC_ALLOWED_HOSTS", "").split(",") if x.strip()}
    return h in {"localhost", me, me + ".local"} | extra or h.endswith(".localhost")
def _loopback_trusted(request): return _client(request) in LOOPBACK and trusted_host(request)

SEC_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                               "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()"}
if os.environ.get("GAC_DESKTOP") == "1":
    # Desktop app (pywebview): its bridge script builds window.pywebview.api with `new Function(...)` (webview/js/api.js), which
    # script-src 'self' blocks as eval ("Refused to evaluate a string as JavaScript"). Without it, desktop.js sees no
    # pywebview.api.save_file and exports fall back to a webview download, which pywebview cancels by default. Inline
    # scripts stay blocked; the server only listens on 127.0.0.1 in the desktop build.
    SEC_HEADERS["Content-Security-Policy"] = SEC_HEADERS["Content-Security-Policy"].replace("script-src 'self'", "script-src 'self' 'unsafe-eval'", 1)
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
MAX_BODY = 26 * 1024 * 1024   # one photo (25 MB) + form overhead; checked before the body is read

CSRF_COOKIE = "gac_csrf"; CSRF_HEADER = "x-csrf-token"
CSRF_EXEMPT = {"/api/auth/login", "/api/auth/setup", "/api/auth/logout"}   # no session yet (logout: round 23, the login page may hold a stale CSRF cookie); protected by Origin/Referer
def csrf_for(tok):
    """Per-session CSRF token (double-submit): readable cookie, echoed back by the page in X-CSRF-Token."""
    return hashlib.sha256(b"gac-csrf:" + tok.encode()).hexdigest()[:40]

def _no_origin(request):
    return not (request.headers.get("origin") or request.headers.get("referer"))

def _cross_origin(request):
    """CSRF defence in depth: a state-changing request whose Origin (or Referer) names another host:port is refused.
    SameSite=Lax alone does not stop other sites on the same host/LAN name (e.g. another app on another port)."""
    src = request.headers.get("origin") or request.headers.get("referer")
    if not src or src == "null": return src == "null"
    from urllib.parse import urlsplit
    u = urlsplit(src)   # scheme counts too: http://host:port is a different origin from https://host:port
    return (u.scheme.lower(), u.netloc.lower()) != (request.url.scheme.lower(), (request.headers.get("host") or "").lower())

async def middleware(request: Request, call_next):
    p = request.url.path
    if demo.enabled():
        r = demo.refuse(request)
        if r is not None:
            for k, v in SEC_HEADERS.items(): r.headers.setdefault(k, v)
            return r
    if request.method in UNSAFE:
        if _cross_origin(request):
            return JSONResponse({"error": "Cross-site request refused."}, 403, headers=SEC_HEADERS)
        if _no_origin(request) and not (p == "/api/scan" and _loopback_trusted(request)):
            return JSONResponse({"error": "Request refused. Reload the page and try again."}, 403, headers=SEC_HEADERS)
        tok = request.cookies.get(COOKIE)
        if tok and p not in CSRF_EXEMPT and not hmac.compare_digest(request.headers.get(CSRF_HEADER, ""), csrf_for(tok)):
            return JSONResponse({"error": "This page is out of date. Reload it and try again.", "need": "reload"}, 403, headers=SEC_HEADERS)
    try: clen = int(request.headers.get("content-length") or 0)
    except ValueError: clen = 0
    if clen > MAX_BODY: return JSONResponse({"error": "Upload is too large (limit 25 MB per photo)."}, 413, headers=SEC_HEADERS)
    resp = await _route(request, call_next)
    for k, v in SEC_HEADERS.items(): resp.headers.setdefault(k, v)
    if p.startswith("/api/"): resp.headers["X-GAC-Asset"] = asset_version()   # round 9: an open tab sees the app was updated
    ctype = resp.headers.get("content-type", "")
    if p.startswith("/api/") or ctype.startswith("text/html"): resp.headers["Cache-Control"] = "no-store"   # Back after sign-out must not show the app
    elif p.startswith("/static/ui/") and p.endswith((".js", ".css")):
        # audit 2026-10 P2: the page is ES modules; an imported module's URL carries no ?v= (the CSP blocks an inline import
        # map), so every module is revalidated on each load (ETag/Last-Modified -> 304) instead of being cached by heuristic
        resp.headers["Cache-Control"] = "no-cache"
    tok = request.cookies.get(COOKIE)
    if tok and getattr(request.state, "user", None) and request.cookies.get(CSRF_COOKIE) != csrf_for(tok):
        resp.set_cookie(CSRF_COOKIE, csrf_for(tok), httponly=False, samesite="strict", secure=request.url.scheme == "https", max_age=SESSION_HOURS * 3600, path="/")
    return resp

async def _route(request: Request, call_next):
    p = request.url.path
    if p in PUBLIC or p.startswith(PUBLIC_PREFIX):
        return await call_next(request)
    # machine API kept open on loopback only (benchmarks / scripts on the same computer)
    if p == "/api/scan" and _loopback_trusted(request):
        return await call_next(request)
    from starlette.concurrency import run_in_threadpool
    u = await run_in_threadpool(current_user, request)   # audit 2026-10 P1: database work off the event loop
    if not u:
        if p.startswith("/api/") or request.method != "GET":
            return JSONResponse({"error": "Sign in to continue.", "need": "login"}, 401)
        return RedirectResponse("/setup" if user_count() == 0 else "/login?next=" + __import__("urllib.parse").parse.quote(p, safe="/"), 303)
    request.state.user = u
    if (p.startswith("/api/admin/") or p.startswith("/sync/")) and u["role"] != "admin":
        return JSONResponse({"error": "Admins only."}, 403)
    resp = await call_next(request)
    resp.headers["X-GAC-User"] = str(u["id"])   # lets the page notice when another tab signed this browser in as someone else
    return resp

_fails = {}   # (username, client address) -> times of recent wrong passwords
_DUMMY_PW = f"pbkdf2_sha256${ITER}${'00' * 16}${'00' * 32}"   # never matches; costs the same PBKDF2 work as a real check
def _clear_fails(un):
    for k in [k for k in list(_fails) if k[0] == un]: _fails.pop(k, None)
def prune_fails(now=None):
    now = now or time.time()
    for k in [k for k, ts in list(_fails.items()) if not ts or max(ts) < now - 300]: _fails.pop(k, None)
@router.get("/login")
def login_page():
    if user_count() == 0: return RedirectResponse("/setup", 303)
    if demo.enabled(): return demo.page(os.path.join(STATIC, "ui", "login.html"), login=True)
    return versioned_html(os.path.join(STATIC, "ui", "login.html"))

_AV = {}
def asset_version():
    """Round 9 (reviewer r9): short fingerprint of the page code. Asset URLs carry it, so a new version is never served
    from an old cache, and the API sends it so an open tab can reload itself.
    audit 2026-10 P2: every script under static/ui (the ES modules in core/, ui/, views/, main.js, desktop.js, login.js) plus
    ui.css, so a change in any module changes the version."""
    import glob, hashlib
    root = os.path.join(STATIC, "ui")
    fs = sorted(set(glob.glob(os.path.join(root, "**", "*.js"), recursive=True)) | {os.path.join(root, "ui.css"), os.path.join(root, "login.js")})
    key = tuple((f, os.path.getmtime(f)) if os.path.isfile(f) else (f, 0) for f in fs)
    if _AV.get("key") != key:
        h = hashlib.sha1()
        for f in fs:
            if os.path.isfile(f): h.update(os.path.relpath(f, root).encode() + b"\0" + open(f, "rb").read())
        _AV.update(key=key, v=h.hexdigest()[:10])
    return _AV["v"]
def versioned_html(path):
    import re as _re
    from fastapi.responses import HTMLResponse
    html = open(path, encoding="utf-8").read(); v = asset_version()
    html = _re.sub(r'(/static/ui/(?:main\.js|ui\.css|login\.js|desktop\.js))(\?v=[^"\']*)?', lambda m: f"{m.group(1)}?v={v}", html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

@router.get("/setup")
def setup_page(request: Request):
    if user_count() > 0: return RedirectResponse("/login", 303)
    return FileResponse(os.path.join(STATIC, "ui", "login.html"), headers={"Cache-Control": "no-cache"})

def _start_session(request, uid):
    tok = secrets.token_urlsafe(32)
    with db() as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        c.execute("INSERT INTO sessions(token,user_id,created,expires,ip) VALUES(?,?,?,?,?)",
                  (hashlib.sha256(tok.encode()).hexdigest(), uid, time.time(), time.time() + SESSION_HOURS * 3600, "" if demo.enabled() else _client(request)))
    return tok

def _set_cookie(resp, request, tok):
    resp.set_cookie(COOKIE, tok, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=SESSION_HOURS * 3600, path="/")
    resp.set_cookie(CSRF_COOKIE, csrf_for(tok), httponly=False, samesite="strict", secure=request.url.scheme == "https", max_age=SESSION_HOURS * 3600, path="/")
    return resp

@router.get("/api/auth/policy")
def policy(): return {"image_retention_days": get_setting("image_retention_days"), "retention_enabled": get_setting("retention_enabled") == "1"}

@router.get("/api/auth/state")
def state(request: Request):
    u = current_user(request)
    return {"needs_setup": user_count() == 0, "user": pub(u) if u else None, "setup_allowed": trusted_host(request) and (_client(request) in LOOPBACK or os.getenv("GAC_ALLOW_REMOTE_SETUP") == "1")}

@router.post("/api/auth/setup")
def setup(request: Request, body: dict = Body(...)):
    if user_count() > 0: return JSONResponse({"error": "Setup was already done. Please sign in."}, 409)
    if not trusted_host(request):
        return JSONResponse({"error": "First-time setup must be opened by address (http://localhost:8765 or the computer's IP address), not through another site's name."}, 403)
    if _client(request) not in LOOPBACK and os.getenv("GAC_ALLOW_REMOTE_SETUP") != "1":
        return JSONResponse({"error": "Do first-time setup on the computer that runs the scanner."}, 403)
    try: uid = create_user(body.get("username", ""), body.get("display", ""), body.get("password", ""), "admin", body.get("initials"))
    except ValueError as e: return JSONResponse({"error": str(e)}, 422)
    alog(body.get("username"), "setup_admin_created", _client(request))
    return _set_cookie(JSONResponse({"ok": True}), request, _start_session(request, uid))

@router.post("/api/auth/login")
def login(request: Request, body: dict = Body(...)):
    if not isinstance(body.get("username") or "", str) or not isinstance(body.get("password") or "", str):   # fuzz 2026-10: username: [..] was a 500
        return JSONResponse({"error": "Send the username and password as text."}, 422)
    un = (body.get("username") or "").strip().lower(); ip = _client(request)
    # audit 2026-10 P1: wrong passwords are counted per (username, address) and per address. Someone else on the network
    # can no longer lock a colleague (or the admin) out by guessing at their username from another computer.
    now = time.time()
    f = [t for t in _fails.get((un, ip), []) if t > now - 300]
    per_ip = sum(1 for (u_, ip_), ts in list(_fails.items()) if ip_ == ip for t in ts if t > now - 300)
    if len(f) >= 5 or per_ip >= 20: return JSONResponse({"error": "Too many wrong passwords. Wait 5 minutes or ask an admin to reset it."}, 429)
    r = db().execute("SELECT * FROM users WHERE username=?", (un,)).fetchone()
    ok = check_pw(body.get("password") or "", r["pw"] if r else _DUMMY_PW)   # same work for unknown names (no timing hint)
    if not r or not r["active"] or not ok:
        f.append(now); _fails[(un, ip)] = f; alog(un, "login_failed", ip)
        return JSONResponse({"error": "Wrong username or password."}, 401)
    _clear_fails(un); alog(un, "login", ip)
    return _set_cookie(JSONResponse({"ok": True, "user": pub(dict(r))}), request, _start_session(request, r["id"]))

@router.post("/api/auth/logout")
def logout(request: Request):
    tok = request.cookies.get(COOKIE)
    if tok:
        with db() as c: c.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256(tok.encode()).hexdigest(),))
    r = JSONResponse({"ok": True}); r.delete_cookie(COOKIE, path="/"); return r

@router.post("/api/me/password")
def change_pw(request: Request, body: dict = Body(...)):
    u = request.state.user
    if not check_pw(body.get("old") or "", u["pw"]): return JSONResponse({"error": "Current password is wrong."}, 422)
    p = pw_problem(body.get("new"))
    if p: return JSONResponse({"error": p}, 422)
    keep = hashlib.sha256((request.cookies.get(COOKIE) or "").encode()).hexdigest()
    with db() as c:
        c.execute("UPDATE users SET pw=?, must_change=0 WHERE id=?", (hash_pw(body["new"]), u["id"]))
        c.execute("DELETE FROM sessions WHERE user_id=? AND token!=?", (u["id"], keep))  # sign out other devices
    alog(u["username"], "password_changed", _client(request)); return {"ok": True}

# ---------------- admin: users
@router.get("/api/admin/users")
def list_users(): return [pub(dict(r)) for r in db().execute("SELECT * FROM users ORDER BY role, username")]

@router.post("/api/admin/users")
def add_user(request: Request, body: dict = Body(...)):
    try: uid = create_user(body.get("username", ""), body.get("display", ""), body.get("password", ""), body.get("role", "reviewer"), body.get("initials"), must_change=True)
    except ValueError as e: return JSONResponse({"error": str(e)}, 422)
    alog(request.state.user["username"], f"created user {body.get('username')} ({body.get('role','reviewer')})", _client(request)); return {"id": uid}

@router.post("/api/admin/users/{uid}")
def edit_user(uid: int, request: Request, body: dict = Body(...)):
    me = request.state.user
    r = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if 0 < uid < 2**63 else None   # fuzz 2026-10: a huge id was a 500
    if not r: return JSONResponse({"error": "No such user."}, 404)
    # audit 2026-10 P0-7: every check BEFORE the first write. Returning from inside `with db()` COMMITS what was already
    # written (e.g. {password, active: false} on yourself reset the password and ended your sessions, then said "error").
    if "password" in body:
        p = pw_problem(body["password"])
        if p: return JSONResponse({"error": p}, 422)
    if "active" in body and uid == me["id"] and not body["active"]: return JSONResponse({"error": "You can't deactivate yourself."}, 422)
    if "role" in body and body["role"] in ("admin", "reviewer") and uid == me["id"] and body["role"] != "admin":
        return JSONResponse({"error": "You can't remove your own admin role."}, 422)
    with db() as c:
        if "password" in body:
            c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (hash_pw(body["password"]), uid))
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            _clear_fails(r["username"])   # a reset by an admin also lifts the wrong-password lock
        if "active" in body:
            c.execute("UPDATE users SET active=? WHERE id=?", (int(bool(body["active"])), uid))
            if not body["active"]: c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if "role" in body and body["role"] in ("admin", "reviewer"):
            c.execute("UPDATE users SET role=? WHERE id=?", (body["role"], uid))
    what = []
    if "active" in body:   # its own audit row, so "deactivated" can't be misread as "activated"
        alog(me["username"], f"{'reactivated' if body['active'] else 'deactivated'} user {r['username']}", _client(request))
        if len(body) == 1: return {"ok": True}
    if "role" in body: what.append(f"role set to {body['role']}")
    if "password" in body: what.append("password reset (lock lifted)")
    what += [k for k in body if k not in ("active", "role", "password")]
    alog(me["username"], f"updated user {r['username']}: {', '.join(what)}", _client(request))
    return {"ok": True}

@router.get("/api/admin/settings")
def get_settings(): return {k: get_setting(k) for k in DEFAULTS}

@router.get("/api/admin/backup-status")
def backup_status():
    """Round 11 (manager-r10 L-r10-1): the same-disk backup warning is shown in Admin > Settings, not only in the server log."""
    from . import backup as _b
    return _b.status() | {"same_disk": _b.same_disk(), "enabled": os.getenv("GAC_BACKUP", "1") != "0"}

SETTING_NAMES = {"image_retention_days": "Delete photos after (days)", "export_retention_days": "Delete stored exports after (days)",
                 "retention_enabled": "Automatic deletion", "ai_check_enabled": "AI double-check", "corrections_enabled": "Keep corrected cards as test examples", "mctrade_updates_enabled": "Allow 'update existing MC Trade contact'",
                 "mctrade_affcode": "MC Trade affiliation code", "phone_format": "Phone format",
                 "phone_mode_allowed": "Scan with phone", "update_check_enabled": "Check for updates"}
def _sv(k, v): return {"1": "on", "0": "off"}.get(v, v) if k.endswith(("_enabled", "_allowed")) else (v or "(empty)")

@router.post("/api/admin/settings")
def save_settings(request: Request, body: dict = Body(...)):
    with _SETTINGS_LOCK: return _save_settings(request, body)   # two admins saving at once: check-then-write is one step
_SETTINGS_LOCK = threading.Lock()
def _save_settings(request, body):
    before = get_settings()
    # round 15 (manager r14 H-r14-1): optimistic locking. The Settings page sends "_seen" = the values it showed. A setting the
    # person did not touch is left as it is now (never reset to the old value on screen); a setting they changed that ANOTHER
    # admin changed meanwhile is refused with 409 and nothing is saved.
    seen = body.get("_seen") if isinstance(body.get("_seen"), dict) else None
    # round 16 (manager r15 H-1): a save without "_seen" (or without the shown value of a setting it sends) is refused with 428,
    # not applied blindly; every refusal is an audit row (M-1)
    unseen = [k for k in DEFAULTS if k in body and (seen is None or k not in seen)]
    if unseen:
        alog(request.state.user["username"], "refused (stale admin page): settings save without the values the page showed (" + ", ".join(SETTING_NAMES.get(k, k) for k in unseen[:12]) + "): nothing was saved", _client(request))
        return JSONResponse({"error": "Nothing was saved: the page is out of date. Reload Admin → Settings and try again.",
                             "need": "version_required", "thing": "settings", "keys": unseen}, 428)
    if seen is not None:
        clash = [k for k in DEFAULTS if k in body and k in seen and str(body[k]).strip() != str(seen[k]) and before[k] != str(seen[k])]
        if clash:
            r = db().execute("SELECT ts, username FROM auth_log WHERE event LIKE 'settings changed:%' ORDER BY id DESC LIMIT 1").fetchone()
            who = f" by {r['username']} at {time.strftime('%H:%M', time.localtime(r['ts']))}" if r else ""
            alog(request.state.user["username"], "refused (stale admin page): settings save of " + ", ".join(SETTING_NAMES.get(k, k) for k in clash) + f" (another admin changed it{who}): nothing was saved", _client(request))
            return JSONResponse({"error": "Another admin changed " + ", ".join(SETTING_NAMES.get(k, k) for k in clash) + who +
                                 " after you opened this page. Nothing was saved: reload Admin → Settings, check their change, then try again.",
                                 "need": "stale_admin", "thing": "settings", "keys": clash, "now": {k: before[k] for k in clash}}, 409)
        body = {k: v for k, v in body.items() if not (k in DEFAULTS and k in seen and str(v).strip() == str(seen[k]))}
    # audit 2026-10 P0-7: validate EVERY value first, then write them all in one transaction (a bad value used to return
    # 422 after the earlier settings had already been saved, with no audit row)
    new = {}
    for k in DEFAULTS:
        if k in body:
            v = str(body[k]).strip()
            if k.endswith("_days") and (not v.isdigit() or not 1 <= int(v) <= 3650): return JSONResponse({"error": "Enter whole days from 1 to 3650."}, 422)
            if k == "mctrade_affcode" and not re.fullmatch(r"[A-Za-z0-9 _.-]{0,40}", v): return JSONResponse({"error": "Affiliation code: letters, digits, space, - _ . only (max 40)."}, 422)
            if k == "phone_format" and v not in ("gac", "e164"): return JSONResponse({"error": "Choose a phone format from the list."}, 422)
            if k in ("phone_mode_allowed", "update_check_enabled") and v not in ("0", "1"): return JSONResponse({"error": f"{SETTING_NAMES.get(k, k)} must be on or off."}, 422)
            new[k] = v
    with db() as c:
        for k, v in new.items(): c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))
    if get_setting("phone_mode_allowed") != "1":
        from . import phone; phone.revoke_all()      # turning phone mode off closes the LAN listener at once
    after = get_settings(); diff = [k for k in DEFAULTS if before[k] != after[k]]
    if diff:   # only real changes are logged, in words; a save with no change logs nothing
        alog(request.state.user["username"], "settings changed: " + "; ".join(f"{SETTING_NAMES.get(k, k)}: {_sv(k, before[k])} → {_sv(k, after[k])}" for k in diff), _client(request))
    return get_settings() | {"_changed": diff}
