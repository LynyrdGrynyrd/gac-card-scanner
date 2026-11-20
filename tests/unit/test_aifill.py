"""AIFILL (2026-11-20): the local AI reads every card in full and its reading FILLS the review form when the card is still
untouched; otherwise it is suggested as before. Cards are the generated test cards (fictional people); the model is stubbed."""
import json, os, time
import pytest
from test_app import mk

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CARD3 = os.path.join(ROOT, "tests", "cards", "card3_dark.jpg")   # the rules read the title "Directorof Marketing" (the AI lengthens it)
CARD1 = os.path.join(ROOT, "tests", "cards", "card1_left.jpg")   # a clean read: every field sure
ANS3 = {"first_name": "Priya", "last_name": "Raman", "title": "Director of Marketing Strategy", "company": "Firestone Park Health Clinic",
        "department": "", "emails": ["praman@fphealth.org"], "phones": [{"type": "work", "number": "(330) 555-0123"}],
        "website": "www.fphealth.org", "address": "777 E Market St, Akron, OH 44305"}

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
    sure = scanned(env, CARD1); assert ui.ai_reason(st.get(sure)["fields"]) is None   # the rules were sure: not "doubted"
    assert ui.maybe_ai_check(sure) == "queued"; ui.AI_WAIT.pop(sure, None)
    qr = scanned(env); f = st.get(qr)["fields"]; f["sources"]["qr"] = "vcard"; st.update(qr, fields=f)
    assert ui.maybe_ai_check(qr) == "not needed"   # QR cards are exact already
    nophoto = mk(ui, st); assert ui.maybe_ai_check(nophoto) == "skip"
    monkeypatch.setattr(ui, "ai_available", lambda: False); assert ui.maybe_ai_check(scanned(env, CARD1)) == "unavailable"
    monkeypatch.setattr(auth, "get_setting", lambda k: "0"); assert ui.maybe_ai_check(sure) == "off"
    assert ui.AI_MAX_WAIT == int(os.environ.get("AI_MAX_WAIT", "14400"))   # default 4 h: a 38-card stack takes ~1 h 45 min

def test_read_asks_for_all_fields_without_hints(env, monkeypatch):
    ui = env["ui"]; cid = scanned(env); seen = []; stub(monkeypatch, ui, ANS3, seen)
    ui._ai_run(cid, ["name"])   # even a narrow reason (today: a subset of fields) reads the whole card
    assert seen == [{}]

def test_reading_fills_the_form_like_the_pipeline(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]; from app import pipeline
    cid = scanned(env); before = st.get(cid)["fields"]; assert before["title"] == "Directorof Marketing"
    stub(monkeypatch, ui, ANS3); m, det = run(ui, cid)
    expected = pipeline.scan(open(CARD3, "rb").read(), use_vlm=False, vlm_result=ANS3)["fields"]   # the pipeline's own merge and the steps after it
    now = st.get(cid)["fields"]; assert now == expected and now["title"] == "Director of Marketing Strategy"
    assert m["ai_status"] == "checked" and det["applied"] is True and det["changed"] == ["title"]
    assert det["diff"] == {"title": {"from": "Directorof Marketing", "to": "Director of Marketing Strategy"}}
    src = json.loads(m["field_sources"]); assert src["title"] == "ai" and not any(str(v).startswith(("edited", "confirmed")) for v in src.values())
    h = [x for x in ui.history(cid) if x["action"] == "ai_checked"]; assert len(h) == 1 and list(h[0]["detail"]["changed"]) == ["title"] and h[0]["detail"]["applied"]
    d = rev.get(f"/api/cards/{cid}").json(); assert d["ai_detail"]["applied"] and d["sources"]["title"] == "ai"
    assert "emails" in d["low"]   # the rules doubted the email and still do: the AI's source never counts as a person's check

def test_disagreement_shows_check(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]; cid = scanned(env, CARD1)
    assert "emails" not in rev.get(f"/api/cards/{cid}").json()["low"]
    f = st.get(cid)["fields"]; ans = {"first_name": f["first_name"], "last_name": f["last_name"], "emails": ["mdelgad0@summitvalleybank.com"]}   # a letter read differently
    stub(monkeypatch, ui, ans); m, det = run(ui, cid)
    assert st.get(cid)["fields"]["emails"] == f["emails"] and det["applied"] and det["diff"] == {}   # no value changed ...
    assert "emails" in rev.get(f"/api/cards/{cid}").json()["low"]   # ... but rules and model disagree: Check, not dropped as "AI found nothing"

GUARDS = {
    "edited": lambda env, cid: env["rev"].post(f"/api/cards/{cid}", json={"fields": {"company": "Firestone Park Clinic"}}),
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
    stub(monkeypatch, ui, ANS3); m, det = run(ui, cid)
    assert st.get(cid)["fields"] == f1 and st.get(cid)["fields"]["title"] == "Directorof Marketing"   # nothing on the card changed
    assert m["ai_status"] == "suggested" and det["applied"] is False and det["diff"]["title"]["to"] == "Director of Marketing Strategy", det
    assert not calls   # no second OCR for a card that only gets suggestions
    if why == "edited": assert f1 != f0   # (the test's own edit)

def test_version_changed_during_the_read(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env)
    def edit_meanwhile():   # a change that is neither a person's edit nor a draft: only the version tells
        f = st.get(cid)["fields"]; f["website"] = "www.fphealth.example"; st.update(cid, fields=f)
    stub(monkeypatch, ui, ANS3, during=edit_meanwhile); m, det = run(ui, cid)
    assert m["ai_status"] == "suggested" and st.get(cid)["fields"]["title"] == "Directorof Marketing" and st.get(cid)["fields"]["website"] == "www.fphealth.example"

def test_cancelled_check_changes_nothing(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env); f0 = st.get(cid)["fields"]
    stub(monkeypatch, ui, ANS3, during=lambda: ui.set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"note": "the card was decided before the AI check finished (check cancelled)"})))
    ui._ai_run(cid, ["read"]); assert st.get(cid)["fields"] == f0 and ui.meta(cid)["ai_status"] == "skipped"

