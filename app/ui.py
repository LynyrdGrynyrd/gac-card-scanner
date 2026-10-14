"""Data-team web UI (/ui) + JSON API. Only ADDS routes (and takes over the legacy page URLs, which now redirect to /ui
so every path goes through the same checks). /api/scan contract untouched.
UI state (batches, hashes, archive, audit history, duplicate decisions, undo snapshots, exports, field sources)
lives in extra tables in the same SQLite DB so store.py stays unchanged."""
import io, os, re, csv, json, time, uuid, hashlib, datetime, threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Body, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, Response, RedirectResponse, JSONResponse
from . import store, export, mctrade_sync, auth

router = APIRouter()
STATIC = os.path.join(os.path.dirname(__file__), "static")
DATA = os.path.join(os.path.dirname(__file__), "..", "data")
UP = os.path.join(DATA, "uploads"); EXP = os.path.join(DATA, "exports")
INBOX = os.path.join(DATA, "inbox")   # accepted-but-not-yet-read uploads; survives a crash/restart and is re-queued at start
DONE = os.path.join(DATA, "jobs_done")   # small result records so an open browser can still look a job up after a restart (24 h)
for _d in (UP, EXP, INBOX, DONE): os.makedirs(_d, exist_ok=True)

# ---------------------------------------------------------------- extra tables
META_COLS = ["card_id", "batch", "batch_label", "filename", "sha256", "archived", "dup_resolution", "crm_action", "exported",
             "field_sources", "image_deleted", "ai_status", "ai_detail", "override", "reexport", "back_image", "kept_apart"]
def db():
    c = store.db()
    c.execute("""CREATE TABLE IF NOT EXISTS card_meta(card_id INTEGER PRIMARY KEY, batch TEXT, batch_label TEXT,
      filename TEXT, sha256 TEXT, archived INTEGER DEFAULT 0, dup_resolution TEXT, crm_action TEXT, exported REAL)""")
    have = {r[1] for r in c.execute("PRAGMA table_info(card_meta)")}
    for col, typ in (("field_sources", "TEXT"), ("image_deleted", "REAL"), ("ai_status", "TEXT"), ("ai_detail", "TEXT"), ("override", "TEXT"), ("reexport", "REAL"), ("back_image", "TEXT"), ("kept_apart", "TEXT")):
        if col not in have:
            try: c.execute(f"ALTER TABLE card_meta ADD COLUMN {col} {typ}")
            except Exception as e:   # another thread added it first
                if "duplicate column" not in str(e): raise
    c.execute("""CREATE TABLE IF NOT EXISTS card_history(id INTEGER PRIMARY KEY, card_id INTEGER, ts REAL, reviewer TEXT,
      action TEXT, from_status TEXT, to_status TEXT, detail TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, ts REAL, user_id INTEGER, username TEXT, label TEXT,
      snapshot TEXT, undone REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS exports(id INTEGER PRIMARY KEY, ts REAL, username TEXT, initials TEXT, kind TEXT,
      filter TEXT, count INTEGER, filename TEXT, card_ids TEXT, stored TEXT)""")
    if "batch_label" not in {r[1] for r in c.execute("PRAGMA table_info(exports)")}:
        try: c.execute("ALTER TABLE exports ADD COLUMN batch_label TEXT")
        except Exception as e:
            if "duplicate column" not in str(e): raise
    return c

def meta(cid):
    r = db().execute("SELECT * FROM card_meta WHERE card_id=?", (cid,)).fetchone()
    return dict(r) if r else {k: None for k in META_COLS} | {"card_id": cid, "archived": 0}

def set_meta(cid, **kw):
    m = meta(cid); m.update(kw)
    with db() as c:
        c.execute(f"INSERT OR REPLACE INTO card_meta({','.join(META_COLS)}) VALUES({','.join(':' + k for k in META_COLS)})", {k: m.get(k) for k in META_COLS})

def log(cid, reviewer, action, frm=None, to=None, detail=None):
    with db() as c:
        c.execute("INSERT INTO card_history(card_id,ts,reviewer,action,from_status,to_status,detail) VALUES(?,?,?,?,?,?,?)",
                  (cid, time.time(), reviewer, action, frm, to, json.dumps(detail) if detail is not None else None))

def history(cid):
    out = [dict(r) | {"detail": json.loads(r["detail"]) if r["detail"] else None}
           for r in db().execute("SELECT * FROM card_history WHERE card_id=? ORDER BY id", (cid,))]
    for h in out: h["text"] = _audit_text(h["action"], h["from_status"], h["to_status"], h["detail"])
    return out

def all_metas():
    return {r["card_id"]: dict(r) for r in db().execute("SELECT * FROM card_meta")}

def sources(cid):
    try: return json.loads(meta(cid).get("field_sources") or "{}")
    except Exception: return {}

# ---------------------------------------------------------------- undo (snapshot before every change)
def snapshot(ids, user, label):
    snap = []
    for i in ids:
        r = db().execute("SELECT * FROM cards WHERE id=?", (i,)).fetchone()
        m = db().execute("SELECT * FROM card_meta WHERE card_id=?", (i,)).fetchone()
        if r: snap.append({"card": dict(r), "meta": dict(m) if m else None,
                           "hist_max": db().execute("SELECT COALESCE(MAX(id),0) FROM card_history WHERE card_id=?", (i,)).fetchone()[0]})
    with db() as c:
        return c.execute("INSERT INTO actions(ts,user_id,username,label,snapshot) VALUES(?,?,?,?,?)",
                         (time.time(), user["id"], user["username"], label, json.dumps(snap))).lastrowid

def _who(request): return request.state.user["initials"]

# ---------------------------------------------------------------- validation & attention (single source of truth)
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}$")
def _digits(s): return re.sub(r"\D", "", s or "")
def phone_ok(n): return 10 <= len(_digits(n)) <= 15
def validate(f):
    err = {}
    if not (f.get("first_name") or "").strip():
        err["name"] = "First name is required." if f.get("last_name") else "Name is required."
    bad = [e for e in f.get("emails", []) if not EMAIL.match(e)]
    if bad: err["emails"] = "Not a valid email: " + ", ".join(bad)
    badp = [p["number"] for p in f.get("phones", []) if not phone_ok(p.get("number"))]
    if badp: err["phones"] = "Phone number looks incomplete: " + ", ".join(badp)
    if not f.get("emails") and not f.get("phones"): err.setdefault("emails", "Add at least an email or a phone number.")
    return err

ANY_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
def hard_errors(f):
    """Problems that 'Approve anyway' can NOT override: a blank first name, and values that are certainly not an email / phone number."""
    err = {}
    if not (f.get("first_name") or "").strip():
        err["name"] = "First name is required." if f.get("last_name") else "Name is required (at least a first name)."
    bad = [e for e in f.get("emails", []) if not ANY_EMAIL.match(e)]
    if bad: err["emails"] = "Not an email address at all: " + ", ".join(bad) + ". Fix or delete it."
    badp = [p["number"] for p in f.get("phones", []) if len(_digits(p.get("number"))) < 7]
    if badp: err["phones"] = "Not a phone number (too few digits): " + ", ".join(badp) + ". Fix or delete it."
    from . import mctrade_export as _mx
    for k, msg in _mx.content_problems(f).items(): err.setdefault(k, msg[0].upper() + msg[1:] + ". Fix it: it can't go into MC Trade.")
    return err

def low_fields(f, src=None):
    """Fields the reviewer should double-check: low confidence, or listed in the parser's needs_review.
    A field a person already edited or explicitly confirmed (e.g. 'Keep current' on an AI suggestion) is not listed."""
    done = {k for k, v in (src or {}).items() if str(v).startswith(("edited", "confirmed"))}
    if "first_name" in done or "last_name" in done: done.add("name")
    out = [k for k in (f.get("needs_review") or []) if isinstance(k, str) and k not in done]
    for n, v in (f.get("confidence") or {}).items():
        if v is None or v >= 0.6 or n in done: continue
        val = f.get(n) if n != "name" else (f.get("first_name") or f.get("last_name"))
        if (val or n in ("name", "company", "emails")) and n not in out: out.append(n)
    return out

def _as_row(c):
    f = c["fields"]
    return {"profile_id": f"card:{c['id']}", "first_name": f.get("first_name", ""), "last_name": f.get("last_name", ""),
            "organization": f.get("company", ""), "email": (f.get("emails") or [""])[0],
            "phone": (f.get("phones") or [{"number": ""}])[0]["number"]}

def dupes(c, others, metas):
    f = c["fields"]; m = metas.get(c["id"]) or {}
    crm = [d for d in mctrade_sync.match(f) if d["score"] >= 0.3]
    rows = [_as_row(o) for o in others if o["id"] != c["id"] and o["status"] != "rejected"
            and not (metas.get(o["id"]) or {}).get("archived")]
    q = [d | {"card_id": int(d["profile_id"].split(":")[1])} for d in mctrade_sync.match(f, rows) if d["score"] >= 0.5]
    h = m.get("sha256")
    if h:
        same = [o["id"] for o in others if o["id"] != c["id"] and (metas.get(o["id"]) or {}).get("sha256") == h
                and o["status"] != "rejected" and not (metas.get(o["id"]) or {}).get("archived")]
        for sid in same:
            if not any(d["card_id"] == sid for d in q):
                q.insert(0, {"card_id": sid, "profile_id": f"card:{sid}", "name": "", "organization": "", "score": 1.0, "why": ["same photo"]})
    res = m.get("dup_resolution")
    if c["status"] == "rejected": q = []   # a rejected card is never exported, so its look-alikes don't matter
    for x in q:
        o = next((o for o in others if o["id"] == x["card_id"]), None)
        x["strong"] = is_true_duplicate(x, m, metas.get(x["card_id"]) or {})
        x["kept_apart"] = (not x["strong"]) and (x["card_id"] in _kept(m) or c["id"] in _kept(metas.get(x["card_id"]) or {})
                                                 or (res == "keep_both" and not _kept(m)))   # legacy all-matches choice
        if o: x["other_status"] = o["status"]
        om = metas.get(x["card_id"]) or {}
        x["same_batch"] = bool(m.get("batch")) and m.get("batch") == om.get("batch")
        x["blocking"] = x["strong"] or x["same_batch"] or "same photo" in x.get("why", [])   # cross-batch look-alikes only warn
    open_q = [x for x in q if not x["kept_apart"]]
    return {"crm": crm, "queue": q, "open": open_q, "unresolved_queue": any(x["blocking"] for x in open_q), "lookalikes_elsewhere": [x["card_id"] for x in open_q if not x["blocking"]], "resolution": res, "crm_action": m.get("crm_action"), "meta": m}

def _kept(m):
    try: return set(json.loads(m.get("kept_apart") or "[]"))
    except Exception: return set()

def is_true_duplicate(x, m, om):
    """Same photo, or same batch with the same email/phone: almost certainly the same card scanned twice.
    These can't be cleared with 'keep both'; merge or reject one of them."""
    same_batch = bool(m.get("batch")) and m.get("batch") == om.get("batch")
    if "same photo" in x.get("why", []): return same_batch   # a deliberate "Scan it anyway" in another batch can be kept apart
    return same_batch and m.get("batch") == om.get("batch") and any(w in ("email exact", "phone exact") for w in x.get("why", []))

WHY = {"email exact": "same email", "phone exact": "same phone", "same photo": "same photo uploaded"}
def _why(ws): return ", ".join(WHY.get(w, "similar name" if w.startswith("name") else "similar company" if w.startswith("org") else w) for w in ws)
LABEL = {"name": "Name", "title": "Job title", "company": "Company", "emails": "Email", "phones": "Phone", "website": "Website",
         "address": "Address", "department": "Department", "other_address": "Other address",
         "first_name": "First name", "last_name": "Last name", "credentials": "Credentials", "social": "Social profiles", "note": "Note"}

