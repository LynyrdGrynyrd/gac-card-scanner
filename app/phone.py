"""Phone mode: "Scan with phone" pairing (opt-in per session; admins can switch it off in Settings).

How it works
- The desktop app itself keeps listening on 127.0.0.1 only. When a signed-in user clicks "Scan with phone", a SECOND,
  minimal web server is started on this computer's LAN address (PHONE_PORT, default 8766). It serves ONLY the phone page
  and one upload endpoint: no review queue, no exports, no admin, no card data can be read through it.
- The QR code carries http://<lan-ip>:8766/m?t=<pairing token>. The token is random (128 bit), expires after
  PHONE_TOKEN_MINUTES (default 15), and only allows uploading photos into the desktop's job queue, attributed to the
  user who showed the QR code. On first open the token moves into an HttpOnly SameSite=Strict cookie and is removed
  from the address bar.
- Uploads need the double-submit CSRF header + a same-origin Origin header, are rate limited per token and per IP, and
  go through the same image checks and duplicate check as desktop uploads.
- When the last token expires or is stopped (or the admin turns phone mode off), the LAN server is shut down again.
- HTTPS is not available on the LAN, so browsers treat the page as insecure: live camera preview (getUserMedia) and the
  service worker are unavailable there. The page then uses <input type=file capture=environment>, which opens the
  phone's camera app over plain http on iOS Safari and Android Chrome. See docs/PHONE-MODE.md.
"""
import hashlib, hmac, io, os, re, secrets, socket, threading, time
from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile, Body
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from . import auth

PORT = int(os.getenv("PHONE_PORT", "8766"))
TTL = int(os.getenv("PHONE_TOKEN_MINUTES", "15")) * 60
MAX_UPLOADS = int(os.getenv("PHONE_MAX_UPLOADS", "300"))      # per pairing
RATE_PER_MIN = int(os.getenv("PHONE_RATE_PER_MIN", "20"))     # uploads per token per minute
BAD_PER_MIN = 10                                             # wrong/expired token attempts per IP per minute
STATIC = os.path.join(os.path.dirname(__file__), "static", "phone")
COOKIE = "gac_phone"; CSRF_COOKIE = "gac_phone_csrf"; CSRF_HEADER = "x-csrf-token"

TOKENS: dict = {}     # token -> {user, initials, display, expires, batch, batch_label, uploads, times[]}
_BAD: dict = {}       # ip -> [timestamps]
_LOCK = threading.Lock()
_SRV = {"server": None, "thread": None, "host": None}

def allowed(): return auth.get_setting("phone_mode_allowed") == "1"
_CSRF_KEY = secrets.token_bytes(32)   # skeptic R9-2: a server secret, so nobody can compute the value from the cookie
def csrf_for(tok): return hmac.new(_CSRF_KEY, (tok or "").encode(), hashlib.sha256).hexdigest()[:40]
def valid_session(sess):
    """skeptic R9-2: the phone's cookie is a separate random session secret minted when the QR link is first opened,
    never the QR token itself. Returns (qr_token, pairing) or (None, None)."""
    if not sess: return None, None
    with _LOCK:
        for t, v in TOKENS.items():
            if v.get("sess") and hmac.compare_digest(v["sess"], sess):
                return (t, v) if v["expires"] > time.time() else (None, None)
    return None, None

def _rank(ip):
    """Lower is better: a private home/office LAN address first (192.168/16, then 10/8, then 172.16/12), never loopback or
    link-local. Docker/VM bridges (172.17-172.31.x, 192.168.56.x VirtualBox host-only) rank after a normal LAN address."""
    import ipaddress
    try: a = ipaddress.ip_address(ip)
    except ValueError: return 99
    if a.version != 4 or a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast: return 99
    if ip.startswith("192.168.56."): return 5
    if ip.startswith("192.168."): return 0
    if ip.startswith("10."): return 1
    if a in ipaddress.ip_network("172.16.0.0/12"): return 3 if a in ipaddress.ip_network("172.16.0.0/16") else 4
    if a in ipaddress.ip_network("100.64.0.0/10"): return 6   # carrier-grade NAT / VPN (Tailscale)
    return 8 if a.is_private else 9                        # a public address: a phone on Wi-Fi rarely reaches it
