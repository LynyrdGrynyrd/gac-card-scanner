"""AIFILL (2026-11-20): the local AI reads every card in full and its reading FILLS the review form when the card is still
untouched; otherwise it is suggested as before. Cards are the generated test cards (fictional people); the model is stubbed."""
import json, os, time
import pytest
from test_app import mk

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CARD3 = os.path.join(ROOT, "tests", "cards", "card3_dark.jpg")
CARD1 = os.path.join(ROOT, "tests", "cards", "card1_left.jpg")
# OCR reads these cards a little differently on each platform (Mac vs the Linux CI runner), so NO test asserts a literal OCR
# result: what the rules read comes from a scan at run time, and the stubbed model's answer is built from it (same values,
# only the title lengthened, which the merge takes by construction).
_BASE = {}
def base3():
    if not _BASE:
        from app import pipeline
        _BASE.update(pipeline.scan(open(CARD3, "rb").read(), use_vlm=False)["fields"])
    return _BASE
def old(): return base3()["title"]                  # the title the rules read
def new(): return old() + " Strategy"                # the model's longer title
def ans3(**over):
    f = base3()
    return {"first_name": f.get("first_name") or "", "last_name": f.get("last_name") or "", "title": new(), "company": f.get("company") or "",
            "department": f.get("department") or "", "emails": list(f.get("emails") or []), "website": f.get("website") or "", "address": f.get("address") or "",
            "phones": [{"type": q["type"], "number": q["number"]} for q in f.get("phones") or []]} | over

def scanned(env, path=CARD3):
    """A really scanned pending card (OCR + rules), like an upload makes it."""
    ui = env["ui"]
    cid, src = ui.ingest(open(path, "rb").read(), None, ".jpg", meta_kw={"batch": "aifill", "batch_label": "AIFILL"})
    ui.set_meta(cid, field_sources=json.dumps(src)); ui.log(cid, "RR", "scanned", None, "pending", {"file": os.path.basename(path)})
    return cid

def stub(monkeypatch, ui, answer, seen=None, during=None):
    from app import vlm
    def ext(data, ocr_text="", **kw):
        if seen is not None: seen.append(kw)
        if during: during()
        return answer
    monkeypatch.setattr(vlm, "extract", ext)

def run(ui, cid): ui._ai_run(cid, ["read"]); return ui.meta(cid), json.loads(ui.meta(cid)["ai_detail"])

def test_every_pending_card_with_a_photo_is_queued(env, monkeypatch):
    ui, st = env["ui"], env["store"]; from app import auth
    monkeypatch.setattr(ui, "ai_available", lambda: True); monkeypatch.setattr(auth, "get_setting", lambda k: "1" if k == "ai_check_enabled" else None)
    monkeypatch.setattr(ui, "ai_reason", lambda f: None)   # the rules are "sure" of every card here (by construction, not by what OCR reads): it is queued all the same
    sure = scanned(env, CARD1)
    assert ui.maybe_ai_check(sure) == "queued"; ui.AI_WAIT.pop(sure, None)
    qr = scanned(env); f = st.get(qr)["fields"]; f["sources"]["qr"] = "vcard"; st.update(qr, fields=f)
    assert ui.maybe_ai_check(qr) == "not needed"   # QR cards are exact already
    nophoto = mk(ui, st); assert ui.maybe_ai_check(nophoto) == "skip"
    monkeypatch.setattr(ui, "ai_available", lambda: False); assert ui.maybe_ai_check(scanned(env, CARD1)) == "unavailable"
    monkeypatch.setattr(auth, "get_setting", lambda k: "0"); assert ui.maybe_ai_check(sure) == "off"
    assert ui.AI_MAX_WAIT == int(os.environ.get("AI_MAX_WAIT", "14400"))   # default 4 h: a 38-card stack takes ~1 h 45 min

def test_read_asks_for_all_fields_without_hints(env, monkeypatch):
    ui = env["ui"]; cid = scanned(env); seen = []; stub(monkeypatch, ui, ans3(), seen)
    ui._ai_run(cid, ["name"])   # even a narrow reason (today: a subset of fields) reads the whole card
    assert seen == [{}]