def attention(c, d):
    f = c["fields"]; r = []
    v = validate(f)
    for k, msg in v.items(): r.append({"code": "invalid", "field": k, "text": msg})
    try: _src = json.loads((d.get("meta") or {}).get("field_sources") or "{}")
    except Exception: _src = {}
    for k in low_fields(f, _src):
        if k not in v: r.append({"code": "low", "field": k, "text": f"Hard to read: {LABEL.get(k, k)}"})
    if c["status"] == "pending":   # re-checked live, so a fix by the reviewer clears it
        from . import consistency
        import copy as _cp
        for fl in consistency.check(_cp.deepcopy(f))[1]: r.append({"code": "consistency", "field": fl["fields"][0], "text": fl["text"]})
    if c["status"] == "pending":
        try:
            from . import plausibility
            for sg in plausibility.check(json.loads(json.dumps(f))):
                r.append({"code": "hint", "field": sg.get("field"), "text": "Suggestion: " + (sg.get("text") or ""), "suggestion": sg.get("suggestion")})
        except Exception: pass
    if d["unresolved_queue"]: r.append({"code": "dup_queue", "text": "May be the same person as card " + ", ".join(f"#{x['card_id']}" for x in d["open"] if x["blocking"])})
    if d["crm"] and not d["crm_action"]: r.append({"code": "dup_crm", "text": f"May already be in MC Trade: {d['crm'][0]['name']}"})
    m = d.get("meta") or {}
    if c["status"] == "approved" and m.get("override"):
        r.append({"code": "override", "text": "Approved anyway: " + (_ov(m).get("reason") or "")})
    if m.get("reexport"): r.append({"code": "reexport", "text": "Changed after export: export it again"})
    return r

def _ov(m):
    try: return json.loads(m.get("override") or "{}")
    except Exception: return {}

def _active(include_archived=False):
    metas = all_metas(); cards = store.all_(None)
    if not include_archived: cards = [c for c in cards if not (metas.get(c["id"]) or {}).get("archived")]
    return cards, metas

def enrich(c, cards, metas, full=False):
    d = dupes(c, cards, metas); m = metas.get(c["id"]) or meta(c["id"]); a = attention(c, d)
    f = c["fields"]
    try: src = json.loads(m.get("field_sources") or "{}")
    except Exception: src = {}
    out = {"id": c["id"], "status": c["status"], "image": c["image"], "created": c["created"],
           "name": f"{f.get('first_name','')} {f.get('last_name','')}".strip(), "company": f.get("company", ""),
           "email": (f.get("emails") or [""])[0], "conf": f.get("overall_confidence"), "reviewer": c.get("reviewer"),
           "attention": a, "needs_attention": any(x["code"] != "hint" for x in a), "dup": bool(d["queue"] or d["crm"]), "lookalikes_elsewhere": d["lookalikes_elsewhere"],
           "batch": m.get("batch"), "batch_label": m.get("batch_label"), "filename": m.get("filename"),
           "archived": bool(m.get("archived")), "exported": m.get("exported"), "qr": "qr" in src.values(),
           "image_deleted": m.get("image_deleted"), "ai_status": m.get("ai_status"),
           "ai_detail": json.loads(m["ai_detail"]) if m.get("ai_detail") else None,
           "override": _ov(m) or None, "reexport": m.get("reexport"), "back_image": m.get("back_image"),
           "ai_progress": ai_progress(c["id"]) if m.get("ai_status") in ("queued", "checking") else None}
    if full:
        d = {k: v for k, v in d.items() if k != "meta"}
        out |= {"card": c, "dupes": d, "history": history(c["id"]), "errors": validate(f), "low": low_fields(f, src), "sources": src}
        for x in d["queue"]:
            o = store.get(x["card_id"])
            if o: x |= {"name": f"{o['fields'].get('first_name','')} {o['fields'].get('last_name','')}".strip(),
                        "organization": o["fields"].get("company", ""), "status": o["status"], "why_text": _why(x["why"])}
        for x in d["crm"]: x["why_text"] = _why(x["why"])
    return out

# ---------------------------------------------------------------- pages (legacy URLs now lead to /ui)
@router.get("/ui")
def ui():
    from . import demo
    if demo.enabled(): return demo.page(os.path.join(STATIC, "ui", "index.html"))
    return FileResponse(os.path.join(STATIC, "ui", "index.html"), headers={"Cache-Control": "no-store"})
@router.get("/app")
def app_alias(): return RedirectResponse("/ui", 307)
@router.get("/")
def legacy_home(): return RedirectResponse("/ui#upload", 307)
@router.get("/queue")
def legacy_queue(status: str = ""): return RedirectResponse(f"/ui#queue?s={status if status in ('pending','approved','rejected') else ''}", 307)
@router.get("/card/{cid}")
def legacy_card(cid: int): return RedirectResponse(f"/ui#review/{cid}", 307)
@router.post("/card/{cid}")
def legacy_card_post(cid: int):
    return JSONResponse({"error": "This old page was retired. Review cards at /ui so validation, duplicate and audit checks apply.", "use": f"/ui#review/{cid}"}, 410)
@router.post("/scan")
def legacy_scan(): return JSONResponse({"error": "This old upload form was retired. Scan cards at /ui.", "use": "/ui#upload"}, 410)
@router.get("/sync/dry-run")
@router.get("/sync/dry-run/{cid}")
def legacy_sync(cid: int = 0): return JSONResponse({"error": "Retired. Use Export → MC Trade import (Excel)."}, 410)
@router.get("/export.csv")
def legacy_csv(status: str = "approved"): return RedirectResponse(f"/ui#export", 307)
@router.get("/export.vcf")
def legacy_vcf(status: str = "approved"): return RedirectResponse(f"/ui#export", 307)
@router.get("/export.xlsx")
def legacy_xlsx(status: str = "approved"): return RedirectResponse(f"/ui#export", 307)
@router.get("/privacy")
def privacy(): return FileResponse(os.path.join(STATIC, "ui", "privacy.html"), headers={"Cache-Control": "no-cache"})

@router.get("/img/{name}")
def img(name: str, w: int = 0):
    if not name or "\x00" in name or len(name) > 255: raise HTTPException(404, "No such photo")
    p = os.path.join(UP, os.path.basename(name))
    if not os.path.isfile(p):
        drop_thumbs(name)
        return Response(PLACEHOLDER, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
    if w:   # small cached thumbnail for the queue list instead of the full-resolution original
        t = _thumb(p, w)
        if t: return FileResponse(t, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})
    return FileResponse(p, headers={"Cache-Control": "private, max-age=3600"})
THUMBS = os.path.join(DATA, "thumbs"); os.makedirs(THUMBS, exist_ok=True)
THUMB_SIZES = (160, 320)
def _thumb(p, w):
    """Return the path of a cached WebP thumbnail (width snapped to THUMB_SIZES), building it on first use. None on failure."""
    w = min(THUMB_SIZES, key=lambda s: abs(s - w)); base = os.path.basename(p)
    t = os.path.join(THUMBS, f"{base}.{w}.webp")
    try:
        if os.path.isfile(t) and os.path.getmtime(t) >= os.path.getmtime(p): return t
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(p, formats=FORMATS) as im:
            im = ImageOps.exif_transpose(im); im.draft("RGB", (w * 2, w * 2)); im = im.convert("RGB"); im.thumbnail((w, w * 2))
            tmp = t + ".tmp"; im.save(tmp, "WEBP", quality=70, method=4); os.replace(tmp, t)
        return t
    except Exception:
        return None
def drop_thumbs(name):
    """Delete cached thumbnails of a photo (called wherever the photo itself is deleted)."""
    if not name: return
    base = os.path.basename(name)
    for s_ in THUMB_SIZES:
        try: os.remove(os.path.join(THUMBS, f"{base}.{s_}.webp"))
        except FileNotFoundError: pass
PLACEHOLDER = b"""<svg xmlns="http://www.w3.org/2000/svg" width="420" height="240" viewBox="0 0 420 240"><rect width="420" height="240" fill="#eee"/><text x="210" y="112" text-anchor="middle" font-family="Lato,sans-serif" font-size="18" fill="#555">Photo deleted</text><text x="210" y="140" text-anchor="middle" font-family="Lato,sans-serif" font-size="13" fill="#777">(retention policy)</text></svg>"""

@router.get("/api/me")
def me(request: Request): return auth.pub(request.state.user)

# ---------------------------------------------------------------- async scan jobs
SCAN_WORKERS = max(1, int(os.environ.get("SCAN_WORKERS", "1")))
POOL = ThreadPoolExecutor(max_workers=SCAN_WORKERS)
# Caps how many photos are read (OCR) at the same time across ALL entry points (the /ui job pool, /api/scan, back-of-card),
# so a burst of uploads queues instead of multiplying RAM use.
SCAN_SEM = threading.BoundedSemaphore(SCAN_WORKERS)
def scan_limited(*a, **k):
    from . import pipeline
    with SCAN_SEM: return pipeline.scan(*a, **k)
JOBS, JLOCK = {}, threading.Lock()
MAX_BYTES = 25 * 1024 * 1024

# Only plain raster formats are decoded (no EPS/PDF/etc. plugins, which can shell out to external tools), and images above
# MAX_PIXELS are refused before decoding (decompression bombs: a small file that expands to gigabytes of pixels).
FORMATS = ["JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "MPO"]
MAX_PIXELS = 60_000_000      # ~60 MP: above any phone camera
def _check_image(data):
    import warnings
    from PIL import Image, ImageStat
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(data), formats=FORMATS)
            if im.size[0] * im.size[1] > MAX_PIXELS: raise Image.DecompressionBombError("too many pixels")
            im.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "This picture is far too large (too many pixels). Use a normal phone photo."
    except Exception:
        return "This file isn't a photo the scanner can open (use JPG or PNG)."
    w, h = im.size
    if w < 200 or h < 100: return f"Photo is too small ({w}×{h} pixels). Take the picture closer to the card."
    g = im.convert("L"); g.thumbnail((400, 400))
    if ImageStat.Stat(g).stddev[0] < 6: return "Photo looks blank (one solid colour). Please retake it."
    return None

QR_KEYS = ("first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address", "social")
def ingest(data, engine, ext):
    """Image -> card using the shared pipeline (QR/vCard decode + OCR + parser). Returns (card_id, field_sources)."""
    from . import pipeline, qr
    name = uuid.uuid4().hex + ext
    with open(os.path.join(UP, name), "wb") as fh: fh.write(data)
    r = scan_limited(data, None if engine in (None, "", "auto", "standard", "tesseract") else engine, use_vlm=False)
    f = r["fields"]; src = {}
    qrv = None
    if (f.get("sources") or {}).get("qr"):
        for t in qr.decode(data):
            qrv = qr.parse_vcard(t)
            if qrv: break
    for k in QR_KEYS:
        if f.get(k): src[k] = "qr" if qrv and qrv.get(k) and qrv.get(k) == f.get(k) else "ocr"
    cid = store.add(r["engine"], r["text"], f, name)
    return cid, src

def _run(jid, data, engine, ext, batch, label, fname, sha, who):  # noqa: PLR0913
    with JLOCK: JOBS[jid]["state"] = "reading"; JOBS[jid]["started"] = time.time()
    try:
        if data is None:   # queued jobs keep only a file on disk, not the photo bytes in memory
            with open(os.path.join(INBOX, jid + ".bin"), "rb") as fh: data = fh.read()
        cid, src = ingest(data, engine, ext)
        set_meta(cid, batch=batch, batch_label=label, filename=fname, sha256=sha, field_sources=json.dumps(src))
        log(cid, who, "scanned", None, "pending", {"file": fname, "batch": label, "qr": "qr" in src.values()})
        maybe_ai_check(cid)
        cards, metas = _active()
        e = enrich(store.get(cid), cards, metas)
        with JLOCK: JOBS[jid] |= {"state": "done", "card": e, "finished": time.time()}
    except Exception as ex:
        with JLOCK: JOBS[jid] |= {"state": "error", "error": f"Could not read this card ({type(ex).__name__}).", "finished": time.time()}
    finally:
        with JLOCK: j = dict(JOBS.get(jid) or {})
        try:
            with open(os.path.join(DONE, jid + ".json"), "w") as fh:
                json.dump({k: j.get(k) for k in ("id", "state", "file", "batch", "error", "created", "started", "finished")} | {"card_id": (j.get("card") or {}).get("id")}, fh)
        except Exception: pass
        for x in (".bin", ".json"):
            try: os.remove(os.path.join(INBOX, jid + x))
            except FileNotFoundError: pass

