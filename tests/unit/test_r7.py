"""Round-7 regression tests (parttimer-r1, mctrade-r4, manager-r4, newcomer-r7, skeptic-r7)."""
import io, os, json, zipfile, threading
from test_app import mk
from openpyxl import Workbook, load_workbook
from app import mctrade_export as M, crm_source, parser, plausibility

SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "data", "existing_contacts.csv")
FAKE_REAL = os.path.join(os.path.dirname(__file__), "fake_real_contacts.csv")
def _ap(c, cid, **kw): return c.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"} | kw)
def _card(i, t=0, **f):
    base = {"first_name": "", "last_name": "", "company": "", "emails": [], "phones": []}; base.update(f)
    return {"id": i, "fields": base, "status": "approved", "decided": t}
NOERR = lambda f: {}

# ---- email rules (mctrade-r4 R4-4)
def test_email_rfc_rules(env):
    ui = env["ui"]
    for good in ["ann&co@acme.com", "ann#1@acme.com", "ann+events@gmail.com", "a@mail.akron.oh.us", "o'brien@x.co.uk", "x@xn--mnchen-3ya.de", " ANN@X.COM "]:
        assert ui.email_syntax(good) is None, good
    for bad in ["ann..lee@acme.com", "ann@acme..com", "ann@acme_co.com", "ann@acme", "ann@acme.c", "=1+1@x.com", "-x@a.com", "<b>@x.com", "a@-b.com"]:
        assert ui.email_syntax(bad), bad
        assert "emails" in ui.hard_errors({"first_name": "A", "emails": [bad]}), bad     # hard: 'approve anyway' can't pass it

def test_approve_anyway_cannot_bypass_email_syntax(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Syn", last_name="Tax", emails=["syn@tax"]); ui.set_meta(cid, batch="r7e")
    r = _ap(rev, cid, override_reason="sure"); assert r.status_code == 422 and r.json()["need"] == "fix"

# ---- phones with extensions (skeptic R7-1)
def test_plus_phone_with_extension_not_formula():
    for v in ["+1 (330) 555-0185 x12", "+1 330-555-0185 ext. 12", "+1 330-555-0185 Ext.12", "+44 20 7946 0958 x3", "+1 330 555 0185 #12"]:
        assert not M.looks_formula(v), v
        assert not M.content_problems({"phones": [{"type": "work", "number": v}]}), v
    assert M.phone("+1 330 555 0185 #12") == "330-555-0185 x12"
    assert M.looks_formula("=1+2+3") and M.looks_formula("+1 -1") and M.looks_formula("+SUM(1) x2")

# ---- optimistic locking (skeptic R7-2 / R7-3)
def test_version_required_and_atomic(env):
    ui, st, rev, r2 = env["ui"], env["store"], env["rev"], env["rev2"]
    cid = mk(ui, st, first_name="Lock", last_name="Test", emails=["lock@t.io"]); ui.set_meta(cid, batch="r7v")
    for v in (None, "", 0, "0"):
        b = {"_nov": True, "card_id": cid, "fields": {"title": "x"}} | ({} if v is None else {"version": v})
        r = rev.post(f"/api/cards/{cid}", json=b); assert r.status_code == 409 and r.json()["need"] == "version", (v, r.text)
    v = rev.get(f"/api/cards/{cid}").json()["version"]; out = {}
    def go(n, c):
        out[n] = c.post(f"/api/cards/{cid}", json={"_nov": True, "card_id": cid, "version": v, "fields": {"title": "race " + n}}).status_code
    ts = [threading.Thread(target=go, args=("A", rev)), threading.Thread(target=go, args=("B", rev))]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(out.values()) == [200, 409], out

def test_bulk_needs_current_version(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Bulk", last_name="Ver", emails=["bulk@v.io"]); ui.set_meta(cid, batch="r7b")
    r = rev.post("/api/cards-bulk", json={"ids": [cid], "status": "rejected", "versions": {str(cid): "deadbeef0000"}}).json()
    assert r["updated"] == [] and r["skipped"][0]["need"] == "stale" and st.get(cid)["status"] == "pending"
    r = rev.post("/api/cards-bulk", json={"ids": [cid], "status": "rejected"}).json(); assert r["updated"] == [cid]   # conftest fills the current one

def test_ai_decide_empty_is_noop_and_needs_version(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Ai", last_name="Empty", emails=["ai@e.io"]); ui.set_meta(cid, ai_status="queued")
    r = rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {}}); assert r.status_code == 400
    assert ui.meta(cid)["ai_status"] == "queued"
    ui.set_meta(cid, ai_status="suggested", ai_detail=json.dumps({"diff": {"title": {"from": "CFO", "to": "CEO"}}}))
    r = rev.post(f"/api/cards/{cid}/ai-decide", json={"_nov": True, "choices": {"title": "accept"}}); assert r.status_code == 409 and r.json()["need"] == "version"
    r = rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"title": "accept"}}); assert r.status_code == 200 and st.get(cid)["fields"]["title"] == "CEO"

