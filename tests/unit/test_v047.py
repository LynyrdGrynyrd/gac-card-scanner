"""v0.4.7 regression tests (bot reports qa/*-v046.md). Made-up cards only."""
import json
from test_app import mk
from test_v045 import _user, _uid, _src


def _ini(name):
    from app import auth
    return auth.db().execute("SELECT initials FROM users WHERE username=?", (name,)).fetchone()[0]


def _world(env, tag):
    """The bots' scenario: reviewer R with an OLD own batch and the CURRENT own batch, own no-batch cards, and another
    user's batch, all holding look-alikes of R's current card."""
    ui, st = env["ui"], env["store"]
    r = _user(env, f"r{tag}"); o = _user(env, f"o{tag}")
    ui.claim_batch(f"{tag}old", {"id": _uid(f"r{tag}")}); ui.claim_batch(f"{tag}cur", {"id": _uid(f"r{tag}")}); ui.claim_batch(f"{tag}oth", {"id": _uid(f"o{tag}")})
    same = dict(first_name="Maria", last_name="Delgado", company="Delgado Tile", emails=[f"md@{tag}.example.com"], website=f"{tag}.example.com")
    ids = {}
    for k, b in (("cur", f"{tag}cur"), ("cur2", f"{tag}cur"), ("old", f"{tag}old"), ("oth", f"{tag}oth"), ("nob", None)):
        ids[k] = mk(ui, st, by=_ini(f"r{tag}") if k != "oth" else _ini(f"o{tag}"), **same)
        ui.set_meta(ids[k], batch=b, batch_label={"cur": "Current", "cur2": "Current", "old": "Old own", "oth": "Other person", "nob": None}[k])
    return r, o, ids


# ---- #1 HIGH: a reviewer's panels name only cards of the CURRENT batch
def test_v047_panels_name_only_the_current_batch(env):
    adm = env["adm"]
    r, o, ids = _world(env, "v47p")
    d = r.get(f"/api/cards/{ids['cur']}").json(); s = json.dumps(d)
    assert [x["card_id"] for x in d["dupes"]["queue"]] == [ids["cur2"]]          # same batch: in full
    assert d["dupes"]["hidden_open"] >= 3                                          # old own + other person + no batch: a count
    for k in ("old", "oth", "nob"):
        assert f'"card_id": {ids[k]}' not in s and f"#{ids[k]}" not in s, k
    assert "Old own" not in s and "Other person" not in s
    # the reviewer can still open their own old card (it is theirs), but its panel does not list the current batch either
    assert r.get(f"/api/cards/{ids['old']}").status_code == 200 and r.get(f"/api/cards/{ids['oth']}").status_code == 404
    d2 = r.get(f"/api/cards/{ids['old']}").json(); assert not d2["dupes"]["queue"] and d2["dupes"]["hidden_open"] >= 4   # >=: earlier tests in the same DB may add more Maria Delgados
    # no-batch card: nothing named
    d3 = r.get(f"/api/cards/{ids['nob']}").json(); assert not d3["dupes"]["queue"] and d3["dupes"]["hidden_open"] >= 4
    # merge: preview and merge into the old own batch refused like a card that doesn't exist
    assert r.post(f"/api/cards/{ids['cur']}/merge-preview", json={"into": ids["old"]}).status_code == 404
    assert r.post(f"/api/cards/{ids['cur']}/merge-preview", json={"into": ids["cur2"]}).status_code == 200
    v = d["version"]; rr = r.post(f"/api/cards/{ids['cur']}", json={"status": "rejected", "merge_into": ids["old"], "version": v})
    assert rr.status_code in (403, 409, 422) and env["store"].get(ids["cur"])["status"] == "pending"
    # list rows say nothing about the other ids either
    lst = json.dumps(r.get(f"/api/cards?batch=v47pcur").json())
    for k in ("old", "oth", "nob"): assert f"#{ids[k]}" not in lst
    # an admin sees all four
    full = adm.get(f"/api/cards/{ids['cur']}").json(); assert {ids[k] for k in ("cur2", "old", "oth", "nob")} <= {x["card_id"] for x in full["dupes"]["queue"]}


def test_v047_history_text_names_no_other_batch_card(env):
    ui = env["ui"]
    r, o, ids = _world(env, "v47h")
    ui.log(ids["cur"], "ZZ", "duplicate_kept_both", detail={"cards": [ids["cur2"], ids["old"], ids["oth"], ids["nob"]]})
    ui.log(ids["cur"], "ZZ", "edited", detail={"address": {"from": "1 Main St #200", "to": "1 Main St #201"}})
    h = r.get(f"/api/cards/{ids['cur']}").json()["history"]; t = " | ".join(x["text"] for x in h)
    assert f"#{ids['cur2']}" in t and "3 other cards" in t, t
    for k in ("old", "oth", "nob"): assert f"#{ids[k]}" not in t
    assert "#200" in t and "#201" in t   # an address value is not a card number
    assert f"#{ids['old']}" in " ".join(x["text"] for x in env["adm"].get(f"/api/cards/{ids['cur']}").json()["history"])


