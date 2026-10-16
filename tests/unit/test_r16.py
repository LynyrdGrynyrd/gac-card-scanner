"""Round-16 tests: versions are REQUIRED for shared admin changes (manager r15 H-1), refused attempts are audited (M-1),
export refuses a sign-off that went stale, pagination fixes (skeptic r15 M1/L2), duplicate-reason dedupe and the
approve refusal listing every problem (reviewer r15), website warning on merged rows (mctrade r15 M2), CSV fax '+'."""
import io, os, csv
from test_app import mk
from test_r15ui import _tpl_bytes

def _ev(ui, like): return [r[0] for r in ui.db().execute("SELECT event FROM auth_log WHERE event LIKE ? ORDER BY id", (like,))]

def test_template_without_version_refused_and_audited(env):
    adm, ui = env["adm"], env["ui"]
    v0 = ui.template_version(); n0 = len(_ev(ui, "refused (stale admin page)%"))
    r = adm.post("/api/admin/mctrade-template", files={"image": ("t.xlsx", _tpl_bytes(), "application/octet-stream")}, params={"_nov": "1"})
    assert r.status_code == 428 and r.json()["need"] == "version_required", r.text
    assert ui.template_version() == v0
    assert adm.post("/api/admin/mctrade-template/revert", params={"_nov": "1", "to_none": "1"}).status_code == 428
    assert adm.post("/api/admin/mctrade-contacts/remove", params={"_nov": "1"}).status_code == 428
    r = adm.post("/api/admin/mctrade-template", files={"image": ("t.xlsx", _tpl_bytes(), "application/octet-stream")}, data={"expected_version": "deadbeef0000"})
    assert r.status_code == 409
    ev = _ev(ui, "refused (stale admin page)%"); assert len(ev) >= n0 + 4, ev
    assert any("without a version" in e for e in ev) and any("deadbeef0000" in e for e in ev)
    # refusals never become the "last change" shown to admins
    lc = adm.get("/api/admin/mctrade-template").json()["last_change"]
    assert not lc or "refused" not in lc["what"].lower()

def test_template_revert_remove_rows_show_version_no_leftover(env):
    adm, ui = env["adm"], env["ui"]
    from app import mctrade_export as mx
    r = adm.post("/api/admin/mctrade-template", files={"image": ("a.xlsx", _tpl_bytes(), "application/octet-stream")}); assert r.status_code == 200, r.text
    r = adm.post("/api/admin/mctrade-template", files={"image": ("b.xlsx", _tpl_bytes("IndTitle"), "application/octet-stream")}); assert r.status_code == 200
    r = adm.post("/api/admin/mctrade-template/revert"); assert r.status_code == 200, r.text
    assert _ev(ui, "settings: reverted%")[-1].endswith("template version now " + r.json()["version"])
    while os.path.isfile(mx.TEMPLATE_XLSX + ".bak"): adm.post("/api/admin/mctrade-template/revert")
    r = adm.post("/api/admin/mctrade-template/revert", params={"to_none": "1"}); assert r.status_code == 200 and r.json()["present"] is False
    assert not os.path.exists(mx.TEMPLATE_XLSX + ".removed")
    assert "template version now none" in _ev(ui, "settings: removed the MC Trade import template%")[-1]
    info = adm.get("/api/admin/mctrade-template").json(); assert info["last_change"]["by"] == "adm"