def test_edit_of_exported_card_with_status_flags_reexport(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Re", last_name="Export", emails=["re@ex.io"]); ui.set_meta(cid, batch="r7x")
    assert _ap(rev, cid).status_code == 200; ui.set_meta(cid, exported=1.0)
    assert rev.post(f"/api/cards/{cid}", json={"status": "approved", "fields": {"title": "Changed"}}).status_code == 200
    assert ui.meta(cid)["reexport"]

def test_validate_covers_all_fields(env):
    rev = env["rev"]
    for k in ("other_address", "department", "credentials"):
        r = rev.post("/api/validate", json={"fields": {"first_name": "A", "emails": ["a@b.co"], k: "=1+1"}}).json()
        assert k in r["hard"], (k, r)

# ---- cross-batch (skeptic R7-4)
def test_cross_batch_phone_only_needs_confirm_and_none_same_logs(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    PH = [{"type": "work", "number": "330-555-0177"}]
    a = mk(ui, st, first_name="Ophelia", last_name="Strand<b>", emails=["o1@x.io"], phones=PH); ui.set_meta(a, batch="r7xa")
    assert _ap(rev, a, last_name="Strand", fields={"last_name": "Strand"}).status_code == 200
    b = mk(ui, st, first_name="Ophelia", last_name="Strand", emails=["o2@y.io"], phones=[{"type": "mobile", "number": "+1 330.555.0177 x5"}]); ui.set_meta(b, batch="r7xb")
    r = _ap(rev, b); assert r.status_code == 409 and r.json()["need"] == "confirm_cross_batch" and a in r.json()["others"], r.text
    r = _ap(rev, b, keep_apart="all"); assert r.status_code == 200, r.text
    assert any(h["action"] == "cross_batch_confirmed" for h in ui.history(b))

# ---- MC Trade export (mctrade-r4 R4-1 / R4-2, newcomer r7 F1)
def test_nickname_same_identity_one_row():
    f = dict(last_name="Quarrington", company="Quarrington Widgets", emails=["zeb@quarrington-widgets.com"], phones=[{"type": "work", "number": "330-555-0150"}])
    r = M.build([_card(103, 2, first_name="Zeb", **f), _card(81, 1, first_name="Zebulon", **f)], "X", "gac", NOERR, kept=lambda a, b: True)
    assert len(r["rows"]) == 1 and r["conflicts"]

def test_no_real_crm_never_assigns_profile_ids(env, monkeypatch):
    monkeypatch.delenv("MCTRADE_CRM_EXPORT", raising=False)
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    assert crm_source.real() is None and not crm_source.info()["real"]
    cid = mk(ui, st, first_name="James", last_name="Okafor", company="Cuyahoga Falls Tire Co.", emails=["jokafor@cftire.com"],
             phones=[{"type": "work", "number": "330-555-0177"}]); ui.set_meta(cid, batch="r7s", batch_label="R7S")
    d = rev.get(f"/api/cards/{cid}").json()["dupes"]["crm"]; assert d and d[0]["sample"] is True
    assert ui.strict_profile_id(st.get(cid)) is None
    assert rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "update_existing", "confirm_cross_batch": True}).status_code == 200
    r = adm.get("/api/export/xlsx?status=approved&batch=r7s&preview=1"); assert "updates.xlsx" not in r.headers["X-Companions"]
    s = json.loads(r.headers["X-Summary"]); assert s["possible"] == [cid] and s["new_rows"] == 0 and not s["crm_real"]
    rd = adm.get("/api/export/xlsx?status=approved&batch=r7s&preview=1&companion=readme.txt").text
    assert "Test MC Trade list" in rd and "may already be in MC Trade" in rd
    v = adm.get("/api/export/xlsx?status=approved&batch=r7s&preview=1&view=1").json(); assert v["rows"] == [] and v["left"][0][0] == cid

