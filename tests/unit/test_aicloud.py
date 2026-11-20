"""AICLOUD (2026-11-20): an admin can send card photos to a cloud model instead of the local one. OFF by default; nothing leaves
the computer unless an admin switches it on with the consent tick and a key. A stand-in HTTP server on 127.0.0.1 plays the
provider: no test ever calls a real service. Cards are the generated test cards."""
import json, os, stat, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CARD1 = os.path.join(ROOT, "tests", "cards", "card1_left.jpg")
KEY = "sk-test-0123456789abcdef"
RAW = "RAW-PROVIDER-TEXT"
ANS = {"first_name": "Maria", "last_name": "Delgado", "title": "Vice President, Commercial Lending", "company": "Summit Valley Bank", "department": "",
       "emails": ["mdelgado@summitvalleybank.com"], "phones": [], "website": "www.summitvalleybank.com", "address": "200 S Main St, Suite 400, Akron, OH 44308"}

class Stub(BaseHTTPRequestHandler):
    log = []; status = 200; raw = None   # log: every request that reaches the "provider": (path, headers, body); raw: a 200 answer sent as is
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)); self.log.append((self.path, dict(self.headers), body))
        if Stub.raw is not None and Stub.status == 200:
            self.send_response(200); self.send_header("Content-Length", str(len(Stub.raw))); self.end_headers(); self.wfile.write(Stub.raw); return
        out = json.dumps({"choices": [{"message": {"content": json.dumps(ANS)}}]} if Stub.status == 200 else {"error": RAW + " " + KEY}).encode()
        self.send_response(Stub.status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def do_GET(self):   # the local server's /health
        self.log.append((self.path, dict(self.headers), b"")); out = b'{"status": "ok"}'
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

class Other(Stub): log = []     # a second server that must never receive anything (a redirect target, a proxy)
class Redirect(BaseHTTPRequestHandler):
    target = ""
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(302); self.send_header("Location", Redirect.target + "/chat/completions"); self.send_header("Content-Length", "0"); self.end_headers()
    do_GET = do_POST

def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv, f"http://127.0.0.1:{srv.server_address[1]}"

@pytest.fixture(scope="module")
def provider():
    srv, url = _serve(Stub); yield url; srv.shutdown()
@pytest.fixture(scope="module")
def other():
    srv, url = _serve(Other); yield url; srv.shutdown()
@pytest.fixture(scope="module")
def redirector(other):
    srv, url = _serve(Redirect); Redirect.target = other; yield url; srv.shutdown()

@pytest.fixture(autouse=True)
def reset(env, monkeypatch):
    from app import auth, cloud
    import urllib.request as ur
    real = ur.OpenerDirector.open
    def only_here(self, req, *a, **k):   # a test can never reach a real service (every urlopen and every opener goes through here)
        url = req if isinstance(req, str) else req.full_url
        assert url.startswith("http://127.0.0.1"), "a test tried to call " + url
        return real(self, req, *a, **k)
    monkeypatch.setattr(ur.OpenerDirector, "open", only_here)
    Stub.log.clear(); Other.log.clear(); Stub.status = 200; Stub.raw = None
    yield
    for k, v in (("read_source", "local"), ("cloud_base_url", cloud.DEFAULT_BASE), ("cloud_model", cloud.DEFAULT_MODEL)): auth.set_setting(k, v)
    cloud.clear_key()

def turn_on(base, key=KEY, model="gemini-3.8-flash"):
    """Cloud on the way the Settings page does it (consent ticked, key typed)."""
    from app import auth, cloud
    auth.set_setting("read_source", "cloud"); auth.set_setting("cloud_base_url", base); auth.set_setting("cloud_model", model)
    if key: cloud.set_key(key)

def save(adm, **kw):
    cur = adm.get("/api/admin/settings").json()
    return adm.post("/api/admin/settings", json=kw | {"_seen": {k: v for k, v in cur.items() if not k.startswith("_")}})

def audit_text(adm): return json.dumps(adm.get("/api/admin/audit").json())

def test_off_by_default_and_cloud_off_is_the_local_request(env, provider, monkeypatch):
    from app import auth, cloud, vlm
    s = env["adm"].get("/api/admin/settings").json()
    assert s["read_source"] == "local" and s["cloud_key_set"] is False and s["cloud_base_url"].startswith("https://generativelanguage.googleapis.com") and s["cloud_model"] == "gemini-3.8-flash"
    assert not cloud.active() and not cloud.selected()
    auth.set_setting("cloud_base_url", provider); cloud.set_key(KEY)   # everything for the cloud is in place, but the source is "local"
    monkeypatch.setattr(vlm, "URL", provider + "/llama")   # a stand-in for llama-server
    out = vlm.extract(open(CARD1, "rb").read(), "OCR TEXT")
    path, hdr, raw = Stub.log[-1]; body = json.loads(raw)
    assert out["first_name"] == "Maria" and path == "/llama/v1/chat/completions" and len(Stub.log) == 1   # one request, to the local address
    assert body["cache_prompt"] is True and "model" not in body and "reasoning_effort" not in body and body["max_tokens"] == vlm.MAX_TOKENS
    assert "Authorization" not in hdr and KEY not in json.dumps(hdr)   # the cloud key is not sent to the local server
    assert vlm.available() is True and Stub.log[-1][0] == "/llama/health" and KEY not in json.dumps(Stub.log[-1][1])   # "available" asks the local server, not the cloud

def test_only_an_admin_can_change_the_cloud_settings(env, provider):
    from app import auth
    r = env["rev"].post("/api/admin/settings", json={"read_source": "cloud", "cloud_consent": True, "cloud_api_key": KEY, "_seen": {}})
    assert r.status_code == 403 and auth.get_setting("read_source") == "local"
    from app import cloud; assert not cloud.key_set() and env["rev"].get("/api/admin/settings").status_code == 403

def test_cloud_needs_the_consent_tick(env, provider):
    from app import auth, cloud
    adm = env["adm"]
    r = save(adm, read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY)   # no tick
    assert r.status_code == 422 and r.json()["need"] == "cloud_consent" and auth.get_setting("read_source") == "local" and not cloud.key_set() and not Stub.log
    r = save(adm, read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent=False); assert r.status_code == 422
    r = save(adm, read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent="true"); assert r.status_code == 422   # a real true only
    assert auth.get_setting("read_source") == "local"
    r = save(adm, read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent=True); assert r.status_code == 200, r.text
    assert auth.get_setting("read_source") == "cloud" and cloud.active()
    a = audit_text(adm); assert "Where cards are read: On this computer" in a and "Cloud service" in a and "cloud reading switched ON" in a and "API key set" in a and KEY not in a
    # pointing the service at another address needs the tick again; the same address does not
    r = save(adm, cloud_base_url=provider + "/v2"); assert r.status_code == 422 and r.json()["need"] == "cloud_consent" and auth.get_setting("cloud_base_url") == provider
    assert save(adm, cloud_base_url=provider + "/v2", cloud_consent=True).status_code == 200
    assert save(adm, read_source="local").status_code == 200 and not cloud.active()   # off needs no tick
    assert "On this computer" in audit_text(adm)

def test_the_key_is_never_returned_logged_or_shown(env, provider, capsys):
    from app import auth, cloud, vlm
    adm = env["adm"]; r = save(adm, read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent=True)
    texts = [r.text, adm.get("/api/admin/settings").text, env["rev"].get("/api/ai/status").text, adm.get("/api/ai/status").text, audit_text(adm)]
    with auth.db() as c: texts.append(json.dumps([list(x) for x in c.execute("SELECT * FROM auth_log")] + [list(x) for x in c.execute("SELECT * FROM settings")]))
    assert all(KEY not in t for t in texts)
    assert adm.get("/api/admin/settings").json()["cloud_key_set"] is True and "cloud_api_key" not in adm.get("/api/admin/settings").json()
    assert open(cloud.KEY_FILE).read() == KEY
    if os.name == "posix": assert stat.S_IMODE(os.stat(cloud.KEY_FILE).st_mode) == 0o600   # owner only
    bad = save(adm, cloud_api_key="has space and \n newline"); assert bad.status_code == 422 and "has space" not in bad.text   # refused, and not echoed
    assert cloud.get_key() == KEY
    # a provider error: calm text, no provider text, no key, nowhere (message, chained exception, console)
    Stub.status = 401
    with pytest.raises(vlm.CloudError) as e: vlm.extract(open(CARD1, "rb").read(), "x")
    assert str(e.value) == "cloud service answered HTTP 401" and e.value.__cause__ is None and e.value.__suppress_context__
    out = capsys.readouterr(); assert KEY not in out.out + out.err and RAW not in out.out + out.err
    assert save(adm, cloud_clear_key=True).status_code == 200 and not cloud.key_set() and not os.path.exists(cloud.KEY_FILE)
    assert "API key removed" in audit_text(adm) and KEY not in audit_text(adm)

def test_failed_check_in_the_ai_run_is_calm(env, provider, capsys):
    from app import vlm
    ui, st = env["ui"], env["store"]; turn_on(provider); Stub.status = 500
    cid, _ = ui.ingest(open(CARD1, "rb").read(), None, ".jpg", meta_kw={"batch": "cl", "batch_label": "BATCH-SECRET", "filename": "FILE-SECRET.jpg"})
    ui._ai_run(cid, ["read"]); m = ui.meta(cid); blob = m["ai_detail"] + capsys.readouterr().out
    assert m["ai_status"] in ("failed", "busy") and RAW not in blob and KEY not in blob and "HTTP 500" not in m["ai_detail"]

def test_the_cloud_request_carries_only_the_image_the_text_and_the_instructions(env, provider):
    from app import vlm
    ui = env["ui"]; turn_on(provider)
    cid, _ = ui.ingest(open(CARD1, "rb").read(), None, ".jpg", meta_kw={"batch": "cl2", "batch_label": "BATCH-SECRET", "filename": "FILE-SECRET.jpg"})
    ui.log(cid, "SECRETREVIEWER", "scanned", None, "pending", {"file": "FILE-SECRET.jpg"})
    ui._ai_run(cid, ["read"])
    reqs = [x for x in Stub.log if x[0] == "/chat/completions"]; assert reqs
    path, hdr, raw = reqs[0]; body = json.loads(raw)
    assert hdr["Authorization"] == "Bearer " + KEY and set(body) == {"model", "messages", "temperature", "max_tokens", "response_format", "reasoning_effort"}
    assert body["model"] == "gemini-3.8-flash" and body["temperature"] == 0 and body["reasoning_effort"] == "low" and body["max_tokens"] >= 2000 and "cache_prompt" not in body
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    parts = body["messages"][0]["content"]; assert [p["type"] for p in parts] == ["image_url", "text"] and parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "business card photo" in parts[1]["text"].lower() and "given name only" in parts[1]["text"]   # the app's prompt, with the OCR text
    for secret in ("BATCH-SECRET", "FILE-SECRET", "SECRETREVIEWER", "cl2"): assert secret not in raw.decode()
    assert vlm.CLOUD_TIMEOUT == 60

def test_available_in_cloud_mode_means_on_and_a_key_with_no_request(env, provider):
    from app import auth, cloud, vlm
    auth.set_setting("read_source", "cloud"); auth.set_setting("cloud_base_url", provider)
    assert vlm.available() is False and env["ui"].ai_available() is False   # no key yet
    cloud.set_key(KEY); assert vlm.available() is True and env["ui"].ai_available() is True
    assert not Stub.log   # never a provider call per card

def test_saving_the_cloud_settings_makes_one_text_only_check(env, provider):
    adm = env["adm"]; body = dict(read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent=True)
    r = save(adm, **body).json(); assert r["cloud_check"]["ok"] is True and r["cloud_check"]["note"].startswith("OK") and len(Stub.log) == 1
    path, hdr, raw = Stub.log[0]; assert path == "/chat/completions" and "image_url" not in raw.decode() and "business card" not in raw.decode().lower()   # text only
    assert save(adm, cloud_model="gemini-4-hydrogen").json()["cloud_check"]["ok"] and len(Stub.log) == 2   # a changed model is checked again
    assert "cloud_check" not in save(adm, cloud_model="gemini-4-hydrogen").json() and len(Stub.log) == 2   # nothing changed: no request
    Stub.status = 401; r = save(adm, cloud_model="x-model").json()
    assert r["cloud_check"] == {"ok": False, "note": "The service refused the key."} and r["cloud_model"] == "x-model"   # saved either way
    r = save(adm, cloud_base_url="http://127.0.0.1:1", cloud_consent=True).json()
    assert r["cloud_check"] == {"ok": False, "note": "Could not reach the service."} and r["cloud_base_url"] == "http://127.0.0.1:1"
    n = len(Stub.log); save(adm, read_source="local"); assert len(Stub.log) == n   # switching off asks nobody

def test_https_only(env, provider):
    from app import auth, cloud, vlm
    ok = ("https://api.example.com/v1", "https://api.example.com/v1/", "http://127.0.0.1:8081/v1")
    bad = ("http://api.example.com/v1", "http://localhost:8081/v1", "ftp://api.example.com", "https://user:pw@api.example.com/v1", "https://api.example.com/v1?key=1", "https://api.example.com/v1#x", "api.example.com", "")
    assert all(cloud.safe_base(u) for u in ok) and not any(cloud.safe_base(u) for u in bad)
    for u in bad:
        r = save(env["adm"], read_source="cloud", cloud_base_url=u, cloud_api_key=KEY, cloud_consent=True); assert r.status_code == 422, u
    assert auth.get_setting("read_source") == "local" and not cloud.key_set()
    turn_on("http://api.example.com/v1")   # even if a bad address got into the settings, no request is made
    assert not cloud.active() and vlm.available() is False
    with pytest.raises(vlm.CloudError): vlm.extract(open(CARD1, "rb").read(), "x")
    assert not Stub.log

def test_never_in_demo_mode(env, provider, monkeypatch):
    from app import cloud, demo, vlm
    monkeypatch.setattr(demo, "enabled", lambda: True)
    r = save(env["adm"], read_source="cloud", cloud_base_url=provider, cloud_api_key=KEY, cloud_consent=True); assert r.status_code == 403
    turn_on(provider)   # forced into the settings anyway
    assert not cloud.selected() and not cloud.active()
    monkeypatch.setattr(vlm, "URL", provider + "/llama"); vlm.extract(open(CARD1, "rb").read(), "x")
    assert [x[0] for x in Stub.log] == ["/llama/v1/chat/completions"]   # the local path, never the cloud one

def test_skip_the_ai_double_check_still_works_with_cloud_on(env, provider):
    ui = env["ui"]; turn_on(provider); jid = "c1c1c1c1c1c1"
    me = (env["rev"].get("/api/me").json().get("user") or {}).get("initials") or "RR"
    ui.JOBS[jid] = {"id": jid, "state": "queued", "file": "x.jpg", "batch": "clsk", "created": time.time(), "who": me}
    ui._run(jid, open(CARD1, "rb").read(), "auto", ".jpg", "clsk", None, "x.jpg", "sha-clsk", me, skip_ai=True)
    cid = ui.JOBS[jid]["card_id"]; assert ui.meta(cid)["ai_status"] == "skipped" and not Stub.log
    ui.JOBS.pop(jid, None)

def test_the_prompt_asks_for_the_given_name_only():
    from app import vlm
    assert "first_name is the given name only" in vlm.PROMPT and "middle initial" in vlm.PROMPT
    assert "given name only" in vlm.PROMPT_SHORT and "middle" in vlm.PROMPT_SHORT
    for mode in ("long", "short"):   # both prompt modes, with and without a field subset
        os.environ["VLM_PROMPT"] = mode
        try: assert all("given name" in vlm._prompt_for(k, "OCR", "") for k in (None, ["first_name", "last_name"]))
        finally: os.environ.pop("VLM_PROMPT", None)

def test_the_key_file_is_not_in_a_backup(env, tmp_path):
    import sqlite3, tarfile
    from app import backup
    data = tmp_path / "data"; (data / "cloud").mkdir(parents=True); (data / "uploads").mkdir()
    (data / "cloud" / "api-key").write_text(KEY); (data / "uploads" / "p.jpg").write_bytes(b"photo")
    db = data / "cards.db"; c = sqlite3.connect(db); c.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY)"); c.commit(); c.close()
    t = tarfile.open(backup.make(dest=str(tmp_path / "bk"), data=str(data), db=str(db)))
    assert "data/uploads/p.jpg" in t.getnames() and not [n for n in t.getnames() if "cloud" in n or "api-key" in n]


