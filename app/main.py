import os, uuid
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from . import store
from fastapi.staticfiles import StaticFiles
from . import ui as _ui, auth as _auth

app = FastAPI(title="GAC Card Scanner (pilot)", docs_url=None, redoc_url=None, openapi_url=None)  # no public API explorer
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.include_router(_auth.router)
app.include_router(_ui.router)  # also answers the retired legacy URLs (redirect or 410)
app.middleware("http")(_auth.middleware)  # sign-in required everywhere except /login, /setup, /static, /health
UP = os.path.join(os.path.dirname(__file__), "..", "data", "uploads"); os.makedirs(UP, exist_ok=True)

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
    problem = await run_in_threadpool(_ui._check_image, data)
    if problem: return JSONResponse({"error": problem}, 422)
    cid = await run_in_threadpool(_ingest, data, engine); return store.get(cid)

@app.get("/img/{name}")
def img(name: str): return FileResponse(os.path.join(UP, os.path.basename(name)))  # shadowed by app/ui.py's /img (registered first)

# The old server-rendered pages (/card/{id} form, /queue, /export.*, /sync/dry-run) were retired in round 4:
# every approval now goes through /api/cards/{id} (one validator). app/ui.py answers the old URLs with a redirect or 410.
_AI = {"t": 0, "up": False}
def _ai_up():
    import time
    if time.time() - _AI["t"] > 30:
        _AI.update(t=time.time(), up=_ui.ai_available())
    return _AI["up"]
@app.get("/health")
def health():
    up = _ai_up()
    return {"ok": True, "ai_checker": "online" if up else "offline",
            **({} if up else {"ai_note": "AI checker offline: start it with start-ai-checker.command (VLM_URL " + os.getenv("VLM_URL", "http://127.0.0.1:8090") + "). Scanning still works."})}

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
_startup_checks(); _ai_banner()
from . import demo as _demo
if _demo.enabled(): _demo.start()
@app.get("/api/demo")
def demo_info():
    """Public: lets a page/script know whether this is the public demo (no secrets beyond the published demo login)."""
    return {"demo": _demo.enabled(), **({"banner": _demo.BANNER_TEXT, "wipe_hours": _demo.wipe_hours(), "max_cards": _demo.max_cards(),
            "max_mb": _demo.max_bytes() // (1024 * 1024)} if _demo.enabled() else {})}