def test_contacts_upload_used_by_export_and_dryrun(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    assert rev.post("/api/admin/mctrade-contacts", files={"image": ("c.csv", open(SAMPLE_CSV, "rb"))}).status_code in (401, 403)
    assert adm.post("/api/admin/mctrade-contacts", files={"image": ("real export.csv", open(SAMPLE_CSV, "rb"))}).status_code == 422   # round 8: SAMPLE refused
    r = adm.post("/api/admin/mctrade-contacts", files={"image": ("real export.csv", open(FAKE_REAL, "rb"))}); assert r.status_code == 200, r.text
    assert r.json()["real"] and crm_source.real()
    cid = mk(ui, st, first_name="Maria", last_name="Delgado", company="Summit Valley Bank", emails=["maria.delgado@svb-test.example"]); ui.set_meta(cid, batch="r7c", batch_label="R7C")
    assert rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "update_existing", "confirm_cross_batch": True}).status_code == 200
    r = adm.get("/api/export/xlsx?status=approved&batch=r7c&preview=1"); assert "updates.xlsx" in r.headers["X-Companions"]
    d = rev.get("/api/export/dryrun?status=approved&batch=r7c"); assert d.status_code == 200 and "Compared against" in d.text and "SAMPLE/FAKE" not in d.text
    log = adm.get("/api/admin/audit?q=dry+run").json(); assert any("REAL" in x["what"] and "R7C" in x["what"] and x["kind"] == "export" for x in log)
    adm.post("/api/admin/mctrade-contacts/remove"); assert crm_source.real() is None
    assert adm.post("/api/admin/mctrade-contacts", files={"image": ("x.txt", b"hi")}).status_code == 422

def test_dryrun_refusal_audited(env):
    rev, adm = env["rev"], env["adm"]
    assert rev.get("/api/export/dryrun?status=approved").status_code == 403
    assert any("dry run REFUSED" in x["what"] for x in adm.get("/api/admin/audit?q=REFUSED").json())

# ---- template upload hardening (mctrade-r4 R4-3/R4-5, manager-r4)
def _tpl(cols):
    wb = Workbook(); wb.active.append(cols); b = io.BytesIO(); wb.save(b); return b.getvalue()
GOOD = ["ProfileID", "OrgName", "IndFirstName", "IndLastName", "IndEmail", "AffCode1"]
def test_template_upload_limits_backups_revert(env, tmp_path, monkeypatch):
    adm = env["adm"]; monkeypatch.setattr(M, "TEMPLATE_XLSX", str(tmp_path / "mctrade_template.xlsx"))
    up = lambda data, n="t.xlsx": adm.post("/api/admin/mctrade-template", files={"image": (n, data)})
    assert up(_tpl(GOOD + [f"C{i}" for i in range(250)])).status_code == 422                       # too wide
    assert up(_tpl(GOOD + ['=HYPERLINK("http://evil","x")'])).status_code == 422                   # formula header
    assert up(_tpl(GOOD + ["<img src=x>"])).status_code == 422                                     # HTML header
    assert up(_tpl(["ProfileID", "IndEmail", "AffCode1"])).status_code == 422                      # no name columns
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", "<workbook/>"); z.writestr("xl/sharedStrings.xml", "A" * (30 * 1024 * 1024))
    r = up(bomb.getvalue(), "bomb.xlsx"); assert r.status_code == 422 and "zip bomb" in r.json()["error"] or "40 MB" in r.json()["error"]
    log = adm.get("/api/admin/audit?q=REFUSED").json(); assert sum("template upload" in x["what"] for x in log) >= 5
    for n in range(3): assert up(_tpl(GOOD + [f"Extra{n}"])).status_code == 200
    assert os.path.isfile(M.TEMPLATE_XLSX + ".bak") and os.path.isfile(M.TEMPLATE_XLSX + ".bak2")
    assert adm.get("/api/admin/mctrade-template").json()["previous"] == 2
    assert "Extra2" in M.headers()[0]
    assert adm.post("/api/admin/mctrade-template/revert").status_code == 200 and "Extra1" in M.headers()[0]
    assert any("reverted" in x["what"] for x in adm.get("/api/admin/audit?q=reverted").json())