@router.post("/api/jobs")
async def create_job(request: Request, image: UploadFile = File(...), engine: str = Form("auto"), batch: str = Form(""),
                     batch_label: str = Form(""), allow_duplicate: str = Form("")):
    data = await image.read(); fname = image.filename or "photo"
    if len(data) > MAX_BYTES: return JSONResponse({"error": "File is larger than 25 MB."}, 422)
    if not data: return JSONResponse({"error": "File is empty."}, 422)
    from starlette.concurrency import run_in_threadpool
    problem = await run_in_threadpool(_check_image, data)
    if problem: return JSONResponse({"error": problem}, 422)
    sha = hashlib.sha256(data).hexdigest()
    if not allow_duplicate:
        # the OLDEST active, non-rejected card with this photo: the same one the review screen lists as "same photo"
        r = db().execute("SELECT m.card_id, c.created, m.batch_label FROM card_meta m JOIN cards c ON c.id=m.card_id WHERE m.sha256=? AND m.archived=0 "
                         "ORDER BY (c.status='rejected'), c.id ASC", (sha,)).fetchone()
        if r:
            h = db().execute("SELECT reviewer FROM card_history WHERE card_id=? ORDER BY id LIMIT 1", (r[0],)).fetchone()
            who = (h[0] if h and h[0] not in (None, "system") else None) or "someone"
            when = datetime.datetime.fromtimestamp(r[1]).strftime("%b %d, %I:%M %p").replace(" 0", " ") if r[1] else "earlier"
            return JSONResponse({"error": f"This exact photo was already scanned by {who} on {when} (card #{r[0]}" + (f", batch {r[2]}" if r[2] else "") + ").",
                                 "duplicate_of": r[0], "by": who, "when": r[1]}, 409)
        with JLOCK:
            for j in JOBS.values():
                if j.get("sha") == sha and j["state"] in ("queued", "reading"):
                    return JSONResponse({"error": "This exact photo is already in this upload.", "duplicate_of": None}, 409)
    jid = uuid.uuid4().hex[:12]; ext = os.path.splitext(fname)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"): ext = ".jpg"
    with JLOCK:
        ahead = sum(1 for j in JOBS.values() if j["state"] in ("queued", "reading"))
        JOBS[jid] = {"id": jid, "state": "queued", "file": fname, "batch": batch, "sha": sha, "created": time.time(), "ahead": ahead}
    args = dict(engine=engine, ext=ext, batch=batch or None, label=batch_label or None, fname=fname, sha=sha, who=_who(request))
    with open(os.path.join(INBOX, jid + ".bin"), "wb") as fh: fh.write(data)
    with open(os.path.join(INBOX, jid + ".json"), "w") as fh: json.dump(args, fh)
    POOL.submit(_run, jid, None, **args)
    return {"job": jid, "state": "queued", "ahead": ahead}

@router.get("/api/jobs")
def list_jobs(ids: str = "", batch: str = ""):
    want = set(filter(None, ids.split(",")))
    with JLOCK:
        js = [dict(j) for j in JOBS.values() if (j["id"] in want) or (batch and j["batch"] == batch)]
        missing = want - set(JOBS)
    for jid in missing:   # finished before a restart: answer from the result record
        if not re.fullmatch(r"[0-9a-f]{12}", jid): continue
        try:
            with open(os.path.join(DONE, jid + ".json")) as fh: r = json.load(fh)
        except (FileNotFoundError, ValueError): continue
        if r.get("card_id") and store.get(r["card_id"]):
            cards_, metas = _active(); r["card"] = enrich(store.get(r["card_id"]), cards_, metas)
        elif r.get("state") == "done": r = r | {"state": "error", "error": "This card was removed."}
        js.append(r)
    with JLOCK: done = [j["finished"] - j["started"] for j in JOBS.values() if j.get("finished") and j.get("started")]
    avg = sum(done[-10:]) / len(done[-10:]) if done else None
    for j in js: j.pop("sha", None)
    return {"jobs": js, "avg_seconds": avg}

# ---------------------------------------------------------------- AI double-check (optional local vision model)
# Fast path is OCR+rules+QR. If a card looks uncertain and the local vision server (llama.cpp, VLM_URL, default
# 127.0.0.1:8090) is running, a second pass runs in the background on its own single worker and merges results
# (app/merge.py rules). It only changes cards that are still pending and not edited by a person; otherwise it is skipped.
import queue as _queue, itertools as _it
AI_Q: "_queue.PriorityQueue" = _queue.PriorityQueue()   # (priority, seq, cid, why): 0 = asked for by a person, 1 = background
AI_SEQ = _it.count(); AI_WAIT: dict = {}                  # cid -> (priority, seq) while waiting
AI_TIMES: list = []                                       # recent run times (s), for the progress estimate
AI_RUNNING: dict = {}
AI_MAX_WAIT = int(os.environ.get("AI_MAX_WAIT", "600"))   # background checks waiting longer than this are skipped
def _ai_worker():
    while True:
        prio, seq, cid, why = AI_Q.get()
        if AI_WAIT.get(cid) != (prio, seq): continue      # superseded (e.g. re-queued as manual)
        AI_WAIT.pop(cid, None)
        try:
            c = store.get(cid); m = meta(cid); det = json.loads(m.get("ai_detail") or "{}")
        except Exception: c, m, det = None, {}, {}
        why_skip = None
        if not c or c["status"] != "pending": why_skip = "the card was already decided"
        elif prio == 1 and m.get("exported"): why_skip = "the card was already exported"
        elif prio == 1 and time.time() - (det.get("queued_at") or time.time()) > AI_MAX_WAIT: why_skip = "the AI was busy for too long"
        if why_skip:
            if c: set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"why": why, "note": why_skip}))
            continue
        t0 = time.time(); AI_RUNNING.update(cid=cid, since=t0)
        try: _ai_run(cid, why)
        finally: AI_TIMES.append(time.time() - t0); del AI_TIMES[:-10]; AI_RUNNING.clear()
threading.Thread(target=_ai_worker, daemon=True, name="ai-check").start()
def ai_progress(cid):
    """Where a card is in the AI line and how long a check usually takes."""
    w = AI_WAIT.get(cid); typical = round(sum(AI_TIMES) / len(AI_TIMES)) if AI_TIMES else None
    ahead = sum(1 for v in list(AI_WAIT.values()) if w and v < w) if w else 0
    run_for = round(time.time() - AI_RUNNING["since"]) if AI_RUNNING.get("since") else 0
    busy = run_for > max(2 * (typical or 45), 120)   # the model is slow right now (e.g. shared with other jobs)
    return {"ahead": ahead, "typical_seconds": typical, "busy": busy, "current_running_seconds": run_for}
KEY_FIELDS = ("name", "company", "title", "emails", "phones")
def ai_reason(f):
    k = f.get("confidence") or {}
    if (f.get("sources") or {}).get("qr"): return None             # QR data is already exact
    low = [x for x in KEY_FIELDS if k.get(x) is not None and k[x] < 0.75] + [x for x in (f.get("needs_review") or []) if x in KEY_FIELDS]
    if not (f.get("first_name") or f.get("last_name")): low.append("name")
    if not f.get("company"): low.append("company")
    ov = f.get("overall_confidence")
    if low or (ov is not None and ov < 0.8): return sorted(set(low)) or ["overall"]
    return None

def ai_available():
    try:
        from . import vlm
        return vlm.available(timeout=1.0)
    except Exception: return False

def maybe_ai_check(cid, force=False):
    if auth.get_setting("ai_check_enabled") != "1" and not force: return "off"
    c = store.get(cid)
    if not c or c["status"] != "pending" or not c.get("image"): return "skip"
    why = ai_reason(c["fields"]) if not force else ["requested"]
    if not why: return "not needed"
    if not ai_available(): set_meta(cid, ai_status="unavailable"); return "unavailable"
    if meta(cid).get("ai_status") == "checking": return "queued"
    prio = 0 if force else 1; key = (prio, next(AI_SEQ))
    if cid in AI_WAIT and AI_WAIT[cid] <= key: return "queued"
    AI_WAIT[cid] = key
    set_meta(cid, ai_status="queued", ai_detail=json.dumps({"why": why, "queued_at": time.time(), "manual": bool(force)}))
    AI_Q.put((prio, key[1], cid, why)); return "queued"

def _ai_run(cid, why):
    """Runs the vision model and stores the differences as SUGGESTIONS only. The card itself is never changed here:
    the reviewer accepts or keeps each value in the review screen (so typed, unsaved edits can never be overwritten)."""
    from . import vlm, merge
    try:
        started = time.time(); set_meta(cid, ai_status="checking", ai_detail=json.dumps({"why": why, "started": started}))
        c = store.get(cid); p = os.path.join(UP, os.path.basename(c.get("image") or ""))
        if not os.path.isfile(p): set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"why": why, "note": "photo missing"})); return
        v = vlm.extract(open(p, "rb").read(), c["raw_text"] or "")
        c = store.get(cid); f = c["fields"]; g = merge.merge(f, v, c["raw_text"] or "")
        src = sources(cid)
        edited = {k for k, x in src.items() if str(x).startswith("edited")}
        if "first_name" in edited or "last_name" in edited: edited.add("name")
        changed = {k: {"from": f.get(k), "to": g.get(k), "edited_by_person": k in edited}
                   for k in QR_KEYS + ("credentials", "other_address") if k in g and g.get(k) != f.get(k)}
        secs = round(time.time() - started, 1)
        set_meta(cid, ai_status="suggested" if changed else "checked", ai_detail=json.dumps(
            {"why": why, "diff": changed, "changed": [], "applied": False, "seconds": secs, "finished": time.time()}))
        log(cid, "AI", "ai_checked", detail={"changed": {}, "suggested": list(changed), "seconds": secs})
    except Exception as e:
        slow = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
        msg = ("The AI model was too busy to answer in time (other jobs are using it). Nothing was changed; you can try again later."
               if slow else f"{type(e).__name__}: {str(e)[:160]}")
        set_meta(cid, ai_status="busy" if slow else "failed", ai_detail=json.dumps({"why": why, "error": msg}))

@router.post("/api/cards/{cid}/ai-check")
def ai_check_now(cid: int):
    r = maybe_ai_check(cid, force=True)
    if r == "unavailable": return JSONResponse({"error": "The AI double-check isn't running on this computer (vision server not started)."}, 503)
    if r == "skip": return JSONResponse({"error": "Only pending cards with a photo can be AI-checked."}, 409)
    return {"status": r} | ai_progress(cid)

@router.post("/api/cards/{cid}/ai-decide")
def ai_decide(cid: int, request: Request, body: dict = Body(...)):
    """body: {field: "accept"|"reject"}. 'accept' puts the AI value in, 'reject' keeps/restores the earlier value.
    Goes through the normal edit path (snapshot, undo, history, re-export flag)."""
    c = store.get(cid); m = meta(cid)
    if not c: raise HTTPException(404, "Card not found")
    try: det = json.loads(m.get("ai_detail") or "{}")
    except Exception: det = {}
    diff = det.get("diff") or {}; fields = {}; made = {}
    for k, choice in (body.get("choices") or {}).items():
        if k not in diff or choice not in ("accept", "reject"): continue
        want = diff[k]["to"] if choice == "accept" else diff[k]["from"]
        if choice == "accept" and c["fields"].get(k) != want: fields[k] = want
        det.setdefault("decided", {})[k] = choice; made[k] = choice
    if fields and not body.get("record_only"):   # record_only: the browser put the value in the form; the person saves it
        r = update(cid, request, {"fields": fields, "note": c.get("note"), "_via_ai": True})
        if isinstance(r, JSONResponse): return r
    src = sources(cid); rv = request.state.user["initials"]
    for k, ch in made.items():
        if ch == "reject" and not str(src.get(k, "")).startswith("edited"): src[k] = "confirmed:" + rv
    set_meta(cid, field_sources=json.dumps(src))
    det["resolved"] = all(k in det.get("decided", {}) for k in diff)
    set_meta(cid, ai_detail=json.dumps(det), ai_status=("checked" if det["resolved"] else meta(cid).get("ai_status")))
    if made: log(cid, rv, "ai_suggestion", detail=made)
    return card(cid)

@router.post("/api/validate")
def validate_api(body: dict = Body(...)):
    f = {"first_name": "", "last_name": "", "emails": [], "phones": []}; _apply_fields(f, body.get("fields") or {})
    return {"errors": validate(f), "hard": hard_errors(f)}