VIRT_IF = re.compile(r"^(docker|br-|veth|virbr|vboxnet|vmnet|cni|flannel|podman|lxc|lxd|tun|zt)")
def lan_candidates():
    """All IPv4 addresses of this computer, best first (round 8, part-timer r2: the pick was the default-route address)."""
    ips = []; virt = set()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("10.255.255.255", 1)); ips.append(s.getsockname()[0])
    except OSError: pass
    finally: s.close()
    try: ips += [x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError: pass
    try:
        import subprocess
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=2).stdout
        for ifn, ip in re.findall(r"^\d+:\s*(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/", out, re.M):
            ips.append(ip)
            if VIRT_IF.match(ifn): virt.add(ip)
    except Exception: pass
    ips = [i for i in dict.fromkeys(ips) if _rank(i) < 99]
    ips = sorted(ips, key=lambda i: (_rank(i), ips.index(i)))
    # round 10 (skeptic R9-5): Docker / VM bridge addresses (172.17.0.1, virbr0, vboxnet) are never shown when a real
    # LAN address exists; a phone cannot reach them
    real = [i for i in ips if i not in virt and _rank(i) not in (4, 5)]
    return real or [i for i in ips if i not in virt] or ips
def lan_ip():
    """This computer's address on the local network: PHONE_HOST if set, else the best private LAN address."""
    if os.getenv("PHONE_HOST"): return os.environ["PHONE_HOST"]
    c = lan_candidates()
    return c[0] if c else "127.0.0.1"

def _purge():
    now = time.time()
    with _LOCK:
        for t in [t for t, v in TOKENS.items() if v["expires"] < now]: TOKENS.pop(t, None)
        alive = bool(TOKENS)
    if not alive or not allowed(): stop_server()

def valid(tok):
    if not tok: return None
    with _LOCK:
        for t, v in TOKENS.items():
            if hmac.compare_digest(t, tok): return v if v["expires"] > time.time() else None
    return None

def _bad(ip):
    now = time.time(); xs = [x for x in _BAD.get(ip, []) if now - x < 60]; xs.append(now); _BAD[ip] = xs
    return len(xs) > BAD_PER_MIN
def _blocked(ip): return len([x for x in _BAD.get(ip, []) if time.time() - x < 60]) > BAD_PER_MIN

# ---------------------------------------------------------------- LAN server lifecycle
def start_server():
    if _SRV["server"] and _SRV["thread"] and _SRV["thread"].is_alive(): return _SRV["host"]
    import uvicorn
    host = lan_ip()
    srv = uvicorn.Server(uvicorn.Config(phone_app, host=host, port=PORT, log_level="warning", access_log=False, lifespan="off"))
    srv.install_signal_handlers = lambda: None
    th = threading.Thread(target=srv.run, daemon=True, name="phone-lan"); th.start()
    for _ in range(50):
        if srv.started: break
        time.sleep(0.05)
    _SRV.update(server=srv, thread=th, host=host)
    threading.Thread(target=_reaper, daemon=True).start()
    return host

def stop_server():
    srv = _SRV.get("server")
    if srv: srv.should_exit = True
    _SRV.update(server=None, thread=None, host=None)

def running(): return bool(_SRV["server"] and _SRV["thread"] and _SRV["thread"].is_alive())

def _reaper():
    while running():
        time.sleep(15)
        try: _purge()
        except Exception as e: print("phone reaper error (continuing):", repr(e), flush=True)   # audit 2026-10 P0-3

# ---------------------------------------------------------------- desktop side (signed-in, main app)
router = APIRouter()

