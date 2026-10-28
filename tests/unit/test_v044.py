"""v0.4.4 regression tests (bot reports qa/*-v043.md). Made-up cards only; files read as UTF-8; nothing from training/."""
import json
from test_app import mk


def _user(env, name):
    from conftest import Client
    from app import main
    env["adm"].post("/api/admin/users", json={"username": name, "display": name.title() + " Tester", "password": "temp-pass-1234"})
    c = Client(main.app); assert c.post("/api/auth/login", json={"username": name, "password": "temp-pass-1234"}).status_code == 200
    return c


def _src(p): return open(p, encoding="utf-8").read()


# ---- user decision: only admins confirm email / website / address
def test_v044_only_admin_confirms(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Ada", last_name="Cole", emails=["ada@colelaws.com"], website="colelaw.com")
    v0 = rev.get(f"/api/cards/{cid}").json()["version"]
    r = rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "emails", "value": ["ada@colelaws.com"], "version": v0, "reason": "on card"})
    assert r.status_code == 403 and "An admin needs to confirm this." in r.text
    assert adm.post(f"/api/cards/{cid}/confirm-correct", json={"field": "emails", "value": ["ada@colelaws.com"], "version": v0, "reason": "on card"}).status_code == 200
    assert "An admin needs to confirm this." in _src("app/static/ui/views/review.js")


# ---- #1 merge never writes into another person's card or batch
def test_v044_merge_into_other_users_batch_refused(env):
    ui, st = env["ui"], env["store"]
    a = _user(env, "mrga44"); b = _user(env, "mrgb44")
    from app import auth
    ida = auth.db().execute("SELECT id FROM users WHERE username='mrga44'").fetchone()[0]
    idb = auth.db().execute("SELECT id FROM users WHERE username='mrgb44'").fetchone()[0]
    ui.claim_batch("v44a", {"id": ida}); ui.claim_batch("v44b", {"id": idb})
    tgt = mk(ui, st, first_name="Nia", last_name="Park", emails=["np@v44m.example.com"]); ui.set_meta(tgt, batch="v44a", batch_label="v44a")
    src = mk(ui, st, first_name="Nia", last_name="Park", company="Park Co", emails=["np@v44m.example.com"]); ui.set_meta(src, batch="v44b", batch_label="v44b")
    before = json.dumps(st.get(tgt)["fields"], sort_keys=True)
    r = b.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt})
    assert r.status_code in (403, 409, 422) and r.json().get("need") in ("merge_other_user", "merge_other_batch", "merge_missing"), r.text   # v0.4.6: another person's card is "not found"
    assert json.dumps(st.get(tgt)["fields"], sort_keys=True) == before and st.get(src)["status"] != "rejected"


# ---- #2 every value not kept goes to the note (address too)
def test_v044_merge_unkept_address_to_note(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    from app import auth
    me = auth.db().execute("SELECT id FROM users WHERE username='rev'").fetchone()[0]
    ui.claim_batch("v44n", {"id": me})
    tgt = mk(ui, st, first_name="Ola", last_name="Bem", emails=["ob@v44n.example.com"], address="1 Main St, Akron, OH 44308")
    src = mk(ui, st, first_name="Ola", last_name="Bem", emails=["ob@v44n.example.com"], address="9 Oak Ave, Kent, OH 44240")
    for c in (tgt, src): ui.set_meta(c, batch="v44n", batch_label="v44n")
    r = rev.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt, "merge_keep": {"address": "tgt"}})
    assert r.status_code == 200, r.text
    assert "9 Oak Ave" in (st.get(tgt).get("note") or "")
    assert "Goes to note" in _src("app/static/ui/views/review.js")


# ---- #3 one 'To check' number
def test_v044_one_to_check_wording(env):
    ui = env["ui"]
    from app import mctrade_export as MX
    cnt = MX.counts({1: (MX.NEW, ""), 2: (MX.REVIEW, ""), 3: (MX.REVIEW, "")})
    assert "2 to decide" in ui.readme_totals(cnt) and "To check: 2 of the rows" in ui.readme_totals(cnt, to_check=2)
    af = _src("app/admin_files.py"); assert "TO CHECK" in af and "NEEDS REVIEW 0" not in af
    assert "May already be in MC Trade" in _src("app/static/ui/views/review.js") and "May already be in MC Trade" in _src("app/static/ui/views/export.js")