@router.post("/api/admin/cards/{cid}/delete")
def hard_delete(cid: int, request: Request, body: dict = Body(default={})):
    """Removal request: delete the card, its photo, metadata, history and any undo snapshots holding its data.
    Exported files already downloaded are outside the app; stored export copies containing it are deleted too."""
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    if body.get("confirm") != cid: return JSONResponse({"error": "Confirm by sending {\"confirm\": <card id>}."}, 422)
    p = os.path.join(UP, os.path.basename(c.get("image") or ""))
    if c.get("image") and os.path.isfile(p): os.remove(p)
    drop_thumbs(c.get("image"))
    bi = meta(cid).get("back_image")
    if bi and os.path.isfile(os.path.join(UP, os.path.basename(bi))): os.remove(os.path.join(UP, os.path.basename(bi)))
    if os.path.isdir(CORR):
        for fn in os.listdir(CORR):
            if fn.startswith(f"card{cid}_"): os.remove(os.path.join(CORR, fn))
        gp = os.path.join(CORR, "gt.json")
        if os.path.isfile(gp):
            with open(gp) as fh: gt = json.load(fh)
            with open(gp, "w") as fh: json.dump({k: v for k, v in gt.items() if not k.startswith(f"card{cid}_")}, fh, indent=1)
    removed_exports = 0; removed_merged = 0
    x0 = db(); x0.execute("PRAGMA secure_delete=ON")   # overwrite freed pages so the text can't be recovered from the file
    with x0 as x:
        x.execute("DELETE FROM cards WHERE id=?", (cid,)); x.execute("DELETE FROM card_meta WHERE card_id=?", (cid,))
        # Audit rows are KEPT for accountability (who scanned/edited/approved/exported it and when); only the personal
        # data inside them is removed. Statuses, reviewer initials, time and card number stay (PRIVACY-NOTE.md).
        for h in x.execute("SELECT id, action, detail FROM card_history WHERE card_id=?", (cid,)).fetchall():
            x.execute("UPDATE card_history SET detail=? WHERE id=?", (json.dumps(_redact(h["action"], h["detail"])), h["id"]))
        targets = {}   # card that received this card's details -> (merge time, values copied)
        for h in x.execute("SELECT id, card_id, ts, action, detail FROM card_history WHERE action IN ('merged_from','back_added')").fetchall():
            try: dd = json.loads(h["detail"] or "{}")
            except Exception: continue
            if isinstance(dd, dict) and h["action"] == "merged_from" and dd.get("card") == cid and dd.get("added"):
                removed_merged += _unmerge(x, h["card_id"], dd["added"], cid)        # the contact details the merge copied over
                pv = targets.get(h["card_id"]); targets[h["card_id"]] = (min(h["ts"], pv[0]) if pv else h["ts"], (pv[1] if pv else []) + _vals(dd["added"]))
            elif isinstance(dd, dict) and dd.get("from_card") == cid: targets.setdefault(h["card_id"], (h["ts"], []))
            if isinstance(dd, dict) and (dd.get("card") == cid or dd.get("from_card") == cid):   # details copied from it
                x.execute("UPDATE card_history SET detail=? WHERE id=?", (json.dumps({"card": cid, "added": {}, "removed_on_request": True}), h["id"]))
        # the merge target's LATER history rows (edits, back-to-pending problems) can quote the merged values: blank them
        for tid, (since, vals) in targets.items():
            for h in x.execute("SELECT id, detail FROM card_history WHERE card_id=? AND ts>=? AND action IN ('edited','back_to_pending','decision')", (tid, since)).fetchall():
                det = h["detail"] or ""; new = det
                for v in vals:
                    if v and len(v) >= 3: new = new.replace(json.dumps(v)[1:-1], "[removed on request]")
                if new != det: x.execute("UPDATE card_history SET detail=? WHERE id=?", (new, h["id"]))
        # undo snapshots: of this card, and of any card its details were merged into (they hold copies of those details)
        for a in x.execute("SELECT id, snapshot FROM actions").fetchall():
            if any(sn["card"]["id"] == cid or sn["card"]["id"] in targets for sn in json.loads(a["snapshot"] or "[]")): x.execute("DELETE FROM actions WHERE id=?", (a["id"],))
        for e in x.execute("SELECT id, ts, stored, card_ids FROM exports WHERE stored IS NOT NULL").fetchall():
            ids_ = json.loads(e["card_ids"] or "[]")
            if cid in ids_ or any(t in ids_ and e["ts"] >= targets[t][0] for t in targets):   # also exports of a merge target made after the merge
                ep = os.path.join(EXP, e["stored"])
                for q in [ep] + [ep + "." + n for n in COMPANION]:
                    if os.path.isfile(q): os.remove(q)
                x.execute("UPDATE exports SET stored=NULL WHERE id=?", (e["id"],)); removed_exports += 1
    x0.execute("VACUUM"); x0.close()
    for fn in os.listdir(DONE):   # job records (they hold the original file name)
        p_ = os.path.join(DONE, fn)
        try:
            with open(p_) as fh: jd = json.load(fh)
            if jd.get("card_id") == cid: os.remove(p_)
        except Exception: pass
    with JLOCK:
        for jid in [k for k, j in JOBS.items() if (j.get("card") or {}).get("id") == cid]: JOBS.pop(jid, None)
    AI_WAIT.pop(cid, None)
    log(cid, request.state.user["initials"], "deleted_on_request", detail={"export_copies": removed_exports, "merged_removed": removed_merged})
    auth.alog(request.state.user["username"], f"deleted card #{cid} on request (photo, details; history kept without personal data; {removed_exports} stored export file(s))")
    return {"deleted": cid, "export_copies_deleted": removed_exports, "merged_details_removed": removed_merged}

def _redact(action, detail):
    """What is left of a history row's detail after a removal request: no names, contact details, file names or notes."""
    try: d = json.loads(detail) if detail else None
    except Exception: d = None
    out = {"redacted": True}
    if isinstance(d, dict):
        if action == "edited": out["fields"] = sorted(d.keys())
        if action == "decision": out.update({k: True for k in ("bulk",) if d.get(k)}); out.update({"override": True} if d.get("override") else {})
        if action == "merged_from" and d.get("card"): out["card"] = d["card"]
        if action == "duplicate_kept_both" and d.get("cards"): out["cards"] = d["cards"]
        if action in ("exported", "redownloaded") and d.get("export_id"): out["export_id"] = d["export_id"]
        if action == "exported" and d.get("file"): out["file"] = d["file"]   # export file names hold no personal data
        for k in ("why", "undid", "seconds", "after_days"):
            if k in d and action != "back_to_pending": out[k] = d[k]
    elif action == "mc_trade_choice": out["choice"] = d
    return out

def _vals(added):
    out = []
    for k, v in (added or {}).items():
        if k == "phones": out += [p.get("number") or "" for p in v]
        elif isinstance(v, list): out += [str(e) for e in v]
        else: out.append(str(v))
    return out

def _unmerge(x, tid, added, cid):
    """Remove from card tid the values a merge copied in from a card that is being deleted on request."""
    r = x.execute("SELECT fields, note FROM cards WHERE id=?", (tid,)).fetchone()
    if not r: return 0
    f = json.loads(r["fields"]); n = 0
    for k, v in added.items():
        if k == "note":
            nt = (r["note"] or "").replace(f" | From #{cid}: {v}", "").replace(f"From #{cid}: {v}", "").strip(" |")
            x.execute("UPDATE cards SET note=? WHERE id=?", (nt, tid)); n += 1
        elif k == "phones":
            gone = {_digits(p.get("number")) for p in v}; before = len(f.get("phones") or [])
            f["phones"] = [p for p in f.get("phones") or [] if _digits(p.get("number")) not in gone]; n += before - len(f["phones"])
        elif isinstance(v, list):
            before = len(f.get(k) or []); f[k] = [e for e in f.get(k) or [] if e not in v]; n += before - len(f[k])
        elif f.get(k) == v: f[k] = ""; n += 1
    x.execute("UPDATE cards SET fields=? WHERE id=?", (json.dumps(f), tid))
    return n

@router.get("/api/ai/status")
def ai_status():
    return {"enabled": auth.get_setting("ai_check_enabled") == "1", "available": ai_available()}

# ---------------------------------------------------------------- cards
@router.get("/api/cards")
def cards(status: str | None = None, batch: str | None = None, archived: bool = False):
    cs, metas = _active(include_archived=archived)
    out = [enrich(c, cs, metas) for c in cs]
    if archived: out = [c for c in out if c["archived"]]
    if status: out = [c for c in out if c["status"] == status]
    if batch: out = [c for c in out if c["batch"] == batch]
    return out

@router.get("/api/batches")
def batches():
    rows = db().execute("""SELECT m.batch, m.batch_label, COUNT(*) n, SUM(c.status='pending') pending, MIN(c.created) started
       FROM card_meta m JOIN cards c ON c.id=m.card_id WHERE m.archived=0 AND m.batch IS NOT NULL GROUP BY m.batch ORDER BY started DESC""")
    out = [dict(r) for r in rows]
    nob = db().execute("SELECT COUNT(*) FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id WHERE m.batch IS NULL AND COALESCE(m.archived,0)=0").fetchone()[0]
    if nob: out.append({"batch": "__none__", "batch_label": "Earlier cards (no batch)", "n": nob})
    return out

@router.get("/api/cards/{cid}")
def card(cid: int):
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    cs, metas = _active(include_archived=True)
    return enrich(c, cs, metas, full=True)

def _apply_fields(f, body_fields):
    changed = {}
    for k, v in body_fields.items():
        if k in ("confidence", "overall_confidence", "ocr_conf", "fallback_reason", "edited", "sources"): continue
        if k in ("emails", "social"):
            v = [str(x).strip() for x in (v or []) if str(x).strip()]
        elif k == "phones":
            v = [{"type": str(p.get("type", "work")), "number": str(p.get("number", "")).strip(), "valid": phone_ok(str(p.get("number", "")))} for p in (v or []) if str(p.get("number", "")).strip()]
            old = [{"type": p.get("type"), "number": p.get("number"), "valid": phone_ok(p.get("number"))} for p in f.get("phones", [])]
            if old == v: continue
        elif k in f and isinstance(f[k], str) or k in ("first_name", "last_name", "title", "company", "website", "address"):
            v = str(v or "").strip()
        else: continue
        if f.get(k) != v: changed[k] = {"from": f.get(k), "to": v}; f[k] = v
    if changed: f["edited"] = True
    return changed

