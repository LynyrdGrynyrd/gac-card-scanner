"""v0.4.3 regression tests (bot reports qa/*-v042.md). Made-up cards only."""
import json, time
from test_app import mk


def _user(env, name):
    from conftest import Client
    from app import main
    env["adm"].post("/api/admin/users", json={"username": name, "display": name.title() + " Tester", "password": "temp-pass-1234"})
    c = Client(main.app); assert c.post("/api/auth/login", json={"username": name, "password": "temp-pass-1234"}).status_code == 200
    return c


# ---- #1 Undo is refused once the card was exported after the action
def test_v043_undo_refused_after_export(env):
    ui, st = env["ui"], env["store"]
    rv = _user(env, "undo43")
    from app import auth
    ini = auth.db().execute("SELECT initials FROM users WHERE username='undo43'").fetchone()[0]
    cid = mk(ui, st, first_name="Ulla", last_name="Nox", emails=["un@undo43.example.com"], by=ini); ui.set_meta(cid, batch="u43", batch_label="u43")
    assert rv.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    ui.log(cid, ini, "exported")
    r = rv.post("/api/undo", json={}); assert r.status_code == 409 and r.json()["need"] == "exported" and cid in r.json()["cards"]
    assert st.get(cid)["status"] == "approved"


# ---- #2 the server ends an idle session even with the tab closed; polling is not activity
def test_v043_server_idle_signout(env, monkeypatch):
    from app import auth
    c = _user(env, "idle43")
    monkeypatch.setenv("GAC_IDLE_MINUTES", "1")
    assert c.get("/api/me").status_code == 200
    db = auth.db(); now = time.time()
    with db: db.execute("UPDATE sessions SET last_active=? WHERE user_id=(SELECT id FROM users WHERE username='idle43')", (now - 50,))
    assert c.get("/api/counts").status_code == 200          # a background poll: allowed, but does not count
    la = db.execute("SELECT last_active FROM sessions WHERE user_id=(SELECT id FROM users WHERE username='idle43')").fetchone()[0]
    assert la < now - 40
    assert c.get("/api/counts", headers={"X-User-Active": "1"}).status_code == 200   # a click: counts
    la = db.execute("SELECT last_active FROM sessions WHERE user_id=(SELECT id FROM users WHERE username='idle43')").fetchone()[0]
    assert la >= now - 1
    with db: db.execute("UPDATE sessions SET last_active=? WHERE user_id=(SELECT id FROM users WHERE username='idle43')", (now - 90,))
    assert c.get("/api/me").status_code == 401
    assert not db.execute("SELECT 1 FROM sessions WHERE user_id=(SELECT id FROM users WHERE username='idle43')").fetchone()


def test_v043_idle_dialog_keeps_draft():
    src = open("app/static/ui/header.js").read()
    assert "kept as your draft" in src and "if (!window.gacIdleOut) clearDrafts()" in src
    assert "X-User-Active" in open("app/static/ui/core/api.js").read()


# ---- #3 History after 'Different'; Approve still knows about earlier exports
def test_v043_history_different_wording():
    from app import audit_log
    t = audit_log._audit_text("cross_batch_confirmed", None, None, {"cards": [17, 25, 30], "via": "none are the same person"})
    assert "may be the same person" not in t and "marked different from 3 cards" in t
    t = audit_log._audit_text("cross_batch_confirmed", None, None, {"cards": [17, 25], "via": "confirm", "kept": [25]})
    assert "#17 may be the same person" in t and "different from 1 card" in t


