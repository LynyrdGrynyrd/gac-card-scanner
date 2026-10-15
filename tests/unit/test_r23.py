"""Round 23: per-field 'This is correct' with a required reason, confirmations re-checked everywhere (also old/pre-r23 ones),
no confirmations through merges, truthful Cancel count, export default helpers, Morg4n / 7-digit phones / E*Trade /
CoffeeCo. / ZIP, sign-out from the login page, reader memory backstop."""
import json, os, time
from test_app import mk
from app import ui as U, mctrade_export as MX

def H(**f): return U.hard_errors({"first_name": "Ann", "phones": [{"number": "330-555-0100"}]} | f)
def _approved(ui, store, batch, **f):
    a = mk(ui, store, **f); ui.set_meta(a, batch=batch, batch_label=batch); store.update(a, status="approved", reviewer="RR"); return a

def test_wrong_blocks_and_misses():
    assert "company" not in H(company="E*Trade") and "company" not in H(company="Highland Square CoffeeCo.")
    assert "company" in H(company="Higneniscdaie CoffeeCa") and "company" in H(company="Acme Gr0up")
    assert "name" in H(first_name="Morg4n") and "last_name" in H(last_name="Sm1th") and "name" not in H(first_name="Morgan")
    assert "phones" in H(phones=[{"number": "555-0100"}]) and "no area code" in H(phones=[{"number": "555-0100"}])["phones"]
    for ok in ("330-555-0100", "330-555-0170 x4271", "(330) 555-0100 ext 12", "+44 20 7946 0958", "1-330-555-0100"): assert "phones" not in H(phones=[{"number": ok}]), ok
    m = H(address="g W Exchange St, Cuyahoga Falls, OH 44223")["address"]; assert "44223" in m
    assert "phones" in U.payload_problems({"phones": [{"number": "555-0100"}]}) or "phones" in H(phones=[{"number": "555-0100"}])

def _confirm(c, cid, field, value, reason="printed like this on the card"):
    v = c.get(f"/api/cards/{cid}").json()["version"]
    return c.post(f"/api/cards/{cid}/confirm-correct", json={"field": field, "value": value, "version": v, **({"reason": reason} if reason is not None else {})})

def test_confirm_one_field_needs_reason_and_is_logged(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Ann", last_name="Lee", company="Acme Gr0up", title="Acc0unt Manager", emails=["ann@acme.com"])
    r = _confirm(rev, cid, "company", "Acme Gr0up", reason=None); assert r.status_code == 422 and r.json()["need"] == "reason"
    assert _confirm(rev, cid, "company", "Acme Gr0up", reason="\u200b-").status_code == 422
    r = _confirm(rev, cid, "company", "Acme Gr0up"); assert r.status_code == 200, r.text
    h = U.hard_errors(st.get(cid)["fields"]); assert "company" not in h and "title" in h   # ONE field only
    hist = [x for x in U.history(cid) if x["action"] == "hard_check_override"][-1]
    assert "Company" in hist["text"] and "Acme Gr0up" in hist["text"] and "printed like this" in hist["text"], hist["text"]
    au = [x for x in env["adm"].get("/api/admin/audit?q=as correct").json() if x.get("card") == cid]
    assert len(au) == 1 and au[0]["kind"] == "card", au   # round 24: ONE audit row per confirm
    d = rev.get(f"/api/cards/{cid}").json(); assert "company" in d["confirmed"] and d["confirmed"]["company"]["by"]
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "phones", "value": [], "version": d["version"], "reason": "abc"}).status_code == 400

def test_old_and_invalid_confirmations_do_not_count(env):
    ui, st = env["ui"], env["store"]
    old = {"company": json.dumps("Acme Gr0up")}
    f = {"first_name": "Ann", "company": "Acme Gr0up", "phones": [{"number": "33o-555-0100"}], "confirmed_ok": dict(old, phones=json.dumps([{"number": "33o-555-0100"}])), "confirmed_by": {"company": "QS"}}
    assert "company" in U.hard_errors(f) and "phones" in U.hard_errors(f)   # pre-r23 (no author / reason), and phones never
    meta = {"user": "rev", "by": "RR", "role": "reviewer", "reason": "on card", "value": old["company"]}
    assert "company" not in U.hard_errors(dict(f, confirmed_meta={"company": meta}))
    e = json.dumps(["a@acmegroupexample.com"])
    f2 = {"first_name": "Ann", "emails": ["a@acmegroupexample.com"], "confirmed_ok": {"emails": e}, "confirmed_meta": {"emails": dict(meta, value=e)}}
    assert "emails" in U.hard_errors(f2)                                     # a reviewer can't confirm an email
    assert "emails" not in U.hard_errors(dict(f2, confirmed_meta={"emails": dict(meta, value=e, role="admin")}))
    assert "company" in U.hard_errors(dict(f, company="Acme Gr0up2", confirmed_meta={"company": meta}))   # edited since: no longer confirmed

def test_export_rechecks_old_confirmations(env):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    b = "r23-old"
    a = _approved(ui, st, b, first_name="Old", last_name="Confirm", company="Acme Gr0up", emails=["old@acme23.com"],
                  confirmed_ok={"company": json.dumps("Acme Gr0up")}, confirmed_by={"company": "?"})
    v = adm.get(f"/api/export/xlsx?preview=1&view=1&status=approved_new&batch={b}").json()
    assert not v["rows"] and any(x[0] == a and "FIX FIRST" in x[1] for x in v["left"]), v["left"]