# ---- #5 website / company auto-fixes are marked 'changed'
def test_v044_autofix_marked_changed():
    from app import pipeline
    f = pipeline.mark_read_changes({"website": "www.acme.com", "company": "Acme Widgets"}, "ACME\nAcmeWidgets\nwww .acme .com")
    assert "website" in f["auto_fixed"] and "company" in f["auto_fixed"]
    f = pipeline.mark_read_changes({"website": "www.acme.com", "company": "Acme Widgets"}, "Acme Widgets\nwww.acme.com")
    assert "website" not in f["auto_fixed"] and "company" not in f["auto_fixed"]
    assert "now_ === String(was).trim()" in _src("app/static/ui/views/review.js")


# ---- #6 / #9 export picker and badge
def test_v044_export_loading_and_badge():
    ex = _src("app/static/ui/views/export.js"); assert "seq" in ex and "Loading…" in ex
    assert "Loading…" in _src("app/static/ui/index.html")
    assert "reading`" in _src("app/static/ui/header.js")


# ---- #7 reject on an exported card explains itself
def test_v044_reject_exported_explains(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Pia", last_name="Lund", emails=["pl@v44r.example.com"])
    assert rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    ui.set_meta(cid, exported=1.0)
    r = rev.post(f"/api/cards/{cid}", json={"status": "rejected"})
    assert r.status_code == 409 and r.json()["need"] == "exported_reject" and "can't be rejected" in r.text
    assert st.get(cid)["status"] == "approved"


# ---- #8 summary workbook
def test_v044_summary_companion():
    from app import exporting
    assert "summary.xlsx" in exporting.COMPANION


# ---- #10 drafts on the server, for their owner only
def test_v044_server_draft(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    other = _user(env, "drf44")
    cid = mk(ui, st, first_name="Rae", last_name="Moss", emails=["rm@v44d.example.com"])
    assert rev.post(f"/api/cards/{cid}/draft", json={"vals": {"f_title": "Owner"}, "version": "x"}).status_code == 200
    assert rev.get(f"/api/cards/{cid}").json()["my_draft"]["vals"] == {"f_title": "Owner"}
    assert "my_draft" not in other.get(f"/api/cards/{cid}").json()
    assert rev.post(f"/api/cards/{cid}/draft", json={"vals": {"x": 5}}).status_code == 422
    assert rev.post(f"/api/cards/{cid}/draft", json={"vals": {}}).status_code == 200
    assert "my_draft" not in rev.get(f"/api/cards/{cid}").json()
    h = _src("app/static/ui/header.js"); assert "if (!window.gacIdleOut) clearDrafts()" not in h and "refreshUndo(); }" in h


def test_v044_jobs_pruned(env):
    import time
    ui = env["ui"]
    with ui.JLOCK: ui.JOBS["old44"] = {"id": "old44", "state": "done", "finished": time.time() - 9000}; ui.JOBS["new44"] = {"id": "new44", "state": "done", "finished": time.time()}
    ui._trim_mem()
    try: assert "old44" not in ui.JOBS and "new44" in ui.JOBS
    finally:
        with ui.JLOCK: ui.JOBS.pop("new44", None)


# ---- #11 signed-out help has no app menu; the version comes from the server
def test_v044_help_menu_and_version():
    h = _src("app/static/ui/help.html"); assert '<nav aria-label="Main"' not in h and "data-ver" in h
    import re
    v = _src("VERSION").strip(); assert set(re.findall(r"version (?:<span data-ver>)?(\d+\.\d+\.\d+)", h)) == {v}
    n = _src("app/static/ui/help-nav.js"); assert "/api/me" in n and "/health" in n


# ---- #12 no false 'one letter off' hint when the name is the misread part; Export line
def test_v044_no_false_letter_off():
    from app import plausibility as P
    assert not any(x["code"] == "email_name" for x in P.check({"first_name": "Morg4n", "last_name": "Raman", "emails": ["praman@fphealth.example.org"]}))
    assert "Preview doesn't." in _src("app/static/ui/index.html")


# ---- #13 pending-but-exported cards get the 'export it again' mark
def test_v044_repair_pending_exported(env):
    ui, st = env["ui"], env["store"]
    cid = mk(ui, st, first_name="Sol", last_name="Ng", emails=["sn@v44x.example.com"])
    ui.set_meta(cid, exported=1.0)
    c = ui.db(); ui._repair_pending_exported(c)
    assert ui.meta(cid).get("reexport")
    assert any(h["action"] == "reexport_needed" for h in ui.history(cid))