def _qr_svg(url):
    import qrcode, qrcode.image.svg
    b = io.BytesIO(); qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2).save(b)
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(b.getvalue()).decode()

@router.post("/api/phone/start")
def phone_start(request: Request, body: dict = Body(default={})):
    if not allowed(): return JSONResponse({"error": "Phone scanning is off. An admin can turn it on in Admin → Settings."}, 403)
    u = request.state.user
    from . import ui
    label = str(body.get("batch_label") or "").strip()[:60]
    tok = secrets.token_urlsafe(16); batch = "phone-" + secrets.token_hex(4)
    # round 9 (R8-7): phone batch names are unique: a blank name gets the person and the time, and a name another
    # batch already uses gets " (2)" etc.
    if not label: label = f"Phone scans {u['initials']} " + time.strftime("%b %d %I:%M %p").replace(" 0", " ")
    with _LOCK:
        for t in [t for t, v in TOKENS.items() if v["user"] == u["id"]]: TOKENS.pop(t)   # one live pairing per user
        label = ui.unique_batch_label(label, batch, [v["batch_label"] for v in TOKENS.values()])
        TOKENS[tok] = {"user": u["id"], "initials": u["initials"], "display": u["display"], "expires": time.time() + TTL,
                       "batch": batch, "batch_label": label, "uploads": 0, "times": [], "jobs": []}
    try: host = start_server()
    except Exception as e:
        with _LOCK: TOKENS.pop(tok, None)
        return JSONResponse({"error": "Couldn't start phone scanning. Restart the scanner or ask IT."}, 500)
    url = f"http://{host}:{PORT}/m?t={tok}"
    auth.alog(u["username"], f"phone mode: pairing QR shown (LAN {host}:{PORT}, {TTL // 60} min)", auth._client(request))
    v = TOKENS[tok]
    return {"url": url, "qr": _qr_svg(url), "expires": v["expires"], "ttl": TTL, "host": host, "port": PORT, "batch": v["batch"], "lan_only": host != "127.0.0.1",
            "candidates": lan_candidates() if not os.getenv("PHONE_HOST") else [host]}

@router.get("/api/phone/status")
def phone_status(request: Request):
    u = request.state.user; _purge()
    with _LOCK: v = next((dict(v) for v in TOKENS.values() if v["user"] == u["id"]), None)
    return {"allowed": allowed(), "active": bool(v), "listening": running(), "expires": v and v["expires"], "uploads": v and v["uploads"],
            "batch": v and v["batch"], "jobs": (v or {}).get("jobs", [])[-50:]}

@router.post("/api/phone/stop")
def phone_stop(request: Request):
    u = request.state.user
    with _LOCK:
        for t in [t for t, v in TOKENS.items() if v["user"] == u["id"]]: TOKENS.pop(t)
    _purge(); return {"ok": True, "listening": running()}

def revoke_all():
    with _LOCK: TOKENS.clear()
    stop_server()

# ---------------------------------------------------------------- phone side (LAN server: upload only)
phone_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
SEC = dict(auth.SEC_HEADERS); SEC["Content-Security-Policy"] = SEC["Content-Security-Policy"].replace(" 'unsafe-eval'", "").replace("connect-src 'self'", "connect-src 'self'; media-src 'self' blob:; worker-src 'self'; manifest-src 'self'")

from .bodylimit import BodyLimit as _BodyLimit
phone_app.add_middleware(_BodyLimit, limit=52 * 1024 * 1024, message="Upload is too large (25 MB per photo).", headers=SEC)   # audit 2026-10 P0-12