# ---- outside review round 1 (2026-11-20)
def test_k1_a_redirect_never_hands_the_key_to_another_address(env, provider, other, redirector):
    from app import cloud, vlm
    r = save(env["adm"], read_source="cloud", cloud_base_url=redirector, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent=True).json()
    assert r["cloud_check"] == {"ok": False, "note": "The service answered with a redirect. Check the web address."}   # not "OK" from the other host
    with pytest.raises(vlm.CloudError) as e: vlm.extract(open(CARD1, "rb").read(), "x")
    assert str(e.value) == "cloud service answered with a redirect" and e.value.kind == "redirect"
    assert Other.log == [] and Stub.log == []   # the second server saw nothing: no request, no Authorization header

def test_k2_loopback_never_goes_through_a_proxy(env, provider, other, monkeypatch):
    from app import vlm
    for k in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"): monkeypatch.setenv(k, other)   # the "proxy" is another stand-in
    for k in ("no_proxy", "NO_PROXY"): monkeypatch.delenv(k, raising=False)
    turn_on(provider); out = vlm.extract(open(CARD1, "rb").read(), "x")
    assert out["first_name"] == "Maria" and len(Stub.log) == 1 and Other.log == []   # straight to the address, the proxy saw nothing

def test_k3_any_new_address_needs_the_tick_and_config_is_one_read(env, provider, monkeypatch):
    from app import auth, cloud
    adm = env["adm"]; assert auth.get_setting("read_source") == "local"
    r = save(adm, cloud_base_url=provider + "/v9"); assert r.status_code == 422 and r.json()["need"] == "cloud_consent"   # cloud is OFF: a new address still needs the tick
    assert auth.get_setting("cloud_base_url") != provider + "/v9"
    r = save(adm, read_source="local", cloud_base_url=provider + "/v9", cloud_consent=False); assert r.status_code == 422
    assert save(adm, cloud_base_url=provider + "/v9", cloud_consent=True).status_code == 200 and auth.get_setting("cloud_base_url") == provider + "/v9"
    turn_on(provider); monkeypatch.setattr(auth, "get_setting", lambda k: (_ for _ in ()).throw(AssertionError("per-setting read")))
    assert cloud.config() == (provider, "gemini-3.8-flash", KEY) and cloud.selected()   # source, address and model come from one read