@router.post("/api/cards/{cid}")
def update(cid: int, request: Request, body: dict = Body(...)):
    """body: fields?, status?, note?, override_reason?, confirm_redecide?, dup_resolution?, merge_into?, crm_action?
       The reviewer is always the signed-in user."""
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    user = request.state.user; rv = user["initials"]
    f = c["fields"]
    st = body.get("status"); st = st if st in ("pending", "approved", "rejected") else None
    # dry-run the checks before taking a snapshot so refused requests don't create undo entries
    import copy
    f2 = copy.deepcopy(f); changes = _apply_fields(f2, body.get("fields") or {})
    if (st and st != c["status"] or body.get("merge_into")):
        if c["status"] != "pending" and not body.get("confirm_redecide"):
            return JSONResponse({"error": f"This card was already {c['status']} by {c.get('reviewer') or 'someone'}. Change it?",
                                 "need": "confirm_redecide", "previous": {"status": c["status"], "reviewer": c.get("reviewer")}}, 409)
    if st == "approved" and not body.get("merge_into"):   # EVERY approval (new or re-sent on an approved card) is checked
        refused = approval_check(c, f2, body, changes)
        if refused is not None: return refused
    if body.get("keep_apart") or body.get("dup_resolution") == "keep_both":
        cs_, metas_ = _active()
        strong = [x["card_id"] for x in dupes(c | {"fields": f2}, cs_, metas_)["queue"] if x["strong"] and x["card_id"] in _req_ids(c, f2, cs_, metas_, body)]
        if strong:
            return JSONResponse({"error": f"Card #{strong[0]} is the same photo, or the same email/phone in the same batch: that's a duplicate scan, "
                                          "not a different person. Merge or reject one of them.", "need": "true_duplicate", "other": strong[0]}, 409)
    merge_tgt = store.get(int(body["merge_into"])) if body.get("merge_into") else None
    if body.get("merge_into") and not merge_tgt: return JSONResponse({"error": "Card to merge into was not found."}, 404)
    label = ({"approved": "Approve", "rejected": "Reject", "pending": "Move to pending"}.get(st, "Edit") + f" card #{cid}")
    if merge_tgt: label = f"Merge card #{cid} into #{merge_tgt['id']}"
    elif body.get("crm_action") and not st: label = f"MC Trade choice on card #{cid}"
    elif body.get("dup_resolution") and not st: label = f"Keep-both choice on card #{cid}"
    snapshot([cid] + ([merge_tgt["id"]] if merge_tgt else []), user, label)

    f = f2; note = body.get("note", c.get("note"))
    if changes:
        src = sources(cid)
        for k in changes: src[k] = "edited:" + rv
        set_meta(cid, field_sources=json.dumps(src))
    if body.get("crm_action") in ("update_existing", "create_new"):
        set_meta(cid, crm_action=body["crm_action"]); log(cid, rv, "mc_trade_choice", detail=body["crm_action"])
    if body.get("keep_apart") or body.get("dup_resolution") == "keep_both":
        cs_, metas_ = _active(); ids = _keep_ids(c, f2, cs_, metas_, body)
        set_meta(cid, kept_apart=json.dumps(sorted(_kept(meta(cid)) | set(ids))), dup_resolution="keep_both")
        log(cid, rv, "duplicate_kept_both", detail={"cards": ids})
    if merge_tgt:
        tf = merge_tgt["fields"]; filled = {}
        for k in ("first_name", "last_name", "title", "company", "website", "address", "department"):
            if not tf.get(k) and f.get(k): tf[k] = f[k]; filled[k] = f[k]
        for k in ("emails", "social"):
            add = [x for x in f.get(k, []) if x not in tf.get(k, [])]
            if add: tf[k] = tf.get(k, []) + add; filled[k] = add
        nums = {_digits(p["number"]) for p in tf.get("phones", [])}
        addp = [p for p in f.get("phones", []) if _digits(p["number"]) not in nums]
        if addp: tf["phones"] = tf.get("phones", []) + addp; filled["phones"] = addp
        dn = (body.get("note") if body.get("note") is not None else c.get("note") or "").strip()
        if dn and dn not in (merge_tgt.get("note") or ""):
            tn = ((merge_tgt.get("note") or "") + f" | From #{cid}: {dn}").strip(" |")
            with db() as conn: conn.execute("UPDATE cards SET note=? WHERE id=?", (tn, merge_tgt["id"]))
            filled["note"] = dn
        store.update(merge_tgt["id"], fields=tf); log(merge_tgt["id"], rv, "merged_from", detail={"card": cid, "added": filled})
        sb, tb = meta(cid).get("back_image"), meta(merge_tgt["id"]).get("back_image")
        if sb and not tb:   # carry the back photo over with the back's details
            set_meta(merge_tgt["id"], back_image=sb); set_meta(cid, back_image=None); log(merge_tgt["id"], rv, "back_added", detail={"filled": [], "from_card": cid})
        if merge_tgt["status"] == "approved": _recheck_approved(merge_tgt["id"], tf, rv, f"details merged from #{cid}")
        if filled and meta(merge_tgt["id"]).get("exported"):   # target already went out: it must be exported again
            set_meta(merge_tgt["id"], reexport=time.time()); log(merge_tgt["id"], rv, "reexport_needed", detail={"why": f"details merged from #{cid}"})
        st = "rejected"; note = f"Duplicate of #{merge_tgt['id']} (details merged)"; set_meta(cid, dup_resolution=f"merged_into:{merge_tgt['id']}")
    if st == "approved" and not merge_tgt and STALE_DUP.search(note or ""):   # re-approved after a merge: the note is no longer true
        note = STALE_DUP.sub("", note).strip(" |"); set_meta(cid, dup_resolution=None)
    store.update(cid, fields=f, status=st, reviewer=rv if st else c.get("reviewer"), note=note)
    if st in ("approved", "rejected") and meta(cid).get("ai_status") == "queued":
        AI_WAIT.pop(cid, None); set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"note": "the card was decided before the AI got to it"}))
    if st == "approved":
        try: save_correction(cid, f)
        except Exception as e: print("correction capture failed:", e)
        errs_now = validate(f); why = (body.get("override_reason") or "").strip()
        if not why and not changes and c["status"] == "approved" and meta(cid).get("override") and errs_now: pass   # re-sent, nothing changed: keep the reason
        else: set_meta(cid, override=json.dumps({"reason": why, "problems": list(errs_now.values()), "by": rv}) if errs_now and why else None)
    elif st: set_meta(cid, override=None)
    if changes and not st and c["status"] == "approved" and meta(cid).get("exported"):
        set_meta(cid, reexport=time.time())
    moved = _recheck_approved(cid, f, rv, "edited after approval") if changes and not st and c["status"] == "approved" else False
    if not st and note != c.get("note"):
        with db() as conn: conn.execute("UPDATE cards SET note=? WHERE id=?", (note, cid))
    if note != c.get("note") and not merge_tgt and "note" in body:
        changes = dict(changes); changes["note"] = {"from": c.get("note") or "", "to": note or ""}
    if changes and not body.get("_via_ai"): log(cid, rv, "edited", detail=changes)
    if st and st != c["status"]:
        log(cid, rv, "decision", c["status"], st, {"override": body.get("override_reason")} if body.get("override_reason") else None)
    out = card(cid)
    if moved: out["notice"] = "This approved card now has problems, so it was moved back to pending: " + "; ".join(validate(f).values())
    return out

STALE_DUP = re.compile(r"\s*\|?\s*Duplicate of #\d+ \(details merged\)")
def approval_check(c, f2, body, changes=None):
    """The one validator for approving a card. Returns a JSONResponse refusing it, or None."""
    cid = c["id"]
    hard = hard_errors(f2)
    if hard:   # list every problem at once; the hard ones can't be overridden
        return JSONResponse({"error": "Some values can't be approved even with a reason.", "need": "fix",
                             "errors": validate(f2) | hard, "hard": list(hard)}, 422)
    errs = validate(f2)
    kept_override = c["status"] == "approved" and meta(cid).get("override") and not changes
    if errs and not (body.get("override_reason") or "").strip() and not kept_override:
        return JSONResponse({"error": "Please fix the highlighted fields before approving.", "need": "fix_or_override", "errors": errs}, 422)
    cs, metas = _active()
    if body.get("dup_resolution") == "keep_both" or body.get("keep_apart"):
        metas.setdefault(cid, {})["kept_apart"] = json.dumps(sorted(_kept(metas.get(cid) or {}) | set(_keep_ids(c, f2, cs, metas, body))))
    if body.get("crm_action"): metas.setdefault(cid, {})["crm_action"] = body["crm_action"]
    d = dupes(c | {"fields": f2, "status": "approved"}, cs, metas)
    appr = [x for x in d["open"] if x["card_id"] != cid and x["blocking"] and (store.get(x["card_id"]) or {}).get("status") == "approved"]
    if appr:
        x = appr[0]
        how = "Merge this card into it, or reject this card." if x.get("strong") else "Use the choices in the orange box: merge into that card, or mark them as different people."
        return JSONResponse({"error": f"Card #{x['card_id']} for what looks like the same person is already approved. {how}",
                             "need": "resolve_duplicate", "other": x["card_id"], "strong": bool(x.get("strong"))}, 409)
    if d["crm"] and not d["crm_action"]:
        return JSONResponse({"error": f"{d['crm'][0]['name']} may already be in MC Trade.", "need": "crm_choice", "match": d["crm"][0] | {"why_text": _why(d["crm"][0]["why"])}}, 409)
    return None

def _req_ids(c, f2, cs, metas, body):
    if body.get("keep_apart") == "all":   # "none of these are the same person": every look-alike that isn't a duplicate scan
        return {x["card_id"] for x in dupes(c | {"fields": f2}, cs, metas)["queue"] if not x["strong"]}
    if body.get("keep_apart"): return {int(x) for x in body["keep_apart"] if str(x).isdigit()}
    return {x["card_id"] for x in dupes(c | {"fields": f2}, cs, metas)["queue"]}   # legacy: all current matches

def _keep_ids(c, f2, cs, metas, body):
    q = dupes(c | {"fields": f2}, cs, metas)["queue"]; want = _req_ids(c, f2, cs, metas, body)
    return [x["card_id"] for x in q if x["card_id"] in want and not x["strong"]]

def _recheck_approved(cid, f, rv, why):
    """An approved card that was edited or merged into is checked again; if it no longer passes it goes back to pending."""
    errs = validate(f) | hard_errors(f)
    if not errs: return False
    store.update(cid, status="pending", reviewer=rv, note=(store.get(cid) or {}).get("note"))
    set_meta(cid, override=None)
    log(cid, rv, "back_to_pending", "approved", "pending", {"why": why, "problems": list(errs.values())})
    return True

# ---------------------------------------------------------------- reviewer corrections -> labelled benchmark data
CORR = os.environ.get("CORRECTIONS_DIR", os.path.join(os.path.dirname(__file__), "..", "bench", "corrections"))
GT_KEYS = ("first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address")
def save_correction(cid, final):
    """When a card a person edited is approved, keep (photo, approved fields) as a labelled example in bench/corrections/.
    Off with setting corrections_enabled=0. Photos here follow the same photo-retention period (see purge)."""
    if auth.get_setting("corrections_enabled") != "1": return
    src = sources(cid); edited = sorted(k for k, v in src.items() if str(v).startswith(("edited", "ai")))
    if not edited: return
    c = store.get(cid); img = c.get("image") or ""; p = os.path.join(UP, os.path.basename(img))
    if not img or not os.path.isfile(p): return
    os.makedirs(CORR, exist_ok=True)
    name = f"card{cid}_{(meta(cid).get('sha256') or uuid.uuid4().hex)[:8]}{os.path.splitext(img)[1] or '.jpg'}"
    import shutil; shutil.copyfile(p, os.path.join(CORR, name))
    gp = os.path.join(CORR, "gt.json")
    try:
        with open(gp) as fh: gt = json.load(fh)
    except (FileNotFoundError, ValueError): gt = {}
    gt = {k: v for k, v in gt.items() if not k.startswith(f"card{cid}_")}
    gt[name] = {k: final.get(k) or ([] if k in ("emails", "phones") else "") for k in GT_KEYS} | {
        "phones": [{"type": p_.get("type", "work"), "number": p_.get("number", "")} for p_ in final.get("phones") or []],
        "cat": ["correction"], "corrected_fields": edited, "saved": time.time()}
    with open(gp + ".tmp", "w") as fh: json.dump(gt, fh, indent=1)
    os.replace(gp + ".tmp", gp)