def test_export_merge_never_carries_a_confirmed_value():
    meta = {"user": "rev", "by": "RR", "role": "admin", "reason": "on card"}
    lead = {"id": 1, "decided": 2, "fields": {"first_name": "Tay", "last_name": "Fix", "emails": ["t@fix.com"], "phones": [{"number": "330-555-0101"}], "company": "Fix Co", "website": ""}}
    w = "wvw.c0m.xq"
    oth = {"id": 2, "decided": 1, "fields": {"first_name": "Tay", "last_name": "Fix", "emails": ["t@fix.com"], "phones": [{"number": "330-555-0101"}], "company": "Fix Co", "website": w,
                                             "confirmed_ok": {"website": json.dumps(w)}, "confirmed_meta": {"website": dict(meta, value=json.dumps(w))}}}
    res = MX.build([lead, oth], "X", "gac", U.hard_errors, crm_real=False, confirmed=lambda f: list(U.valid_confirmations(f)))
    assert len(res["rows"]) == 1 and w not in json.dumps(res["rows"][0][1]), res["rows"]

def test_card_merge_drops_confirmations(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    t = mk(ui, st, first_name="Mia", last_name="Merge", company="", emails=["mia@merge23.com"])
    s = mk(ui, st, first_name="Mia", last_name="Merge", company="Acme Gr0up", emails=["mia@merge23.com"])
    assert _confirm(rev, s, "company", "Acme Gr0up").status_code == 200
    assert U.merge_pick(st.get(t)["fields"], st.get(s)["fields"], "company") is None   # a garbled value never fills the target, confirmed or not

def test_cancel_counts_only_this_upload(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    for _ in range(3): c = mk(ui, st, first_name="Pre", last_name="Batch"); ui.set_meta(c, batch="r23-cx", batch_label="r23-cx")
    with ui.JLOCK:
        ui.JOBS["r23j1"] = {"id": "r23j1", "state": "queued", "file": "a.jpg", "batch": "r23-cx", "who": "RR", "created": time.time()}
        ui.JOBS["r23j2"] = {"id": "r23j2", "state": "done", "file": "b.jpg", "batch": "r23-cx", "who": "RR", "created": time.time(), "card_id": c}
    r = rev.post("/api/jobs/cancel", json={"ids": [], "session": ["r23j1", "r23j2"], "batch": "r23-cx", "all_waiting": True}).json()
    assert r["cancelled"] == 1 and r["kept"] == 1 and r["kept_ids"] == [c], r
    # an upload still on its way when Cancel was pressed is refused (no card appears after Cancel)
    t0 = time.time() - 5
    assert U._cancelled_since("RR", "r23-cx", t0) and not U._cancelled_since("RR", "other-batch", t0)

def test_logout_from_login_page_works_without_csrf(env):
    from fastapi.testclient import TestClient
    from app import main
    c = TestClient(main.app); assert c.post("/api/auth/login", json={"username": "rev2", "password": "temp-pass-1234"}, headers={"Origin": "http://testserver"}).status_code == 200
    r = c.post("/api/auth/logout", headers={"Origin": "http://testserver", "X-CSRF-Token": "stale"}); assert r.status_code == 200, r.text
    assert c.get("/api/auth/state").json().get("user") is None
    assert c.post("/api/auth/logout", headers={"Origin": "http://evil.example"}).status_code == 403   # cross-site still refused

def test_reader_hard_backstop(monkeypatch):
    from app import reader
    assert reader.backstop_mb(1200) == 4800 and reader.backstop_mb(500) == 4096
    p = os.path.join(os.path.dirname(__file__), "..", "..", "qa", "fixtures", "multipage_07_08_10.pdf"); d = open(p, "rb").read()
    assert len(reader.run_page(d, 0, 3, "m.pdf")) == 1          # normal pages are far below the backstop
    monkeypatch.setenv("READER_BACKSTOP_MB", "150")             # a tiny backstop: the child is refused memory, the server is fine
    try: reader.run_page(d, 0, 3, "m.pdf"); assert False, "expected ReaderError"
    except reader.ReaderError as e: assert str(e) == reader.CALM

def test_readme_plain_labels():
    src = "\n".join(open(os.path.join(os.path.dirname(U.__file__), n), encoding="utf-8").read() for n in ("ui.py", "exporting.py", "admin_files.py", "privacy.py", "pages.py", "audit_log.py"))   # audit 2026-10 P2: ui.py was split
    a = src.index("readme = \"\\n\".join(["); b = src.index("comp = {\"extra.csv\"", a); rd = src[a:b]
    for jargon in ("NeedsAttention", "CROSS-BATCH", "CONFLICT", "WhyLeftOut", "UNVERIFIED", "CONFIRMED BY"): assert jargon not in rd, jargon

def test_skip_ai_is_threaded_to_the_job():
    import inspect
    assert "skip_ai" in inspect.signature(U._run).parameters and "skip_ai" in inspect.signature(U._enqueue_one).parameters
    assert "skip_ai" in inspect.signature(U.create_job).parameters
