"""Public demo mode (GAC_DEMO=1): banner, shared login, caps, preview-only exports, wipe + re-seed, no visitor audit.
Runs against its own temporary DB and data folders so it never touches the other tests' state or data/."""
import io, os, time, pytest
from conftest import Client

@pytest.fixture()
def demo(tmp_path, monkeypatch):
    from app import store, ui, demo as D, main
    monkeypatch.setattr(store, "DB", str(tmp_path / "demo.db"))
    for k in ("UP", "EXP", "THUMBS", "INBOX", "DONE"):
        d = tmp_path / k; d.mkdir(); monkeypatch.setattr(ui, k, str(d))
    monkeypatch.setenv("GAC_DEMO", "1"); monkeypatch.setenv("GAC_DEMO_MAX_MB", "1"); monkeypatch.setenv("GAC_DEMO_MAX_CARDS", "14")
    monkeypatch.setenv("GAC_DEMO_SEED", "12")
    from app import auth; auth.set_setting("corrections_enabled", "0")
    D.ensure_user(); n = D.wipe()
    c = Client(main.app)
    r = c.post("/api/auth/login", json={"username": D.user(), "password": D.password()}); assert r.status_code == 200, r.text
    return {"c": c, "D": D, "n": n, "ui": ui, "store": store, "tmp": tmp_path, "main": main}

def test_seeded_synthetic_cards_only(demo):
    assert demo["n"] == 12
    cards = demo["store"].all_()
    assert len(cards) == 12 and all(c["engine"] == "demo-seed" for c in cards)
    assert all("555" in "".join(p["number"] for p in c["fields"]["phones"]) for c in cards if c["fields"].get("phones"))
    assert len(os.listdir(demo["ui"].UP)) == 12

def test_banner_and_shared_login_shown(demo):
    anon = Client(demo["main"].app)
    lp = anon.get("/login").text
    assert "Public demo" in lp and demo["D"].user() in lp and demo["D"].password() in lp
    assert "Public demo" in demo["c"].get("/ui").text
    assert anon.get("/api/demo").json()["demo"] is True

def test_admin_setup_and_password_change_refused(demo):
    c = demo["c"]
    assert c.post("/api/me/password", json={"old": demo["D"].password(), "new": "x" * 20}).status_code == 403
    assert c.post("/api/admin/users", json={"username": "evil", "display": "E", "password": "p" * 12}).status_code == 403
    assert c.post("/api/auth/setup", json={"username": "x", "display": "x", "password": "p" * 12}).status_code == 403
    assert c.get("/api/me").json()["role"] == "reviewer"

def test_upload_size_and_count_caps(demo):
    c = demo["c"]
    big = b"\xff\xd8" + b"0" * (1024 * 1024 + 10)
    r = c.post("/api/jobs", files={"image": ("big.jpg", io.BytesIO(big), "image/jpeg")}); assert r.status_code == 413
    for i in range(2): demo["store"].add("t", "", {"first_name": "Filler"}, "")
    small = open(os.path.join(os.path.dirname(__file__), "..", "cards", "card1_left.jpg"), "rb").read()
    r = c.post("/api/jobs", files={"image": ("c.jpg", io.BytesIO(small), "image/jpeg")}); assert r.status_code == 429, r.text

def test_exports_are_preview_only(demo):
    c = demo["c"]; ui = demo["ui"]; st = demo["store"]
    card = st.all_()[0]; cid = card["id"]; st.update(cid, status="approved", reviewer="DEMO")
    b = (ui.meta(cid) or {}).get("batch") or "__none__"   # since r15 a reviewer exports/previews one batch at a time
    for kind in ("xlsx", "csv"):
        r = c.get(f"/api/export/{kind}?status=approved&batch={b}")
        assert r.status_code == 200, r.text
        assert r.headers.get("X-Preview") == "1" and "PREVIEW-" in r.headers["Content-Disposition"]
    assert os.listdir(ui.EXP) == []
    assert ui.db().execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert not (ui.meta(cid) or {}).get("exported")

def test_no_visitor_ip_recorded(demo):
    from app import auth
    rows = auth.db().execute("SELECT ip FROM auth_log").fetchall() + auth.db().execute("SELECT ip FROM sessions").fetchall()
    assert rows and all(not r[0] for r in rows)
    assert auth.get_setting("corrections_enabled") == "0"

def test_wipe_removes_uploads_and_reseeds(demo):
    D, st, ui = demo["D"], demo["store"], demo["ui"]
    open(os.path.join(ui.UP, "visitor.jpg"), "wb").write(b"x"); st.add("t", "", {"first_name": "Visitor"}, "visitor.jpg")
    open(os.path.join(ui.EXP, "x.csv"), "w").write("x")
    assert D.wipe() == 12
    assert not any(c["fields"].get("first_name") == "Visitor" for c in st.all_())
    assert "visitor.jpg" not in os.listdir(ui.UP) and os.listdir(ui.EXP) == []
    assert len(st.all_()) == 12

def test_demo_off_by_default(monkeypatch):
    from app import demo as D
    monkeypatch.delenv("GAC_DEMO", raising=False); assert not D.enabled()