def test_audit_filename_sanitised(env):
    ui = env["ui"]; assert "\n" not in ui._safe_fname("evil%0Aname<img src=x>.xlsx") and "<" not in ui._safe_fname("a<b>.xlsx")

# ---- part-timer r1
def test_blank_name_and_glued_words_never_look_good(env):
    ui, st = env["ui"], env["store"]
    f = parser.parse("Summit Valley Bank\n200 S Main St\nAkron, OH 44308\n(330) 555-0142")
    assert not f["first_name"] and f["overall_confidence"] <= 0.5 and "name" in f["needs_review"]
    assert any(s["code"] == "glued_words" for s in plausibility.check({"address": "45 E Market StSuite 210, Stow, OH 44224"}))
    assert any(s["code"] == "glued_words" for s in plausibility.check({"company": "Highland Squarecoffee Co"}))
    assert not plausibility.check({"company": "McDonald Bank", "first_name": "A", "last_name": "Bc"}) or all(s["code"] != "glued_words" for s in plausibility.check({"company": "McDonald Bank"}))
    cid = mk(ui, st, first_name="Luis", last_name="Rasmussen", emails=["irasmussen@firestone.example.com"], overall_confidence=0.91)
    c = [x for x in env["rev"].get("/api/cards").json() if x["id"] == cid][0]
    assert c["attention"] and c["needs_attention"] and c["conf"] < 0.6

def test_ampersand_spacing_postprocess():
    f = {"company": "Hughes& Partners Law", "title": "R&D Lead", "address": "AT&T Tower"}; parser._postprocess(f)
    assert f == {"company": "Hughes & Partners Law", "title": "R&D Lead", "address": "AT&T Tower"}

def test_batches_mine_and_ready(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Mine", last_name="Batch", emails=["mine@b.io"]); ui.set_meta(cid, batch="r7mine", batch_label="R7 mine")
    ui.log(cid, "RR", "scanned", detail={"file": "x.jpg"})
    assert _ap(rev, cid).status_code == 200
    b = [x for x in rev.get("/api/batches").json() if x["batch"] == "r7mine"][0]
    assert b["mine"] and b["ready"] == 1 and b["approved"] == 1
    ui.set_meta(cid, exported=1.0)
    assert [x for x in rev.get("/api/batches").json() if x["batch"] == "r7mine"][0]["ready"] == 0

# ---- coordinator r1 / reviewer r7 / advice
BAD = [{"title": "<img src=x onerror=alert(1)>"}, {"company": "=HYPERLINK(\"http://e\",\"x\")"}, {"other_address": "+SUM(1)"},
       {"emails": ["=1+1@x.com"]}, {"last_name": "Lee\u200b"}, {"department": "&lt;b&gt;x"}]
def test_same_bad_payloads_refused_by_every_writer(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Pay", last_name="Load", emails=["pay@load.io"]); ui.set_meta(cid, batch="r7p")
    for bad in BAD:
        assert ui.payload_problems(bad), bad
        assert rev.post(f"/api/cards/{cid}", json={"fields": bad}).status_code == 422, bad                       # save
        assert rev.post(f"/api/cards/{cid}", json={"fields": bad, "status": "approved", "override_reason": "x"}).status_code == 422, bad   # approve
        assert rev.post("/api/validate", json={"fields": {"first_name": "A"} | bad}).json()["hard"], bad          # validate
        k = next(iter(bad)); ui.set_meta(cid, ai_status="suggested", ai_detail=json.dumps({"diff": {k: {"from": st.get(cid)["fields"].get(k), "to": bad[k]}}}))
        assert rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {k: "accept"}}).status_code == 422, bad   # AI accept
    assert st.get(cid)["status"] == "pending" and "<img" not in json.dumps(st.get(cid)["fields"])