def test_reading_fills_the_form_like_the_pipeline(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]; from app import pipeline
    cid = scanned(env); before = st.get(cid)["fields"]; low0 = rev.get(f"/api/cards/{cid}").json()["low"]
    stub(monkeypatch, ui, ans3()); m, det = run(ui, cid)
    expected = pipeline.scan(open(CARD3, "rb").read(), use_vlm=False, vlm_result=ans3())["fields"]   # the pipeline's own merge and the steps after it
    now = st.get(cid)["fields"]; assert now == expected and now["title"] == new()
    assert m["ai_status"] == "checked" and det["applied"] is True and det["changed"] == ["title"]
    assert det["diff"] == {"title": {"from": old(), "to": new()}}
    src = json.loads(m["field_sources"]); assert src["title"] == "ai" and not any(str(v).startswith(("edited", "confirmed")) for v in src.values())
    h = [x for x in ui.history(cid) if x["action"] == "ai_checked"]; assert len(h) == 1 and list(h[0]["detail"]["changed"]) == ["title"] and h[0]["detail"]["applied"]
    d = rev.get(f"/api/cards/{cid}").json(); assert d["ai_detail"]["applied"] and d["sources"]["title"] == "ai"
    assert set(low0) <= set(d["low"]) and "title" in d["low"]   # what the rules doubted stays doubted: the AI's source never counts as a person's check

def test_disagreement_shows_check(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]; cid = scanned(env, CARD1)
    f = st.get(cid)["fields"]; e = f["emails"][0]; i = next(k for k, ch in enumerate(e.split("@")[0]) if ch.isalpha())
    ans = {"first_name": f["first_name"], "last_name": f["last_name"], "emails": [e[:i] + "0" + e[i + 1:]]}   # a letter read differently (same domain)
    stub(monkeypatch, ui, ans); m, det = run(ui, cid)
    assert st.get(cid)["fields"]["emails"] == f["emails"] and det["applied"] and det["diff"] == {}   # no value changed ...
    assert "emails" in rev.get(f"/api/cards/{cid}").json()["low"]   # ... but rules and model disagree: Check, not dropped as "AI found nothing"

GUARDS = {
    "edited": lambda env, cid: env["rev"].post(f"/api/cards/{cid}", json={"fields": {"company": "Edited Co"}}),
    "confirmed": lambda env, cid: env["ui"].set_meta(cid, field_sources=json.dumps({"company": "confirmed:RR"})),
    "this_is_correct": lambda env, cid: env["store"].update(cid, fields=dict(env["store"].get(cid)["fields"], confirmed_ok={"company": "x"}, confirmed_by={"company": "RR"})),   # confirm-correct marks fields only
    "draft": lambda env, cid: env["ui"].db().execute("INSERT INTO drafts(user_id,card_id,vals,version,ts) VALUES(1,?,?,?,?)", (cid, '{"title": "Dir"}', "v", time.time())) and None,
    "decided": lambda env, cid: env["store"].update(cid, status="approved", reviewer="RR", note=""),
    "archived": lambda env, cid: env["ui"].set_meta(cid, archived=1),
    "exported": lambda env, cid: env["ui"].set_meta(cid, exported=time.time()),
    "in_import_file": lambda env, cid: env["ui"].db().execute("INSERT INTO exports(ts, username, initials, kind, filter, count, filename, card_ids) VALUES(?,?,?,?,?,?,?,?)",
                                                              (time.time(), "admin", "EA", "xlsx", "approved", 1, "x.xlsx", json.dumps([cid]))) and None,   # the card is in an MC Trade file
    "merged_from": lambda env, cid: env["ui"].log(cid, "RR", "merged_from", detail={"card": 1, "added": {}}),   # details from a duplicate: pipeline.scan would drop them
    "back_added": lambda env, cid: env["ui"].log(cid, "RR", "back_added", detail={"filled": []}),
}
@pytest.mark.parametrize("why", sorted(GUARDS))
def test_guard_turns_apply_into_suggestions(env, monkeypatch, why):
    ui, st = env["ui"], env["store"]; cid = scanned(env); f0 = st.get(cid)["fields"]
    GUARDS[why](env, cid); f1 = st.get(cid)["fields"]
    calls = []; real = ui.scan_limited; monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: calls.append(1) or real(*a, **k))
    stub(monkeypatch, ui, ans3()); m, det = run(ui, cid)
    assert st.get(cid)["fields"] == f1 and st.get(cid)["fields"]["title"] == old()   # nothing on the card changed
    assert m["ai_status"] == "suggested" and det["applied"] is False and det["diff"]["title"]["to"] == new(), det
    assert not calls   # no second OCR for a card that only gets suggestions
    if why == "edited": assert f1 != f0   # (the test's own edit)

