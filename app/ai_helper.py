"""Optional "AI helper" for the desktop builds: downloads llama.cpp's llama-server + Qwen3-VL-4B (Apache-2.0) into the
data dir, verifies sha256, and runs llama-server on 127.0.0.1:8090 next to the app. Rules-only scanning never needs it.
Admin-only routes (the auth middleware guards /api/admin/*):
  GET  /api/admin/ai-helper          status (installed, running, download progress)
  POST /api/admin/ai-helper/download start the ~3 GB download in the background
  POST /api/admin/ai-helper/start | /stop
  POST /api/admin/ai-helper/remove   delete the downloaded files"""
import hashlib, json, os, platform, secrets, shutil, subprocess, sys, tarfile, threading, time, urllib.request, zipfile
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from . import paths

router = APIRouter()
DIR = paths.data("ai-helper")
PORT = int(os.environ.get("GAC_AI_PORT", "8090"))
LLAMA_BUILD = "b11604"
_GH = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/"
LLAMA = {  # (asset, sha256) pinned so the download is reproducible and verifiable
    ("Windows", "x64"): (f"llama-{LLAMA_BUILD}-bin-win-cpu-x64.zip", "3a84136c4b3f38f6987d62f42357f342903389dd2e4e59ce47660c4e644bb556"),
    ("Darwin", "arm64"): (f"llama-{LLAMA_BUILD}-bin-macos-arm64.tar.gz", "442b8592d697eb6d20c631e7a73fb6e650f5f61962a651a7b2972be28c747859"),
    ("Darwin", "x64"): (f"llama-{LLAMA_BUILD}-bin-macos-x64.tar.gz", "d5a45b997f63f5af1be4d7f509cad695d803e680bd4826bc765054c16f84dae9"),
}
# pinned repo revision (not "main"), so a later upload to the model repo can't change what gets downloaded; the files are
# also sha256-checked. Dockerfile.space / space/start.sh use the same revision and hashes (keep them in step).
HF_REVISION = "1cd86afb9a95c410a6038ab3b40d8b578c892266"
_HF = f"https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/{HF_REVISION}/"
MODEL = ("Qwen3VL-4B-Instruct-Q4_K_M.gguf", "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a", 2497281664)
MMPROJ = ("mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf", "30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d", 453974304)

# llama-server is started with a random API key, new on every start, so other programs (or web pages) on this computer
# can't use the model server. The key is in this file (owner-only); app/vlm.py sends it as "Authorization: Bearer <key>".
# It is passed with --api-key-file, so it never shows in the process list.
KEY_FILE = os.path.join(DIR, "api-key")

_state = {"phase": "idle", "file": "", "done": 0, "total": 0, "error": ""}
_proc = {"p": None}
_lock = threading.Lock()

def _arch():
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x64"
def llama_asset(): return LLAMA.get((platform.system(), _arch()))

def _server_path():
    root = os.path.join(DIR, "llama")
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    for d, _, fs in os.walk(root):
        if name in fs: return os.path.join(d, name)
    return None

def installed():
    return bool(_server_path()) and all(os.path.exists(os.path.join(DIR, f[0])) for f in (MODEL, MMPROJ))

