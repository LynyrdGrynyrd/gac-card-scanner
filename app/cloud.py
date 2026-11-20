"""Optional cloud reading source (AICLOUD, 2026-11-20). OFF by default: nothing leaves this computer unless an admin
switches "Where cards are read" to "Cloud service", ticks the consent box and enters an API key (Admin -> Settings -> AI check).

Everything about the key and the on/off rule is in this file, so it can be reviewed in one place:
- the key lives ONLY in <data>/cloud/api-key (owner read/write only), never in the settings table, an API answer, a log line,
  the audit log or an error text; the only thing that ever leaves this module about it is "a key is set" (key_set());
- active() is the one question "may a card go to the cloud?": setting says cloud AND not demo mode AND a key is set AND the
  address is https (http only for 127.0.0.1, so tests can use a stand-in server);
- post() is the ONLY function that sends anything to the cloud (the card request and the save-time check both use it): it never
  follows a redirect (urllib would copy the Authorization header to the other host) and sends a 127.0.0.1 address past any proxy.
app/vlm.py asks active() before every request and builds the request; this module never builds a card request."""
import json, os, re, urllib.error, urllib.request
from urllib.parse import urlsplit
from . import demo, paths

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-3.8-flash"
KEY_FILE = paths.data("cloud", "api-key")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")

def _settings():
    """read_source, cloud_base_url and cloud_model in ONE read, so a save in between can never give a mix of old and new."""
    from . import auth
    keys = ("read_source", "cloud_base_url", "cloud_model")
    got = dict(auth.db().execute("SELECT key, value FROM settings WHERE key IN (?,?,?)", keys).fetchall())
    return {k: got.get(k, auth.DEFAULTS[k]) for k in keys}

class CloudError(Exception):
    """A short calm message only: never the provider's text, never the key. kind: refused | redirect | http | unreachable | format | off."""
    def __init__(self, msg, kind="http", code=None): super().__init__(msg); self.kind, self.code = kind, code

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None   # a 3xx becomes an HTTPError: the key is never handed to another address

def post(base, path, body, key, timeout):
    """POST JSON to {base}{path} with the key; returns the parsed JSON object. Raises CloudError (calm text only)."""
    loopback = urlsplit(base).hostname == "127.0.0.1"
    opener = urllib.request.build_opener(_NoRedirect, *([urllib.request.ProxyHandler({})] if loopback else []))   # loopback (tests) never goes to a proxy
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try: raw = opener.open(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400: raise CloudError("cloud service answered with a redirect", "redirect", e.code) from None
        raise CloudError(f"cloud service answered HTTP {e.code}", "refused" if e.code in (401, 403) else "http", e.code) from None
    except TimeoutError: raise CloudError("cloud service timed out", "unreachable") from None
    except Exception as e: raise CloudError("cloud service connection failed" if isinstance(e, OSError) else "cloud service answer unusable", "unreachable") from None
    try: out = json.loads(raw)
    except ValueError: raise CloudError("cloud service answer unusable", "format") from None
    if not isinstance(out, dict): raise CloudError("cloud service answer unusable", "format")
    return out

def safe_base(url):
    """The base URL without a trailing slash, or None when it must not be used: https only (http only for 127.0.0.1), no
    user:password, no query, no fragment."""
    if "?" in (url or "") or "#" in (url or ""): return None   # not even an empty query or fragment (urlsplit would let those through)
    try: u = urlsplit((url or "").strip())
    except ValueError: return None
    if u.username or u.password or u.query or u.fragment or not u.hostname: return None
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname == "127.0.0.1"): return None
    return url.strip().rstrip("/")

# ---- the key: one owner-only file
def get_key():
    try:
        with open(KEY_FILE, encoding="utf-8") as f: return f.read().strip()
    except OSError: return ""
def key_set(): return bool(get_key())
def set_key(key):
    """Raises OSError when the file can not be written; no api-key.tmp is left behind."""
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    tmp = KEY_FILE + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # created owner-only (a no-op on Windows, where the data folder is per user)
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(key.strip())
        os.replace(tmp, KEY_FILE)
    except BaseException:
        try: os.remove(tmp)
        except FileNotFoundError: pass
        raise
def clear_key():
    """Only "there is no key file" is fine; any other failure raises OSError (the key would still be there)."""
    try: os.remove(KEY_FILE)
    except FileNotFoundError: pass

# ---- on / off
def selected():
    """The admin chose "Cloud service" (and this is not the public demo)."""
    return _settings()["read_source"] == "cloud" and not demo.enabled()
def config():
    """(base, model, key) when a card may be sent to the cloud right now, else None. THE off-by-default rule."""
    st = _settings()
    if st["read_source"] != "cloud" or demo.enabled(): return None
    base, key, model = safe_base(st["cloud_base_url"]), get_key(), (st["cloud_model"] or "").strip()
    return (base, model, key) if base and key and MODEL_RE.fullmatch(model) else None
def active(): return config() is not None

# ---- "is the key good?": ONE small text-only request when the cloud settings are saved
def check(timeout=15):
    """-> {"ok": bool, "note": str}. No image, no card data. The provider's own text is never passed on."""
    cfg = config()
    if not cfg: return {"ok": False, "note": "Cloud reading is not set up yet (needs a key)."}
    base, model, key = cfg
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with the word OK."}], "temperature": 0, "max_tokens": 64, "reasoning_effort": "low"}
    try: out = post(base, "/chat/completions", body, key, timeout)
    except CloudError as e:
        if e.kind == "refused": return {"ok": False, "note": "The service refused the key."}
        if e.kind == "redirect": return {"ok": False, "note": "The service answered with a redirect. Check the web address."}
        if e.kind == "http": return {"ok": False, "note": f"The service answered with an error (HTTP {e.code}). Check the web address and the model name."}
        if e.kind == "format": return {"ok": False, "note": "The service answered, but not in the expected format."}
        return {"ok": False, "note": "Could not reach the service."}
    if not isinstance(out.get("choices"), list): return {"ok": False, "note": "The service answered, but not in the expected format."}
    return {"ok": True, "note": "OK: the cloud service accepted the key and the model."}