# ---------------------------------------------------------------- back of the card (optional second photo)
@router.post("/api/cards/{cid}/back")
async def add_back(cid: int, request: Request, image: UploadFile = File(...), confirm_other_person: str = Form("")):
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    data = await image.read()
    if not data or len(data) > MAX_BYTES: return JSONResponse({"error": "File is empty or larger than 25 MB."}, 422)
    from starlette.concurrency import run_in_threadpool
    problem = await run_in_threadpool(_check_image, data)
    if problem: return JSONResponse({"error": problem}, 422)
    from . import pipeline
    r = await run_in_threadpool(scan_limited, data, None, False)
    f0, b0 = c["fields"], r["fields"]
    if not confirm_other_person and _other_person(f0, b0):
        who_b = f"{b0.get('first_name','')} {b0.get('last_name','')}".strip() or b0.get("company") or "someone else"
        return JSONResponse({"error": f"This back photo looks like a different person's card ({who_b}), not "
                                      f"{(f0.get('first_name','') + ' ' + f0.get('last_name','')).strip() or 'this card'}. Nothing was added. "
                                      "Scan it as its own card, or confirm that it really is the back of this card.",
                             "need": "confirm_other_person", "back_name": who_b}, 409)
    ext = os.path.splitext(image.filename or "")[1].lower()
    name = uuid.uuid4().hex + "_back" + (ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg")
    with open(os.path.join(UP, name), "wb") as fh: fh.write(data)
    old = meta(cid).get("back_image")
    if old and os.path.isfile(os.path.join(UP, os.path.basename(old))): os.remove(os.path.join(UP, os.path.basename(old)))
    f = c["fields"]; b = r["fields"]; filled = {}; src = sources(cid)
    for k in QR_KEYS + ("credentials", "other_address"):      # the back only fills gaps; it never overwrites the front or a person's edit
        if b.get(k) and not f.get(k) and not str(src.get(k, "")).startswith("edited"):
            f[k] = b[k]; filled[k] = b[k]; src[k] = "back"
    for k in ("emails", "phones"):
        if f.get(k) and b.get(k):
            have = {json.dumps(x, sort_keys=True) for x in f[k]}
            add = [x for x in b[k] if json.dumps(x, sort_keys=True) not in have and (k != "phones" or _digits(x["number"]) not in {_digits(y["number"]) for y in f[k]})]
            if add: f[k] = f[k] + add; filled[k] = add; src[k] = src.get(k) or "back"
    snapshot([cid], request.state.user, f"Add back of card #{cid}")
    store.update(cid, fields=f)
    with db() as x: x.execute("UPDATE cards SET raw_text=? WHERE id=?", ((c.get("raw_text") or "") + "\n\n--- back of card ---\n" + r["text"], cid))
    set_meta(cid, back_image=name, field_sources=json.dumps(src))
    log(cid, request.state.user["initials"], "back_added", detail={"filled": list(filled)})
    return {"filled": list(filled), "card": card(cid)}

def _other_person(f, b):
    """The back names a different person (both sides have a last name and they differ), or a different company with
    no name in common. A plain back (logo, services list) never counts as another person."""
    from . import mctrade_export as mx
    fl, bl = mx._nm(f.get("last_name")), mx._nm(b.get("last_name"))
    ff, bf = mx._nm(f.get("first_name")), mx._nm(b.get("first_name"))
    if bl and fl and bl != fl: return True
    if bf and ff and bl and bf != ff and bf[:1] != ff[:1]: return True
    return False

@router.post("/api/cards-bulk")
def bulk(request: Request, body: dict = Body(...)):
    st = body.get("status"); user = request.state.user; rv = user["initials"]
    if st not in ("pending", "approved", "rejected"): raise HTTPException(400, "bad status")
    ids = [int(i) for i in body.get("ids", [])]; todo, skipped = [], []
    cs, metas = _active()
    for i in ids:
        c = store.get(i)
        if not c or c["status"] == st: continue
        if c["status"] != "pending" and not body.get("confirm_redecide"):
            skipped.append({"id": i, "why": f"already {c['status']}"}); continue
        if st == "approved":
            if validate(c["fields"]) or hard_errors(c["fields"]): skipped.append({"id": i, "why": "has missing or invalid fields"}); continue
            if approval_check(c, c["fields"], {}) is not None: skipped.append({"id": i, "why": "possible duplicate or MC Trade choice needed"}); continue
            d = dupes(c, cs, metas)
            if d["unresolved_queue"]: skipped.append({"id": i, "why": "possible duplicate of another card"}); continue
        todo.append(c)
    if todo:
        snapshot([c["id"] for c in todo], user, f"Bulk {({'approved': 'approve', 'rejected': 'reject', 'pending': 'move to pending'})[st]} {len(todo)} card(s)")
        for c in todo:
            nt = c.get("note")
            if st == "approved" and STALE_DUP.search(nt or ""): nt = STALE_DUP.sub("", nt).strip(" |"); set_meta(c["id"], dup_resolution=None)
            store.update(c["id"], status=st, reviewer=rv, note=nt); log(c["id"], rv, "decision", c["status"], st, {"bulk": True})
    return {"updated": [c["id"] for c in todo], "skipped": skipped}

@router.post("/api/batches/archive")
def archive(request: Request, body: dict = Body(...)):
    user = request.state.user; rv = user["initials"]; b = body.get("batch")
    if user["role"] != "admin": return JSONResponse({"error": "Only an admin can archive a batch (see the privacy note)."}, 403)
    if b == "__all__":
        if user["role"] != "admin": return JSONResponse({"error": "Only an admin can clear all data."}, 403)
        if body.get("confirm") != "CLEAR": return JSONResponse({"error": "Type CLEAR (capital letters) to confirm archiving everything."}, 422)
        ids = [c["id"] for c in store.all_(None)]
    elif b == "__none__": ids = [r[0] for r in db().execute("SELECT c.id FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id WHERE m.batch IS NULL")]
    else: ids = [r[0] for r in db().execute("SELECT card_id FROM card_meta WHERE batch=?", (b,))]
    ids = [i for i in ids if not meta(i).get("archived")]
    if ids: snapshot(ids, user, f"Archive {len(ids)} card(s)")
    for i in ids: set_meta(i, archived=1); log(i, rv, "archived", detail={"batch": b})
    if b == "__all__": auth.alog(user["username"], f"Clear all test data: archived {len(ids)} card(s) (nothing deleted; Undo restores them)")
    return {"archived": len(ids)}

# ---------------------------------------------------------------- undo
@router.get("/api/undo")
def undo_peek(request: Request):
    r = db().execute("SELECT id,ts,label FROM actions WHERE user_id=? AND undone IS NULL ORDER BY id DESC LIMIT 1", (request.state.user["id"],)).fetchone()
    return dict(r) if r else {}

@router.post("/api/undo")
def undo(request: Request, body: dict = Body(default={})):
    user = request.state.user
    q = "SELECT * FROM actions WHERE user_id=? AND undone IS NULL" + (" AND id=?" if body.get("id") else "") + " ORDER BY id DESC LIMIT 1"
    a = db().execute(q, (user["id"], body["id"]) if body.get("id") else (user["id"],)).fetchone()
    if not a: return JSONResponse({"error": "Nothing to undo."}, 404)
    if time.time() - a["ts"] > 24 * 3600: return JSONResponse({"error": "That action is more than a day old and can't be undone here."}, 409)
    snap = json.loads(a["snapshot"])
    with db() as c:
        for s in snap:
            cd = s["card"]
            c.execute("UPDATE cards SET status=?,raw_text=?,fields=?,reviewer=?,note=?,decided=? WHERE id=?",
                      (cd["status"], cd["raw_text"], cd["fields"], cd["reviewer"], cd["note"], cd["decided"], cd["id"]))
            if s["meta"]:
                m = s["meta"]; c.execute(f"INSERT OR REPLACE INTO card_meta({','.join(META_COLS)}) VALUES({','.join('?' for _ in META_COLS)})", [m.get(k) for k in META_COLS])
            else: c.execute("DELETE FROM card_meta WHERE card_id=?", (cd["id"],))
            c.execute("INSERT INTO card_history(card_id,ts,reviewer,action,detail) VALUES(?,?,?,?,?)",
                      (cd["id"], time.time(), user["initials"], "undo", json.dumps({"undid": a["label"]})))
        c.execute("UPDATE actions SET undone=? WHERE id=?", (time.time(), a["id"]))
    moved = [s["card"]["id"] for s in snap if s["card"]["status"] == "approved"
             and _recheck_approved(s["card"]["id"], json.loads(s["card"]["fields"] or "{}"), user["initials"], "undo restored an approval that no longer passes the checks")]
    return {"undone": a["label"], "cards": [s["card"]["id"] for s in snap], "moved_to_pending": moved}

# ---------------------------------------------------------------- exports (reviewer, duplicate guard, history)
XCOLS = ["IndFirstName", "IndLastName", "IndTitle", "OrgName", "IndEmail", "IndEmail2", "IndPhone", "IndCellPhone", "IndFax",
         "WebAddress", "Address", "AffCode1"]
MORE = ["Credentials", "Department", "OtherAddress", "AllEmails", "AllPhones", "Note"]
AUDIT = ["ScanCardID", "ReviewedBy", "DecidedAt", "Batch", "MCTradeAction", "NeedsAttention"]
FILTERS = {"approved_new": "approved, not yet exported", "approved": "all approved", "all": "all cards", "pending": "pending only", "rejected": "rejected only"}

def _export_set(status, batch=""):
    cs, metas = _active()
    mm = lambda c: metas.get(c["id"]) or {}
    if status == "approved_new": sel = [c for c in cs if c["status"] == "approved" and (not mm(c).get("exported") or mm(c).get("reexport"))]
    else: sel = [c for c in cs if status == "all" or c["status"] == status]
    if batch: sel = [c for c in sel if (mm(c).get("batch") or "__none__") == batch]
    probs = []
    if batch:   # a batch export is only blocked by look-alikes inside the same batch; other people's batches don't block it
        inb = {c["id"] for c in cs if (mm(c).get("batch") or "__none__") == batch}
    for c in sel:   # all batches: look-alikes anywhere in the active queue (pending ones too)
        d = dupes(c, cs, metas)
        if batch: d["open"] = [x for x in d["open"] if x["card_id"] in inb]
        clash = [x["card_id"] for x in d["open"]]
        if clash: probs.append({"id": c["id"], "with": clash, "strong": [x["card_id"] for x in d["open"] if x.get("strong")],
                                "batch": mm(c).get("batch_label") or mm(c).get("batch") or ""})
    return sel, metas, probs

ADMIN_ONLY_FILTERS = ("all", "pending")
REVIEWER_FILTERS = ("approved_new", "approved")      # anything else (rejected, any free text) is admin-only
def _filter_refused(status, user):
    if user["role"] == "admin": return status not in FILTERS and status != "rejected"
    return status not in REVIEWER_FILTERS

PLAINNUM = re.compile(r"[+-]\d+(?:\.\d+)?"); HANDLE = re.compile(r"@[A-Za-z0-9_.]{1,40}(?:\s+@[A-Za-z0-9_.]{1,40})*")
NUMBERISH = re.compile(r"[+-][\d\s().-]*\d[\d\s().-]*(?:\s*(?:x|ext\.?)\s*\d+)?")
def safe_cell(v):
    """CSV formula-injection guard. A leading ' is added ONLY when a spreadsheet would evaluate the text: it starts with
    = or @ or TAB/CR, or with + / - followed by something that is not a plain phone number or number
    ('+1 330-555-0181' and '-5' stay as they are; '+SUM(1)' and '-2+3' get the '). XLSX cells are always typed as text,
    so the Excel file needs (and gets) no prefix at all."""
    if not isinstance(v, str) or not v: return v
    if HANDLE.fullmatch(v): return " " + v      # '@gachamber' (social handle): a leading space keeps it text without a stray '
    if v[0] in "=@\t\r": return "'" + v
    if v[0] in "+-":
        if PLAINNUM.fullmatch(v): return v          # '-5', '+3.5': a number either way, nothing changes
        if NUMBERISH.fullmatch(v) and re.search(r"[\s()]", v): return v   # '+1 330-555-0181': Excel can't evaluate it, stays text
        return "'" + v                              # '+1-330-555-0182', '+1-1', '+SUM(1)': Excel WOULD calculate it
    return v

def _when(t): return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else ""
def _slug(s, n=40): return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:n].strip("-")
def _bname(label):
    """Batch name for file names: the typed name only (not the ' · date · initials' the UI appends)."""
    return (label or "").split(" · ")[0]
def _fname(kind, status, ext, batch_label=""):
    tag = {"approved_new": "new", "approved": "approved", "all": "all", "pending": "pending"}.get(status, _slug(status))
    if batch_label: tag += "-" + _slug(_bname(batch_label), 28)
    kind = {"contacts-for-MC-Trade": "MCTrade"}.get(kind, kind)
    return f"GAC-{kind}-{tag}-{datetime.datetime.now().strftime('%Y-%m-%d_%H%M')}.{ext}"

@router.get("/api/export/check")
def export_check(request: Request, status: str = "approved_new", batch: str = ""):
    if _filter_refused(status, request.state.user):
        return JSONResponse({"error": "Only an admin can export pending, rejected or all cards.", "admin_only": True}, 403)
    sel, metas, probs = _export_set(status, batch)
    flagged = [c["id"] for c in sel if (metas.get(c["id"]) or {}).get("override") or validate(c["fields"])]
    ok_batches = []
    if probs and not batch:   # all batches is blocked: say which single batches can be exported right now
        for b in sorted({(metas.get(c["id"]) or {}).get("batch") or "__none__" for c in sel}):
            s2, m2, p2 = _export_set(status, b)
            if s2 and not p2: ok_batches.append({"batch": b, "label": (m2.get(s2[0]["id"]) or {}).get("batch_label") or b, "count": len(s2)})
    return {"count": len(sel), "duplicates": probs, "flagged": flagged, "ok_batches": ok_batches,
            "admin_only": _filter_refused(status, request.state.user)}

def _note(c):
    """Note as exported: a stale 'Duplicate of #N (details merged)' on a card that is no longer rejected is dropped."""
    n = c.get("note") or ""
    return STALE_DUP.sub("", n).strip(" |") if c.get("status") != "rejected" else n
