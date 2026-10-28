"""Round-13 tests: strict card ids everywhere (skeptic r11 R11-1/2/3), company digit/letter hint, no phantom diff columns."""
import json, pytest
from test_app import mk

BAD_JSON = [True, False, None, 266.0, 1.5, "abc", " 1", "1 ", "1.0", "1e3", "0x10", "-1", 0, -1, 2**31 + 1, 2**63, 2**70,
            99999999999999999999, "", [], {}, [1], "٣", "²"]
BAD_PATH = ["abc", "1.0", "%201", "1e3", "0x10", "0", "-1", str(2**31 + 1), str(2**63), "99999999999999999999", "true", "٣"]

def test_strict_id_rule(env):
    ui = env["ui"]
    for ok_ in (1, "1", "266", 2**31, str(2**31)): assert ui.strict_id(ok_) == int(ok_)
    for b in BAD_JSON:
        with pytest.raises(ui.BadId): ui.strict_id(b)

def test_path_ids_never_500(env):
    rc = env["rev"]
    for p in BAD_PATH:
        for m, u, kw in (("GET", f"/api/cards/{p}", {}), ("POST", f"/api/cards/{p}", {"json": {"fields": {}}}),
                         ("POST", f"/api/cards/{p}/ai-check", {"json": {}}), ("POST", f"/api/cards/{p}/ai-decide", {"json": {"choices": {}}}),
                         ("POST", f"/api/cards/{p}/merge-preview", {"json": {"into": 1}}), ("POST", f"/api/cards/{p}/back", {"files": {"image": ("b.jpg", b"x", "image/jpeg")}}),
                         ("POST", f"/api/admin/cards/{p}/delete", {"json": {}}), ("GET", f"/card/{p}", {})):
            r = env["adm"].request(m, u, **kw) if "admin" in u else rc.request(m, u, **kw)
            assert r.status_code == 422, (m, u, r.status_code)