def test_v047_scrub_ids_text_unit(env):
    ui = env["ui"]
    assert ui._scrub_ids_text("marked as a different person from #1, #2, #3", {1}) == "marked as a different person from #1 and 2 other cards"
    assert ui._scrub_ids_text("from #5", set()) == "from 1 other card"
    assert ui._scrub_ids_text("from #5 and #6", {5, 6}) == "from #5 and #6"


def test_v047_label_in_another_batch_not_someone_else(env):
    js = _src("app/static/ui/views/review.js")
    assert '(${bestQ.same_batch ? "someone else\'s card" : "in another batch"})' in js
    assert 'more in ${hid === 1 ? "another batch" : "other batches"}' in js and "Also looks like" not in js


# ---- #2 MED: a card exported and then edited is not put into the next IMPORT-ME file as "create new"
def _approved(ui, st, tag, **f):
    a = mk(ui, st, **f); ui.set_meta(a, batch=f"{tag}b", batch_label=tag); st.update(a, status="approved", reviewer="RR"); return a


def test_v047_changed_after_export_not_in_next_file(env):
    import time
    ui, st = env["ui"], env["store"]
    a = _approved(ui, st, "v47chg", first_name="Edda", last_name="Twice", emails=["edda@twice47.example.com"])
    b = _approved(ui, st, "v47chg", first_name="Finn", last_name="Once", emails=["finn@once47.example.com"])
    ui.set_meta(a, exported=time.time(), reexport=1); ui.log(a, "RR", "exported", detail={"file": "GAC_IMPORT-ME_v47.xlsx"})
    with ui.db() as c_:   # v0.4.8: "exported" means: in an earlier MC Trade import file
        c_.execute("INSERT INTO exports(ts,username,initials,kind,filter,count,filename,card_ids,stored,batch_label,people) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (time.time(), "rr", "RR", "xlsx", "approved_new", 1, "GAC_IMPORT-ME_v47.xlsx", json.dumps([a]), None, "", json.dumps(["e:edda@twice47.example.com"])))
    cs, ms = ui._active(); sel = [c for c in cs if c["id"] in (a, b)]
    res = ui.build_export("xlsx", sel, ms, "approved_new", "T (TT)", "", preview=True)
    summ = res[4]; r_ = summ["ready"]
    assert a in summ["changed_ids"] and r_["changed"] == 1 and r_["clean"] + r_["to_check"] == r_["rows"]
    assert summ["decisions"][str(a)] != "new" and summ["decisions"][str(b)] == "new"
    assert "Not in the file: 1 edited after export." in r_["text"]
    blob = json.dumps({k: (v.decode("utf-8", "ignore") if isinstance(v, (bytes, bytearray)) else str(v)) for k, v in (res[3] or {}).items()})
    assert ("Edited after export, so it is not in this file" in blob or "Edited after export, so it is not in this file." in blob) and "GAC_IMPORT-ME_v47.xlsx" in blob and "by hand" not in blob
    res2 = ui.build_export("xlsx", sel, ms, "approved_new", "T (TT)", "", preview=True, include_changed=True)
    assert res2[4]["decisions"][str(a)] == "new"   # the admin's "Put it in as new anyway" (a warning goes with it)


def test_v047_ready_line_never_impossible():
    from app import exporting as E
    assert E.ready_line({"rows": 3, "clean": 2, "to_check": 1, "outside": 0, "changed": 0}) == "Ready to import: 3 rows (2 clean, 1 to check). Test 2 rows first."
    t = E.ready_line({"rows": 1, "clean": 1, "to_check": 0, "outside": 2, "changed": 1})
    assert t == "Ready to import: 1 row (1 clean, 0 to check). Not in the file: 1 edited after export, 2 to decide."
    assert E.ready_line({"rows": 0, "clean": 0, "to_check": 0}) == "Nothing new to import."


# ---- #4 Needs admin
def test_v047_needs_admin_reason_append_and_clear(env):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    rev = _user(env, "na47"); ui.claim_batch("v47na", {"id": _uid("na47")})
    cid = mk(ui, st, first_name="Morg4n", last_name="Pike", emails=["mp@pike47.example.com"], by=_ini("na47")); ui.set_meta(cid, batch="v47na")
    long_ = "Department “" + "x" * 150 + "”"
    r = rev.post(f"/api/cards/{cid}/needs-admin", json={}); na = r.json()["needs_admin"]
    assert r.status_code == 200 and na["reason"] == "First name “Morg4n”: looks misread", na
    r = rev.post(f"/api/cards/{cid}/needs-admin", json={"reason": "the card really says Morg4n"}); na = r.json()["needs_admin"]
    assert na["reason"] == "First name “Morg4n”: looks misread · the card really says Morg4n"
    assert rev.post(f"/api/cards/{cid}/needs-admin", json={"reason": "the card really says Morg4n"}).json().get("already")
    assert "First name" in ui.na_reason({"name": "x"}, {"first_name": long_}) and len(ui.na_reason({"name": "x"}, {"first_name": long_})) < 80
    assert adm.get("/api/export/summary?status=approved_new&batch=v47na").json().get("needs_admin") == 1
    assert cid in {c["id"] for c in rev.get("/api/cards?batch=v47na&needs_admin=1").json()}
    # an approve while flagged is still refused (the flag never lets a card through)
    v = rev.get(f"/api/cards/{cid}").json()["version"]
    assert rev.post(f"/api/cards/{cid}", json={"status": "approved", "version": v, "card_id": cid}).status_code == 422
    # fixed by the reviewer: nothing is left to confirm, so the flag comes off by itself
    f = dict(st.get(cid)["fields"], first_name="Morgan"); v = rev.get(f"/api/cards/{cid}").json()["version"]
    assert rev.post(f"/api/cards/{cid}", json={"fields": f, "version": v, "card_id": cid}).status_code == 200
    assert not ui.meta(cid).get("needs_admin") and any(h["action"] == "needs_admin_cleared" for h in ui.history(cid))


def test_v047_confirm_on_a_field_with_nothing_to_confirm_is_not_admin(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Ann", last_name="Plain", emails=["ann@plain47.example.com"])
    v = rev.get(f"/api/cards/{cid}").json()["version"]
    r = rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "emails", "value": ["ann@plain47.example.com"], "version": v, "reason": "x"})
    assert r.status_code == 409 and "Nothing to confirm" in r.json()["error"]


