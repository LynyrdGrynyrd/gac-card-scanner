"""Round-14 tests: archived cards are read-only (skeptic r12), a no-op save makes no undo entry, a repeated AI request
doesn't move the card back, rejected cards keep look-alike hints (reviewer r12), the look-alike index finds the same pairs,
bulk refusals name the problem (coordinator r6), shared reading line count."""
import json, time
from test_app import mk

def _n_actions(ui): return ui.db().execute("SELECT COUNT(*) FROM actions").fetchone()[0]

def test_archived_refused_everywhere(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Arch", last_name="Ived"); t = mk(ui, store, first_name="Arch", last_name="Other")
    ui.set_meta(a, archived=1); before = store.get(a)
    for body in ({"fields": {"company": "X"}}, {"status": "approved"}, {"status": "rejected"}, {"status": "rejected", "merge_into": t}):
        r = rc.post(f"/api/cards/{a}", json=body); assert r.status_code == 409 and r.json()["need"] == "archived", (body, r.text)
    assert rc.post(f"/api/cards/{a}/ai-decide", json={"choices": {"company": "accept"}}).status_code == 409
    assert rc.post(f"/api/cards/{a}/back", files={"image": ("b.jpg", b"x" * 10, "image/jpeg")}).status_code == 409
    r = rc.post("/api/cards-bulk", json={"ids": [t, a], "status": "rejected"}); assert r.status_code == 409 and r.json()["need"] == "archived"
    assert store.get(t)["status"] == "pending" and store.get(a) == before

def test_noop_save_no_undo(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="No", last_name="Op", company="Same Co")
    n0 = _n_actions(ui)
    assert rc.post(f"/api/cards/{a}", json={"fields": {"company": "Same Co"}}).status_code == 200
    assert _n_actions(ui) == n0
    assert rc.post(f"/api/cards/{a}", json={"fields": {"company": "Other Co"}}).status_code == 200
    assert _n_actions(ui) == n0 + 1

def test_ai_rerequest_keeps_place(env, monkeypatch):
    ui, store = env["ui"], env["store"]
    monkeypatch.setattr(ui, "ai_available", lambda: True)
    a = mk(ui, store, first_name="Ai", last_name="Again")
    with store.db() as c: c.execute("UPDATE cards SET image='x.jpg' WHERE id=?", (a,))
    ui.AI_WAIT.pop(a, None)
    assert ui.maybe_ai_check(a, force=True) == "queued"; k1 = ui.AI_WAIT[a]; turns = dict(ui.AI_TURN)
    for _ in range(3): assert ui.maybe_ai_check(a, force=True) == "already"
    assert ui.AI_WAIT[a] == k1 and ui.AI_TURN == turns
    ui.AI_WAIT.pop(a, None)

def test_rejected_keeps_lookalikes(env):
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="Rhea", last_name="Lookalike", phones=[{"number": "330-555-0101", "type": "work"}])
    b = mk(ui, store, first_name="Rhea", last_name="Lookalike", phones=[{"number": "330-555-0101", "type": "work"}])
    cs, ms = ui._active(); q = ui.dupes(store.get(a), cs, ms)["queue"]; assert any(x["card_id"] == b for x in q)
    store.update(a, status="rejected"); store.update(b, status="rejected")
    cs, ms = ui._active(); d = ui.dupes(store.get(a), cs, ms)
    assert any(x["card_id"] == b for x in d["queue"]) and not d["unresolved_queue"]
    assert all(not x["blocking"] for x in d["queue"])

def test_index_finds_misread_name(env):
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="Jonathan", last_name="Pemberton", company="Akron Widgets", emails=["jp@akronwidgets.com"])
    b = mk(ui, store, first_name="Jonathon", last_name="Pemberton", company="Akron Widgets")
    cs, ms = ui._active()
    assert any(x["card_id"] == b for x in ui.dupes(store.get(a), cs, ms)["queue"])
    # cached second call gives the same answer, and an edit is seen at once
    assert any(x["card_id"] == b for x in ui.dupes(store.get(a), cs, ms)["queue"])
    store.update(b, fields=store.get(b)["fields"] | {"first_name": "Zed", "last_name": "Quill", "company": "Other"})
    cs, ms = ui._active()
    assert not any(x["card_id"] == b for x in ui.dupes(store.get(a), cs, ms)["queue"])