def build_export(kind, sel, metas, status, who, batch_label=""):
    def flag(c):
        m = metas.get(c["id"]) or {}; ov = _ov(m); errs = validate(c["fields"]); out = []
        if ov: out.append(f"APPROVED ANYWAY by {ov.get('by')}: {ov.get('reason')}")
        if errs: out.append("CHECK: " + "; ".join(errs.values()))
        return " | ".join(out)
    def aud(c):
        m = metas.get(c["id"]) or {}
        return [c["id"], c.get("reviewer") or "", _when(c.get("decided")), m.get("batch_label") or "",
                {"update_existing": "update existing", "create_new": "create new"}.get(m.get("crm_action"), ""), flag(c)]
    def more(c):
        f = c["fields"]
        return [f.get("credentials") or "", f.get("department") or "", f.get("other_address") or "",
                "; ".join(f.get("emails") or []), "; ".join(f"{p.get('type')}: {p.get('number')}" for p in f.get("phones") or []), _note(c)]
    if kind == "csv":
        b = io.StringIO(); w = csv.writer(b)
        w.writerow(export.COLS + ["credentials", "department", "other_address", "all_emails", "all_phones", "note",
                                  "reviewed_by", "decided_at", "batch", "mc_trade_action", "needs_attention"])
        for c in sel:
            r = export._flat(c); r["social"] = r["social"]; a = aud(c); w.writerow([safe_cell(x) for x in [r[k] for k in export.COLS] + more(c) + a[1:]])
        return ("\ufeff" + b.getvalue()).encode(), "text/csv", _fname("contacts", status, "csv", batch_label)   # BOM: Excel opens UTF-8 correctly
    if kind == "vcf":
        return export.to_vcard(sel).encode(), "text/vcard", _fname("contacts", status, "vcf", batch_label)
    if kind == "xlsx":   # MC Trade import file: template columns only, one sheet, one row per person (see mctrade_export.py)
        from openpyxl import Workbook
        from . import mctrade_export as mx
        aff = auth.get_setting("mctrade_affcode") or ""; style = auth.get_setting("phone_format") or "gac"
        def _kept_pair(a, b_): return b_ in _kept(metas.get(a) or {}) or a in _kept(metas.get(b_) or {})
        def _pid(c):
            m_ = mctrade_sync.match(c["fields"]); return m_[0]["profile_id"] if m_ and m_[0]["score"] >= 0.5 else None
        res = mx.build(sel, aff, style, hard_errors, kept=_kept_pair, crm_profile=_pid, action=lambda c: (metas.get(c["id"]) or {}).get("crm_action") or "")
        hdr, source, rows, left, upd = res["headers"], res["source"], res["rows"], res["left"], res["updates"]
        def _book(rws):
            wb = Workbook(); ws = wb.active; ws.title = "Sheet1"; ws.append(hdr)
            for c, r_ in rws: ws.append(mx.cells(hdr, r_))
            for rw in ws.iter_rows():
                for cell in rw:
                    if isinstance(cell.value, str): cell.data_type = "s"   # plain text, never a formula; no ' prefix needed
            b_ = io.BytesIO(); wb.save(b_); return b_.getvalue()
        body_x = _book(rows)
        fn = _fname("contacts-for-MC-Trade", status, "xlsx", batch_label)
        # companion files (not for import): every non-template column + rows left out, and the READ ME notes
        e = io.StringIO(); w = csv.writer(e)
        w.writerow(["ScanCardID", "InImportFile", "WhyLeftOut", "FirstName", "LastName", "Email2", "Website", "Credentials", "Department", "OtherAddress",
                    "AllEmails", "AllPhones", "Social", "Note", "ReviewedBy", "DecidedAt", "Batch", "MCTradeAction", "NeedsAttention"])
        why = {c["id"]: r for c, r in left}; updids = {c["id"] for c, _ in upd}
        for c in sel:
            f_ = c["fields"]; a = aud(c); em = f_.get("emails") or []
            inimp = "updates file" if c["id"] in updids else "no" if c["id"] in why else "yes"
            w.writerow([safe_cell(x) for x in [c["id"], inimp, why.get(c["id"], ""), mx.clean(f_.get("first_name")), mx.clean(f_.get("last_name")),
                        em[1] if len(em) > 1 else "", mx.clean(f_.get("website"))] + [mx.clean(x) for x in more(c)[:5]] + [" ".join(f_.get("social") or []), mx.clean(_note(c))] + a[1:]])
        nflag = sum(1 for c in sel if aud(c)[-1])
        readme = "\n".join([
            "GAC Card Scanner: MC Trade import file (internal pilot)",
            f"Created {_when(time.time())} by {who}; {len(rows)} new-profile row(s) and {len(upd)} update row(s) from {len(sel)} card(s), filter = {FILTERS.get(status, status)}" + (f", batch {batch_label}" if batch_label else "") + ".",
            f"New profiles: {fn} (one sheet, columns = {source}, in template order).",
            (f"Updates of existing MC Trade profiles: {os.path.splitext(fn)[0]}-UPDATES.xlsx ({len(upd)} row(s), with ProfileID and MemberSince 1/1/1900). "
             "MC Trade needs new profiles and updates in SEPARATE imports." if upd else "No 'update existing' cards in this export."),
            "Before importing: in MC Trade Admin > Import Profiles download GAC's template and save it as data/mctrade_template.xlsx",
            "on the scanner computer; exports then copy its header row exactly. Test with two rows first: an import can't be undone.",
            (f"Template columns the scanner does not fill (left blank): {', '.join(res['unknown_cols'])}." if res["unknown_cols"] else "Every template column was recognised."),
            (f"Scanner fields with no column in this template (in the companion CSV only): {', '.join(res['unfilled'])}." if res["unfilled"] else ""),
            f"AffCode1 = '{aff}' (Admin > Settings). The code must already exist in MC Trade exactly, or the file is refused.",
            f"Phones are written as {'+13305550181 (E.164)' if style == 'e164' else '330-555-0181 (GAC style)'}; addresses are split into street/city/state/zip.",
            "A person's website is NOT in the individuals file (Website is an organisation column in MC Trade); it is in the companion CSV.",
            "Text that a spreadsheet could run as a formula (=, +, -, @) or HTML code can't be approved; older cards with it are left out as FIX FIRST.",
            f"Rows left out of the import file: {len(left)} (same person twice: their details were combined into one row; a value that must be fixed first; or an update without a Profile ID). See the companion CSV.",
            f"Cards approved anyway or still failing a soft check: {nflag}. See NeedsAttention in the companion CSV.",
            "Audit details (reviewer, batch, notes, extra emails/phones, credentials, department) are in the companion CSV, not in the import file."])
        comp = {"extra.csv": ("\ufeff" + e.getvalue()).encode(), "readme.txt": readme.encode()}
        if upd: comp["updates.xlsx"] = _book(upd)
        return body_x, MT["xlsx"], fn, comp
    raise HTTPException(404)

