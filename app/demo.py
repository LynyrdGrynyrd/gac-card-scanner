"""Public demo mode (GAC_DEMO=1): for a shared, internet-facing demo such as a Hugging Face Space.

What changes when it is on:
- one shared demo login (shown on the sign-in page); first-run setup, password changes and all /api/admin/* calls are refused
- synthetic sample cards (tests/synth2, fictional people, 555 numbers) are seeded at start and after every wipe
- a banner on every page: "Public demo — don't upload real cards"
- every export is a preview: nothing is stored or marked exported, and the MC Trade Excel is a dry-run file only
- uploads are capped (GAC_DEMO_MAX_MB per photo, GAC_DEMO_MAX_CARDS cards in total) and everything is wiped every
  GAC_DEMO_WIPE_HOURS hours (default 6), then re-seeded
- no audit of visitors: IP addresses are not stored in sessions or the sign-in log, and the corrections dataset is off
Never turn this on for real member data."""
import os, json, glob, shutil, time, uuid, threading, html

ROOT = os.path.join(os.path.dirname(__file__), "..")
BANNER_TEXT = "Public demo — don't upload real cards"
SEED_LABEL = "Demo · synthetic sample cards"

def enabled(): return os.environ.get("GAC_DEMO") == "1"
def user(): return os.environ.get("GAC_DEMO_USER", "demo")
def password(): return os.environ.get("GAC_DEMO_PASSWORD", "try-the-demo-2026")
def max_bytes(): return int(float(os.environ.get("GAC_DEMO_MAX_MB", "5")) * 1024 * 1024)
def max_cards(): return int(os.environ.get("GAC_DEMO_MAX_CARDS", "60"))
def wipe_hours(): return float(os.environ.get("GAC_DEMO_WIPE_HOURS", "6"))
def seed_count(): return int(os.environ.get("GAC_DEMO_SEED", "12"))

UPLOAD_PATHS = ("/api/jobs", "/api/scan")
def is_upload(p): return p in UPLOAD_PATHS or (p.startswith("/api/cards/") and p.endswith("/back"))
BLOCKED_PREFIX = ("/api/admin/", "/api/phone/")   # audit 2026-10 P1: no phone pairing (it would show the container's LAN address)
BLOCKED = {"/api/me/password", "/api/auth/setup", "/api/jobs/cancel"}   # one shared login: a visitor could cancel everyone's uploads

_STATE = {"last_wipe": 0.0}
_LOCK = threading.Lock()

# ------------------------------------------------------------------ pages
def _banner():
    return ('<div id="demoBanner" role="alert" style="background:#b00020;color:#fff;text-align:center;padding:8px 12px;'
            'font:600 15px/1.3 Lato,system-ui,sans-serif">' + html.escape(BANNER_TEXT) +
            f'. Everything here is wiped every {wipe_hours():g} h; exports are previews only.</div>')
def _login_box():
    return ('<div id="demoLogin" class="panel" style="margin:12px 0;padding:12px 16px;border:2px dashed #b00020">'
            '<strong>Shared demo login</strong><br>Username: <code>' + html.escape(user()) + '</code><br>Password: <code>' +
            html.escape(password()) + '</code></div>')
def page(path, login=False):
    """The static page with the demo banner (and the demo login on the sign-in page) inserted."""
    from fastapi.responses import HTMLResponse
    from . import auth   # v0.2.1: same ?v=<fingerprint> asset URLs as the normal pages (else ui.js reloads itself in a loop)
    s = auth.versioned_html(path).body.decode("utf-8")
    s = s.replace("<body>", "<body>" + _banner(), 1)
    if login: s = s.replace('<form class="panel" id="f"', _login_box() + '<form class="panel" id="f"', 1)
    return HTMLResponse(s, headers={"Cache-Control": "no-cache"})

# ------------------------------------------------------------------ guard
def refuse(request):
    """Return a JSONResponse when demo mode refuses this request, else None."""
    from fastapi.responses import JSONResponse
    p = request.url.path; m = request.method
    if m in ("POST", "PUT", "PATCH", "DELETE") and (p in BLOCKED or p.startswith(BLOCKED_PREFIX)):
        return JSONResponse({"error": "Disabled in the public demo."}, 403)
    if m == "POST" and is_upload(p):
        try: clen = int(request.headers.get("content-length") or 0)
        except ValueError: clen = 0
        if clen > max_bytes():
            return JSONResponse({"error": f"Public demo: photos are limited to {max_bytes() // (1024 * 1024)} MB."}, 413)
        if capacity_left() <= 0:
            return JSONResponse({"error": f"Public demo is full ({max_cards()} cards). It is wiped every {wipe_hours():g} hours."}, 429)
    return None