def test_save_reports_what_blocks_approval(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Maria", last_name="Sv", emails=["maria@x.io"])
    assert rev.post(f"/api/cards/{cid}", json={"fields": {"first_name": "", "company": ""}}).status_code == 422   # round 13: blanking the name is refused
    r = rev.post(f"/api/cards/{cid}", json={"fields": {"phones": [{"type": "work", "number": "555-01"}], "company": ""}}); assert r.status_code == 200
    assert r.json()["save_problems"]
    assert rev.post(f"/api/cards/{cid}", json={"fields": {"emails": ["maria@@x"]}}).status_code == 422   # syntax: refused even on save

def test_update_existing_needs_admin_switch(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]; auth = __import__("app.auth", fromlist=["x"])
    cid = mk(ui, st, first_name="Up", last_name="Switch", emails=["up@sw.io"])
    auth.set_setting("mctrade_updates_enabled", "0")
    try:
        r = rev.post(f"/api/cards/{cid}", json={"crm_action": "update_existing"}); assert r.status_code == 409 and r.json()["need"] == "updates_off"
        assert rev.post(f"/api/cards/{cid}", json={"crm_action": "create_new"}).status_code == 200
    finally: auth.set_setting("mctrade_updates_enabled", "1")

def test_name_and_company_match_without_email_or_phone(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = mk(ui, st, first_name="Farid", last_name="Pemberton", company="Greenway Grounds LLC", emails=[], phones=[]); ui.set_meta(a, batch="r7f")
    b = mk(ui, st, first_name="Farid", last_name="Pemberton", company="Greenway Grounds LLC", emails=["fpembertn@greenwayexample.com"]); ui.set_meta(b, batch="r7f")
    assert a in [x["card_id"] for x in rev.get(f"/api/cards/{b}").json()["dupes"]["queue"]]

def test_missing_company_email_website_not_looks_good(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="No", last_name="Company", company="", website="")
    c = [x for x in rev.get("/api/cards").json() if x["id"] == cid][0]
    assert any(a["code"] == "missing" for a in c["attention"]) and c["needs_attention"]

def test_merge_keeps_the_fuller_title():
    f = dict(first_name="Farid", last_name="Pemberton", company="Greenway", emails=["fp@g.io"])
    r = M.build([_card(6, 2, title="Head Groundskeeper", **f), _card(39, 1, title="Regional Head Groundskeeper", **f)], "X", "gac", NOERR)
    assert r["rows"][0][1]["IndTitle"] == "Regional Head Groundskeeper"

def test_keep_current_is_not_offered_again(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Keep", last_name="Current", title="CFO")
    ui.set_meta(cid, ai_status="suggested", ai_detail=json.dumps({"diff": {"title": {"from": "CFO", "to": "CEO"}}}))
    assert rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"title": "reject"}}).status_code == 200
    assert json.loads(ui.meta(cid)["ai_rejected"])["title"] == "CEO"

def test_preview_readme_says_preview_and_ocr_lookalike_hint(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Pre", last_name="View", emails=["pre.r7pv@viewzz.io"]); ui.set_meta(cid, batch="r7pv", batch_label="R7PV")
    r = _ap(rev, cid); assert r.status_code == 200, r.text
    rd = adm.get("/api/export/xlsx?status=approved&batch=r7pv&preview=1&companion=readme.txt").text
    assert rd.startswith("*** PREVIEW ONLY") and "not checked against MC Trade" in rd and "Every column of GAC" not in rd
    assert any(s["code"] == "ocr_lookalike" for s in plausibility.check({"company": "Rnbber City Robotics"}))
    ck = rev.get("/api/export/check?status=approved&batch=r7pv").json(); assert "pending_count" in ck and ck["cards"][0]["id"] == cid