def test_v047_audit_refused_confirm_is_a_card_row(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Ivo", last_name="Pole", title="Vice Pres|dent", emails=["ivo@pole47.example.com"])
    v = rev.get(f"/api/cards/{cid}").json()["version"]
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "title", "value": "Vice Pres|dent", "version": v, "reason": "x"}).status_code == 403
    from app import audit_log
    src = _src("app/audit_log.py"); assert 'kind = "card"' in src
    with st.db() as c:
        ev = c.execute("SELECT event FROM auth_log WHERE event LIKE ? ORDER BY id DESC LIMIT 1", (f"#{cid} %",)).fetchone()[0]
    assert "reviewer confirm refused" in ev and ev.startswith(f"#{cid} Job title")


# ---- #5 Undo: the batch on the button; the All view only undoes the current batch
def test_v047_undo_names_batch_and_stays_in_current_batch(env):
    ui, st = env["ui"], env["store"]
    rc = _user(env, "undo47"); u = {"id": _uid("undo47")}; ui.claim_batch("v47u1", u); ui.claim_batch("v47u2", u)
    a = mk(ui, st, first_name="Ola", last_name="Undo", emails=["ou@v47u.example.com"], by=_ini("undo47")); ui.set_meta(a, batch="v47u1", batch_label="Old U")
    rc.post(f"/api/cards/{a}", json={"fields": {"title": "Undo A"}})
    b = mk(ui, st, first_name="Pia", last_name="Undo", emails=["pu@v47u.example.com"], by=_ini("undo47")); ui.set_meta(b, batch="v47u2", batch_label="New U")
    p = rc.get("/api/undo").json()
    assert not p or p.get("batch") != "v47u1"   # no batch given: an older batch's action is not offered
    rc.post(f"/api/cards/{b}", json={"fields": {"title": "Undo B"}})
    p = rc.get("/api/undo").json(); assert p.get("batch") == "v47u2" and p.get("batch_label") == "New U"
    hd = _src("app/static/ui/header.js"); assert "u.batch_short" in hd and "in this batch only" in hd