def test_bulk_refusal_names_field(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Bad", last_name="Mail", emails=["not-an-email"])
    r = rc.post("/api/cards-bulk", json={"ids": [a], "status": "approved"}).json()
    sk = [x for x in r.get("skipped", []) if x["id"] == a]
    assert sk and "email" in sk[0]["why"].lower(), r

def test_jobs_queue_ahead(env):
    ui, rc = env["ui"], env["rev"]
    with ui.JLOCK:
        ui.JOBS["aaaaaaaaaaa1"] = {"id": "aaaaaaaaaaa1", "state": "queued", "batch": "x", "created": time.time() - 5}
        ui.JOBS["aaaaaaaaaaa2"] = {"id": "aaaaaaaaaaa2", "state": "queued", "batch": "y", "created": time.time()}
    try:
        n1 = rc.get("/api/jobs?ids=aaaaaaaaaaa2").json()["queue_ahead"]
        with ui.JLOCK: ui.JOBS["aaaaaaaaaaa1"]["state"] = "done"
        assert n1 >= 1 and rc.get("/api/jobs?ids=aaaaaaaaaaa2").json()["queue_ahead"] == n1 - 1
    finally:
        with ui.JLOCK: ui.JOBS.pop("aaaaaaaaaaa1", None); ui.JOBS.pop("aaaaaaaaaaa2", None)

def test_merge_replaces_truncated_phone_and_garbled_address(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Farid", last_name="Haddad", phones=[{"number": "555-0165", "type": "work"}], address="380oEmbassy Pkwy, Akron, OH 44333")
    a = mk(ui, store, first_name="Farid", last_name="Haddad", phones=[{"number": "(330) 555-0165", "type": "work"}], address="3800 Embassy Pkwy, Akron, OH 44333")
    assert rc.post(f"/api/cards/{a}", json={"status": "rejected", "merge_into": t}).status_code == 200
    f = store.get(t)["fields"]
    assert [p["number"] for p in f["phones"]] == ["(330) 555-0165"], f["phones"]
    assert f["address"].startswith("3800 Embassy"), f["address"]

def test_merge_preview_shows_spacing_only(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Sq", last_name="Coffee", company="Squarecoffee")
    a = mk(ui, store, first_name="Sq", last_name="Coffee", company="Square Coffee")
    rows = rc.post(f"/api/cards/{a}/merge-preview", json={"into": t}).json()["rows"]
    assert any(r["field"] == "company" and r["keep"] == "src" for r in rows), rows   # v0.4.1 #5: says what the merge really keeps (this card's)

def test_bulk_dry_run_changes_nothing(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Dry", last_name="Run", emails=["dry@run.example.com"])
    n0 = _n_actions(ui)
    r = rc.post("/api/cards-bulk", json={"ids": [a], "status": "approved", "dry_run": True}).json()
    assert r["dry_run"] and "ai_pending" in r and store.get(a)["status"] == "pending" and _n_actions(ui) == n0

def test_missing_phone_hint(env):
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="No", last_name="Phone", phones=[])
    cs, ms = ui._active(); att = ui.enrich(store.get(a), cs, ms)["attention"]
    assert any(x["code"] == "missing" and "Phone" in x["text"] for x in att), att

def test_ai_rerequest_not_rate_limited(env, monkeypatch):
    """Asking again for a card already waiting in the AI line is never refused by the per-person limit (it takes no turn)."""
    ui, store, rc = env["ui"], env["store"], env["rev"]
    monkeypatch.setattr(ui, "ai_available", lambda: True); monkeypatch.setattr(ui, "ai_progress", lambda cid: {})
    a = mk(ui, store, first_name="Rate", last_name="Again"); b = mk(ui, store, first_name="Rate", last_name="New")
    with store.db() as c: c.execute("UPDATE cards SET image='x.jpg' WHERE id IN (?, ?)", (a, b))
    ui.AI_WAIT.pop(a, None); ui.AI_WAIT.pop(b, None); ui.AI_MANUAL.clear()
    assert rc.post(f"/api/cards/{a}/ai-check", json={}).status_code == 200
    uid = next(iter(ui.AI_MANUAL)); ui.AI_MANUAL[uid] = [time.time()] * ui.AI_MANUAL_MAX   # the limit is reached
    r = rc.post(f"/api/cards/{a}/ai-check", json={}); assert r.status_code == 200 and r.json()["status"] == "queued", r.text
    assert len(ui.AI_MANUAL[uid]) == ui.AI_MANUAL_MAX   # no extra turn counted
    assert rc.post(f"/api/cards/{b}/ai-check", json={}).status_code == 429   # a NEW card still is limited
    ui.AI_WAIT.pop(a, None); ui.AI_WAIT.pop(b, None); ui.AI_MANUAL.clear()

def test_lookalike_cache_follows_own_meta_and_data(env):
    """The look-alike cache never answers for other data: an in-place kept_apart change on the card itself (approval_check)
    and a fresh card list with a different status are both seen at once, inside the 3-second window."""
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="Cache", last_name="Twin", phones=[{"number": "330-555-0199", "type": "work"}])
    b = mk(ui, store, first_name="Cache", last_name="Twin", phones=[{"number": "330-555-0199", "type": "work"}])
    ui.set_meta(b, batch="b2", batch_label="B2")   # another batch: a look-alike that "different people" can clear
    cs, ms = ui._active(); c = next(x for x in cs if x["id"] == a)
    assert any(x["card_id"] == b for x in ui.dupes(c, cs, ms)["open"])
    ms.setdefault(a, {})["kept_apart"] = json.dumps([b])   # in place, same objects, same request
    assert not any(x["card_id"] == b for x in ui.dupes(c, cs, ms)["open"])
    ms[a]["kept_apart"] = None
    store.update(b, status="rejected"); cs2, ms2 = ui._active()   # new data right after
    # round 15 (reviewer r14): a rejected twin stays listed as a hint, but never blocks (the cache saw the new status)
    q2 = [x for x in ui.dupes(next(x for x in cs2 if x["id"] == a), cs2, ms2)["queue"] if x["card_id"] == b]
    assert all(x.get("other_status") == "rejected" and not x["blocking"] for x in q2)
