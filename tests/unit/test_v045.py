"""v0.4.5 regression tests (bot reports qa/*-v044.md). Made-up cards only; files read as UTF-8; nothing from training/."""
import json, os, threading, time
from test_app import mk


def _user(env, name, role="reviewer"):
    from conftest import Client
    from app import main
    env["adm"].post("/api/admin/users", json={"username": name, "display": name.title() + " Tester", "password": "temp-pass-1234", "role": role})
    c = Client(main.app); assert c.post("/api/auth/login", json={"username": name, "password": "temp-pass-1234"}).status_code == 200
    return c


def _src(p): return open(p, encoding="utf-8").read()


def _uid(name):
    from app import auth
    return auth.db().execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]


# ---- #1 memory: one sqlite connection per thread, not one per call (they piled up into GBs under parallel requests)
def test_v045_db_connections_reused(env):
    from app import store
    a = store.db(); b = store.db(); assert a is b
    a.close(); assert store.db().execute("SELECT 1").fetchone()[0] == 1   # close() is a no-op on the shared one
    def fds(): return len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else 0
    ui = env["ui"]
    for i in range(5): mk(ui, env["store"], first_name=f"Fd{i}", last_name="Test", emails=[f"fd{i}@fd45.example.com"])
    f0 = fds()
    def work():
        for _ in range(3): env["rev"].get("/api/cards?status=pending")
    ts = [threading.Thread(target=work) for _ in range(4)]; [t.start() for t in ts]; [t.join() for t in ts]
    assert fds() - f0 < 40, (f0, fds())


def test_v045_session_cap(env, monkeypatch):
    from app import auth
    from conftest import Client
    from app import main
    _user(env, "cap45")
    for _ in range(auth.MAX_SESSIONS + 5):
        assert Client(main.app).post("/api/auth/login", json={"username": "cap45", "password": "temp-pass-1234"}).status_code == 200
    n = auth.db().execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (_uid("cap45"),)).fetchone()[0]
    assert n <= auth.MAX_SESSIONS


def test_v045_health_uptime_and_soak_bench():
    assert "uptime_s" in _src("app/main.py") and "_mem_watch" in _src("app/main.py")
    assert os.path.exists("bench/mem_soak.py")


# ---- #2 ONLY admins confirm ANY field; reviewer confirmations never count
def test_v045_admin_only_confirm_any_field(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Ivo", last_name="Rand", title="Vlce Pres|dent", emails=["ivo@rand45.example.com"])
    v0 = rev.get(f"/api/cards/{cid}").json()["version"]
    r = rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "title", "value": "Vlce Pres|dent", "version": v0, "reason": "on card"})
    assert r.status_code == 403
    meta = {"user": "rev", "by": "RR", "role": "reviewer", "reason": "on card", "value": json.dumps("Vlce Pres|dent")}
    f = {"first_name": "Ivo", "title": "Vlce Pres|dent", "confirmed_ok": {"title": json.dumps("Vlce Pres|dent")}, "confirmed_meta": {"title": meta}}
    assert "title" in ui.hard_errors(f)                                                  # an old reviewer confirmation is dropped
    assert "title" not in ui.hard_errors(dict(f, confirmed_meta={"title": dict(meta, role="admin")}))
    assert adm.post(f"/api/cards/{cid}/confirm-correct", json={"field": "title", "value": "Vlce Pres|dent", "version": v0, "reason": "on card"}).status_code == 200
    assert "Fix it, or ask an admin if the card is right." in _src("app/static/ui/views/review.js")


# ---- #3 merge only inside the current batch, whoever is signed in
def test_v045_merge_other_batch_refused_even_same_owner(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    me = _uid("rev"); ui.claim_batch("v45a", {"id": me}); ui.claim_batch("v45b", {"id": me})
    tgt = mk(ui, st, first_name="Kai", last_name="Lo", emails=["kl@v45m.example.com"]); ui.set_meta(tgt, batch="v45a", batch_label="v45a")
    src = mk(ui, st, first_name="Kai", last_name="Lo", company="Lo Co", emails=["kl@v45m.example.com"]); ui.set_meta(src, batch="v45b", batch_label="v45b")
    before = json.dumps(st.get(tgt)["fields"], sort_keys=True)
    for who in (rev, env["adm"]):
        r = who.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt})
        assert r.status_code >= 400 and r.json().get("need") == "merge_other_batch", r.text
    assert json.dumps(st.get(tgt)["fields"], sort_keys=True) == before


