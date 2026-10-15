"""Update check: on startup (unless an admin turned it off) ask GitHub Releases for the latest version of
LynyrdGrynyrd/gac-card-scanner and show a banner with a link to the release notes when it is newer. Never downloads or
installs anything. Only the public, unauthenticated releases API is called; no card data or usage data is sent."""
import json, os, re, threading, time, urllib.request
from fastapi import APIRouter
from . import auth

REPO = os.getenv("GAC_UPDATE_REPO", "LynyrdGrynyrd/gac-card-scanner")
API = os.getenv("GAC_UPDATE_URL", f"https://api.github.com/repos/{REPO}/releases/latest")
VERSION_FILE = os.path.join(os.path.dirname(__file__), "..", "VERSION")
STATE: dict = {"checked": None, "latest": None, "url": None, "name": None, "error": None}

def current_version():
    if os.getenv("GAC_VERSION"): return os.environ["GAC_VERSION"]
    try: return open(VERSION_FILE).read().strip()
    except OSError: return "0.0.0"

_COMMIT = None
def current_commit():
    """Round 11 (part-timer r4): the build is identifiable. Git checkout: HEAD when the server started; a zip install: the
    COMMIT file that scripts/build_zip.py writes; otherwise 'unknown'."""
    global _COMMIT
    if _COMMIT is None:
        root = os.path.join(os.path.dirname(__file__), "..")
        try: _COMMIT = open(os.path.join(root, "COMMIT")).read().strip()[:12]
        except OSError: _COMMIT = ""
        if not _COMMIT and os.path.isdir(os.path.join(root, ".git")):
            try:
                import subprocess
                _COMMIT = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3).stdout.strip()
                if _COMMIT and subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=no", "app"], capture_output=True, text=True, timeout=3).stdout.strip():
                    _COMMIT += "+local-changes"
            except Exception: _COMMIT = ""
        _COMMIT = _COMMIT or "unknown"
    return _COMMIT

def _parse(v):
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(.*))?$", v or "")
    if not m: return None
    pre = m.group(4) or ""
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), 0 if pre else 1, pre)   # 1.2.0 > 1.2.0-rc1

def newer(latest, current):
    a, b = _parse(latest), _parse(current)
    return bool(a and b and a > b)

def check(timeout=5):
    if auth.get_setting("update_check_enabled") != "1": STATE.update(error="disabled"); return STATE
    try:
        req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "gac-card-scanner-update-check"})
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        if r.get("draft") or r.get("prerelease"): r = {}
        STATE.update(checked=time.time(), latest=r.get("tag_name"), name=r.get("name"), error=None,
                     url=r.get("html_url") if str(r.get("html_url", "")).startswith("https://github.com/") else None)
    except Exception as e:
        STATE.update(checked=time.time(), error=type(e).__name__)
    return STATE

def check_in_background():
    if os.getenv("GAC_UPDATE_CHECK", "1") == "0": return
    threading.Thread(target=lambda: (time.sleep(3), check()), daemon=True, name="update-check").start()

router = APIRouter()
@router.get("/api/update")
def update_status():
    on = auth.get_setting("update_check_enabled") == "1"; cur = current_version()
    avail = on and STATE.get("latest") and newer(STATE["latest"], cur)
    return {"enabled": on, "current": cur, "latest": STATE.get("latest") if on else None, "update_available": bool(avail),
            "url": STATE.get("url") if avail else None, "name": STATE.get("name") if avail else None,
            # round 20 (e): the top-of-page banner is OFF in the local pilot (GAC_UPDATE_BANNER=1 turns it on, admins only);
            # Admin > Settings still shows the version status
            "show_banner": os.getenv("GAC_UPDATE_BANNER", "0") == "1"}