def test_v043_exported_elsewhere_kept_after_different(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = mk(ui, st, first_name="Kira", last_name="Dove", emails=["kd@v43x.example.com"]); ui.set_meta(a, batch="v43xa", batch_label="v43xa")
    assert rev.post(f"/api/cards/{a}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    ui.set_meta(a, exported=time.time()); ui.log(a, "RR", "exported")
    b = mk(ui, st, first_name="Kira", last_name="Dove", emails=["kd@v43x.example.com"]); ui.set_meta(b, batch="v43xb", batch_label="v43xb")
    ui.set_meta(b, kept_apart=json.dumps([a]), dup_resolution="keep_both")
    xe = rev.get(f"/api/cards/{b}").json()["exported_elsewhere"]
    assert [x["card_id"] for x in xe] == [a] and xe[0]["kept_apart"] is True


# ---- #4 possible MC Trade match: CSV Check note, preview/dry run list
def test_v043_mc_possible_in_summary_and_dryrun_code():
    src = open("app/exporting.py").read(); assert '"mc_possible"' in src and "_mcn" in src
    assert "NEEDS REVIEW before import" in open("app/admin_files.py").read()
    assert "Needs review (" in open("app/static/ui/views/export.js").read()


# ---- #5 'example' domains
def test_v043_example_rule(env):
    ui = env["ui"]
    he = lambda e, w="": ui.hard_errors({"first_name": "Ann", "emails": ["x@" + e], "website": w}).get("emails")
    for d in ("theperfectexample.com", "bestexample.com"): assert not he(d, d) and not he(d, "www." + d), d
    for d in ("goodyearheightsfamexample.com", "summitridgeanalytiexample.com"): assert he(d), d
    assert he("theperfectexample.com", "other.com")
    assert not he("akroncivicevents.example.com")


# ---- #6 merge: fuller value, per-field choice, nothing dropped silently
def test_v043_merge_pick_fuller(env):
    ui = env["ui"]
    t = {"first_name": "A", "address": "1 Main St, Akron", "emails": []}; s = {"first_name": "A", "address": "1 Main St, Suite 4, Akron, OH 44308", "emails": []}
    assert ui.merge_pick(t, s, "address") == "src"


def test_v043_merge_keeps_other_value_in_note(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    tgt = mk(ui, st, first_name="Mona", last_name="Ruiz", company="Ruiz Labs", emails=["mr@v43m.example.com"], phones=[{"type": "work", "number": "330-555-4301"}])
    src = mk(ui, st, first_name="Mona", last_name="Ruiz", company="Ruiz Analytics", emails=["mr@v43m.example.com"], phones=[{"type": "work", "number": "330-555-4301"}])
    for c in (tgt, src): ui.set_meta(c, batch="v43m", batch_label="v43m")
    r = rev.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt, "merge_keep": {"company": "tgt"}})
    assert r.status_code == 200, r.text
    t = st.get(tgt); assert t["fields"]["company"] == "Ruiz Labs" and "Ruiz Analytics" in (t.get("note") or "")


# ---- #7 staff may confirm with a reason
def test_v043_staff_confirm_everything():
    from app import ui
    assert ui.ADMIN_OVERRIDE == ()
    assert "Ask an admin to confirm" not in open("app/static/ui/views/review.js").read().replace("no \"Ask an admin\"", "")


# ---- #8 smaller fixes
def test_v043_upload_into_other_batch_refused(env):
    import io
    ui, st = env["ui"], env["store"]
    a = _user(env, "own43"); b = _user(env, "oth43")
    from app import auth
    uid = auth.db().execute("SELECT id FROM users WHERE username='own43'").fetchone()[0]
    ui.claim_batch("v43own", {"id": uid})
    r = b.post("/api/jobs", data={"batch": "v43own", "batch_label": "Own43"}, files={"image": ("x.jpg", io.BytesIO(b"\xff\xd8\xff" + b"0" * 100), "image/jpeg")})
    assert r.status_code == 403 and r.json()["need"] == "not_your_batch"
    assert ui.batch_owner_id("v43own") == uid


def test_v043_owner_by_user_id(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    from app import auth, exporting
    me = auth.db().execute("SELECT id, initials FROM users WHERE username='rev'").fetchone()
    ui.claim_batch("v43id", {"id": me[0]})
    assert not exporting._batch_refused("v43id", {"id": me[0], "initials": "ZZ", "role": "reviewer"})   # initials changed: still yours
    assert exporting._batch_refused("v43id", {"id": me[0] + 999, "initials": me[1], "role": "reviewer"})


def test_v043_export_history_own_only(env):
    from app import exporting
    ui = env["ui"]
    with ui.db() as c: c.execute("INSERT INTO exports(ts,username,initials,kind,filter,count,filename,card_ids) VALUES(?,?,?,?,?,?,?,?)", (time.time(), "adm", "AA", "csv", "approved", 1, "x.csv", "[1]"))
    assert all(x["username"] == "rev" for x in env["rev"].get("/api/exports").json())


def test_v043_frontend_small_fixes():
    rv = open("app/static/ui/views/review.js").read()
    assert "already exported `" not in rv and "AI check not finished" in rv and "waitForAI" in rv and "can_same" in rv
    up = open("app/static/ui/views/upload.js").read(); assert "conn.f >= 2" in up and "j.batch_label" in up
    assert 'id="helpNav" hidden' in open("training/build_help.py").read()
    assert "signs you out" in open("training/REVIEWER-GUIDE.md").read()


def test_v043_readme_more_notes_not_overcounted():
    src = open("app/exporting.py").read(); assert "_more = _flagged - _named" in src
