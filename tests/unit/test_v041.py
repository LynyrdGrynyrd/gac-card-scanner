"""v0.4.1 regression tests (bot reports qa/*-v040.md). Made-up cards only."""
from test_app import mk


def _merge(rc, src, tgt):
    return rc.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt, "card_id": src})


# ---- #2 'Same person?' picks the best match; the server refuses unrelated / other people's merges
def test_merge_unrelated_card_refused(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Maria", last_name="Delgado", emails=["md@v041a.example.com"])
    b = mk(ui, store, first_name="Hiro", last_name="Jorgensen", emails=["hj@v041b.example.com"], company="Other Co")
    r = _merge(rc, a, b); assert r.status_code == 422 and r.json()["need"] == "merge_unrelated"
    assert store.get(a)["status"] == "pending" and store.get(b)["fields"]["emails"] == ["hj@v041b.example.com"]


def test_merge_into_other_users_card_refused(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Taylor", last_name="Fixture", emails=["tf@v041c.example.com"], by="")
    b = mk(ui, store, first_name="Taylor", last_name="Fixture", emails=["tf@v041c.example.com"], by="")
    ui.log(a, "RR", "scanned"); ui.log(b, "QN", "scanned")
    r = _merge(rc, a, b); assert r.status_code == 422 and r.json()["need"] == "merge_other_user"
    ui.log(b, "RR", "scanned")   # only the FIRST scan row counts
    assert _merge(rc, a, b).status_code == 422


def test_merge_same_user_lookalike_allowed(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Grace", last_name="Castellano", emails=["gc@v041d.example.com"])
    b = mk(ui, store, first_name="Grace", last_name="Castellano", emails=["gc@v041d.example.com"])
    ui.log(a, "RR", "scanned"); ui.log(b, "RR", "scanned")
    assert _merge(rc, a, b).status_code == 200


def test_dupes_carry_score_and_owner(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    me = mk(ui, store, first_name="Samir", last_name="Galloway", emails=["sg@v041e.example.com"], phones=[{"type": "work", "number": "330-555-4411"}])
    phone_only = mk(ui, store, first_name="Taylor", last_name="Other", emails=["to@v041f.example.com"], phones=[{"type": "work", "number": "330-555-4411"}])
    exact = mk(ui, store, first_name="Samir", last_name="Galloway", emails=["sg@v041e.example.com"], phones=[{"type": "work", "number": "330-555-4411"}])
    for c_ in (me, exact): ui.log(c_, "RR", "scanned")
    ui.log(phone_only, "QN", "scanned")
    q = {x["card_id"]: x for x in rc.get(f"/api/cards/{me}").json()["dupes"]["queue"]}
    assert exact in q and q[exact]["same_user"] and q[exact]["match"] > q.get(phone_only, {"match": 0})["match"]
    if phone_only in q: assert not q[phone_only]["same_user"]


def test_match_score_parts(env):
    ui = env["ui"]
    assert ui.match_score({"why": ["email exact", "phone exact", "name~0.95"]}) == 2.95
    assert ui.match_score({"why": ["phone exact"]}) == 1.0


# ---- #3 phone clean-up never drops digits; every automatic change is marked
def test_phone_lookalike_letters_become_digits():
    from app import parser
    f = parser.parse("Grace Castellano\nOwner\nT (33O) 555-0178\nM (234) 555-O102\n")
    nums = [p["number"] for p in f["phones"]]
    assert "(330) 555-0178" in nums and "(234) 555-0102" in nums


def test_lookalike_fix_leaves_addresses_alone():
    from app import parser
    assert parser.fix_phone_lookalikes("1 Oak Lane, Stow, OH 44224") == "1 Oak Lane, Stow, OH 44224"
    assert parser.fix_phone_lookalikes("Suite l00") == "Suite l00"


def test_changed_marks_cover_phone_website_company():
    from app import parser, pipeline
    t = "Grace Castellano\nOwner\nT (33O) 555-0178\nM 234-555-0199\nwww .firestoneparkhardw.example.com\nHighland SquareCoffeeCo.\n"
    f = parser.parse(t); f["company"] = "Highland Square CoffeeCo."   # what the spacing clean-up makes of it
    f = pipeline.postfix_marked(f); pipeline.mark_read_changes(f, t); af = f["auto_fixed"]
    assert "website" in af and "www .firestone" in af["website"]
    assert "company" in af and af["company"] == "Highland SquareCoffeeCo."
    assert "phones" in af and any("33O" in p["number"] for p in af["phones"])
    assert f["confidence"]["phones"] <= 0.5   # flagged for a look


def test_unchanged_card_has_no_marks():
    from app import parser, pipeline
    t = "Jonah Dunleavy\nSales Manager\nAcme Example Co\n330-555-0142\njd@acme.example.com\nwww.acme.example.com\n"
    f = parser.parse(t); f = pipeline.postfix_marked(f); pipeline.mark_read_changes(f, t)
    assert f["auto_fixed"] == {}, f["auto_fixed"]


# ---- #4 counts: sheet = READ-ME "Check" lines = export page; #5 'Different' reaches the export
def _approve_mk(ui, st, rev, batch, **f):
    c = mk(ui, st, **f); ui.set_meta(c, batch=batch, batch_label=batch)
    assert rev.post(f"/api/cards/{c}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    return c


def test_summary_to_check_counts_cross_batch_lines(env):
    import json
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = _approve_mk(ui, st, rev, "v41cnt", first_name="Nora", last_name="Quist", emails=["nq@v41cnt.example.com"])
    b = _approve_mk(ui, st, rev, "v41cnt", first_name="Owen", last_name="Rahl", emails=["or@v41cnt.example.com"])
    ui.log(a, "RR", "cross_batch_confirmed", detail={"cards": [999999]})   # approved over a look-alike in another batch
    s = rev.get("/api/export/summary?status=approved_new&batch=v41cnt").json()
    assert s["to_check"] == 1 and s["check_ids"] == [a], s
    chk = rev.get("/api/export/check?status=approved_new&batch=v41cnt").json()
    assert a in chk["flagged"] and b not in chk["flagged"]
    # 'Different' from that card: no longer a double-import warning anywhere
    ui.set_meta(a, kept_apart=json.dumps([999999]))
    s = rev.get("/api/export/summary?status=approved_new&batch=v41cnt").json()
    assert s["to_check"] == 0, s


def test_summary_review_decisions_use_string_keys(env, monkeypatch):
    from app import exporting
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = _approve_mk(ui, st, rev, "v41rv", first_name="Pia", last_name="Sand", emails=["ps@v41rv.example.com"])
    real = exporting.build_export
    def fake(*a_, **k):
        r = list(real(*a_, **k)); sm = dict(r[4]); v = dict(sm["_view"]); v["left"] = [[a, "may be in MC Trade"]]; v["rows"] = []
        sm["_view"] = v; sm["decisions"] = {str(a): "review"}; sm["check_ids"] = []; r[4] = sm; return tuple(r)
    monkeypatch.setattr(exporting, "build_export", fake)
    s = rev.get("/api/export/summary?status=approved_new&batch=v41rv").json()
    assert s["to_check"] == 0 and s["left_out"] == 0, s   # v0.4.9 #1: the counts come from the ONE ready dict built with the file (string keys read fine)


# ---- #5 the merge preview says what the merge really does
def test_merge_preview_matches_result(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    pairs = [({"company": "Highland Square CoffeeCo.", "address": "2300 State Rd,Stow,OH 44224"}, {"company": "Highland Square Coffee Co.", "address": "2300 State Rd, Stow, OH 44224"}),
             ({"title": "Owner"}, {"title": "Regional Owner"}),
             ({"address": "g W Exchange St, Cuyahoga Falls, OH 44223"}, {"address": "9 W Exchange St, Cuyahoga Falls, OH 44223"})]
    for n, (tf, sf) in enumerate(pairs):
        em = [f"hj{n}@v41mp.example.com"]
        t = mk(ui, store, first_name="Hiro", last_name="Jorgensen", emails=em, **tf)
        s_ = mk(ui, store, first_name="Hiro", last_name="Jorgensen", emails=em, **sf)
        before_t, before_s = store.get(t)["fields"], store.get(s_)["fields"]
        pv = rc.post(f"/api/cards/{s_}/merge-preview", json={"into": t}).json()
        assert _merge(rc, s_, t).status_code == 200
        after = store.get(t)["fields"]
        for row in pv["rows"]:
            k = row["field"]
            want = before_s[k] if row["keep"] == "src" else before_t[k]
            assert after.get(k) == want, (n, k, row, after.get(k))
        for k in ("company", "address", "title"):
            if k not in {r["field"] for r in pv["rows"]} and before_t.get(k):
                assert after.get(k) == before_t[k], (n, k)


def test_review_js_safety_rules():
    import os
    js = open(os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui", "views", "review.js"), encoding="utf-8").read()
    assert "e.repeat" in js and "ENTER_PAUSE = 600" in js and "INPUT)$/.test(t)" in js   # #1
    assert 'primary: true, focus: true}]' in js and "sameOpen()" in js
    assert "x.same_user && x.same_batch" in js and "-(x.match || 0)" in js   # #2: best match, not lowest id
    assert 'c.status !== "pending" ? null' in js   # #5: no red block on a decided card


# ---- #8 checks
def test_bestexample_not_blocked_but_lost_dot_is(env):
    ui = env["ui"]
    ok = {"first_name": "Bea", "emails": ["bea@bestexample.com"], "website": "www.bestexample.com", "phones": []}
    h = ui.hard_errors(ok); assert "emails" not in h and "website" not in h, h
    bad = {"first_name": "Grace", "emails": ["g@firestoneparkhardwexample.com"], "website": "www.firestoneparkhardwexample.com", "phones": []}
    h = ui.hard_errors(bad); assert "emails" in h and "website" in h


def test_morg4n_blocks_in_last_name_too(env):
    ui = env["ui"]
    assert "last_name" in ui.hard_errors({"first_name": "Jonah", "last_name": "Morg4n", "emails": [], "phones": []})


def test_soft_company_hint_can_be_confirmed(env):
    ui, st, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Hiro", last_name="Jorgensen", company="Highland Square CoffeeCo.", emails=["hj@v41co.example.com"])
    d = rc.get(f"/api/cards/{cid}").json()
    assert any(a["code"] == "hint" and a["field"] == "company" for a in d["attention"])
    assert rc.post(f"/api/cards/{cid}/confirm-correct", json={"field": "company", "value": "Highland Square CoffeeCo.", "version": d["version"], "reason": "printed like this"}).status_code == 403   # v0.4.5 #2 admins only
    rc = env["adm"]
    r = rc.post(f"/api/cards/{cid}/confirm-correct", json={"field": "company", "value": "Highland Square CoffeeCo.", "version": d["version"], "reason": "printed like this"})
    assert r.status_code == 200, r.text
    d = rc.get(f"/api/cards/{cid}").json()
    assert not any(a["code"] == "hint" and a["field"] == "company" for a in d["attention"]) and "company" in d["confirmed"]
    plain = mk(ui, st, first_name="Ann", company="Acme Inc"); v = rc.get(f"/api/cards/{plain}").json()["version"]
    assert rc.post(f"/api/cards/{plain}/confirm-correct", json={"field": "company", "value": "Acme Inc", "version": v, "reason": "printed like this"}).status_code == 409


def test_reject_asks_and_save_reject_on_main_bar():
    import os
    base = os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui")
    js = open(os.path.join(base, "views", "review.js"), encoding="utf-8").read(); html = open(os.path.join(base, "index.html"), encoding="utf-8").read()
    assert "Reject card #${sid}?" in js and "are saved with it" in js   # #6
    bar = html[html.index('<div class="btns actions">'):html.index('id="rMore"')]
    assert 'id="bSave"' in bar and 'id="bReject"' in bar   # #8: not under More
    assert "data-softconfirm" in js and "confirmBtn(S.cur.overridable, sid, S.cur.hard)" in js


# ---- #7 export default + unique batch names
def test_batch_names_unique_on_server(env):
    ui, st = env["ui"], env["store"]
    a = mk(ui, st, first_name="Una"); ui.set_meta(a, batch="Bv41-1", batch_label="v041 QA")
    assert ui.batch_label_for("Bv41-1", "anything") == "v041 QA"          # a batch keeps its first name
    assert ui.batch_label_for("Bv41-2", "v041 QA") == "v041 QA (2)"       # a new batch never reuses a name
    b = mk(ui, st, first_name="Vic"); ui.set_meta(b, batch="Bv41-2", batch_label="v041 QA (2)")
    assert ui.batch_label_for("Bv41-3", "V041 qa") == "V041 qa (3)"
    assert ui.batch_label_for("Bv41-4", "fresh name") == "fresh name"


def test_export_default_is_current_batch_and_owner_named():
    import os
    js = open(os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui", "views", "export.js"), encoding="utf-8").read()
    assert "const def = curB || today[0]" in js and "mine.filter(b => b.own).sort(nw)[0]" not in js
    assert "Not your batch: ${esc(bo_.owner" in js   # v0.4.2 #6: a full line


# ---- #9 layout, accessibility and zoom
def test_layout_a11y_and_zoom_rules():
    import os
    base = os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui")
    rd = lambda *p: open(os.path.join(base, *p), encoding="utf-8").read()
    css, html, z, js = rd("ui.css"), rd("index.html"), rd("views", "zoom.js"), rd("views", "review.js")
    assert "grid-template-columns:minmax(0,1fr) minmax(0,1fr)" in css   # compare panel fits
    assert "word-break:keep-all;white-space:nowrap" in css              # no 'Addres/s'
    assert ".aidiff.pv" in css and 'class="aidiff pv"' in rd("views", "export.js")
    assert "already exported `" not in js                                     # space before 'Scanned twice'
    assert 'role="region" aria-label="Same person?"' in html
    assert '"emails.0"' not in z and '"phones.0"' not in z and "focusout" in z
    assert "min-height:44px;min-width:44px" in css

