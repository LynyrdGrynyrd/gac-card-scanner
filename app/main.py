import os, uuid, contextlib
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from . import store
from fastapi.staticfiles import StaticFiles
from . import ui as _ui, auth as _auth, phone as _phone, updates as _updates

@contextlib.asynccontextmanager
async def _lifespan(_app):
    # Everything with side effects runs here, when uvicorn SERVES the app, never on import (round 6).
    _startup_checks(); _ai_banner(); _ui.start_workers(); _updates.check_in_background()
    yield
app = FastAPI(title="GAC Card Scanner (pilot)", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)  # no public API explorer
_HELP_PDFS = {"Reviewer": "GAC-Card-Scanner-Reviewer-Guide.pdf", "Admin": "GAC-Card-Scanner-Admin-Guide.pdf",
              "Help": "GAC-Card-Scanner-Reviewer-Guide.pdf"}   # v0.2.1: the combined guide was split; its old link opens the reviewer guide
@app.get("/static/ui/GAC-Card-Scanner-{which}-Guide.pdf", include_in_schema=False)
def help_pdf(which: str):   # round 8 (newcomer r8): the printable guides open in the browser (inline), they are not forced to download
    from fastapi.responses import Response
    n = _HELP_PDFS.get(which)
    if not n: return Response(status_code=404)
    p = os.path.join(os.path.dirname(__file__), "static", "ui", n)
    return FileResponse(p, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{n}"', "Cache-Control": "no-cache"})
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.add_exception_handler(_ui.BadId, lambda request, e: _ui.bad_id_response(e))   # round 13: strict card ids -> 422
app.include_router(_auth.router)
from . import ai_helper as _aih
app.include_router(_aih.router)
app.include_router(_phone.router)
app.include_router(_updates.router)
app.include_router(_ui.router)  # also answers the retired legacy URLs (redirect or 410)
app.middleware("http")(_auth.middleware)  # sign-in required everywhere except /login, /setup, /static, /health
from . import paths
UP = paths.data("uploads"); os.makedirs(UP, exist_ok=True)

def _ingest(data: bytes, engine: str, ext=".jpg"):
    name = uuid.uuid4().hex + ext
    open(os.path.join(UP, name), "wb").write(data)
    # Fast path via the shared pipeline: QR/vCard + OCR (+ crop pass) + rules. The slow vision-model pass is NOT run here;
    # the /ui job queue schedules it in the background as an "AI double-check" (see app/ui.py).
    r = _ui.scan_limited(data, None if engine in (None, "", "tesseract", "auto", "standard", "hybrid") else engine, use_vlm=False)
    return store.add(r["engine"], r["text"], r["fields"], name)

@app.post("/api/scan")
async def api_scan(image: UploadFile = File(...), engine: str = Form("tesseract")):
    from starlette.concurrency import run_in_threadpool  # keep the event loop free while OCR runs
    data = await image.read()
    if not data or len(data) > _ui.MAX_BYTES: return JSONResponse({"error": "File is empty or larger than 25 MB."}, 422)
    from . import formats
    try: data = await run_in_threadpool(formats.normalize_photo, data)
    except formats.FormatError as e: return JSONResponse({"error": str(e)}, 422)
    problem = await run_in_threadpool(_ui._check_image, data)
    if problem: return JSONResponse({"error": problem}, 422)
    cid = await run_in_threadpool(_ingest, data, engine); return store.get(cid)

@app.get("/img/{name}")
def img(name: str): return FileResponse(os.path.join(UP, os.path.basename(name)))  # shadowed by app/ui.py's /img (registered first)

# The old server-rendered pages (/card/{id} form, /queue, /export.*, /sync/dry-run) were retired in round 4:
# every approval now goes through /api/cards/{id} (one validator). app/ui.py answers the old URLs with a redirect or 410.
_AI = {"t": 0, "up": False}
def _ai_up():
    """Round 20 (a): a cached 'online' is kept for 5 s only, and 'offline' is never cached, so /health says offline as soon
    as nothing answers on VLM_URL (it said online for up to 30 s after the AI stopped)."""
    import time
    if not (_AI["up"] and time.time() - _AI["t"] < 5):
        _AI.update(t=time.time(), up=_ui.ai_available())
    return _AI["up"]
@app.get("/health")
def health():
    up = _ai_up()
    from . import updates as _up
    return {"ok": True, "version": _up.current_version(), "commit": _up.current_commit(), "ai_checker": "online" if up else "offline",
            **({} if up else {"ai_note": "AI check is off right now. Scanning still works.", "ai_hint": "Start it from Admin > Settings > AI helper (desktop app) or start-ai-checker.command (VLM_URL " + os.getenv("VLM_URL", "http://127.0.0.1:8090") + ")."})}

def _startup_checks():
    """Warn loudly at startup (console) if a required dependency is missing, so two installs can't silently differ.
    GAC_STRICT_DEPS=1 turns the warning into a startup failure."""
    from . import parser
    if parser.NAME_LEXICON_ERROR:
        msg = "WARNING: gender_guesser missing (" + parser.NAME_LEXICON_ERROR + "). Run: pip install -r requirements.txt"
        print("\n" + "!" * 78 + "\n" + msg + "\n" + "!" * 78 + "\n", flush=True)
        if os.environ.get("GAC_STRICT_DEPS") == "1": raise RuntimeError(msg)
def _ai_banner():
    """Say at startup whether the optional AI double-check is reachable, so a missing checker is noticed at once."""
    import threading
    def run():
        up = _ai_up(); url = os.getenv("VLM_URL", "http://127.0.0.1:8090")
        line = f"AI checker online at {url}" if up else f"AI checker OFFLINE (nothing answers at {url}). Scanning works; the AI double-check is off until start-ai-checker.command runs."
        print("\n" + "=" * 78 + "\n" + line + "\n" + "=" * 78 + "\n", flush=True)
    threading.Thread(target=run, daemon=True).start()
_startup_checks(); _ai_banner(); _aih.autostart()
from . import demo as _demo
if _demo.enabled(): _demo.start()
@app.get("/api/demo")
def demo_info():
    """Public: lets a page/script know whether this is the public demo (no secrets beyond the published demo login)."""
    return {"demo": _demo.enabled(), **({"banner": _demo.BANNER_TEXT, "wipe_hours": _demo.wipe_hours(), "max_cards": _demo.max_cards(),
            "max_mb": _demo.max_bytes() // (1024 * 1024)} if _demo.enabled() else {})}
