"""Round 6 features: phone mode (pairing token, upload-only LAN app, CSRF, rate limit, admin switch), update check,
AI queue ETA, field-subset VLM requests."""
import os, socket, time, json
import pytest
from fastapi.testclient import TestClient

HERE = os.path.dirname(__file__)
IMG = open(os.path.join(HERE, "..", "cards", "card1_left.jpg"), "rb").read()

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture
def phone(env, monkeypatch):
    from app import phone
    monkeypatch.setenv("PHONE_HOST", "127.0.0.1"); monkeypatch.setattr(phone, "PORT", _free_port())
    yield phone
    phone.revoke_all()

def _pair(env, phone):
    r = env["rev"].post("/api/phone/start", json={"batch_label": "Expo"}); assert r.status_code == 200, r.text
    j = r.json(); tok = j["url"].split("t=")[1]
    pc = TestClient(phone.phone_app, base_url=f"http://127.0.0.1:{phone.PORT}")
    return j, tok, pc

def _up(pc, phone, tok, data=IMG, csrf=True, origin=True, **kw):
    h = {}
    if origin: h["Origin"] = f"http://127.0.0.1:{phone.PORT}"
    if csrf: h["X-CSRF-Token"] = (pc.cookies.get("gac_phone_csrf") or "")
    files = {"image": ("front.jpg", data, "image/jpeg")}
    if kw.get("back"): files["back"] = ("back.jpg", kw["back"], "image/jpeg")
    return pc.post("/m/api/upload", files=files, data={"batch_label": kw.get("label", "")}, headers=h)

def test_pairing_starts_lan_listener_only_while_active(env, phone):
    j, tok, pc = _pair(env, phone)
    assert j["qr"].startswith("data:image/svg+xml;base64,") and j["port"] == phone.PORT and phone.running()
    s = socket.create_connection(("127.0.0.1", phone.PORT), timeout=2); s.close()     # really listening
    assert env["rev"].get("/api/phone/status").json()["active"]
    assert env["rev"].post("/api/phone/stop", json={}).json()["listening"] is False
    time.sleep(0.6)
    with pytest.raises(OSError): socket.create_connection(("127.0.0.1", phone.PORT), timeout=1)

def test_phone_page_token_moves_to_cookie_and_expired_refused(env, phone):
    j, tok, pc = _pair(env, phone)
    r = pc.get("/m?t=" + tok, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/m"
    assert "httponly" in r.headers.get("set-cookie", "").lower() and "samesite=strict" in r.headers.get("set-cookie", "").lower()
    assert pc.get("/m").status_code == 200 and "Send card" in pc.get("/m").text
    assert pc.get("/m/manifest.webmanifest").json()["start_url"] == "/m"
    assert pc.get("/m/sw.js").status_code == 200
    bad = TestClient(phone.phone_app); assert bad.get("/m?t=nope").status_code == 403
    for t, v in phone.TOKENS.items(): v["expires"] = time.time() - 1
    assert pc.get("/m/api/state").status_code == 401

def test_phone_upload_needs_csrf_and_origin_and_lands_in_queue(env, phone):
    j, tok, pc = _pair(env, phone); pc.get("/m?t=" + tok)
    assert _up(pc, phone, tok, csrf=False).status_code == 403
    assert _up(pc, phone, tok, origin=False).status_code == 403
    r = _up(pc, phone, tok, label="Expo night"); assert r.status_code == 200, r.text
    jid = r.json()["job"]
    for _ in range(300):
        st = env["rev"].get("/api/jobs?ids=" + jid).json()["jobs"][0]
        if st["state"] in ("done", "error"): break
        time.sleep(0.2)
    assert st["state"] == "done", st
    m = env["ui"].meta(st["card"]["id"]); assert m["batch_label"] == "Expo night" and m["batch"].startswith("phone-")
    h = env["ui"].history(st["card"]["id"]); assert h[0]["reviewer"] == env["rev"].get("/api/me").json()["initials"]
    assert pc.get("/m/api/jobs").json()["jobs"][0]["state"] == "done"
    assert _up(pc, phone, tok).status_code == 409          # same photo again -> duplicate check still applies

def test_phone_app_exposes_nothing_else(env, phone):
    j, tok, pc = _pair(env, phone); pc.get("/m?t=" + tok)
    for u in ("/api/cards", "/ui", "/api/admin/users", "/img/x.jpg", "/m/../api/cards", "/m/ui.js"):
        assert pc.get(u).status_code in (404, 405), u

def test_phone_rate_limit_and_bad_token_lockout(env, phone, monkeypatch):
    monkeypatch.setattr(phone, "RATE_PER_MIN", 1)
    j, tok, pc = _pair(env, phone); pc.get("/m?t=" + tok)
    assert _up(pc, phone, tok, data=b"not an image").status_code == 422
    assert _up(pc, phone, tok).status_code == 429
    phone._BAD.clear(); bad = TestClient(phone.phone_app)
    for _ in range(phone.BAD_PER_MIN + 1): bad.get("/m?t=guess")
    assert bad.get("/m/manifest.webmanifest").status_code == 429
    phone._BAD.clear()

def test_admin_can_disable_phone_mode(env, phone):
    j, tok, pc = _pair(env, phone)
    assert env["adm"].post("/api/admin/settings", json={"phone_mode_allowed": "0"}).status_code == 200
    try:
        assert not phone.TOKENS and not phone.running()
        assert env["rev"].post("/api/phone/start", json={}).status_code == 403
        assert env["rev"].get("/api/phone/status").json()["allowed"] is False
    finally: env["adm"].post("/api/admin/settings", json={"phone_mode_allowed": "1"})
    assert env["rev"].post("/api/admin/settings", json={"phone_mode_allowed": "0"}).status_code == 403   # reviewers can't

def test_phone_status_requires_sign_in(env):
    from app import main
    assert TestClient(main.app).post("/api/phone/start", json={}, headers={"Origin": "http://testserver"}).status_code == 401

def test_update_check(env, monkeypatch):
    from app import updates
    assert updates.newer("v0.2.0", "0.1.0") and not updates.newer("v0.1.0", "0.1.0") and updates.newer("0.1.0", "0.1.0-rc1") and not updates.newer("garbage", "0.1.0")
    class R:
        def __init__(s, b): s.b = b
        def read(s): return s.b
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout=5: R(json.dumps({"tag_name": "v9.0.0", "name": "Big", "html_url": "https://github.com/LynyrdGrynyrd/gac-card-scanner/releases/tag/v9.0.0"}).encode()))
    updates.check(); u = env["rev"].get("/api/update").json()
    assert u["update_available"] and u["url"].startswith("https://github.com/") and u["latest"] == "v9.0.0"
    env["adm"].post("/api/admin/settings", json={"update_check_enabled": "0"})
    try: assert env["rev"].get("/api/update").json()["update_available"] is False
    finally: env["adm"].post("/api/admin/settings", json={"update_check_enabled": "1"})
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout=5: R(json.dumps({"tag_name": "v9.1.0", "html_url": "javascript:alert(1)"}).encode()))
    updates.check(); assert env["rev"].get("/api/update").json()["url"] is None
    updates.STATE.update(latest=None, url=None)