def test_settings_without_seen_refused_and_clash_audited(env):
    adm, ui = env["adm"], env["ui"]
    before = adm.get("/api/admin/settings").json()
    r = adm.post("/api/admin/settings", json={"mctrade_affcode": "Blind16", "_nov": True})
    assert r.status_code == 428 and r.json()["need"] == "version_required"
    r = adm.post("/api/admin/settings", json={"mctrade_affcode": "Blind16", "_seen": {}})
    assert r.status_code == 428
    assert adm.get("/api/admin/settings").json()["mctrade_affcode"] == before["mctrade_affcode"]
    stale = dict(before)
    assert adm.post("/api/admin/settings", json={"mctrade_affcode": "Other16"}).status_code == 200
    r = adm.post("/api/admin/settings", json={"mctrade_affcode": "Mine16", "_seen": stale}); assert r.status_code == 409
    ev = _ev(ui, "refused (stale admin page): settings%"); assert any("without the values" in e for e in ev) and any("another admin changed" in e for e in ev)
    adm.post("/api/admin/settings", json={"mctrade_affcode": before["mctrade_affcode"]})

def test_cards_pagination_archived_and_limits(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    for i in range(3): a = mk(ui, store, first_name="Arch", last_name=f"Ived{i}"); ui.set_meta(a, batch="r16-arc", batch_label="Arc", archived=1)
    r = adm.get("/api/cards?archived=true&limit=2"); assert r.status_code == 200
    assert len(r.json()) == 2 and all(c["archived"] for c in r.json())
    assert int(r.headers["X-Total"]) == len(adm.get("/api/cards?archived=true&limit=0").json()) >= 3
    r = adm.get("/api/cards?archived=true"); assert len(r.json()) >= 3 and all(c["archived"] for c in r.json())
    assert adm.get("/api/cards?limit=100000").headers["X-Limit"] == "500"
    assert adm.get("/api/cards?limit=abc").status_code == 422 and adm.get("/api/cards?limit=abc").json()["need"] == "bad_limit"
    assert adm.get("/api/cards?offset=-1").status_code == 422

def test_duplicate_reasons_once(env):
    ui = env["ui"]
    assert ui._why(["email exact", "phone exact", "name~1.00", "same email", "same phone"]) == "same email, same phone, similar name"

def test_bulk_rejected_twin_keeps_in_batch_hint(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    ids = []
    for _ in range(3):
        a = mk(ui, store, first_name="Derek", last_name="Twins", company="Twin Builds", emails=["derek@twinbuilds16.com"], phones=[{"type": "work", "number": "330-555-0161"}])
        ui.set_meta(a, batch="r16-tw", batch_label="TW"); ids.append(a)
    assert rc.post("/api/cards-bulk", json={"ids": ids[1:], "status": "rejected", "batch": "r16-tw"}).status_code == 200
    ca = next(c for c in rc.get("/api/cards?batch=r16-tw").json() if c["id"] == ids[0])
    t = [x["text"] for x in ca["attention"] if x["code"] == "dup_other"]
    assert t and "May be the same person as card" in t[0] and "rejected, this batch" in t[0] and f"#{ids[1]}" in t[0], t
    rj = next(c for c in rc.get("/api/cards?batch=r16-tw").json() if c["id"] == ids[1])
    assert all("check before approving" not in x["text"] for x in rj["attention"])

def test_approve_blank_first_name_lists_every_problem(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Derek", last_name="Lawson", emails=["derek@lawsonbuilds16.com"])
    v = rc.get(f"/api/cards/{a}").json()["version"]
    r = rc.post(f"/api/cards/{a}", json={"fields": {"first_name": "", "emails": ["derek@lawsonbuilds"]}, "status": "approved", "version": v, "card_id": a})
    assert r.status_code == 422 and {"name", "emails"} <= set(r.json()["errors"]), r.text
    v = rc.post("/api/validate", json={"fields": {"first_name": "", "last_name": "Lawson", "emails": ["derek@lawsonbuilds"]}}).json()
    assert {"name", "emails"} <= set(v["hard"])

def _approved(ui, store, batch, **f):
    a = mk(ui, store, **f); ui.set_meta(a, batch=batch, batch_label=batch); store.update(a, status="approved", reviewer="RR"); return a

def test_export_refuses_stale_signoff_and_busy_is_audited(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    a = _approved(ui, store, "r16-ex", first_name="Stella", last_name="Signoff", company="Sign Co", emails=["stella@signco16.com"])
    chk = adm.get("/api/export/check?status=approved_new&batch=r16-ex").json(); vs = chk["versions"]
    assert set(vs) == {"template", "contacts", "cards"}
    view = adm.get("/api/export/xlsx?preview=1&view=1&status=approved_new&batch=r16-ex").json(); assert view["versions"] == vs
    f = store.get(a)["fields"]; f["title"] = "Changed after sign-off"; store.update(a, fields=f)
    r = adm.get("/api/export/csv", params={"status": "approved_new", "batch": "r16-ex", **{"seen_" + k: v for k, v in vs.items()}})
    assert r.status_code == 409 and r.json()["need"] == "stale_review" and r.json()["changed"] == ["cards"]
    assert any("changed since the sign-off" in e for e in _ev(ui, "refused export%"))
    assert store.get(a)["status"] == "approved" and not ui.meta(a).get("exported")
    # busy: another export of the same cards holds the slot
    ui._export_claim("batch:other", {a}, "someone")
    try:
        r = adm.get("/api/export/csv?status=approved_new&batch=r16-ex"); assert r.status_code == 409 and r.json()["need"] == "export_busy"
    finally: ui._export_release("batch:other")
    assert any("another export of these cards was running" in e for e in _ev(ui, "refused export%"))
    vs2 = adm.get("/api/export/check?status=approved_new&batch=r16-ex").json()["versions"]
    r = adm.get("/api/export/csv", params={"status": "approved_new", "batch": "r16-ex", **{"seen_" + k: v for k, v in vs2.items()}}); assert r.status_code == 200, r.text

def test_csv_international_fax_keeps_plus(env):
    from app import export
    c = {"id": 1, "status": "approved", "fields": {"first_name": "A", "last_name": "B", "title": "", "company": "", "website": "", "address": "", "emails": [],
         "phones": [{"type": "fax", "number": "+44 20 7946 0958"}, {"type": "work", "number": "330-555-0170 x4271"}]}}
    row = next(csv.DictReader(io.StringIO(export.to_csv([c]))))
    assert row["fax"] == "+44 20 7946 0958" and row["work_phone"] == "330-555-0170 x4271"
    from app.ui import safe_cell; assert safe_cell(row["fax"]) == row["fax"]

def test_website_warning_on_merged_row(env):
    ui, store = env["ui"], env["store"]
    a = _approved(ui, store, "r16-web", first_name="Mona", last_name="Merge", company="Acme Tire", emails=["mona@acmetire16.com"], website="www.evil-phish.com")
    b = mk(ui, store, first_name="Mona", last_name="Merge"); ui.set_meta(b, batch="r16-web", dup_resolution=f"merged_into:{a}")
    ok = _approved(ui, store, "r16-web", first_name="Fine", last_name="Site", company="Good Co", emails=["f@goodco16.com"], website="www.goodco16.com")
    w = ui.website_warnings([store.get(a), store.get(ok)], ui.all_metas())
    assert [x[0] for x in w] == [a] and "merge" in w[0][2] and "phishing" in w[0][2]
    rd = env["adm"].get("/api/export/xlsx?preview=1&companion=readme.txt&status=approved_new&batch=r16-web").text
    assert "Check website" in rd and "www.evil-phish.com" in rd and "Phones are written" not in rd   # v0.3.2: phone format is in the admin guide

def test_ai_kept_warning_clears_after_manual_fix(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    import json
    a = mk(ui, store, first_name="", last_name="", company="Civic Events")
    ui.set_meta(a, ai_rejected=json.dumps({"first_name": "Elena", "last_name": "Ibarra"}))
    att = lambda: [x["text"] for x in rc.get(f"/api/cards/{a}").json()["attention"] if x["code"] == "ai_overridden"]
    assert att()
    f = store.get(a)["fields"]; f["first_name"] = "Elena"; f["last_name"] = "Ibarra"; store.update(a, fields=f)
    assert not att()