@phone_app.middleware("http")
async def _guard(request: Request, call_next):
    ip = request.client.host if request.client else ""
    if request.method not in ("GET", "HEAD", "POST"): return JSONResponse({"error": "Not allowed."}, 405, headers=SEC)
    if request.method == "POST":
        src = request.headers.get("origin") or request.headers.get("referer") or ""
        from urllib.parse import urlsplit
        if not src or urlsplit(src).netloc.lower() != (request.headers.get("host") or "").lower():
            return JSONResponse({"error": "Cross-site request refused."}, 403, headers=SEC)
        try: clen = int(request.headers.get("content-length") or 0)
        except ValueError: clen = 0
        if clen > 52 * 1024 * 1024: return JSONResponse({"error": "Upload is too large (25 MB per photo)."}, 413, headers=SEC)
    if _blocked(ip): return JSONResponse({"error": "Too many attempts. Wait a minute and scan the QR code again."}, 429, headers=SEC)
    resp = await call_next(request)
    for k, v in SEC.items(): resp.headers.setdefault(k, v)
    if request.url.path.startswith("/m/api/") or request.url.path == "/m": resp.headers["Cache-Control"] = "no-store"
    return resp

def _set(resp, tok, v):
    age = max(1, int(v["expires"] - time.time()))
    resp.set_cookie(COOKIE, tok, httponly=True, samesite="strict", max_age=age, path="/m")
    resp.set_cookie(CSRF_COOKIE, csrf_for(tok), httponly=False, samesite="strict", max_age=age, path="/m")

@phone_app.get("/")
def p_root(): return RedirectResponse("/m", 303)

@phone_app.get("/m")
def p_page(request: Request, t: str = ""):
    ip = request.client.host if request.client else ""
    if t:
        v = valid(t)
        with _LOCK:   # skeptic R8-4: the QR link works ONCE; a second device (or a copied link) gets the expired page
            used = bool(v and v.get("claimed")); 
            if v and not used: v["claimed"] = time.time(); v["sess"] = secrets.token_urlsafe(32); v["ip"] = ip   # round 15 (skeptic): bound to the claiming device
        if not v or used:
            _bad(ip); return FileResponse(os.path.join(STATIC, "expired.html"), status_code=403)
        r = RedirectResponse("/m", 303); _set(r, v["sess"], v); return r      # token leaves the address bar / history
    if not _session(request)[1]: return FileResponse(os.path.join(STATIC, "expired.html"), status_code=403)
    return FileResponse(os.path.join(STATIC, "index.html"))

_FILES = {"phone.js": "text/javascript", "phone.css": "text/css", "manifest.webmanifest": "application/manifest+json",
          "icon-192.png": "image/png", "icon-512.png": "image/png"}
@phone_app.get("/m/sw.js")
def p_sw(): return FileResponse(os.path.join(STATIC, "sw.js"), media_type="text/javascript", headers={"Service-Worker-Allowed": "/m", "Cache-Control": "no-cache"})
@phone_app.get("/m/{name}")
def p_static(name: str):
    if name not in _FILES: return JSONResponse({"error": "Not found."}, 404)
    return FileResponse(os.path.join(STATIC, name), media_type=_FILES[name], headers={"Cache-Control": "no-cache"})

def _user_ok(v):
    """Merge R7: the pairing only acts for a user who is STILL an active account, and only while phone mode is allowed."""
    try: r = auth.db().execute("SELECT active FROM users WHERE id=?", (v["user"],)).fetchone()
    except Exception: r = None
    return bool(r and r[0]) and allowed()

def _session(request):
    sess = request.cookies.get(COOKIE); qr, v = valid_session(sess)
    # round 15 (skeptic): a copied phone cookie used from another address is refused (the pairing is bound to the IP that
    # opened the QR link). A phone that changes Wi-Fi mid-session just scans a new QR code.
    ip = request.client.host if request.client else ""
    if v and v.get("ip") and ip != v["ip"]: return sess, None
    if v and not _user_ok(v):
        with _LOCK: TOKENS.pop(qr, None)
        v = None
    return sess, v

@phone_app.get("/m/api/state")
def p_state(request: Request):
    tok, v = _session(request)
    if not v: return JSONResponse({"error": "This pairing has expired. Scan a new QR code on the computer.", "need": "pair"}, 401)
    return {"by": v["display"], "expires": v["expires"], "uploads": v["uploads"], "batch_label": v["batch_label"], "max": MAX_UPLOADS}