def test_version_changed_during_the_read(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env)
    def edit_meanwhile():   # a change that is neither a person's edit nor a draft: only the version tells
        f = st.get(cid)["fields"]; f["website"] = "www.fphealth.example"; st.update(cid, fields=f)
    stub(monkeypatch, ui, ans3(), during=edit_meanwhile); m, det = run(ui, cid)
    assert m["ai_status"] == "suggested" and st.get(cid)["fields"]["title"] == old() and st.get(cid)["fields"]["website"] == "www.fphealth.example"

def test_cancelled_check_changes_nothing(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env); f0 = st.get(cid)["fields"]
    stub(monkeypatch, ui, ans3(), during=lambda: ui.set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"note": "the card was decided before the AI check finished (check cancelled)"})))
    ui._ai_run(cid, ["read"]); assert st.get(cid)["fields"] == f0 and ui.meta(cid)["ai_status"] == "skipped"

def test_failed_reread_or_bad_value_falls_back_to_suggestions(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env); cid2 = scanned(env)
    def boom(*a, **k): raise RuntimeError("reader down")
    monkeypatch.setattr(ui, "scan_limited", boom); stub(monkeypatch, ui, ans3()); m, det = run(ui, cid)
    assert m["ai_status"] == "suggested" and st.get(cid)["fields"]["title"] == old()
    c = st.get(cid2); bad = {"fields": dict(c["fields"], title="=cmd|' /C calc'!A0")}   # a formula: refused like at every other write
    ui.set_meta(cid2, ai_status="checking")
    with ui.WRITE_LOCK, st.tx(): assert ui._ai_apply(cid2, c, bad, ["read"], 1.0) is False
    assert st.get(cid2)["fields"]["title"] == old()

def test_second_reading_only_suggests(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env)
    stub(monkeypatch, ui, ans3()); run(ui, cid); assert json.loads(ui.meta(cid)["ai_detail"])["applied"]
    stub(monkeypatch, ui, ans3(address=base3()["address"] + " Suite 9")); m, det = run(ui, cid)   # e.g. a manual "Check again with AI": a longer address (taken by construction)
    assert m["ai_status"] == "suggested" and not det["applied"] and "address" in det["diff"] and st.get(cid)["fields"]["title"] == new()

def test_vlm_answer_reaches_the_ocr_child_as_ascii_json(env, monkeypatch):
    ui = env["ui"]; from app import reader
    ans = {"first_name": "Jörg", "last_name": "Weißmann", "title": "Leiter Qualität", "emails": []}
    got = []; monkeypatch.setattr(reader, "_call", lambda args, data, key=None, **k: got.append(args) or {"ocr": 1}.get("ocr"))
    monkeypatch.setattr(ui, "OCR_CHILD", True); ui.scan_limited(b"x", None, vlm_result=ans)
    a = got[0]; assert a[0] == "ocr" and a[2].isascii() and json.loads(a[2]) == ans   # survives a Windows argv
    with pytest.raises(reader.ReaderError): reader.run_ocr(b"x", None, vlm_result={"title": "x" * (reader.VLM_ARG_MAX + 1)})   # too long: refused, not cut
    from app import pipeline; seen = []
    monkeypatch.setattr(pipeline, "scan", lambda data, engine=None, use_vlm=None, vlm_result=None: seen.append(vlm_result) or {"engine": "e", "text": "t", "fields": {}})
    out = os.path.join(ui.UP, "aifill_child.bin"); open(out, "wb").write(b"x")
    monkeypatch.setenv("GAC_READER_OUT", os.path.join(ui.UP, "aifill_child.json"))
    assert reader._main(["ocr", out, "", json.dumps(ans, ensure_ascii=True)]) and seen == [ans] and seen[0]["first_name"] == "Jörg"
    for x in (out, os.path.join(ui.UP, "aifill_child.json")):
        if os.path.exists(x): os.remove(x)

# ---- review round 1 (2026-11-20)
def applied_card(env, monkeypatch, ans=None):
    ui = env["ui"]; cid = scanned(env); stub(monkeypatch, ui, ans or ans3()); run(ui, cid); assert json.loads(ui.meta(cid)["ai_detail"])["applied"]; return cid