MT = {"csv": "text/csv", "vcf": "text/vcard", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
@router.get("/api/export/{kind}")
def do_export(kind: str, request: Request, status: str = "approved_new", batch: str = "", preview: bool = False):
    """preview=1: build and return the file(s) but change nothing (no 'exported' marks, no history, no stored copy)."""
    if kind not in MT: raise HTTPException(404)
    from . import demo
    if demo.enabled(): preview = True   # public demo: every export (incl. the MC Trade Excel) is a dry-run preview
    if _filter_refused(status, request.state.user):
        return JSONResponse({"error": "Only an admin can export pending, rejected or all cards. Reviewers export approved cards."}, 403)
    sel, metas, probs = _export_set(status, batch)
    if probs and not preview:   # a preview changes nothing, so look-alikes don't block it
        msg = ("Some cards in this batch look like the same person. Resolve them in the review screen before exporting." if batch else
               "With “All batches”, look-alikes from anyone's batch block the export. Choose your batch in “Which batch (event)?”, "
               "or ask an admin to resolve the cards listed.")
        return JSONResponse({"error": msg, "duplicates": probs}, 409)
    if not sel: return JSONResponse({"error": "No cards to export."}, 404)
    user = request.state.user
    blabel = next(((metas.get(c["id"]) or {}).get("batch_label") or "" for c in sel), "") if batch else ""
    res = build_export(kind, sel, metas, status, f"{user['display']} ({user['initials']})", blabel)
    body, mt, fn = res[:3]; extras = res[3] if len(res) > 3 else {}
    if preview:
        fn = "PREVIEW-" + fn
        hdrs = {"Content-Disposition": f'attachment; filename="{fn}"', "X-Card-Count": str(len(sel)), "X-Preview": "1", "X-Companions": ",".join(extras)}
        if request.query_params.get("companion") in extras:
            nm = request.query_params["companion"]; mt2, suf = COMPANION[nm]
            return Response(extras[nm], media_type=mt2, headers=hdrs | {"Content-Disposition": f'attachment; filename="{os.path.splitext(fn)[0] + suf}"'})
        return Response(body, media_type=mt, headers=hdrs)
    stored = uuid.uuid4().hex + "_" + fn
    with open(os.path.join(EXP, stored), "wb") as fh: fh.write(body)
    for nm, data in extras.items():
        with open(os.path.join(EXP, stored + "." + nm), "wb") as fh: fh.write(data)
    now = time.time()
    with db() as c:
        c.execute("INSERT INTO exports(ts,username,initials,kind,filter,count,filename,card_ids,stored,batch_label) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (now, user["username"], user["initials"], kind, status, len(sel), fn, json.dumps([x["id"] for x in sel]), stored, blabel if batch else ""))
    for c in sel:
        if not (metas.get(c["id"]) or {}).get("exported"): set_meta(c["id"], exported=now)
        if (metas.get(c["id"]) or {}).get("reexport"): set_meta(c["id"], reexport=None)
        log(c["id"], user["initials"], "exported", detail={"file": fn})
    with db() as c: eid = c.execute("SELECT MAX(id) FROM exports").fetchone()[0]
    return Response(body, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{fn}"', "X-Card-Count": str(len(sel)),
                                                  "X-Export-Id": str(eid), "X-Companions": ",".join(extras)})

COMPANION = {"extra.csv": ("text/csv", "-extra-columns.csv"), "readme.txt": ("text/plain", "-READ-ME.txt"),
             "updates.xlsx": (MT["xlsx"], "-UPDATES.xlsx")}
@router.get("/api/exports/{eid}/companion/{name}")
def export_companion(eid: int, name: str, request: Request):
    """Companion files of an MC Trade import file: the non-template columns + rows left out, and the READ ME notes."""
    if name not in COMPANION: raise HTTPException(404)
    r = db().execute("SELECT * FROM exports WHERE id=?", (eid,)).fetchone()
    u = request.state.user
    if r and u["role"] != "admin" and r["username"] != u["username"]:
        return JSONResponse({"error": "Only the person who made this export (or an admin) can download it."}, 403)
    p = os.path.join(EXP, (r["stored"] or "") + "." + name) if r and r["stored"] else ""
    if not p or not os.path.isfile(p): return JSONResponse({"error": "No such file (it may have been removed by the retention policy)."}, 404)
    mt, suf = COMPANION[name]
    auth.alog(u["username"], f"downloaded the {suf.strip('-')} companion of export #{eid} ({r['filename']})")
    return FileResponse(p, media_type=mt, filename=os.path.splitext(r["filename"])[0] + suf)

@router.get("/api/exports")
def export_history(request: Request):
    out = []; u = request.state.user
    for r in db().execute("SELECT * FROM exports ORDER BY id DESC LIMIT 200"):
        d = dict(r); d["available"] = bool(d["stored"]) and os.path.isfile(os.path.join(EXP, d["stored"])); d["filter_text"] = FILTERS.get(d["filter"], d["filter"])
        d["mine"] = u["role"] == "admin" or d["username"] == u["username"]; d["available"] = d["available"] and d["mine"]
        d["companions"] = [n for n in COMPANION if d["available"] and os.path.isfile(os.path.join(EXP, d["stored"] + "." + n))]
        d["card_ids"] = json.loads(d["card_ids"] or "[]"); d.pop("stored"); out.append(d)
    return out

@router.get("/api/exports/{eid}/download")
def export_again(eid: int, request: Request):
    r = db().execute("SELECT * FROM exports WHERE id=?", (eid,)).fetchone()
    if not r or not r["stored"] or not os.path.isfile(os.path.join(EXP, r["stored"])):
        return JSONResponse({"error": "No such export file (it may have been removed by the retention policy). Export again instead."}, 404)
    u = request.state.user
    if u["role"] != "admin" and r["username"] != u["username"]:
        return JSONResponse({"error": "Only the person who made this export (or an admin) can download it again."}, 403)
    ids = json.loads(r["card_ids"] or "[]")
    auth.alog(request.state.user["username"], f"re-downloaded export #{eid} ({r['filename']}; {len(ids)} card(s): " + ", ".join(f"#{i}" for i in ids[:50]) + (" …" if len(ids) > 50 else "") + ")")
    for i in ids: log(i, request.state.user["initials"], "redownloaded", detail={"export_id": eid, "file": r["filename"]})
    return FileResponse(os.path.join(EXP, r["stored"]), media_type=MT.get(r["kind"]), filename=r["filename"])

# ---------------------------------------------------------------- retention
def purge(now=None, who="retention"):
    """Delete card photos older than image_retention_days and stored export files older than export_retention_days.
    Card text (the contact details) stays, so approved contacts and the audit trail survive."""
    now = now or time.time(); res = {"images": 0, "exports": 0}
    if auth.get_setting("retention_enabled") != "1": return res
    di = int(auth.get_setting("image_retention_days")); de = int(auth.get_setting("export_retention_days"))
    for r in db().execute("SELECT id,image,created FROM cards WHERE image IS NOT NULL AND image!='' AND status!='pending' AND created<?", (now - di * 86400,)).fetchall():
        p = os.path.join(UP, os.path.basename(r["image"]))
        if os.path.isfile(p): os.remove(p)
        drop_thumbs(r["image"])
        bi = meta(r["id"]).get("back_image")
        if bi and os.path.isfile(os.path.join(UP, os.path.basename(bi))): os.remove(os.path.join(UP, os.path.basename(bi)))
        with db() as c: c.execute("UPDATE cards SET image='' WHERE id=?", (r["id"],))
        set_meta(r["id"], image_deleted=now); log(r["id"], who, "photo_deleted", detail={"after_days": di}); res["images"] += 1
    for r in db().execute("SELECT id,stored,ts FROM exports WHERE stored IS NOT NULL AND ts<?", (now - de * 86400,)).fetchall():
        p = os.path.join(EXP, r["stored"])
        for q in [p] + [p + "." + n for n in COMPANION]:
            if os.path.isfile(q): os.remove(q)
        with db() as c: c.execute("UPDATE exports SET stored=NULL WHERE id=?", (r["id"],))
        res["exports"] += 1
    # undo snapshots hold full copies of card data but can only be used for 24 h: drop them after 2 days
    with db() as c: res["undo_snapshots"] = c.execute("UPDATE actions SET snapshot='[]' WHERE ts<? AND snapshot!='[]'", (now - 2 * 86400,)).rowcount
    # orphan photos (e.g. an upload that crashed before its card was saved) follow the same retention clock
    known = {r[0] for r in db().execute("SELECT image FROM cards WHERE image!=''")} | {r[0] for r in db().execute("SELECT back_image FROM card_meta WHERE back_image IS NOT NULL")}
    # labelled correction photos follow the photo retention too (the benchmark keeps only what is still allowed)
    if os.path.isdir(CORR):
        for fn in os.listdir(CORR):
            fp = os.path.join(CORR, fn)
            if not fn.endswith(".json") and os.path.getmtime(fp) < now - di * 86400 and os.path.getmtime(fp) < now - 3600:
                os.remove(fp); res["corrections"] = res.get("corrections", 0) + 1
    for fn in os.listdir(UP):
        fp = os.path.join(UP, fn)
        if fn not in known and os.path.isfile(fp) and os.path.getmtime(fp) < now - di * 86400 and os.path.getmtime(fp) < now - 3600:
            os.remove(fp); res["orphans"] = res.get("orphans", 0) + 1
    if res["images"] or res["exports"] or res.get("orphans"): auth.alog(who, f"retention purge: {res['images']} photo(s), {res['exports']} export file(s) deleted")
    return res

def _retention_loop():
    while True:
        try: purge()
        except Exception as e: print("retention error:", e)
        time.sleep(3600)
threading.Thread(target=_retention_loop, daemon=True).start()

def recover():
    """After a crash or restart: re-queue uploads that were accepted but not yet read (same job id, so an open browser
    keeps tracking them), and reset AI checks that were in flight."""
    n = 0
    for fn in os.listdir(DONE):
        p = os.path.join(DONE, fn)
        if time.time() - os.path.getmtime(p) > 86400: os.remove(p)
    for fn in sorted(os.listdir(INBOX), key=lambda x: os.path.getmtime(os.path.join(INBOX, x))):
        if not fn.endswith(".json"): continue
        jid = fn[:-5]; bp = os.path.join(INBOX, jid + ".bin")
        try:
            with open(os.path.join(INBOX, fn)) as fh: args = json.load(fh)
            if not os.path.isfile(bp): raise FileNotFoundError(bp)
        except Exception:
            for x in (fn, jid + ".bin"):
                try: os.remove(os.path.join(INBOX, x))
                except FileNotFoundError: pass
            continue
        with JLOCK: JOBS[jid] = {"id": jid, "state": "queued", "file": args["fname"], "batch": args["batch"] or "", "sha": args["sha"],
                                 "created": time.time(), "ahead": n, "recovered": True}
        POOL.submit(_run, jid, None, **args); n += 1
    try:
        for r in db().execute("SELECT card_id FROM card_meta WHERE ai_status IN ('queued','checking')").fetchall():
            set_meta(r[0], ai_status=None); maybe_ai_check(r[0])
    except Exception as e: print("ai recovery error:", e)
    if n: print(f"recovered {n} unfinished upload(s)")
    return n
threading.Thread(target=recover, daemon=True).start()

@router.post("/api/admin/retention/run")
def run_purge(request: Request): return purge(who=request.state.user["username"])

@router.get("/api/admin/retention/preview")
def purge_preview():
    di = int(auth.get_setting("image_retention_days")); now = time.time()
    n = db().execute("SELECT COUNT(*) FROM cards WHERE image IS NOT NULL AND image!='' AND status!='pending' AND created<?", (now - di * 86400,)).fetchone()[0]
    total = db().execute("SELECT COUNT(*) FROM cards WHERE image IS NOT NULL AND image!=''").fetchone()[0]
    return {"would_delete": n, "photos_stored": total, "days": di, "enabled": auth.get_setting("retention_enabled") == "1"}

# ---------------------------------------------------------------- audit log
def _fmtv(v):
    """History values in plain words: phone dicts as 'mobile: 330-555-0101', lists joined."""
    if isinstance(v, list): return ", ".join(_fmtv(x) for x in v)
    if isinstance(v, dict): return f"{v.get('type', '')}: {v.get('number', '')}".strip(": ") if "number" in v else ", ".join(f"{k}: {x}" for k, x in v.items())
    return "" if v is None else str(v)

NAMES = {"scanned": "scanned", "edited": "edited", "exported": "exported", "redownloaded": "re-downloaded in an export",
         "merged_from": "merged details from another card", "mc_trade_choice": "MC Trade choice", "back_added": "back of card added",
         "ai_checked": "double-check", "ai_suggestion": "AI suggestion", "duplicate_kept_both": "marked as a different person"}
def _audit_text(action, frm, to, d):
    d = d or {}
    if isinstance(d, dict) and d.get("redacted"):
        if action == "decision": t = f"{frm} → {to}" + (" (approved despite problems)" if d.get("override") else "") + (" (bulk)" if d.get("bulk") else "")
        elif action == "edited": t = "edited " + ", ".join(LABEL.get(k, k) for k in d.get("fields", []))
        elif action == "merged_from" and d.get("card"): t = f"merged details from card #{d['card']}"
        elif action == "exported": t = "exported" + (f" in {d['file']}" if d.get("file") else "")
        elif action == "redownloaded": t = f"re-downloaded in export #{d.get('export_id')}"
        elif action == "duplicate_kept_both" and d.get("cards"): t = "marked as a different person from " + ", ".join(f"#{i}" for i in d["cards"])
        elif action == "undo": t = f"undid: {d.get('undid', '')}"
        else: t = NAMES.get(action, action.replace("_", " "))
        return t + " [personal details removed on request]"
    if action == "deleted_on_request": return f"card deleted on request (photo and details; {d.get('export_copies', 0)} stored export file(s)); its history is kept without personal data"
    if action == "redownloaded": return f"re-downloaded in export #{d.get('export_id')} ({d.get('file')})"
    if action == "decision":
        t = f"{frm} → {to}"
        if isinstance(d, dict) and d.get("override"): t += f' (approved despite problems: "{d["override"]}")'
        if isinstance(d, dict) and d.get("bulk"): t += " (bulk)"
        return t
    if action == "edited": return "edited " + ", ".join(f"{LABEL.get(k, k)}: “{_fmtv(v.get('from'))}” → “{_fmtv(v.get('to'))}”" for k, v in d.items() if isinstance(v, dict))
    if action == "scanned": return f"scanned {d.get('file', '')}" + (f" in batch “{d.get('batch')}”" if d.get("batch") else "") + (" (QR code found)" if d.get("qr") else "")
    if action == "exported": return f"exported in {d.get('file')}"
    if action == "merged_from":
        add = d.get("added") or {}
        return f"merged details from card #{d.get('card')}" + (" (added " + ", ".join(LABEL.get(k, k.replace("_", " ")) for k in add) + ")" if add else "")
    if action == "mc_trade_choice": return "chose: update existing MC Trade contact" if d == "update_existing" else "chose: add as new MC Trade contact"
    if action == "duplicate_kept_both":
        ids = (d or {}).get("cards") if isinstance(d, dict) else None
        return "marked as a different person from " + ", ".join(f"#{i}" for i in ids) + " (keep both)" if ids else "marked as a different person (keep both)"
    if action == "back_to_pending": return f"moved back to pending ({d.get('why')}): " + "; ".join(d.get("problems") or [])
    if action == "archived": return "archived"
    if action == "undo": return f"undid: {d.get('undid')}"
    if action == "ai_checked":
        ch = d.get("changed") or {}
        if d.get("suggested"): return "double-check: suggestions offered for " + ", ".join(LABEL.get(k, k) for k in d["suggested"]) + f" ({d.get('seconds')} s)"
        return "double-check: " + (("changed " + ", ".join(f"{LABEL.get(k, k)} “{_fmtv(v.get('from'))}” → “{_fmtv(v.get('to'))}”" for k, v in ch.items())) if ch else "no changes needed") + f" ({d.get('seconds')} s)"
    if action == "reexport_needed": return f"needs exporting again ({(d or {}).get('why', '')})"
    if action == "ai_suggestion": return "AI suggestion: " + ", ".join(f"{LABEL.get(k, k)}: " + ("used the AI value" if v == "accept" else "kept the current value") for k, v in d.items())
    if action == "back_added" and d.get("from_card"): return f"back photo carried over from card #{d['from_card']}"
    if action == "back_added": return "added the back of the card" + (" (filled " + ", ".join(LABEL.get(k, k) for k in d.get("filled", [])) + ")" if d.get("filled") else "")
    if action == "photo_deleted": return f"photo deleted by retention policy ({d.get('after_days')} days)"
    return action.replace("_", " ")

@router.get("/api/admin/audit")
def audit(q: str = "", limit: int = 500, fmt: str = "json"):
    rows = []
    for r in db().execute("SELECT * FROM card_history ORDER BY id DESC LIMIT ?", (limit,)):
        d = json.loads(r["detail"]) if r["detail"] else None
        txt = _audit_text(r["action"], r["from_status"], r["to_status"], d)
        rows.append({"ts": r["ts"], "who": r["reviewer"] or "system", "what": txt[:400], "card": r["card_id"], "kind": "card"})
    for r in db().execute("SELECT * FROM auth_log ORDER BY id DESC LIMIT ?", (limit,)):
        ev = r["event"] or ""
        kind = "settings" if ev.startswith("settings") else "export" if ev.startswith("re-downloaded") else "card" if ev.startswith("deleted card") else "account"
        cm = re.match(r"deleted card #(\d+)", ev)
        rows.append({"ts": r["ts"], "who": r["username"], "what": ev + (f" (from {r['ip']})" if r["ip"] else ""), "card": int(cm.group(1)) if cm else None, "kind": kind})
    for r in db().execute("SELECT * FROM exports ORDER BY id DESC LIMIT ?", (limit,)):
        rows.append({"ts": r["ts"], "who": r["initials"], "what": f"export {r['kind']} · {r['count']} card(s) · {FILTERS.get(r['filter'], r['filter'])} · {r['filename']}", "card": None, "kind": "export"})
    for r in db().execute("SELECT * FROM actions WHERE undone IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)):
        rows.append({"ts": r["undone"], "who": r["username"], "what": f"undo: {r['label']}", "card": None, "kind": "undo"})
    rows.sort(key=lambda x: -x["ts"])
    if q: ql = q.lower(); rows = [r for r in rows if ql in (str(r["who"]) + " " + r["what"] + " #" + str(r["card"])).lower()]
    rows = rows[:limit]
    if fmt == "csv":
        b = io.StringIO(); w = csv.writer(b); w.writerow(["time", "who", "type", "card", "what"])
        for r in rows: w.writerow([_when(r["ts"]), r["who"], r["kind"], r["card"] or "", r["what"]])
        return Response(b.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="GAC-scanner-audit-{datetime.date.today()}.csv"'})
    return rows