def test_failed_reread_or_bad_value_falls_back_to_suggestions(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env); cid2 = scanned(env)
    def boom(*a, **k): raise RuntimeError("reader down")
    monkeypatch.setattr(ui, "scan_limited", boom); stub(monkeypatch, ui, ANS3); m, det = run(ui, cid)
    assert m["ai_status"] == "suggested" and st.get(cid)["fields"]["title"] == "Directorof Marketing"
    c = st.get(cid2); bad = {"fields": dict(c["fields"], title="=cmd|' /C calc'!A0")}   # a formula: refused like at every other write
    ui.set_meta(cid2, ai_status="checking")
    with ui.WRITE_LOCK, st.tx(): assert ui._ai_apply(cid2, c, bad, ["read"], 1.0) is False
    assert st.get(cid2)["fields"]["title"] == "Directorof Marketing"

def test_second_reading_only_suggests(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env)
    stub(monkeypatch, ui, ANS3); run(ui, cid); assert json.loads(ui.meta(cid)["ai_detail"])["applied"]
    stub(monkeypatch, ui, dict(ANS3, title="Director of Marketing Strategy Lead")); m, det = run(ui, cid)   # e.g. a manual "Check again with AI"
    assert m["ai_status"] == "suggested" and not det["applied"] and st.get(cid)["fields"]["title"] == "Director of Marketing Strategy"

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
def applied_card(env, monkeypatch, ans=ANS3):
    ui = env["ui"]; cid = scanned(env); stub(monkeypatch, ui, ans); run(ui, cid); assert json.loads(ui.meta(cid)["ai_detail"])["applied"]; return cid

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
    monkeypatch.setattr(ui, "scan_limited", reread); stub(monkeypatch, ui, ANS3); m, det = run(ui, cid)
    assert m["ai_status"] == "suggested" and not det["applied"] and st.get(cid)["fields"]["title"] == "Directorof Marketing"
    if what == "save": assert st.get(cid)["fields"]["company"] == "Typed Co"

def test_f5_dropped_keys_are_recorded_and_a_core_less_reread_is_not_stored(env, monkeypatch):
    ui, st = env["ui"], env["store"]; cid = scanned(env)
    f = st.get(cid)["fields"]; f["custom_x"] = "kept me"; st.update(cid, fields=f)   # a stored key outside the review form that the re-read does not have
    stub(monkeypatch, ui, ANS3); m, det = run(ui, cid); assert det["applied"] and "custom_x" not in st.get(cid)["fields"]
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
    stub(monkeypatch, ui, ANS3); run(ui, cid)
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
    stub(monkeypatch, ui, ANS3); c1, c2, c3, c4, c5 = (scanned(env) for _ in range(5))   # (ingest also uses scan_limited: scan first, patch after)
    GUARDS["draft"](env, c1); run(ui, c1); assert why_of(c1) == "touched:draft"   # pre-check
    monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("reader down"))); run(ui, c2)
    assert why_of(c2) == "reread_failed"
    def save_meanwhile(*a, **k):
        rev.post(f"/api/cards/{c3}", json={"fields": {"company": "Typed Co"}}); return real(*a, **k)
    monkeypatch.setattr(ui, "scan_limited", save_meanwhile); run(ui, c3); assert why_of(c3) == "touched_during:version"   # the check under the lock
    monkeypatch.setattr(ui, "scan_limited", real); monkeypatch.setattr(ui, "payload_problems", lambda f: {"title": "no"}); run(ui, c4)
    assert why_of(c4) == "bad_value"   # _ai_apply refused the stored values
    monkeypatch.undo(); stub(monkeypatch, ui, ANS3); m, det = run(ui, c5)
    assert det["applied"] and "not_applied" not in det and "not applied" not in capsys.readouterr().out   # an applied reading carries no reason


# ---- simplified design (2026-11-20): no Keep/Undo; AI fields stay Check until a person edits them
def test_ai_field_stays_check_until_a_person_edits_it(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    low = lambda cid: rev.get(f"/api/cards/{cid}").json()["low"]
    plain = scanned(env); assert "title" not in low(plain)   # a card with no AI change keeps today's flags
    cid = applied_card(env, monkeypatch); assert "title" in low(cid)
    rev.post(f"/api/cards/{cid}", json={"fields": {"company": "Firestone Park Clinic"}})   # a save that did not touch the field
    assert "title" in low(cid) and json.loads(ui.meta(cid)["field_sources"])["title"] == "ai"
    rev.post(f"/api/cards/{cid}", json={"fields": {"title": "Head of Marketing"}})   # the person edits it
    assert "title" not in low(cid) and json.loads(ui.meta(cid)["field_sources"])["title"].startswith("edited:")
    c2 = applied_card(env, monkeypatch); assert "title" in low(c2)
    st.update(c2, status="approved", reviewer="RR", note="")   # decided: the AI's fields are no longer listed
    assert "title" not in low(c2)
    c3 = scanned(env); GUARDS["edited"](env, c3); stub(monkeypatch, ui, ANS3); run(ui, c3)   # a SUGGESTED reading sets no "ai" source
    assert "ai" not in json.loads(ui.meta(c3)["field_sources"]).values() and "title" not in low(c3)

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