def test_ai_queue_eta(env):
    ui = env["ui"]
    from test_app import mk
    c1, c2 = mk(ui, env["store"]), mk(ui, env["store"])   # round 14: only cards that will really be checked are counted
    ui.AI_TIMES[:] = [20, 20]; ui.AI_WAIT.clear(); ui.AI_WAIT[c1] = (1, 1); ui.AI_WAIT[c2] = (1, 2); ui.AI_RUNNING.update(cid=5, since=time.time() - 5)
    try:
        # audit 2026-10 (Windows CI): 'running for 5 s' can read 6 s on a slow runner (rounded), so the ETA may be 1 s less
        p = ui.ai_progress(c2); assert p["position"] == 2 and p["ahead"] == 1 and p["eta_seconds"] in (20 + 15 + 20, 20 + 14 + 20)
        q = env["rev"].get("/api/ai/status").json()["queue"]; assert q["waiting"] == 2 and q["running"] == 1 and q["eta_seconds"] in (55, 54)
    finally: ui.AI_WAIT.clear(); ui.AI_RUNNING.clear(); ui.AI_TIMES.clear()

def test_vlm_field_subset():
    from app import vlm
    assert vlm.keys_for(["overall"]) is None and vlm.keys_for(["requested"]) is None
    k = vlm.keys_for(["name"], {"company": "A", "title": "B", "emails": ["x@y.z"], "phones": [{}], "website": "w", "address": "a", "department": "d"})
    assert k == ["first_name", "last_name"]
    s = vlm._schema(k); assert set(s["properties"]) == set(k) == set(s["required"])

# ---------------------------------------------------------------- merge R7 + features
def test_merge_phone_upload_rechecks_user_and_validates_back(env, phone):
    from app import auth
    j, tok, pc = _pair(env, phone); pc.get("/m?t=" + tok)
    r = _up(pc, phone, tok, data=open(os.path.join(HERE, "..", "cards", "card2_center.jpg"), "rb").read(), back=b"not an image" * 40)
    assert r.status_code == 422 and r.json()["error"].startswith("Back photo")       # shared image checks on the back too
    assert _up(pc, phone, tok, data=b"junk" * 100).status_code == 422                # and on the front
    uid = env["rev"].get("/api/me").json()["id"]
    with auth.db() as c: c.execute("UPDATE users SET active=0 WHERE id=?", (uid,))
    try: assert _up(pc, phone, tok).status_code == 401 and not phone.TOKENS              # deactivated user: pairing dies
    finally:
        with auth.db() as c: c.execute("UPDATE users SET active=1 WHERE id=?", (uid,))

def test_merge_vlm_long_prompt_default_keeps_r7_hints(monkeypatch):
    from app import vlm
    monkeypatch.delenv("VLM_PROMPT", raising=False)
    p = vlm._prompt_for(["company"], "ACME", "company looks like a person's name")
    assert p.startswith("You are reading a business card") and "company looks like a person's name" in p
    assert "verify these" not in vlm._prompt_for(None, "x", "")
    import inspect; assert inspect.signature(vlm.extract).parameters["timeout"].default == int(os.getenv("VLM_TIMEOUT", "240"))
