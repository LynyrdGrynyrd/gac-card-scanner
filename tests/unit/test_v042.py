"""v0.4.2 regression tests (bot reports qa/*-v041.md). Made-up cards only."""
import io, json, csv
from test_app import mk


# ---- #1 export rights on the server
def test_v042_reviewer_exports_only_own_batch(env):
    from conftest import Client
    from app import main
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    adm.post("/api/admin/users", json={"username": "rev42", "display": "Rex Fortytwo", "password": "temp-pass-1234"})
    rev2 = Client(main.app); assert rev2.post("/api/auth/login", json={"username": "rev42", "password": "temp-pass-1234"}).status_code == 200
    cid = mk(ui, st, first_name="Own", last_name="Batch", emails=["ob@v042own.example.com"]); ui.set_meta(cid, batch="v042own", batch_label="Own")
    st.update(cid, status="approved", reviewer="RR")
    for path in ("/api/export/check", "/api/export/summary", "/api/export/csv", "/api/export/dryrun"):
        assert rev2.get(path, params={"status": "approved_new", "batch": "v042own", "_nov": 1}).status_code == 403, path
        assert rev2.get(path, params={"status": "approved_new", "_nov": 1}).status_code == 403, path        # all batches
        assert rev2.get(path, params={"status": "approved_new", "batch": "__none__", "_nov": 1}).status_code == 403, path
    assert rev.get("/api/export/check", params={"status": "approved_new", "batch": "v042own"}).status_code == 200
    assert adm.get("/api/export/check", params={"status": "approved_new", "batch": "v042own"}).status_code == 200
    assert adm.get("/api/export/check", params={"status": "approved_new"}).status_code == 200



def _appr(ui, st, rev, batch, **f):
    c = mk(ui, st, **f); ui.set_meta(c, batch=batch, batch_label=batch)
    assert rev.post(f"/api/cards/{c}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    return c


# ---- #3 'Different' clears the double-import text in the CSV and the READ-ME
def test_v042_different_clears_double_import_in_csv(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = _appr(ui, st, rev, "v42dif", first_name="Lena", last_name="Voss", emails=["lv@v42dif.example.com"])
    ui.log(a, "RR", "cross_batch_confirmed", detail={"cards": [999998]})
    txt = lambda: rev.get("/api/export/csv?status=approved_new&batch=v42dif&preview=1").content.decode("utf-8-sig")
    assert "double import" in txt()
    ui.set_meta(a, kept_apart=json.dumps([999998]))
    assert "double import" not in txt()


# ---- #4 one count source: page line = sheet = batch list
def test_v042_counts_agree(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = _appr(ui, st, rev, "v42cnt", first_name="Ira", last_name="Bloom", emails=["ib@v42cnt.example.com"])
    b = _appr(ui, st, rev, "v42cnt", first_name="Una", last_name="Pell", emails=["up@v42cnt.example.com"])
    ui.set_meta(b, override=json.dumps({"by": "RR", "reason": "checked"}))   # approved anyway (soft): was counted on the page only
    ui.set_meta(a, exported="")          # an empty 'exported' value: the SQL rule said "0 ready", the export said 2
    chk = rev.get("/api/export/check?status=approved_new&batch=v42cnt").json()
    s = rev.get("/api/export/summary?status=approved_new&batch=v42cnt").json()
    assert sorted(chk["flagged"]) == s["check_ids"], (chk["flagged"], s)
    bl = [x for x in rev.get("/api/batches").json() if x["batch"] == "v42cnt"][0]
    assert bl["ready"] == chk["count"] == 2


# ---- #7 the lost-dot rule allows whole words before 'example'
def test_v042_lost_dot_whole_words(env):
    ui = env["ui"]
    he = lambda d: ui.hard_errors({"first_name": "Ann", "emails": ["x@" + d], "website": d}).get("emails")   # v0.4.3 #5: needs the website too
    for ok in ("theperfectexample.com", "bestexample.com", "counterexample.org", "simplyexample.net"): assert not he(ok), ok
    for bad in ("firestoneparkhardwexample.com", "acmecomcom.com"): assert he(bad), bad


# ---- #10 public help, build info in /health
def test_v042_help_public_and_health_build_info(env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, updates
    anon = TestClient(main.app)
    r = anon.get("/help", follow_redirects=False); assert r.status_code == 307 and r.headers["location"] == "/static/ui/help.html"
    assert anon.get("/ui/help", follow_redirects=False).status_code == 307
    assert anon.get("/static/ui/help.html").status_code == 200
    monkeypatch.setattr(updates, "_BUILD", {"public_commit": "abc1234", "tag": "v0.4.2"})
    h = anon.get("/health").json(); assert h["commit"] == "abc1234" and "public_commit" not in h and h["tag"] == "v0.4.2"


# ---- #11 skeptic lows
def test_v042_merge_replay_refused_no_double_note(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    t = mk(ui, st, first_name="Avery", last_name="Stone", emails=["as@v42rp.example.com"], title="Owner"); ui.set_meta(t, batch="v42rp")
    s = mk(ui, st, first_name="Avery", last_name="Stone", emails=["as@v42rp.example.com"], title="Regional Owner"); ui.set_meta(s, batch="v42rp")
    assert rev.post(f"/api/cards/{s}", json={"status": "rejected", "merge_into": t, "card_id": s}).status_code == 200
    n1 = st.get(t)["note"]
    r = rev.post(f"/api/cards/{s}", json={"status": "rejected", "merge_into": t, "card_id": s, "confirm_redecide": True})
    assert r.status_code == 409 and r.json()["need"] == "merge_done"
    assert st.get(t)["note"] == n1


def test_v042_no_scan_record_is_not_same_scanner(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = mk(ui, st, first_name="Quinn", last_name="Hale", emails=["qh@v42ns.example.com"], by="")
    b = mk(ui, st, first_name="Quinn", last_name="Hale", emails=["qh@v42ns.example.com"], by="")
    r = rev.post(f"/api/cards/{a}", json={"status": "rejected", "merge_into": b, "card_id": a})
    assert r.status_code == 422 and r.json()["need"] == "merge_other_user"
    d = rev.get(f"/api/cards/{a}").json()
    assert not any(x["same_user"] for x in d["dupes"]["queue"] if x["card_id"] == b)