def test_k4_the_key_file_goes_first_and_a_failure_saves_nothing(env, provider, monkeypatch):
    from app import auth, cloud
    adm = env["adm"]; body = dict(read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent=True)
    audit0 = audit_text(adm)
    real_replace = os.replace; monkeypatch.setattr(cloud.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    r = save(adm, **body); assert r.status_code == 500 and "Nothing was saved" in r.json()["error"] and KEY not in r.text
    assert auth.get_setting("read_source") == "local" and not cloud.key_set() and not os.path.exists(cloud.KEY_FILE + ".tmp") and audit_text(adm) == audit0 and not Stub.log
    monkeypatch.setattr(cloud.os, "replace", real_replace); assert save(adm, **body).status_code == 200 and cloud.key_set()
    audit1 = audit_text(adm)   # removing: the file operation fails, the key stays and so do the settings
    monkeypatch.setattr(cloud.os, "remove", lambda p: (_ for _ in ()).throw(PermissionError("no")))
    r = save(adm, cloud_clear_key=True, read_source="local"); assert r.status_code == 500 and cloud.key_set() and auth.get_setting("read_source") == "cloud" and audit_text(adm) == audit1
    monkeypatch.undo(); cloud.clear_key(); cloud.clear_key()   # "no key file" is not an error

def test_k5_no_query_or_fragment_not_even_an_empty_one_and_the_audit_names_only_the_host(env, provider):
    from app import auth, cloud
    for u in ("https://api.example.com/v1?", "https://api.example.com/v1#", "https://api.example.com/v1?key=1", "https://api.example.com/v1/#x", "https://api.example.com?"):
        assert cloud.safe_base(u) is None, u
        assert save(env["adm"], cloud_base_url=u, cloud_consent=True).status_code == 422, u
    assert save(env["adm"], read_source="cloud", cloud_base_url=provider + "/v1/PATHMARK", cloud_api_key=KEY, cloud_consent=True).status_code == 200
    a = audit_text(env["adm"]); assert "127.0.0.1" in a and "PATHMARK" not in a and KEY not in a
    assert "must not contain your key" in open(os.path.join(ROOT, "app", "static", "ui", "index.html"), encoding="utf-8").read()

@pytest.mark.parametrize("raw", [b'{"hello": 1}', b'not json', b'[1, 2]', b'{"choices": "x"}'])
def test_k6_ok_only_for_a_reply_with_a_choices_list(env, provider, raw):
    Stub.raw = raw
    r = save(env["adm"], read_source="cloud", cloud_base_url=provider, cloud_model="gemini-3.8-flash", cloud_api_key=KEY, cloud_consent=True).json()
    assert r["cloud_check"] == {"ok": False, "note": "The service answered, but not in the expected format."} and r["read_source"] == "cloud"   # saved anyway
    Stub.raw = None; assert save(env["adm"], cloud_model="gemini-4-hydrogen").json()["cloud_check"]["ok"] is True
