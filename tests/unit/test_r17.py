"""Round 17 (seven r16 reports)."""
import json
from test_r9 import mk

def _hint(c, code="dup_other"): return [x["text"] for x in c["attention"] if x["code"] in (code, "dup_queue")]
def _row(rc, b, i): return next(c for c in rc.get(f"/api/cards?batch={b}&limit=0").json() if c["id"] == i)

def test_edit_made_twin_hint_survives_bulk_reject(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    b = "r17-ed"
    a = mk(ui, store, first_name="Emily", last_name="Chen", company="Chen Dental Group", emails=["emily@chendental17.com"], phones=[{"type": "work", "number": "330-555-0191"}])
    o1 = mk(ui, store, first_name="Mark", last_name="Olsen", company="Olsen Roofing", emails=["mark@olsenroof17.com"], phones=[{"type": "work", "number": "330-555-0122"}])
    d = mk(ui, store, first_name="Peter", last_name="Grant", company="Grant Law", emails=["pg@grantlaw17.com"], phones=[{"type": "work", "number": "330-555-0133"}])
    for i in (a, o1, d): ui.set_meta(i, batch=b, batch_label="ED")
    assert not _hint(_row(rc, b, a))
    f = dict(store.get(d)["fields"], first_name="Emily", last_name="Chen", company="Chen Dental Group", emails=["emily.chen@chendental17.com"])
    r = rc.post(f"/api/cards/{d}", json={"fields": f}); assert r.status_code == 200, r.text
    ha, hd = _hint(_row(rc, b, a)), _hint(_row(rc, b, d)); assert ha and hd, (ha, hd)
    vs = {str(i): rc.get(f"/api/cards/{i}").json()["version"] for i in (a, o1, d)}
    assert rc.post("/api/cards-bulk", json={"ids": [a, o1, d], "status": "rejected", "batch": b, "versions": vs}).status_code == 200
    ha, hd = _hint(_row(rc, b, a)), _hint(_row(rc, b, d)); print(ha, hd)
    assert ha and f"#{d}" in ha[0] and hd and f"#{a}" in hd[0], (ha, hd)
    full = rc.get(f"/api/cards/{a}").json(); assert _hint(full), full["attention"]
    r = rc.post(f"/api/cards/{a}", json={"status": "pending", "confirm_redecide": True}); assert r.status_code == 200, r.text
    ha = _hint(_row(rc, b, a)); assert ha and "rejected, this batch" in ha[0], ha

def test_in_batch_rejected_twin_not_hidden_by_many_other_batch_lookalikes(env):
    """reviewer r16 NO-GO #1: Emily Chen was scanned in many earlier batches; the in-batch twin was cut off the 5-id list."""
    ui, store, rc = env["ui"], env["store"], env["rev"]
    F = dict(first_name="Emma", last_name="Lindqvist", company="Rubber Robotics Seventeen", emails=["emma@rr17.io"], phones=[{"type": "work", "number": "330-555-0150"}])
    for k in range(12):
        o = mk(ui, store, **F); ui.set_meta(o, batch=f"r17-old{k}", batch_label=f"Old{k}"); store.update(o, status="approved")
    b = "r17-nb"; a = mk(ui, store, **F)
    t = mk(ui, store, **dict(F, phones=[{"type": "work", "number": "330-555-0190"}], website="www.hugheslaw.com"))
    for i in (a, t): ui.set_meta(i, batch=b, batch_label="NB")
    vs = {str(i): rc.get(f"/api/cards/{i}").json()["version"] for i in (a, t)}
    assert rc.post("/api/cards-bulk", json={"ids": [a, t], "status": "rejected", "batch": b, "versions": vs}).status_code == 200
    for x, y in ((a, t), (t, a)):
        h = _hint(_row(rc, b, x)); assert any(f"#{y}" in s and "this batch" in s for s in h), h
        assert any(f"#{y}" in s for s in _hint(rc.get(f"/api/cards/{x}").json()))
        assert all("more" in s for s in h if "another batch" in s)   # 12 other-batch ids: first 10 + '…and 2 more'
    assert rc.post(f"/api/cards/{a}", json={"status": "pending", "confirm_redecide": True}).status_code == 200
    h = _hint(_row(rc, b, a)); assert any(f"#{t} (rejected, this batch): a hint only" in s for s in h), h

def _ev(ui, like): return [r[0] for r in ui.db().execute("SELECT event FROM auth_log WHERE event LIKE ? ORDER BY id", (like,))]
def _approved(ui, store, batch, **f):
    a = mk(ui, store, **f); ui.set_meta(a, batch=batch, batch_label=batch); store.update(a, status="approved", reviewer="RR"); return a

def test_real_export_requires_signoff_versions(env):
    """manager r16 M-1 / skeptic L1: a real export without seen_* gets 428 version_required; the refusal names the cards."""
    ui, store, adm = env["ui"], env["store"], env["adm"]
    a = _approved(ui, store, "r17-ex", first_name="Vera", last_name="Version", company="Ver Co", emails=["vera@verco17.com"])
    r = adm.get("/api/export/csv?status=approved_new&batch=r17-ex&_nov=1")
    assert r.status_code == 428 and r.json()["need"] == "version_required" and "seen_cards" in r.json()["missing"]
    assert not ui.meta(a).get("exported")
    vs = adm.get("/api/export/check?status=approved_new&batch=r17-ex").json()["versions"]
    r = adm.get("/api/export/csv", params={"status": "approved_new", "batch": "r17-ex", "seen_cards": vs["cards"]}); assert r.status_code == 428
    assert adm.get("/api/export/csv?status=approved_new&batch=r17-ex&preview=1").status_code == 200   # a preview needs none
    ev = [e for e in _ev(ui, "refused export%") if "sign-off versions" in e]; assert ev and f"#{a}" in ev[-1]
    rows = [x for x in adm.get("/api/admin/audit?q=sign-off versions").json() if "refused export" in x["what"]]
    assert rows and rows[0]["kind"] == "export" and a in rows[0]["cards"]
    r = adm.get("/api/export/csv", params={"status": "approved_new", "batch": "r17-ex", **{"seen_" + k: v for k, v in vs.items()}}); assert r.status_code == 200, r.text

def test_refused_admin_rows_typed_and_worded(env):
    """manager r16 L-1/L-2/L-3."""
    ui, adm = env["ui"], env["adm"]
    assert adm.post("/api/admin/mctrade-template/revert", params={"_nov": "1"}).status_code == 428
    assert adm.post("/api/admin/mctrade-template/revert", params={"to_none": "1", "_nov": "1"}).status_code == 428
    assert adm.post("/api/admin/mctrade-contacts/remove", params={"_nov": "1"}).status_code == 428
    ev = _ev(ui, "refused (stale admin page)%")
    assert any("revert to the previous file of the MC Trade template" in e for e in ev) and any("remove of the MC Trade template" in e for e in ev)
    assert any("remove of the MC Trade contacts file" in e for e in ev)
    kinds = {x["what"].split(":")[1].strip()[:30]: x["kind"] for x in adm.get("/api/admin/audit?q=refused").json()}
    au = adm.get("/api/admin/audit?q=refused").json()
    assert all(x["kind"] != "account" for x in au if x["what"].startswith("refused"))
    assert any(x["kind"] == "template" for x in au) and any(x["kind"] == "contacts" for x in au)
    r = adm.post("/api/admin/mctrade-contacts/remove", params={"expected_version": "bogus-version"})
    assert r.status_code == 409 and "not one this server has ever had" in r.json()["error"] and "after you opened" not in r.json()["error"]

def test_xlsx_international_fax_matches_csv(env):
    from app import mctrade_export as mx
    assert mx.phone("+442079460958") == "+44 20 7946 0958" and mx.phone("330-555-0170 x4271") == "330-555-0170 x4271"
    assert mx.phone("+442079460958", "e164") == "+442079460958"

def test_check_website_only_exported_rows(env):
    """mctrade r16: CHECK WEBSITE lists only cards in an import file, named by the exported row's card."""
    ui, store, adm = env["ui"], env["store"], env["adm"]
    b = "r17-web"
    a = _approved(ui, store, b, first_name="Olga", last_name="Strand", company="Strandline", emails=["olga@strandline17.net"], phones=[{"type": "work", "number": "330-555-0171"}])
    m = mk(ui, store, first_name="Olga", last_name="Strand", company="Strandline", emails=["olga@strandline17.net"], website="www.evil-phish.com")
    ui.set_meta(m, batch=b, batch_label=b, dup_resolution=f"merged_into:{a}"); store.update(m, status="rejected")
    f = store.get(a)["fields"]; f["website"] = "www.evil-phish.com"; store.update(a, fields=f)
    bad = _approved(ui, store, b, first_name="Fix", last_name="First", company="X", emails=["fix@"], website="www.secure-login17.com")
    rd = adm.get(f"/api/export/xlsx?preview=1&companion=readme.txt&status=approved_new&batch={b}").text
    lines = [l for l in rd.splitlines() if "CHECK WEBSITE" in l]
    assert any(f"card #{a} " in l for l in lines), lines
    assert not any(f"#{bad} " in l for l in lines) and not any(f"card #{m} " in l for l in lines), lines