# ---- #6 Undo: current batch, recent, says what it undoes
def test_v045_undo_scoped_to_batch_and_recent(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = mk(ui, st, first_name="Una", last_name="Bee", emails=["ub@v45u.example.com"]); ui.set_meta(a, batch="v45u1", batch_label="U one")
    b = mk(ui, st, first_name="Vic", last_name="Cee", emails=["vc@v45u.example.com"]); ui.set_meta(b, batch="v45u2", batch_label="U two")
    assert rev.post(f"/api/cards/{a}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    assert rev.post(f"/api/cards/{b}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    assert rev.post("/api/undo", json={"batch": "v45u1"}).status_code == 200
    assert rev.post("/api/undo", json={"batch": "v45u1"}).status_code == 404   # nothing to undo in this batch (never the other batch)
    assert st.get(a)["status"] == "pending" and st.get(b)["status"] == "approved"   # the other batch's action was not touched
    with ui.db() as c: c.execute("UPDATE actions SET ts=? WHERE user_id=?", (time.time() - 3 * 3600, _uid("rev")))
    assert rev.post('/api/undo', json={}).status_code == 404   # POST never undoes outside the window
    assert rev.post("/api/undo", json={}).status_code == 404


# ---- #8 import file named; SUMMARY 'Why' real; merge note without misread values
def test_v045_readme_names_import_file_and_summary_why():
    s = _src("app/exporting.py")
    assert "Import only: {rfn}" in s and "NOT-FOR-IMPORT" in s   # v0.4.6 #7


def test_v045_merge_note_skips_misread_values(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    me = _uid("rev"); ui.claim_batch("v45n", {"id": me})
    tgt = mk(ui, st, first_name="Pia", last_name="Mo", title="Vice President", emails=["pm@v45n.example.com"])
    src = mk(ui, st, first_name="Pia", last_name="Mo", title="Vlce Pres|dent", emails=["pm@v45n.example.com"])
    for c in (tgt, src): ui.set_meta(c, batch="v45n", batch_label="v45n")
    r = rev.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt, "merge_keep": {"title": "tgt"}})
    assert r.status_code == 200, r.text
    assert "Pres|dent" not in (st.get(tgt).get("note") or "")


# ---- #9 reviewers see only their own batches; no other people's export file names
def test_v045_reviewer_batches_and_history_private(env):
    ui, st = env["ui"], env["store"]
    r1 = _user(env, "pa45"); _user(env, "pb45")
    ui.claim_batch("v45pa", {"id": _uid("pa45")}); ui.claim_batch("v45pb", {"id": _uid("pb45")})
    a = mk(ui, st, first_name="Ann", last_name="Pa", emails=["ap@v45p.example.com"]); ui.set_meta(a, batch="v45pa", batch_label="PA batch")
    b = mk(ui, st, first_name="Bob", last_name="Pb", emails=["bp@v45p.example.com"]); ui.set_meta(b, batch="v45pb", batch_label="PB batch")
    ui.log(b, "ZZ", "exported", detail={"file": "GAC-MCTrade-secret-PB.xlsx"})
    bl = {x["batch"] for x in r1.get("/api/batches").json()}
    assert "v45pa" in bl and "v45pb" not in bl
    assert "v45pb" in {x["batch"] for x in env["adm"].get("/api/batches").json()}
    assert r1.get(f"/api/cards/{b}").status_code == 404   # v0.4.6 #1: another person's card can't be opened at all
    assert "secret-PB" in json.dumps(env["adm"].get(f"/api/cards/{b}").json()["history"])


def test_v045_migrate_batch_owners(env):
    ui, st = env["ui"], env["store"]
    from app import auth
    ini = auth.db().execute("SELECT initials FROM users WHERE username='rev'").fetchone()[0]
    cid = mk(ui, st, first_name="Old", last_name="Batch", emails=["ob@v45o.example.com"], by=ini); ui.set_meta(cid, batch="v45old", batch_label="old")
    with ui.db() as c: c.execute("DELETE FROM batch_owners WHERE batch='v45old'")
    c = ui.db(); ui._migrate_batch_owners(c)
    assert ui.db().execute("SELECT user_id FROM batch_owners WHERE batch='v45old'").fetchone()[0] == _uid("rev")


# ---- #10 / reviewer b, c: small fixes
def test_v045_small_fixes():
    from app import postfix
    assert postfix.apply({"phones": [{"type": "mobile", "number": "(234)555-0153"}]})["phones"][0]["number"] == "(234) 555-0153"
    ex = _src("app/static/ui/views/export.js"); assert '"Summary"' in ex and "$$(\".tile\").forEach(t => t.disabled = true)" in ex
    assert ".capitalize()" not in _src("app/admin_files.py").split("def export_dryrun")[1].split("html_ =")[0]
    rv = _src("app/static/ui/views/review.js"); assert "Same = merge into" not in rv and "waitForAI.t" in rv
    assert "Approve as a new person?" not in rv


def test_v045_history_count_matches_ids():
    from app import audit_log
    t = audit_log._audit_text("cross_batch_confirmed", None, None, {"cards": [1, 2, 3, 4, 5, 6, 7], "kept": [1, 2, 3]})
    assert "marked different from 3 approved cards in other batches (#1, #2, #3)" in t and "#4, #5, #6, #7 may be the same person" in t


# ---- #11 admin contact placeholder (guides are private; the built help page is public)
def test_v045_help_has_admin_contact_line():
    assert "Your admin:" in _src("app/static/ui/help.html")