def test_f2_second_reading_keeps_ai_fields_checked(env, monkeypatch):
    ui, rev = env["ui"], env["rev"]; cid = applied_card(env, monkeypatch)
    assert "title" in rev.get(f"/api/cards/{cid}").json()["low"]
    m, det = run(ui, cid)   # a manual "Check with AI" with the same answer: nothing differs
    assert not det["applied"] and det["diff"] == {} and m["ai_status"] == "checked"
    assert json.loads(m["field_sources"])["title"] == "ai" and "title" in rev.get(f"/api/cards/{cid}").json()["low"]

@pytest.mark.parametrize("what", ["save", "draft"])
def test_f4_change_during_the_reread_is_caught_by_the_check_under_the_lock(env, monkeypatch, what):
    ui, st, rev = env["ui"], env["store"], env["rev"]; cid = scanned(env); real = ui.scan_limited
    def reread(*a, **k):   # between the first check and the one under the lock
        if what == "save": assert rev.post(f"/api/cards/{cid}", json={"fields": {"company": "Typed Co"}}).status_code == 200
        else:
            with ui.db() as c_: c_.execute("INSERT INTO drafts(user_id,card_id,vals,version,ts) VALUES(1,?,?,?,?)", (cid, '{"company": "Typed Co"}', "v", time.time()))
        return real(*a, **k)
    monkeypatch.setattr(ui, "scan_limited", reread); stub(monkeypatch, ui, ans3()); m, det = run(ui, cid)
    assert m["ai_status"] == "suggested" and not det["applied"] and st.get(cid)["fields"]["title"] == old()
    if what == "save": assert st.get(cid)["fields"]["company"] == "Typed Co"

def test_f5_dropped_keys_are_recorded_and_a_core_less_reread_is_not_stored(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env)
    f = st.get(cid)["fields"]; f["custom_x"] = "kept me"; st.update(cid, fields=f)   # a stored key outside the review form that the re-read does not have
    stub(monkeypatch, ui, ans3()); m, det = run(ui, cid); assert det["applied"] and "custom_x" not in st.get(cid)["fields"]
    h = [x for x in ui.history(cid) if x["action"] == "ai_checked"][-1]["detail"]["changed"]
    assert h["custom_x"]["from"] == "kept me" and "title" in h and "confidence" not in h and "boxes" not in h
    c2 = scanned(env); c = st.get(c2); ui.set_meta(c2, ai_status="checking")
    for bad in (None, {}, {"fields": None}, {"fields": {"first_name": "A", "last_name": "B"}}, {"fields": {"title": "x"}}):
        with ui.WRITE_LOCK, st.tx(): assert ui._ai_apply(c2, c, bad, ["read"], 1.0) is False
    assert st.get(c2)["fields"] == c["fields"]

# ---- review round 2 (2026-11-20)
def test_g5_empty_means_none_or_blank_and_the_shape_is_checked(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env)
    f = st.get(cid)["fields"]; f["custom_n"] = 0; f["custom_b"] = False; st.update(cid, fields=f)   # values, not "empty"
    stub(monkeypatch, ui, ans3()); run(ui, cid)
    h = [x for x in ui.history(cid) if x["action"] == "ai_checked"][-1]["detail"]["changed"]
    assert h["custom_n"]["from"] == 0 and h["custom_b"]["from"] is False
    assert not ui._same(0, False) and not ui._same(False, None) and ui._same("", None) and ui._same([], None) and ui._same("a", "a")   # type-aware: only None, "" and [] are empty
    c2 = scanned(env); c = st.get(c2); ui.set_meta(c2, ai_status="checking"); good = dict(c["fields"])
    for k, v in (("title", 5), ("emails", "a@b.co"), ("phones", [None]), ("emails", [3]), ("emails", None), ("phones", None), ("address", {"x": 1}), ("title", "x" * 5000)):
        with ui.WRITE_LOCK, st.tx(): assert ui._ai_apply(c2, c, {"fields": dict(good, **{k: v})}, ["read"], 1.0) is False, (k, v)
    assert st.get(c2)["fields"] == good

