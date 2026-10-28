"""v0.4.6 regression tests (bot reports qa/*-v045.md). Made-up cards only."""
import json, os, time
import pytest
from test_app import mk
from test_v045 import _user, _uid, _src


def _two(env, tag):
    """Reviewer A (own batch) and reviewer B (another batch with a look-alike of A's card)."""
    ui, st = env["ui"], env["store"]
    ca = _user(env, f"pa{tag}"); cb = _user(env, f"pb{tag}")
    ui.claim_batch(f"{tag}a", {"id": _uid(f"pa{tag}")}); ui.claim_batch(f"{tag}b", {"id": _uid(f"pb{tag}")})
    a = mk(ui, st, first_name="Nora", last_name="Quill", emails=[f"nq@{tag}.example.com"], by=""); ui.set_meta(a, batch=f"{tag}a", batch_label="A batch")
    b = mk(ui, st, first_name="Nora", last_name="Quill", emails=[f"nq@{tag}.example.com"], by=""); ui.set_meta(b, batch=f"{tag}b", batch_label="Secret B batch")
    return ca, cb, a, b


# ---- #1 reviewer privacy, enforced on the server
def test_v046_privacy_every_card_path_refused(env):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    ca, cb, a, b = _two(env, "v46p")
    os.makedirs(ui.UP, exist_ok=True)
    for nm in ("v46p-front.jpg", "v46p-back.jpg"): open(os.path.join(ui.UP, nm), "wb").write(b"\xff\xd8\xff\xd9")
    with ui.db() as c: c.execute("UPDATE cards SET image='v46p-front.jpg' WHERE id=?", (b,))
    ui.set_meta(b, back_image="v46p-back.jpg")
    v = adm.get(f"/api/cards/{b}").json()["version"]
    assert ca.get(f"/api/cards/{a}").status_code == 200
    calls = [ca.get(f"/api/cards/{b}"), ca.post(f"/api/cards/{b}", json={"fields": {"title": "x"}, "version": v}),
             ca.post(f"/api/cards/{b}", json={"status": "approved", "version": v}),
             ca.post(f"/api/cards/{b}/draft", json={"fields": {"title": "x"}}), ca.post(f"/api/cards/{b}/merge-preview", json={"into": a}),
             ca.post(f"/api/cards/{b}/ai-check", json={}), ca.post(f"/api/cards/{b}/ai-decide", json={"choices": {}}),
             ca.post(f"/api/cards/{b}/confirm-correct", json={"field": "title", "value": "x", "reason": "printed like this"}),
             ca.post(f"/api/cards/{b}/needs-admin", json={}), ca.post(f"/api/cards/{b}/back", files={"image": ("x.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}),
             ca.get("/img/v46p-front.jpg"), ca.get("/img/v46p-back.jpg")]
    assert [r.status_code for r in calls] == [404] * len(calls), [(r.status_code, r.text[:60]) for r in calls]
    assert cb.get("/img/v46p-front.jpg").status_code == 200 and adm.get("/img/v46p-back.jpg").status_code == 200
    # merge INTO another person's card, preview into it, bulk on it: "not found"
    va = ca.get(f"/api/cards/{a}").json()["version"]
    r = ca.post(f"/api/cards/{a}", json={"status": "rejected", "merge_into": b, "version": va}); assert r.status_code == 422 and r.json()["need"] == "merge_missing"
    assert ca.post(f"/api/cards/{a}/merge-preview", json={"into": b}).status_code == 404
    r = ca.post("/api/cards-bulk", json={"ids": [b], "status": "rejected"}); assert r.status_code == 422, r.text
    assert st.get(b)["status"] == "pending"
    # list, batch filter, counts, batches
    assert b not in {c["id"] for c in ca.get("/api/cards").json()} and a in {c["id"] for c in ca.get("/api/cards").json()}
    r = ca.get("/api/cards?batch=v46pb"); assert r.status_code == 403 and r.json()["need"] == "not_your_batch"
    cn = ca.get("/api/counts?batch=v46pb").json(); assert cn["batch"]["all"] == 0 and "everyone_pending" not in cn
    bl = ca.get("/api/batches").json(); assert "v46pb" not in {x["batch"] for x in bl} and all("owner" not in x for x in bl)
    assert b in {c["id"] for c in adm.get("/api/cards?batch=v46pb").json()}


def test_v046_lookalike_in_other_batch_is_a_count_only(env):
    ui, adm = env["ui"], env["adm"]
    ca, cb, a, b = _two(env, "v46l")
    d = ca.get(f"/api/cards/{a}").json(); s = json.dumps(d)
    assert f'"card_id": {b}' not in s and "Secret B batch" not in s and f"#{b}" not in s
    assert d["dupes"]["hidden_open"] >= 1 and not d["dupes"]["queue"]
    lst = [c for c in ca.get("/api/cards?batch=v46la").json() if c["id"] == a][0]
    assert f"#{b}" not in json.dumps(lst)
    full = adm.get(f"/api/cards/{a}").json(); assert b in [x["card_id"] for x in full["dupes"]["queue"]]
    # Different (keep_apart all) resolves the hidden ones; approve then works
    va = d["version"]; r = ca.post(f"/api/cards/{a}", json={"keep_apart": "all", "version": va}); assert r.status_code == 200, r.text
    assert ca.get(f"/api/cards/{a}").json()["dupes"]["hidden_open"] == 0


def test_v046_jobs_and_history_scrubbed(env):
    ui = env["ui"]
    ca, cb, a, b = _two(env, "v46h")
    ui.log(a, "ZZ", "merged", detail={"cards": [b], "note": f"merged #{b} into this"})
    h = json.dumps(ca.get(f"/api/cards/{a}").json()["history"])
    assert f"#{b}" not in h and f"[{b}]" not in h


# ---- #2 undo: this batch, the last 2 hours, also for a named id
def test_v046_undo_window_batch_and_named_id(env):
    ui, st = env["ui"], env["store"]
    rc = _user(env, "undo46"); ui.claim_batch("v46u1", {"id": _uid("undo46")}); ui.claim_batch("v46u2", {"id": _uid("undo46")})
    a = mk(ui, st, first_name="Una", last_name="Do", emails=["ud@v46u.example.com"], by=""); ui.set_meta(a, batch="v46u1", batch_label="U1")
    b = mk(ui, st, first_name="Ben", last_name="Do", emails=["bd@v46u.example.com"], by=""); ui.set_meta(b, batch="v46u2", batch_label="U2")
    rc.post(f"/api/cards/{a}", json={"fields": {"title": "Undo A"}}); rc.post(f"/api/cards/{b}", json={"fields": {"title": "Undo B"}})
    pa = rc.get("/api/undo?batch=v46u1").json(); pb = rc.get("/api/undo?batch=v46u2").json()
    assert pa["id"] != pb["id"] and pa["age_min"] == 0 and pa.get("batch_label") == "U1" and len(pa["label"]) < 60   # v0.4.7 #5: the batch is on the button
    # a named id from another batch is refused in this batch
    r = rc.post("/api/undo", json={"id": pb["id"], "batch": "v46u1"}); assert r.status_code == 404
    assert st.get(b)["fields"]["title"] == "Undo B"
    # older than the window: neither the button nor the click
    with ui.db() as c: c.execute("UPDATE actions SET ts=? WHERE id=?", (time.time() - ui.UNDO_WINDOW - 60, pa["id"]))
    assert rc.get("/api/undo?batch=v46u1").json() == {}
    assert rc.post("/api/undo", json={"id": pa["id"], "batch": "v46u1"}).status_code == 404
    assert st.get(a)["fields"]["title"] == "Undo A"
    assert rc.post("/api/undo", json={"id": pb["id"], "batch": "v46u2"}).status_code == 200
    hd = _src("app/static/ui/header.js"); assert "refreshUndo.t = setTimeout(refreshUndo, 60000)" in hd and "btn.hidden = !u.id" in hd


def test_v046_undo_label_has_batch_for_admins_only(env):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    a = mk(ui, st, first_name="Ada", last_name="Lbl", emails=["al@v46ul.example.com"]); ui.set_meta(a, batch="v46ul", batch_label="Label batch")
    adm.post(f"/api/cards/{a}", json={"fields": {"title": "Adm edit"}})
    p = adm.get("/api/undo?batch=v46ul").json(); assert p["batch_label"] == "Label batch"


# ---- #3 blocked cards: admin-only confirm, audit row, Needs admin flag
def test_v046_reviewer_confirm_refused_is_audited_and_needs_admin_flag(env):
    ui, st, adm, rev = env["ui"], env["store"], env["adm"], env["rev"]
    from app import auth
    cid = mk(ui, st, first_name="Morg4n", last_name="Vale", emails=["mv@v46n.example.com"])
    v = rev.get(f"/api/cards/{cid}").json()["version"]
    r = rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "name", "value": "Morg4n", "reason": "printed like this", "version": v})
    assert r.status_code == 403 and r.json()["error"] == "An admin needs to confirm this."
    ev = [x[0] for x in auth.db().execute("SELECT event FROM auth_log WHERE username='rev' ORDER BY id DESC LIMIT 5")]
    assert any("reviewer confirm refused" in e and f"#{cid}" in e for e in ev)
    r = rev.post(f"/api/cards/{cid}/needs-admin", json={}); assert r.status_code == 200 and "Morg4n" in r.json()["needs_admin"]["reason"]
    assert cid in {c["id"] for c in adm.get("/api/cards?needs_admin=1").json()}
    assert adm.get("/api/counts").json()["needs_admin"] >= 1
    assert rev.get(f"/api/cards/{cid}").json()["needs_admin"]["by"]
    assert _user(env, "other46n").post(f"/api/cards/{cid}/needs-admin", json={"clear": True}).status_code == 404   # not their card
    assert adm.post(f"/api/cards/{cid}/needs-admin", json={"clear": True}).json()["needs_admin"] is None
    assert cid not in {c["id"] for c in adm.get("/api/cards?needs_admin=1").json()}
    js = _src("app/static/ui/views/review.js")
    assert 'An admin needs to confirm this.' in js and 'id="bNeedsAdmin">Needs admin<' in js and "Ask an admin." in js
    assert _src("app/static/ui/views/queue.js").count("needs admin") >= 1 and 'id="fNa"' in _src("app/static/ui/index.html")


# ---- #4 / #9 toast wording
def test_v046_same_or_different_toast_wording():
    js = _src("app/static/ui/views/review.js")
    assert 'return $("#rDupQ #dSame") ? "Same person? Answer Same or Different first." : "Pick Different first.";' in js
    assert "function blockedMsg(hard, ov)" in js and js.count('toast("Same person? Answer Same or Different first."') == 0
    assert "Date.now() - lastSameT < 2500" in js


# ---- #5 misreads: a digit inside a word, '|' in title/department
@pytest.mark.parametrize("field,val", [("company", "Rubb3r City"), ("company", "Kent Partn3rs"), ("department", "L3gal"),
                                       ("title", "Own3r 4"), ("first_name", "Morg4n"), ("department", "Acc|ounts"), ("title", "Vice Pres|dent")])
def test_v046_misread_flagged(env, field, val):
    ui = env["ui"]; f = {"first_name": "Ann", "last_name": "Lee", "emails": ["a@b.example.com"], "phones": [], field: val}
    e = ui.hard_errors(f); key = "name" if field == "first_name" else field
    assert key in e, (field, val, e)


@pytest.mark.parametrize("val", ["3M", "B2B Sales", "H2O Labs", "21st Century", "4th Street Bakery", "Level 3", "Q3 Partners", "G4S", "Area51", "7-Eleven"])
def test_v046_digits_that_are_real_not_flagged(env, val):
    assert "company" not in env["ui"].hard_errors({"first_name": "Ann", "last_name": "Lee", "emails": ["a@b.example.com"], "phones": [], "company": val})


def test_v046_x_department_alias_checked(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Dee", last_name="Pt", emails=["dp@v46d.example.com"])
    r = rev.post(f"/api/cards/{cid}", json={"fields": {"x_department": "Acc|ounts"}}); assert r.status_code in (200, 422), r.text
    assert st.get(cid)["fields"].get("department") == "Acc|ounts" or r.status_code == 422


# ---- #6 exported before: one count, Different remembered per pair, short words
def test_v046_exported_before_dialog_wording():
    js = _src("app/static/ui/views/review.js")
    assert "<p>${esc(xeLine(xe0))} Approve anyway?</p>" in js and "<b>${esc(xeLine(xe))}</b>" in js and "`Exported before (${" not in js   # v0.4.8 #5
    assert '"Marked different."' in js and "Different from ${" not in js
    assert "(e.data.other ? [" in js


def test_v046_seen_before_needs_same_company_or_email(env):
    ui = env["ui"]
    assert ui._same_co_or_email({"why": ["same email"]}) and ui._same_co_or_email({"why": ["org exact"]})
    assert not ui._same_co_or_email({"why": ["same name"]})


# ---- #7 export file names, README, ready line
def test_v046_export_names_readme_and_ready_line(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    fn = ui._fname("contacts-for-MC-Trade", "approved_new", "xlsx", "Ready")
    assert fn.startswith("IMPORT-ME_GAC-MCTrade-new-") and len(fn.rsplit("_", 1)[1].split(".")[0]) == 6   # HHMMSS
    assert ui.comp_name(fn, "-SUMMARY.xlsx").startswith("NOT-FOR-IMPORT_") and ui.comp_name(fn, "-UPDATES.xlsx").startswith("IMPORT-ME-UPDATES_")
    assert ui.comp_name("GAC-MCTrade-new-old.xlsx", "-READ-ME.txt") == "GAC-MCTrade-new-old-READ-ME.txt"   # old exports keep their names
    ids = [mk(ui, st, first_name=n, last_name="Ready", emails=[f"{n.lower()}@v46r.example.com"]) for n in ("Ana", "Bo", "Cy")]
    for i in ids: ui.set_meta(i, batch="v46r", batch_label="Ready"); st.update(i, status="approved", reviewer="RR")
    cs, metas = ui._active(); sel = [st.get(i) for i in ids]
    out = ui.build_export("xlsx", sel, metas, "approved_new", "RR", "Ready")
    rd = out[3]["readme.txt"].decode(); rdy = out[4]["ready"]
    assert rdy["text"] in rd and rdy["text"].startswith("Ready to import: ") and "Test 2 rows first." in rdy["text"]
    assert "Import only: IMPORT-ME_" in rd and "DO NOT IMPORT" not in rd and rdy["files"] == 4 + ("updates.xlsx" in out[3])
    assert rdy["text"] not in out[3]["extra.csv"].decode("utf-8-sig")   # v0.4.7 #9 (data-manager L5): no summary row at the end of the CSV
    pv = ui.build_export("xlsx", sel, metas, "approved_new", "RR", "Ready", preview=True)[3]["readme.txt"].decode()
    assert "import none" in pv and "Import only" not in pv
    sm = rev.get("/api/export/summary?status=approved_new&batch=v46r")
    if sm.status_code == 200: assert sm.json()["ready"]["text"] == rdy["text"]
    ex = _src("app/static/ui/views/export.js")
    assert "sum.ready.files" in ex and "no All batches for reviewers" in _src("app/static/ui/views/queue.js") and "seenN[l] > 1" in ex


# ---- #8 copy, /health
def test_v046_copy_and_health(env):
    from conftest import Client
    from app import main
    h = Client(main.app).get("/health").json(); assert "commit" in h and "public_commit" not in h
    js = _src("app/static/ui/views/review.js")
    assert js.count("Fix it, or ask an admin if the card is right.") == 0 and js.count("<b>An admin needs to confirm this.</b> Or fix it:") == 1   # v0.4.7 #4
    assert 'id="batchLegend"' not in _src("app/static/ui/index.html")
    import os
    if os.path.exists("training/REVIEWER-GUIDE.md"):   # the public repo has no training/ folder
        g = _src("training/REVIEWER-GUIDE.md")
        assert "right.**;" not in g and "name, title, company or department" in g and "email, website or address" in g and "Needs a look" in g
        assert "Your admin: ______" in g and "GAC_ADMIN_CONTACT" in _src("training/build_help.py") and "GAC_ADMIN_CONTACT" in _src("training/help_instance.sh")
    h = _src("app/static/ui/help.html"); assert ".;" not in h and "Your admin:" in h and "name, title, company or department" in h


def test_v046_review_badge_counts_own_batches(env):
    ui, st = env["ui"], env["store"]
    ca, cb, a, b = _two(env, "v46c")
    assert ca.get("/api/counts").json()["mine_pending"] >= 1
    n_b = cb.get("/api/counts").json()["mine_pending"]
    st.update(a, status="rejected", reviewer="X")
    assert cb.get("/api/counts").json()["mine_pending"] == n_b


def test_v046_blocked_toast_names_misread_and_badge_grammar():
    import pathlib
    ui = pathlib.Path(__file__).resolve().parents[2] / "app" / "static" / "ui"
    js = (ui / "views" / "review.js").read_text(encoding="utf-8"); hd = (ui / "header.js").read_text(encoding="utf-8")
    assert '`"${mv}" looks misread.`' in js and '" Fix it, or click Needs admin."' in js and '" Waiting for an admin."' in js   # v0.4.8 #6
    assert 'c.needs_admin === 1 ? "needs" : "need"' in hd