def running():
    p = _proc["p"]
    return p is not None and p.poll() is None

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def _fetch(url, dest, sha, label):
    """Download with resume (.part) and sha256 check; skip if a verified copy already exists."""
    if os.path.exists(dest) and os.path.exists(dest + ".ok"): return
    part = dest + ".part"; have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={"User-Agent": "gac-card-scanner", **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206: have = 0   # server ignored the range: start over
        total = have + int(r.headers.get("Content-Length") or 0)
        _state.update(file=label, done=have, total=total)
        with open(part, "ab" if have else "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b: break
                f.write(b); _state["done"] += len(b)
    _state.update(phase="verifying")
    got = _sha256(part)
    if got != sha:
        os.remove(part); raise RuntimeError(f"{label}: checksum mismatch (got {got[:12]}…, expected {sha[:12]}…); please try again")
    os.replace(part, dest); open(dest + ".ok", "w").write(sha); _state.update(phase="downloading")

def _download():
    try:
        os.makedirs(DIR, exist_ok=True)
        a = llama_asset()
        if not a: raise RuntimeError(f"No llama.cpp build for {platform.system()} {platform.machine()}")
        _state.update(phase="downloading", error="")
        arc = os.path.join(DIR, a[0]); _fetch(_GH + a[0], arc, a[1], "llama.cpp runtime")
        dst = os.path.join(DIR, "llama"); shutil.rmtree(dst, ignore_errors=True); os.makedirs(dst)
        if arc.endswith(".zip"):
            with zipfile.ZipFile(arc) as z: z.extractall(dst)
        else:
            with tarfile.open(arc) as t:
                try: t.extractall(dst, filter="data")
                except TypeError: t.extractall(dst)
        sp = _server_path()
        if not sp: raise RuntimeError("llama-server not found in the llama.cpp download")
        if os.name != "nt": os.chmod(sp, 0o755)
        for name, sha, _ in (MMPROJ, MODEL):
            _fetch(_HF + name + "?download=true", os.path.join(DIR, name), sha, name)
        _state.update(phase="installed", file="", error="")
        try:
            from . import auth; auth.set_setting("ai_check_enabled", "1")
        except Exception: pass
        start()
    except Exception as e:
        _state.update(phase="error", error=str(e)[:300])

def _new_key():
    """A fresh random API key in KEY_FILE (owner read/write only; replaced atomically)."""
    os.makedirs(DIR, exist_ok=True)
    key = secrets.token_urlsafe(32); tmp = KEY_FILE + ".tmp"
    try: os.remove(tmp)
    except OSError: pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(key + "\n")
    os.replace(tmp, KEY_FILE)
    return key

def _port_answers():
    """Something already serves /health on our port: usually our own llama-server, left running after the app crashed.
    It keeps the key it was started with, so the key file must not be replaced and a second copy can't bind the port."""
    try: return urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=0.5).status == 200
    except Exception: return False

def start():
    with _lock:
        if running() or not installed(): return running()
        if os.path.exists(KEY_FILE) and _port_answers(): return False
        sp = _server_path(); threads = str(max(2, min(8, (os.cpu_count() or 4) - 1)))
        _new_key()
        # -np 1: the app sends one AI check at a time. --cache-ram 0: otherwise llama.cpp keeps up to 8 GB of prompt cache in
        # RAM (out-of-memory kills on 16 GB machines, see start-ai-checker.command). --no-slots: no /slots endpoint.
        cmd = [sp, "-m", os.path.join(DIR, MODEL[0]), "--mmproj", os.path.join(DIR, MMPROJ[0]), "-c", "4096", "-t", threads,
               "-np", "1", "--cache-ram", "0", "--no-slots", "--api-key-file", KEY_FILE,
               "--host", "127.0.0.1", "--port", str(PORT), "--image-max-tokens", "768"]
        log = open(os.path.join(DIR, "llama-server.log"), "ab")
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW
        _proc["p"] = subprocess.Popen(cmd, cwd=os.path.dirname(sp), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        return True

def stop():
    with _lock:
        p = _proc["p"]; _proc["p"] = None
        if p and p.poll() is None:
            p.terminate()
            try: p.wait(10)
            except Exception: p.kill()
        if p is not None:   # only the key of a server we started (and have now stopped)
            try: os.remove(KEY_FILE)
            except OSError: pass

def status():
    s = dict(_state); s.update(installed=installed(), running=running(), port=PORT, supported=bool(llama_asset()),
                               size_gb=round((MODEL[2] + MMPROJ[2] + 20e6) / 1e9, 1), desktop=os.environ.get("GAC_DESKTOP") == "1")
    if s["phase"] == "idle" and s["installed"]: s["phase"] = "installed"
    return s

@router.get("/api/admin/ai-helper")
def api_status(): return status()

@router.post("/api/admin/ai-helper/download")
def api_download(request: Request):
    if _state["phase"] in ("downloading", "verifying"): return status()
    if not llama_asset(): return JSONResponse({"error": "The AI helper is not available for this computer type."}, 422)
    _state.update(phase="downloading", error="", done=0, total=0)
    threading.Thread(target=_download, daemon=True).start(); return status()

@router.post("/api/admin/ai-helper/start")
def api_start(request: Request):
    if not installed(): return JSONResponse({"error": "Download the AI helper first."}, 422)
    start(); return status()

@router.post("/api/admin/ai-helper/stop")
def api_stop(request: Request): stop(); return status()

@router.post("/api/admin/ai-helper/remove")
def api_remove(request: Request):
    if _state["phase"] in ("downloading", "verifying"): return JSONResponse({"error": "A download is running."}, 409)
    stop(); shutil.rmtree(DIR, ignore_errors=True); _state.update(phase="idle", error=""); return status()

def autostart():
    """Desktop builds: bring the helper up with the app if it was downloaded before."""
    if os.environ.get("GAC_DESKTOP") == "1" and installed():
        threading.Thread(target=start, daemon=True).start()
import atexit; atexit.register(stop)