# ---- #6 misreads: real names allowed, real misreads still flagged
def test_v047_misread_allow_and_flag():
    from app import ui
    for ok in ("4imprint", "E2open", "3M", "Q3 Partners", "G4S", "Web3Labs", "i3 Verticals"): assert "company" not in ui.garbled_errors({"company": ok}), ok
    for ok in ("4thought Partner", "Manager | Sales", "Q3 Lead"): assert "title" not in ui.garbled_errors({"title": ok}), ok
    assert "department" not in ui.garbled_errors({"department": "Accounts | Payable"})
    for bad in ("Vice Pres|dent", "Manag|ng Director"): assert "title" in ui.garbled_errors({"title": bad}), bad
    assert "department" in ui.garbled_errors({"department": "Sa|es"})
    for bad in ("Rubb3r Co", "Partn3r Group"): assert "company" in ui.garbled_errors({"company": bad}), bad
    e = ui.garbled_errors({"company": "Rnbber CityRobotics"})["company"]; assert "Rnbber" in e and "Rubber" in e
    for ok in ("Rubber City Robotics", "Mian & Sons", "Flor Design", "City Hall Cafe"): assert "company" not in ui.garbled_errors({"company": ok}), ok
    assert "title" not in ui.garbled_errors({"title": "Sales Manger"})   # a real word: a suggestion only


# ---- #7 an upload with a batch name and no batch id gets a batch
def test_v047_upload_with_label_only_gets_a_batch(env, monkeypatch):
    ui = env["ui"]; seen = []
    async def fake(data, fname, **k): seen.append(k.get("batch")); return {"job": "x"}
    monkeypatch.setattr(ui, "enqueue_upload", fake)
    rc = _user(env, "up47")
    for _ in range(2): assert rc.post("/api/jobs", data={"batch_label": "Fair 47"}, files={"image": ("a.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}).status_code == 200
    assert seen[0] and seen[0] == seen[1] and ui.batch_owner_id(seen[0]) == _uid("up47")
    assert rc.post("/api/jobs", data={"batch_label": "Other 47"}, files={"image": ("a.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}).status_code == 200
    assert seen[2] != seen[0]


# ---- #8 reviewers: badge = pending in their own batches; no All batches; no everyone's exports
def test_v047_badge_equals_own_batches_pending(env):
    ui, st = env["ui"], env["store"]
    rc = _user(env, "bdg47"); u = {"id": _uid("bdg47")}; ui.claim_batch("v47g1", u); ui.claim_batch("v47g2", u)
    for b_, n_ in (("v47g1", 2), ("v47g2", 1)):
        for k in range(n_): i = mk(ui, st, first_name=f"G{b_}{k}", last_name="Badge", emails=[f"g{k}@{b_}.example.com"], by=_ini("bdg47")); ui.set_meta(i, batch=b_)
    o = mk(ui, st, first_name="Other", last_name="Badge", emails=["o@g47.example.com"], by="ZQ"); ui.set_meta(o, batch="v47gx")
    bs = rc.get("/api/batches").json(); c = rc.get("/api/counts").json()
    assert c["own_pending"] == sum(b.get("pending") or 0 for b in bs) == 3
    # v0.4.8 #7: the badge itself = the batch the queue shows (default: the newest own batch), the same number as the list
    assert c["mine_pending"] == 1 and c["badge_batch"] == "v47g2"
    assert rc.get("/api/counts?batch=v47g1").json()["mine_pending"] == 2 == len(rc.get("/api/cards?status=pending&batch=v47g1").json())
    assert rc.get("/api/counts?batch=v47gx").json()["mine_pending"] == 1   # another person's batch never counts: back to the newest own
    q = _src("app/static/ui/views/queue.js"); assert "All my batches" not in q and "no All batches for reviewers" in q
    assert 'id="exHistEveryoneL" hidden' in _src("app/static/ui/index.html")


# ---- #9 copy
def test_v047_copy(env):
    from app import ui
    rv = _src("app/static/ui/views/review.js")
    assert 'bits[0] = bits[0].replace("<p>Exported before: ", "<p>")' in rv   # the title is not repeated in the body
    assert "idleNote" in _src("app/static/ui/login.html")
    import os
    if os.path.exists("training/build_help.py"):   # the public copy has no training/ folder
        assert "ask the front desk" in _src("training/build_help.py")
        assert "current batch only" in _src("training/REVIEWER-GUIDE.md")
    assert ui.garbled_errors({"website": "www.müller.de"}) == {} and "website" in ui.garbled_errors({"website": "www.mü ller.de"})
    assert ui._ob(1) == "in another batch" and ui._ob(47) == "in other batches"


def test_v047_csv_has_no_trailing_summary_row(env):
    ui, st = env["ui"], env["store"]
    a = _approved(ui, st, "v47csv", first_name="Cee", last_name="Ess", emails=["c@csv47.example.com"])
    cs, ms = ui._active(); sel = [c for c in cs if c["id"] == a]
    ex = ui.build_export("xlsx", sel, ms, "approved_new", "T (TT)", "", preview=False)[3]["extra.csv"].decode("utf-8-sig")
    last = ex.rstrip("\r\n").splitlines()[-1]
    assert last.split(",")[0] == str(a) and not ex.endswith("\r\n\r\n")
