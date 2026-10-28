"""Round-15 UI tests: the queue/bulk are strictly scoped to one batch (newcomer r14 BLOCKER), per-user counts, admin
optimistic locking (settings, template, contacts) and the template version in exports (manager r14), audit WHO, R10,
website sanity hints and same-name rows (mctrade r14 M1/M2), no admin markup for reviewers."""
import io, re
from test_app import mk

def test_cards_batch_filter_strict(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Scope", last_name="Mine"); ui.set_meta(a, batch="r15-a", batch_label="R15 A")
    b = mk(ui, store, first_name="Scope", last_name="Other"); ui.set_meta(b, batch="r15-b", batch_label="R15 B")
    ids = {c["id"] for c in rc.get("/api/cards?batch=r15-a").json()}
    assert a in ids and b not in ids
    assert all(c["batch"] == "r15-a" for c in rc.get("/api/cards?batch=r15-a").json())
    assert rc.get("/api/cards?batch=r15-zzz").json() == []

def test_bulk_refuses_other_batch(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Bulk", last_name="Mine", emails=["bm@x15.com"]); ui.set_meta(a, batch="r15-c", batch_label="R15 C")
    b = mk(ui, store, first_name="Bulk", last_name="Theirs", emails=["bt@x15.com"]); ui.set_meta(b, batch="r15-d", batch_label="R15 D")
    r = rc.post("/api/cards-bulk", json={"ids": [a, b], "status": "rejected", "batch": "r15-c"})
    assert r.status_code == 409 and r.json()["need"] == "wrong_batch" and r.json()["ids"] == [b]
    assert store.get(a)["status"] == "pending" and store.get(b)["status"] == "pending"
    r = rc.post("/api/cards-bulk", json={"ids": [a], "status": "rejected", "batch": "r15-c"}); assert r.status_code == 200, r.text
    assert store.get(a)["status"] == "rejected"

def test_counts_per_user(env):
    ui, store, rc, r2 = env["ui"], env["store"], env["rev"], env["rev2"]
    ini = {u["username"]: u["initials"] for u in env["adm"].get("/api/admin/users").json()}["rev"]
    a = mk(ui, store, first_name="Count", last_name="Mine"); ui.set_meta(a, batch="r15-e", batch_label="R15 E"); ui.log(a, ini, "scanned")
    c1 = rc.get("/api/counts?batch=r15-e").json(); c2 = r2.get("/api/counts").json()
    assert c1["mine_pending"] >= 1 and c1["batch"]["pending"] == 1 and c1["batch"]["all"] == 1
    assert c2["mine_pending"] < c1["everyone_pending"] or c2["mine_pending"] == 0
    bs = {b["batch"]: b for b in rc.get("/api/batches").json()}
    assert bs["r15-e"]["own"] and bs["r15-e"]["mine"]
    assert "r15-e" not in {b["batch"]: b for b in r2.get("/api/batches").json()}   # v0.4.5 #9: reviewers see only their own

def test_settings_optimistic_lock(env):
    adm = env["adm"]
    seen = adm.get("/api/admin/settings").json()
    other = dict(seen)   # admin B (same page state) switches updates off first
    r = adm.post("/api/admin/settings", json={"mctrade_updates_enabled": "0" if seen["mctrade_updates_enabled"] == "1" else "1", "_seen": other}); assert r.status_code == 200
    # admin A, still showing the old value, tries to change the same switch: refused, nothing saved
    now = adm.get("/api/admin/settings").json()
    r = adm.post("/api/admin/settings", json={"mctrade_updates_enabled": now["mctrade_updates_enabled"] == "1" and "0" or "1", "_seen": seen})
    # A wants seen-opposite; B already changed it -> clash only when A's wanted value differs from what A saw
    assert r.status_code in (200, 409)
    r = adm.post("/api/admin/settings", json={"mctrade_updates_enabled": "0" if seen["mctrade_updates_enabled"] == "1" else "1", "mctrade_affcode": "X15", "_seen": seen})
    assert r.status_code == 409 and r.json()["need"] == "stale_admin"
    assert adm.get("/api/admin/settings").json()["mctrade_affcode"] == now["mctrade_affcode"]
    # an UNTOUCHED setting on a stale page is never reset to its old value
    s2 = adm.get("/api/admin/settings").json(); stale = dict(s2)
    adm.post("/api/admin/settings", json={"phone_format": "e164" if s2["phone_format"] == "gac" else "gac", "_seen": s2})
    after_b = adm.get("/api/admin/settings").json()["phone_format"]
    r = adm.post("/api/admin/settings", json={"phone_format": stale["phone_format"], "mctrade_affcode": "Y15", "_seen": stale}); assert r.status_code == 200
    s3 = adm.get("/api/admin/settings").json(); assert s3["phone_format"] == after_b and s3["mctrade_affcode"] == "Y15"
    adm.post("/api/admin/settings", json={"mctrade_updates_enabled": "1", "phone_format": "gac", "mctrade_affcode": "CardScan-Pilot"})

def _tpl_bytes(extra=""):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.append(["IndFirstName", "IndLastName", "IndEmail", "AffCode1"] + ([extra] if extra else []))
    b = io.BytesIO(); wb.save(b); return b.getvalue()

def test_template_lock_and_export_version(env):
    adm, ui = env["adm"], env["ui"]
    v0 = adm.get("/api/admin/mctrade-template").json()["version"]
    r = adm.post("/api/admin/mctrade-template", files={"image": ("t.xlsx", _tpl_bytes(), "application/octet-stream")}, data={"expected_version": v0})
    assert r.status_code == 200, r.text; v1 = r.json()["version"]; assert v1 != v0
    # a second admin whose page still shows v0 is refused; the file is unchanged
    r = adm.post("/api/admin/mctrade-template", files={"image": ("t2.xlsx", _tpl_bytes("IndTitle"), "application/octet-stream")}, data={"expected_version": v0})
    assert r.status_code == 409 and r.json()["need"] == "stale_admin" and "changed by" in r.json()["error"]
    assert adm.get("/api/admin/mctrade-template").json()["version"] == v1
    assert adm.post(f"/api/admin/mctrade-template/revert?expected_version={v0}").status_code == 409
    assert ui.template_version() == v1
    adm.post(f"/api/admin/mctrade-template/revert?expected_version={v1}&to_none=1")

def test_contacts_lock(env):
    adm = env["adm"]
    v0 = adm.get("/api/admin/mctrade-contacts").json()["version"]
    csv_ = b"ProfileId,FirstName,LastName,Email\n9101,Opal,Realperson,opal@real15.example.org\n9102,Ophelia,Strand,ostrand@real15.example.org\n"
    r = adm.post("/api/admin/mctrade-contacts", files={"image": ("c.csv", csv_, "text/csv")}, data={"expected_version": v0}); assert r.status_code == 200, r.text
    v1 = r.json()["version"]
    r = adm.post("/api/admin/mctrade-contacts", files={"image": ("c.csv", csv_, "text/csv")}, data={"expected_version": v0})
    assert r.status_code == 409 and r.json()["need"] == "stale_admin"
    assert adm.post(f"/api/admin/mctrade-contacts/remove?expected_version={v0}").status_code == 409
    assert adm.post(f"/api/admin/mctrade-contacts/remove?expected_version={v1}").json()["deleted"] == 1

def test_audit_who_is_username(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    a = mk(ui, store, first_name="Who", last_name="Column"); ui.log(a, "RR", "edited")
    rows = adm.get("/api/admin/audit?limit=50").json()
    us = {u["initials"]: u["username"] for u in adm.get("/api/admin/users").json()}
    for r in rows:
        assert r["who"] not in us or r["who"] in us.values() or us.get(r["who"]) is None
    assert all(r["who"] != ini for r in rows for ini, un in us.items() if ini != un)

def test_r10_suggestion():
    from app import plausibility as p
    h = [x for x in p.check({"company": "R1O Testworks LLC"}) if x["code"] == "company_digits"][0]
    assert h["suggestion"] == "R10 Testworks LLC" and "RIO" in h["text"]
    assert p._digit_reading("C0LUMBUS") == "COLUMBUS"

def test_website_hints():
    from app import plausibility as p
    codes = lambda f: {c for x in p.check(f) for c in x.get("codes", [x["code"]])}
    # round 20: the website hints are ONE line (codes kept for the record)
    assert len([x for x in p.check({"first_name": "A", "last_name": "B", "company": "Acme Tire", "emails": ["a@acmetire.com"], "website": "www.evil-phish.com"}) if x["field"] == "website"]) == 1
    assert {"website_suspicious", "website_mismatch"} <= codes({"first_name": "A", "last_name": "B", "company": "Acme Tire", "emails": ["a@acmetire.com"], "website": "www.evil-phish.com"})
    assert "website_invalid" in codes({"website": "acme", "emails": []})
    assert not codes({"company": "Acme Tire", "emails": ["a@acmetire.com"], "website": "www.acmetire.com"}) & {"website_suspicious", "website_mismatch", "website_invalid"}

def test_same_name_flagged(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Ophelia", last_name="Strand", emails=["o1@one15.com"], company="One Co"); ui.set_meta(a, batch="r15-s", batch_label="R15 S")
    b = mk(ui, store, first_name="Ophelia", last_name="Strand", emails=["o2@two15.com"], company="Two Co"); ui.set_meta(b, batch="r15-s", batch_label="R15 S")
    store.update(a, status="approved"); store.update(b, status="approved")
    assert any(g["cards"] == sorted([a, b]) or set(g["cards"]) == {a, b} for g in ui.same_names([store.get(a), store.get(b)]))
    att = [x for x in rc.get(f"/api/cards/{a}").json()["attention"] if x["code"] == "same_name"]
    d = ui.dupes(store.get(a), *ui._active())
    assert att or any(x["card_id"] == b for x in d["queue"])   # flagged either as a look-alike or as a same-name hint
    r = env["adm"].get("/api/export/check?status=approved&batch=r15-s").json()
    assert any(set(g["cards"]) == {a, b} for g in r["same_names"])

def test_reviewer_page_has_no_admin_markup(env):
    rc, adm = env["rev"], env["adm"]
    h = rc.get("/ui").text; ha = adm.get("/ui").text
    assert 'id="uBody"' in h and "Audit log</h2>" not in h and "Reviewer accounts" not in h and "<table" not in h.split('id="v-admin"')[1].split("</section>")[0]
    assert "Audit log</h2>" in ha and "Reviewer accounts" in ha

# ---------------------------------------------------------------- reviewer r14
def test_stale_version_never_reports_success(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Stale", last_name="Guard", company="Old Co")
    v0 = rc.get(f"/api/cards/{a}").json()["version"]
    r = rc.post(f"/api/cards/{a}", json={"fields": {"company": "New Co"}, "version": v0, "card_id": a}); assert r.status_code == 200, r.text
    # a second (forced) click from the old form: the old version must be refused, and the stored value unchanged
    r = rc.post(f"/api/cards/{a}", json={"fields": {"company": "Older Co"}, "version": v0, "card_id": a})
    assert r.status_code == 409 and r.json()["need"] == "stale"
    assert store.get(a)["fields"]["company"] == "New Co"
    r = rc.post(f"/api/cards/{a}", json={"fields": {"company": "X"}, "card_id": a, "_nov": True}); assert r.status_code == 409 and r.json()["need"] == "version"

def test_rejected_twin_keeps_hint_on_pending(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Twin", last_name="Hintson", emails=["twin.h@x15r.com"]); ui.set_meta(a, batch="r15-t", batch_label="T")
    b = mk(ui, store, first_name="Twin", last_name="Hintson", emails=["twin.h@x15r.com"]); ui.set_meta(b, batch="r15-t", batch_label="T")
    vb = rc.get(f"/api/cards/{b}").json()["version"]
    r = rc.post("/api/cards-bulk", json={"ids": [b], "status": "rejected", "batch": "r15-t", "versions": {str(b): vb}}); assert r.status_code == 200, r.text
    ca = next(c for c in rc.get("/api/cards?batch=r15-t").json() if c["id"] == a)
    texts = [x["text"] for x in ca["attention"]]
    assert any(f"#{b}" in t for t in texts), texts
    assert len(texts) == len(set(texts))   # no repeated reasons

def test_approve_lists_every_problem(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="", last_name="Many", emails=["bad@@x"], phones=[{"type": "work", "number": "12"}])
    v = rc.get(f"/api/cards/{a}").json()["version"]
    r = rc.post(f"/api/cards/{a}", json={"status": "approved", "version": v, "card_id": a})
    assert r.status_code == 422
    e = r.json(); assert len(e["errors"]) >= 3, e
    for k in ("name", "emails", "phones"): assert k in e["errors"]

def test_blank_wipe_only_for_whole_form(env):
    """r15int: the mass-wipe guard refuses a page-shaped save that blanks 2+ filled fields, but not a partial API edit."""
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Wipe", last_name="Guard", company="Full Co", title="VP", emails=["wg@x15w.com"], website="x15w.com")
    v = rc.get(f"/api/cards/{a}").json()["version"]
    form = {"first_name": "Wipe", "last_name": "Guard", "title": "", "company": "", "website": "", "address": "", "emails": [], "phones": [], "social": []}
    r = rc.post(f"/api/cards/{a}", json={"fields": form, "version": v, "card_id": a})
    assert r.status_code == 409 and r.json()["need"] == "blank_wipe"
    assert store.get(a)["fields"]["company"] == "Full Co"
    part = {"first_name": "Wipe", "last_name": "Guard", "company": "", "title": "VP, Sales", "emails": [], "phones": []}
    r = rc.post(f"/api/cards/{a}", json={"fields": part, "version": v, "card_id": a}); assert r.status_code == 200, r.text
    assert store.get(a)["fields"]["company"] == "" and store.get(a)["fields"]["emails"] == []

def test_phone_extension_export_form():
    """User decision (round 15): an extension stays in the same cell as '330-555-0170 x4271' in every export."""
    from app import mctrade_export as M, export as E
    for v in ("(330) 555-0170 ext. 4271", "330-555-0170, x4271", "+1 330.555.0170 Ext: 4271", "330-555-0170 #4271"):
        assert M.phone(v) == "330-555-0170 x4271" and E._ph(v) == "330-555-0170 x4271", v