def capacity_left():
    """Audit 2026-10 P1 (F09): cards that exist PLUS uploads still queued or being read count toward the cap (parallel
    uploads, or one PDF with many pages, used to get past it)."""
    from . import store, ui
    n = store.db().execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    with ui.JLOCK:
        n += sum(1 for j in ui.JOBS.values() if j.get("state") in ("queued", "reading") and j.get("kind") != "pdf")
        n += sum(max(0, (j.get("pages") or 0) - (j.get("page") or 0)) for j in ui.JOBS.values() if j.get("kind") == "pdf" and j.get("state") in ("queued", "splitting"))
    return max_cards() - n

# ------------------------------------------------------------------ seed / wipe
def ensure_user():
    from . import auth
    r = auth.db().execute("SELECT id FROM users WHERE username=?", (user(),)).fetchone()
    if r:
        with auth.db() as c: c.execute("UPDATE users SET pw=?, active=1, must_change=0, role='reviewer' WHERE id=?", (auth.hash_pw(password()), r[0]))
        return r[0]
    return auth.create_user(user(), "Demo Visitor", password(), "reviewer", "DEMO")

def seed():
    """Add synthetic sample cards (fields from tests/synth2_gt.json, no OCR needed) in one pending batch."""
    from . import store, ui
    gt = json.load(open(os.path.join(ROOT, "tests", "synth2_gt.json")))
    n = 0
    for name in sorted(gt)[:seed_count()]:
        src = os.path.join(ROOT, "tests", "synth2", name)
        if not os.path.isfile(src): continue
        f = {k: v for k, v in gt[name].items() if k != "cat"}
        f.setdefault("social", []); f.setdefault("other_address", "")
        img = uuid.uuid4().hex + ".jpg"; shutil.copyfile(src, os.path.join(ui.UP, img))
        cid = store.add("demo-seed", "(synthetic sample card)", f, img)
        ui.set_meta(cid, batch="demo-seed", batch_label=SEED_LABEL); n += 1
    return n

KEEP_TABLES = {"users", "settings", "sqlite_sequence"}
def wipe(reseed=True):
    """Delete every card, upload, export, thumbnail, history row and sign-in log entry, then re-seed."""
    from . import store, ui, auth
    with _LOCK:
        ui.reset_jobs()      # audit 2026-10 P1 (F09): old jobs/queues first, so nothing from before the wipe can come back
        ui.db(); auth.db()   # make sure all tables exist
        with store.db() as c:
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                if t not in KEEP_TABLES: c.execute(f'DELETE FROM "{t}"')
        for d in (ui.UP, ui.EXP, ui.THUMBS, ui.INBOX, ui.DONE):
            for p in glob.glob(os.path.join(d, "*")):
                (shutil.rmtree if os.path.isdir(p) else os.remove)(p)
        _STATE["last_wipe"] = time.time()
        return seed() if reseed else 0

def _loop():
    while True:
        time.sleep(60)
        try:
            if time.time() - _STATE["last_wipe"] >= wipe_hours() * 3600: print("demo wipe:", wipe(), "cards re-seeded", flush=True)
        except Exception as e: print("demo wipe error:", e, flush=True)

def start():
    """Called once at app start when GAC_DEMO=1."""
    from . import auth
    for d in ("UP", "EXP", "THUMBS", "INBOX", "DONE"):
        from . import ui; os.makedirs(getattr(ui, d), exist_ok=True)
    auth.set_setting("corrections_enabled", "0")
    ensure_user(); n = wipe()
    print("=" * 78 + f"\nPUBLIC DEMO MODE: {n} synthetic cards seeded; login {user()} / {password()}; wipe every {wipe_hours():g} h\n" + "=" * 78, flush=True)
    threading.Thread(target=_loop, daemon=True, name="demo-wipe").start()