# ---- H1: a reading that is not applied says why (code only, never a card value)
def test_h1_not_applied_reason_codes(env, monkeypatch, capsys):
    ui, st, rev = env["ui"], env["store"], env["rev"]; real = ui.scan_limited
    def why_of(cid):
        det = json.loads(ui.meta(cid)["ai_detail"]); h = [x for x in ui.history(cid) if x["action"] == "ai_checked"][-1]["detail"]
        assert h["not_applied"] == det["not_applied"] and det["applied"] is False and det["diff"]   # same code in both; the reading is still offered as suggestions
        assert f"AI reading not applied on card {cid}: {det['not_applied']}" in capsys.readouterr().out
        return det["not_applied"]
    stub(monkeypatch, ui, ans3()); c1, c2, c3, c4, c5 = (scanned(env) for _ in range(5))   # (ingest also uses scan_limited: scan first, patch after)
    GUARDS["draft"](env, c1); run(ui, c1); assert why_of(c1) == "touched:draft"   # pre-check
    monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("reader down"))); run(ui, c2)
    assert why_of(c2) == "reread_failed"
    def save_meanwhile(*a, **k):
        rev.post(f"/api/cards/{c3}", json={"fields": {"company": "Typed Co"}}); return real(*a, **k)
    monkeypatch.setattr(ui, "scan_limited", save_meanwhile); run(ui, c3); assert why_of(c3) == "touched_during:version"   # the check under the lock
    monkeypatch.setattr(ui, "scan_limited", real); monkeypatch.setattr(ui, "payload_problems", lambda f: {"title": "no"}); run(ui, c4)
    assert why_of(c4) == "bad_value"   # _ai_apply refused the stored values
    monkeypatch.undo(); stub(monkeypatch, ui, ans3()); m, det = run(ui, c5)
    assert det["applied"] and "not_applied" not in det and "not applied" not in capsys.readouterr().out   # an applied reading carries no reason


# ---- simplified design (2026-11-20): no Keep/Undo; AI fields stay Check until a person edits them
def test_ai_field_stays_check_until_a_person_edits_it(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    low = lambda cid: rev.get(f"/api/cards/{cid}").json()["low"]
    plain = scanned(env); t_low = "title" in low(plain)   # a card with no AI change keeps today's flags (whatever the rules made of the title on this platform)
    cid = applied_card(env, monkeypatch); assert "title" in low(cid)
    rev.post(f"/api/cards/{cid}", json={"fields": {"company": "Edited Co"}})   # a save that did not touch the field
    assert "title" in low(cid) and json.loads(ui.meta(cid)["field_sources"])["title"] == "ai"
    rev.post(f"/api/cards/{cid}", json={"fields": {"title": "Head of Marketing"}})   # the person edits it
    assert "title" not in low(cid) and json.loads(ui.meta(cid)["field_sources"])["title"].startswith("edited:")
    c2 = applied_card(env, monkeypatch); assert "title" in low(c2)
    st.update(c2, status="approved", reviewer="RR", note="")   # decided: the AI's fields are no longer listed
    assert ("title" in low(c2)) == t_low   # only the AI's flag is gone
    c3 = scanned(env); GUARDS["edited"](env, c3); stub(monkeypatch, ui, ans3()); run(ui, c3)   # a SUGGESTED reading sets no "ai" source
    assert "ai" not in json.loads(ui.meta(c3)["field_sources"]).values() and ("title" in low(c3)) == t_low

def test_name_flag_stays_while_either_part_is_the_ais(env):
    ui, st = env["ui"], env["store"]; f = st.get(scanned(env))["fields"]
    assert "name" in ui.low_fields(f, {"first_name": "ai"}) and "name" in ui.low_fields(f, {"last_name": "ai"})
    assert "name" in ui.low_fields(f, {"first_name": "ai", "last_name": "edited:RR"}) and "name" in ui.low_fields(f, {"first_name": "edited:RR", "last_name": "ai"})
    assert "name" not in ui.low_fields(f, {"first_name": "edited:RR", "last_name": "edited:RR"})
    assert {"department", "credentials", "other_address"} <= set(ui.low_fields(f, {"department": "ai", "credentials": "ai", "other_address": "ai"})) and "social" not in ui.low_fields(f, {"social": "ai"})

def test_a_choice_on_an_applied_row_is_refused(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]; cid = applied_card(env, monkeypatch); before = (st.get(cid)["fields"], ui.meta(cid)["field_sources"])
    for ch in ("accept", "reject"):
        r = rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"title": ch}}); assert r.status_code == 409 and r.json()["need"] == "stale_suggestion", ch
    assert (st.get(cid)["fields"], ui.meta(cid)["field_sources"]) == before and "decided" not in json.loads(ui.meta(cid)["ai_detail"])