def test_merge_into_fuzz(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Mo", last_name="Fuzz"); t = mk(ui, store, first_name="Mo", last_name="Fuzz")
    before_a, before_t = store.get(a), store.get(t)
    for b in BAD_JSON + [a, str(a), 999999]:
        r = rc.post(f"/api/cards/{a}", json={"status": "rejected", "merge_into": b, "confirm_redecide": True})
        assert r.status_code == 422, (b, r.status_code, r.text[:120])
    ui.set_meta(t, archived=1)
    r = rc.post(f"/api/cards/{a}", json={"status": "rejected", "merge_into": t}); assert r.status_code == 422 and r.json()["need"] == "merge_archived"
    assert store.get(a)["status"] == before_a["status"] and store.get(t)["fields"] == before_t["fields"]
    ui.set_meta(t, archived=0)
    assert rc.post(f"/api/cards/{a}", json={"status": "rejected", "merge_into": str(t)}).status_code == 200   # digit string is fine

def test_merge_preview_and_keep_apart_fuzz(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store)
    for b in BAD_JSON:
        assert rc.post(f"/api/cards/{a}/merge-preview", json={"into": b}).status_code == 422, b
        if isinstance(b, list): continue
        assert rc.post(f"/api/cards/{a}", json={"keep_apart": [b]}).status_code == 422, b
        if b not in (None, ""): assert rc.post(f"/api/cards/{a}", json={"card_id": b, "fields": {}}).status_code == 422, b

def test_bulk_ids_fuzz(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Bulk", last_name="Fuzz")
    for b in BAD_JSON:
        for ids in ([b], [a, b]):
            r = rc.post("/api/cards-bulk", json={"ids": ids, "status": "rejected", "versions": {}})
            assert r.status_code == 422, (ids, r.status_code)
    for ids in ("266", str(a), {"a": 1}, None, True, [a, a], [a, 999999]):
        assert rc.post("/api/cards-bulk", json={"ids": ids, "status": "rejected", "versions": {}}).status_code == 422, ids
    assert store.get(a)["status"] == "pending"
    assert rc.post("/api/cards-bulk", json={"ids": [a], "status": "rejected"}).status_code == 200 and store.get(a)["status"] == "rejected"

def test_undo_id_fuzz(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store); rc.post(f"/api/cards/{cid}", json={"fields": {"title": "R13 undo keep"}})
    for b in BAD_JSON:
        r = rc.post("/api/undo", json={"id": b}); assert r.status_code == 422, (b, r.status_code)
    assert store.get(cid)["fields"]["title"] == "R13 undo keep"

def test_ai_check_guards(env, monkeypatch):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store); ui.set_meta(a, archived=1)
    assert rc.post(f"/api/cards/{a}/ai-check", json={}).status_code == 409
    assert rc.post("/api/cards/999999/ai-check", json={}).status_code == 404
    monkeypatch.setattr(ui, "maybe_ai_check", lambda cid, force=False: "queued"); monkeypatch.setattr(ui, "ai_progress", lambda cid: {})
    ui.AI_MANUAL.clear(); b = mk(ui, store)
    codes = [rc.post(f"/api/cards/{b}/ai-check", json={}).status_code for _ in range(ui.AI_MANUAL_MAX + 2)]
    assert codes[:ui.AI_MANUAL_MAX] == [200] * ui.AI_MANUAL_MAX and codes[-1] == 429
    assert env["rev2"].post(f"/api/cards/{b}/ai-check", json={}).status_code == 404   # v0.4.6 #1: not rev2's card
    assert env["adm"].post(f"/api/cards/{b}/ai-check", json={}).status_code == 200   # the limit is per person
    ui.AI_MANUAL.clear()

def test_company_digit_letter_hint():
    from app import plausibility as p
    h = [x for x in p.check({"company": "R1O Testworks LLC"}) if x["code"] == "company_digits"]
    assert h and h[0]["suggestion"] == "R10 Testworks LLC"   # round 15 (manager r14 L-r14-1): R10, not RIO
    for c in ("3M Company", "A1 Plumbing", "B2B Supply", "Route 66 Diner", "Studio 54", "Area51 Labs"):
        assert not [x for x in p.check({"company": c}) if x["code"] == "company_digits"], c

def test_same_second_batches_stay_apart(env):
    """part-timer r5: two people starting a batch in the same second got one batch id."""
    ui, store = env["ui"], env["store"]
    a = mk(ui, store); ui.set_meta(a, batch="B20261014105555", batch_label="QA-PT pair2")
    assert ui.batch_for("B20261014105555", "QA-PT pair2") == "B20261014105555"
    assert ui.batch_for("B20261014105555", " qa-pt  PAIR2 ") == "B20261014105555"
    o = ui.batch_for("B20261014105555", "R11 QA qa-rev"); assert o != "B20261014105555" and o == ui.batch_for("B20261014105555", "R11 QA qa-rev")
    assert ui.batch_for("B-new", "x", "AA") == "B-new"
    assert ui.batch_for("B-new", "x", "BB") != "B-new"          # same id, same name, another person: own batch
    assert ui.batch_for("B-new", "x", "AA") == "B-new"

def test_merge_preview_reasons(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Avery", last_name="Why", title="Owner", address="1 Main St, Akron, OH 44308", emails=[])
    s_ = mk(ui, store, first_name="Avery", last_name="Why", title="Regional Owner", address="1 Main St,  Akron, OH 44308", emails=["avery@whyexample"])
    pv = rc.post(f"/api/cards/{s_}/merge-preview", json={"into": t}).json()
    tr = [x for x in pv["rows"] if x["field"] == "title"]
    assert tr and tr[0]["keep"] == "tgt" and tr[0].get("why") != "fails_check"   # round 15 (coordinator r14 #5): keep the clean title, the longer one goes to the note
    assert not [x for x in pv["rows"] if x["field"] == "address"]         # part-timer r5: same address, only spacing differs
    assert pv["email_drop"] == ["avery@whyexample"] and pv["email_drop_why"]["avery@whyexample"] == "fails_check"   # N2: target has no email

def test_blank_first_name_save_refused(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Keep")
    r = rc.post(f"/api/cards/{a}", json={"fields": {"first_name": "  "}}); assert r.status_code == 422 and store.get(a)["fields"]["first_name"] == "Keep"
    b = mk(ui, store, first_name="")
    assert rc.post(f"/api/cards/{b}", json={"fields": {"first_name": "", "title": "X"}}).status_code == 200   # read without one: still saveable

def test_rejected_card_keeps_hints(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Rej", last_name="Hint", company="", website="")
    before = [x["code"] for x in rc.get(f"/api/cards/{a}").json()["card"]["attention"]] if "attention" in rc.get(f"/api/cards/{a}").json().get("card", {}) else None
    assert rc.post(f"/api/cards/{a}", json={"status": "rejected"}).status_code == 200
    q = [c for c in rc.get("/api/cards").json() if c["id"] == a][0]
    assert any(x["code"] == "missing" for x in q["attention"]) and q["conf"] is None or q["conf"] < 0.6