@phone_app.post("/m/api/upload")
async def p_upload(request: Request, image: UploadFile = File(...), back: UploadFile | None = File(None), batch_label: str = Form("")):
    tok, v = _session(request); ip = request.client.host if request.client else ""
    if not v:
        _bad(ip); return JSONResponse({"error": "This pairing has expired. Scan a new QR code on the computer.", "need": "pair"}, 401)
    if not hmac.compare_digest(request.headers.get(CSRF_HEADER, ""), csrf_for(tok)):
        return JSONResponse({"error": "Security token missing. Reload the page.", "need": "reload"}, 403)
    now = time.time()
    with _LOCK:
        v["times"] = [x for x in v["times"] if now - x < 60]
        if len(v["times"]) >= RATE_PER_MIN: return JSONResponse({"error": f"Slow down: at most {RATE_PER_MIN} cards a minute."}, 429)
        if v["uploads"] >= MAX_UPLOADS: return JSONResponse({"error": "Upload limit for this pairing reached. Show a new QR code on the computer."}, 429)
        v["times"].append(now)
    from . import ui
    data = await image.read(); bdata = (await back.read()) if back is not None else None
    if bdata is not None and (not bdata or len(bdata) > ui.MAX_BYTES): return JSONResponse({"error": "Back photo is empty or larger than 25 MB."}, 422)
    if bdata:   # same shared image checks as the desktop "Add back of card" (merge R7)
        from starlette.concurrency import run_in_threadpool
        from . import formats
        try: bdata = await run_in_threadpool(formats.normalize_photo, bdata)
        except formats.FormatError as e: return JSONResponse({"error": "Back photo: " + str(e)}, 422)
        problem = await run_in_threadpool(ui._check_image, bdata)
        if problem: return JSONResponse({"error": "Back photo: " + problem}, 422)
    if batch_label.strip() and ui.clean_batch_label(batch_label.strip()[:60]) != v["batch_label"]:
        with _LOCK: v["batch_label"] = ui.unique_batch_label(batch_label.strip()[:60], v["batch"], [x["batch_label"] for x in TOKENS.values() if x is not v])
    r = await ui.enqueue_upload(data, image.filename or "phone.jpg", batch=v["batch"], batch_label=v["batch_label"] or "Phone scans",
                                who=v["initials"], back=bdata)
    if isinstance(r, Response): return r
    ids = [j["job"] for j in r.get("jobs", [])  if j.get("job")] or [r["job"]]   # round 18: a PDF / multi-card sheet is several cards
    with _LOCK: v["uploads"] += 1; v["jobs"].extend(ids)
    return {"ok": True, "job": r["job"], "jobs": ids, "cards": len(ids), "ahead": r.get("ahead", 0), "uploads": v["uploads"],
            **({"pdf": True, "pages": r.get("pages")} if r.get("pdf") else {})}

@phone_app.get("/m/api/jobs")
def p_jobs(request: Request):
    """Progress of THIS pairing's uploads only (state words; no card contents leave the computer)."""
    tok, v = _session(request)
    if not v: return JSONResponse({"error": "expired", "need": "pair"}, 401)
    from . import ui
    with ui.JLOCK:
        want = set(v["jobs"])
        for j in ui.JOBS.values():   # round 20: a PDF is one background job that adds its cards as it reads each page
            if j["id"] in want and j.get("kind") == "pdf": want |= {c["job"] for c in j.get("children") or [] if c.get("job")}
        par = {c["job"]: j["id"] for j in ui.JOBS.values() if j.get("kind") == "pdf" for c in j.get("children") or [] if c.get("job")}
        js = [{"id": j["id"], "state": j["state"], "file": j.get("file"), **({"parent": par[j["id"]]} if j["id"] in par else {})} for j in ui.JOBS.values() if j["id"] in want]
    return {"jobs": js}
