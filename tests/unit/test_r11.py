"""Round-11 regression tests: merge direction (both ways, self-merge refused), merge preview 'replace', already-exported
info, 'Looks good' never next to look-alikes, strict confirm flags, undo id validation, add-back OCR-only, MC Trade
secondary-email hold-back, full update diff, accent folding, dry-run readback of UPDATES, audit card ids once, health version."""
import json
from test_app import mk, sent

def _merge(rc, src, tgt):
    return rc.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt, "card_id": src})

def test_merge_direction_both_ways(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    for direction in ("a_into_b", "b_into_a"):
        a = mk(ui, store, first_name="Avery", last_name="Abernathy", title="Owner", emails=[f"aa.{direction}@sra11.example"])
        b = mk(ui, store, first_name="Avery", last_name="Abernathy", title="Regional Owner", emails=[f"aa.{direction}@sra11.example"])
        src, tgt = (a, b) if direction == "a_into_b" else (b, a)
        before_t = store.get(tgt)["status"]
        r = _merge(rc, src, tgt); assert r.status_code == 200, r.text
        s_, t_ = store.get(src), store.get(tgt)
        assert s_["status"] == "rejected" and f"Duplicate of #{tgt}" in (s_["note"] or "")
        assert t_["status"] == before_t and "Duplicate of" not in (t_["note"] or "")
        assert any(h["action"] == "merged_from" and h["detail"]["card"] == src for h in ui.history(tgt))

def test_merge_into_itself_refused(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Self", last_name="Merge")
    r = _merge(rc, a, a); assert r.status_code == 422 and r.json()["need"] == "merge_self"
    assert store.get(a)["status"] == "pending"
    b = mk(ui, store, first_name="Self", last_name="Merge2")
    r = rc.post(f"/api/cards/{a}", json={"status": "rejected", "merge_into": b, "card_id": b})   # request meant for another card
    assert r.status_code == 409 and store.get(a)["status"] == "pending" and store.get(b)["status"] == "pending"

def test_merge_preview_says_replace(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Avery", last_name="Abernathy", emails=["aabernathy@summitridgeanalytiexample.com"],
           website="www.summitridgeanalyti.example.com", confidence={"emails": 0.45})
    s_ = mk(ui, store, first_name="Avery", last_name="Abernathy", emails=["aabernathy@summitridgeanalyti.example.com"],
            website="www.summitridgeanalyti.example.com", confidence={"emails": 0.97})
    pv = rc.post(f"/api/cards/{s_}/merge-preview", json={"into": t}).json()
    assert pv["email_replace"] == [{"old": "aabernathy@summitridgeanalytiexample.com", "new": "aabernathy@summitridgeanalyti.example.com"}]
    assert _merge(rc, s_, t).status_code == 200
    assert store.get(t)["fields"]["emails"] == ["aabernathy@summitridgeanalyti.example.com"]

def test_review_shows_already_exported(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Exa", last_name="Ported", emails=["exa@exp11.example"]); ui.set_meta(a, batch="r11-e1"); sent(ui, a)
    store.update(a, status="approved", reviewer="RR"); ui.log(a, "RR", "exported", detail={"file": "x.xlsx"})
    b = mk(ui, store, first_name="Exa", last_name="Ported", emails=["exa@exp11.example"]); ui.set_meta(b, batch="r11-e2")
    d = env["adm"].get(f"/api/cards/{b}").json()
    assert [x["card_id"] for x in d["exported_elsewhere"]] == [a] and d["exported_elsewhere"][0]["times"] == 1
    # v0.4.7 #1: a reviewer sees a card in another batch (even their own older one) as a count, never its id
    d = rc.get(f"/api/cards/{b}").json()
    assert len(d["exported_elsewhere"]) == 1 and "card_id" not in d["exported_elsewhere"][0]

def test_no_looks_good_with_lookalike(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Lena", last_name="Look", emails=["lena@look11.example"]); ui.set_meta(a, batch="r11-l1")
    store.update(a, status="approved", reviewer="RR")
    b = mk(ui, store, first_name="Lena", last_name="Look", emails=["lena@look11.example"]); ui.set_meta(b, batch="r11-l2")
    row = next(c for c in rc.get("/api/cards").json() if c["id"] == b)
    assert row["needs_attention"] and any(x["code"].startswith("dup") for x in row["attention"])

def test_confirm_flags_need_true(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Nora", last_name="No", emails=["nora@no11.example"]); ui.set_meta(a, batch="r11-n1")
    store.update(a, status="approved", reviewer="RR")
    b = mk(ui, store, first_name="Nora", last_name="No", emails=["nora@no11.example"]); ui.set_meta(b, batch="r11-n2")
    r = rc.post("/api/cards-bulk", json={"ids": [b], "status": "approved", "confirm_cross_batch": "no"})
    assert r.status_code == 409 and store.get(b)["status"] == "pending"
    r = rc.post(f"/api/cards/{b}", json={"status": "approved", "confirm_cross_batch": "yes"})
    assert r.status_code == 409 and store.get(b)["status"] == "pending"

def test_undo_bad_ids(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store); rc.post(f"/api/cards/{cid}", json={"fields": {"title": "R11 undo keep"}})
    for bad in ([1], 0, None, " 3", True, -1, 3.0, 2**63):   # round 13: "3" is a valid digit-only id now
        r = rc.post("/api/undo", json={"id": bad}); assert r.status_code == 422, (bad, r.status_code)
    assert store.get(cid)["fields"]["title"] == "R11 undo keep"
    assert rc.post("/api/undo", json={"id": 999999}).status_code == 404

def test_add_back_only_printed_email_and_matching_site(env, monkeypatch):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store, first_name="Ophelia", last_name="Strand", emails=["ophelia@strandline-analytics.net"], website="")
    monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: {"fields": {"emails": ["st@strandline-analytics.net"], "website": "analytics.net"},
                                                             "text": "Ophelia Strand Strandline Analytics www.strandline-<b>analytics.net"})
    r = ui.attach_back(cid, b"x", ".jpg", "RR")
    f = store.get(cid)["fields"]
    assert f["emails"] == ["ophelia@strandline-analytics.net"] and not f["website"]
    assert set(r["not_added"]) == {"emails", "website"}
    cid2 = mk(ui, store, first_name="Ev", last_name="Il", emails=["ev@good11.example"], website="")
    monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: {"fields": {"website": "www.evil-phish.com"}, "text": "www.evil-phish.com"})
    ui.attach_back(cid2, b"x", ".jpg", "RR"); assert not store.get(cid2)["fields"]["website"]
    cid3 = mk(ui, store, first_name="Go", last_name="Od", emails=["go@good11.example"], website="")
    monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: {"fields": {"website": "www.good11.example", "emails": ["sales@good11.example"]}, "text": "www.good11.example sales@good11.example"})
    ui.attach_back(cid3, b"x", ".jpg", "RR"); f3 = store.get(cid3)["fields"]
    assert f3["website"] == "www.good11.example" and "sales@good11.example" in f3["emails"]

def test_secondary_email_match_held_back(env):
    ui = env["ui"]
    existing = [{"profile_id": "990031", "first_name": "R", "last_name": "Hughes", "organization": "Hughes & Partners Law", "email": "info@hugheslaw.com", "phone": ""}]
    c = {"id": 1, "fields": {"first_name": "Robert", "last_name": "Hughes", "company": "Hughes & Partners Law", "emails": ["rhughes@hugheslaw.com", "info@hugheslaw.com"], "phones": []}}
    lk = ui.crm_look(c, existing)
    assert lk["sure"] == "990031" and lk["email_differs"]
    from app import mctrade_export as mx
    cat, why, _ = mx.classify(c, "update_existing", {}, True, True, lambda c_: lk)
    assert cat == mx.REVIEW and "first email" in why

def test_accent_folding():
    from app import mctrade_sync
    m = mctrade_sync.match({"first_name": "Maria", "last_name": "Delgado", "emails": [], "phones": []},
                           [{"profile_id": "990021", "first_name": "María", "last_name": "Délgado", "organization": "", "email": "", "phone": ""}])
    assert m and m[0]["profile_id"] == "990021"

def test_audit_card_ids_once(env):
    ui, adm = env["ui"], env["adm"]
    from app import auth
    auth.alog("qa", "dry run: not in either file 1: #4242; cards checked: #4242")
    rows = [r for r in adm.get("/api/admin/audit?q=4242").json() if "#4242" in r["what"]]
    assert rows and all(r["cards"] == [4242] for r in rows)

def test_health_has_version_and_commit(env):
    from fastapi.testclient import TestClient
    from app.main import app
    h = TestClient(app).get("/health").json()
    assert h["version"] and h["commit"]

def test_plausibility_lists_every_lookalike_once():
    from app import plausibility as p
    out = p.check({"first_name": "Ann", "last_name": "Lee", "company": "Rnbber Co", "address": "47 N Mian St, Akrn", "emails": ["ann@acme.co"], "website": "acme.com"})
    txt = " ".join(x["text"] for x in out)
    assert "Akrn" in txt and "Mian" in txt and "Rnbber" in txt and "no state" in txt
    assert len({(x["field"], x["text"]) for x in out}) == len(out)

def test_use_ai_then_keep_current_then_save_records_both(env):
    """coordinator r4: 'Use AI' on company, 'Keep current' on email, Save -> both decisions stored, status checked."""
    ui, store, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store, first_name="Farid", last_name="Keep", company="Squarecoffe", emails=["farid@sq11.example"])
    diff = {"company": {"from": "Squarecoffe", "to": "Square Coffee"}, "emails": {"from": ["farid@sq11.example"], "to": ["farid@sq1l.example"]}}
    ui.set_meta(cid, ai_status="suggested", ai_detail=json.dumps({"diff": diff, "finished": 1}))
    assert rc.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"company": "accept"}}).status_code == 200
    assert rc.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"emails": "reject"}, "record_only": True}).status_code == 200
    assert rc.post(f"/api/cards/{cid}", json={"fields": {"title": "Owner"}}).status_code == 200
    m = ui.meta(cid); d = json.loads(m["ai_detail"])["decided"]
    assert m["ai_status"] == "checked" and d.get("company") == "accept" and d.get("emails") == "reject"

def test_name_plus_truncated_phone(env):
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="Farid", last_name="Haddad", company="", emails=["fh@a11.example"], phones=[{"type": "work", "number": "(330) 555-0165"}])
    b = mk(ui, store, first_name="Farid", last_name="Haddad", company="Squarecoffe", emails=["f.haddad@b11.example"], phones=[{"type": "work", "number": "555-0165"}])
    cs, metas = ui._active()
    assert a in [x["card_id"] for x in ui.dupes(store.get(b), cs, metas)["queue"]]

def test_merge_does_not_add_misread_email_copy(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Farid", last_name="Copy", emails=["farid@summitridge11.example"], confidence={"emails": 0.97})
    s_ = mk(ui, store, first_name="Farid", last_name="Copy", emails=["farid@summitridgel1.example"], confidence={"emails": 0.45})
    pv = rc.post(f"/api/cards/{s_}/merge-preview", json={"into": t}).json(); assert pv["email_drop"] == ["farid@summitridgel1.example"]
    assert rc.post(f"/api/cards/{s_}", json={"status": "rejected", "merge_into": t}).status_code == 200
    assert store.get(t)["fields"]["emails"] == ["farid@summitridge11.example"]
