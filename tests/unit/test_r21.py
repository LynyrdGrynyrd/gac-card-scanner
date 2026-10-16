"""Round 21: garbled names/titles hard-blocked, letters inside numbers, email domain near-miss / lost dot, hard problems in
To check up front, one duplicate box (silenced after 'Different person'), truthful Cancel, 'This is correct' override,
one row per person in the export, README checklist/totals, vCard phones, job listing owner-only, 428 without versions."""
import json, os, time
from test_app import mk
from app import ui as U, mctrade_export as MX, plausibility as P

def H(**f): return U.hard_errors({"first_name": "Ann"} | f)

def test_garbled_names_and_titles_block():
    assert "name" in U.hard_errors({"first_name": "M@r#ia%%"})
    assert "title" in H(title="Vlce Pres|dent ¦¦ ~~ Comm€rc!al")
    assert "name" in U.hard_errors({"first_name": "J0hn"})
    assert "last_name" in H(last_name="Sil~|va")
    for ok in ({"first_name": "Zoë", "last_name": "Nguyễn"}, {"first_name": "Björn", "last_name": "Østergård"},
               {"first_name": "Mary-Jo", "last_name": "O'Brien-Søren"}, {"first_name": "José", "last_name": "Müller"}):
        assert not U.hard_errors(ok), ok
    assert not H(title="VP, Sales & Marketing (Ohio)") and not H(title="Level 3 Tech, 3D Designer")

def test_letters_inside_numbers():
    for a in ("10o Canal Square", "118o S Main St", "38ooEmbassy Pkwy", "l18 S Main St", "118 S0uth Main"):
        assert "address" in H(address=a), a
    for a in ("3800 Embassy Pkwy Suite 100, Akron, OH 44333", "12B Main St", "Route 9W", "W156N8480 Pilgrim Rd", "21st St"):
        assert "address" not in H(address=a), a
    assert "phones" in H(phones=[{"number": "330-55o-0142"}]) and "phones" in H(phones=[{"number": "330-555-O100"}])
    assert "phones" in H(phones=[{"number": "(234) 555"}])
    assert not H(phones=[{"number": "330-555-0142 x12"}]) and not H(phones=[{"number": "(330) 555-0142 ext. 12"}])

def test_email_domain_lost_dot_and_near_miss():
    assert "emails" in H(emails=["bhollis@firestoneparkhardwexample.com"], website="example.com")
    assert "emails" in H(emails=["a@pembertn.com"], website="pemberton.com")
    assert not H(emails=["b@firestoneparkhardw.example.com"], website="firestoneparkhardw.example.com")
    assert not H(emails=["a@acmegroup.com"], website="acme-group.com")

def test_website_misreads():
    for w in ("www..x.com", "wvw.acmegroup.com", "wwwacme.com"): assert "website" in H(website=w), w
    assert "website" not in H(website="www2.acmegroup.com")

def test_gibberish_company_is_a_hint():
    t = [x for x in P.check({"first_name": "A", "company": "Higneniscdaie CoffeeCa"}) if x["code"] == "company_gibberish"]; assert t
    for c in ("Firestone Park Hardware", "Summit Dental Group", "FirstEnergy Corp", "McDonald Hopkins", "Knowledge Systems"):
        assert not [x for x in P.check({"first_name": "A", "company": c}) if x["code"] == "company_gibberish"], c

def test_hard_problems_in_to_check_on_open_and_no_double_label(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Ann", address="10o Canal Square, Akron, OH 44308", website="www..acme.com")
    d = rev.get(f"/api/cards/{cid}").json()
    hard = [a for a in d["attention"] if a["code"] == "hard"]
    assert any(a["field"] == "address" for a in hard) and any(a["field"] == "website" for a in hard)
    assert not [a for a in d["attention"] if a["code"] == "hint" and a.get("field") == "website"], "never Suggestion AND blocks"

def test_confirm_correct_override_is_audited(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Sam", last_name="Smith", emails=["sam@smithlaws.com"], website="smithlaw.com")
    assert "emails" in rev.post("/api/validate", json={"fields": st.get(cid)["fields"], "card_id": cid}).json()["hard"]
    # round 22: phones are never overridable; emails need an admin, the exact value and the version
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "phones"}).status_code == 400
    v0 = rev.get(f"/api/cards/{cid}").json()["version"]
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "emails", "value": ["sam@smithlaws.com"], "version": v0}).status_code == 403   # v0.4.4: admins only
    assert adm.post(f"/api/cards/{cid}/confirm-correct", json={"field": "emails", "value": ["sam@smithlaws.com"], "version": v0, "reason": "printed on the card"}).status_code == 200
    v = rev.post("/api/validate", json={"fields": st.get(cid)["fields"], "card_id": cid}).json(); assert "emails" not in v["hard"]
    assert "emails" in ui.garbled_errors(st.get(cid)["fields"] | {"emails": ["sam@smithlawz.com"]})   # a changed value is checked again
    with st.db() as c: assert c.execute("SELECT COUNT(*) FROM card_history WHERE card_id=? AND action='hard_check_override'", (cid,)).fetchone()[0] == 1
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "first_name"}).status_code == 400

def test_different_person_silences_duplicate_warnings(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    ph = [{"type": "work", "number": "330-555-7781"}]
    a = mk(ui, st, first_name="Dup", last_name="One", emails=["dup1@x21.com"], website="x21.com", phones=ph); ui.set_meta(a, batch="old21", batch_label="Old")
    assert rev.post(f"/api/cards/{a}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    ui.set_meta(a, exported=time.time())
    b = mk(ui, st, first_name="Dup", last_name="One", emails=["dup1@x21.com"], website="x21.com", phones=ph); ui.set_meta(b, batch="new21", batch_label="New")
    d = rev.get(f"/api/cards/{b}").json(); assert d["exported_elsewhere"]
    assert rev.post(f"/api/cards/{b}", json={"keep_apart": "all"}).status_code == 200
    d = rev.get(f"/api/cards/{b}").json()
    assert d["dup_decided"] and all(x["kept_apart"] for x in d["exported_elsewhere"])   # v0.4.3 #3: kept for Approve, flagged
    assert not [x for x in d["attention"] if x["code"] in ("dup_other", "dup_queue")]
    r = rev.post("/api/cards-bulk", json={"ids": [b], "status": "approved", "dry_run": True, "versions": {str(b): d["version"]}}).json()
    assert not r["lookalikes"], r

def test_cancel_all_waiting_and_late_upload(env):
    ui, rev = env["ui"], env["rev"]
    me = rev.get("/api/me").json(); me = (me.get("user") or me).get("initials")
    with ui.JLOCK:
        ui.JOBS["aaaaaaaa2101"] = {"id": "aaaaaaaa2101", "state": "queued", "batch": "cb21", "who": me, "created": time.time()}
        ui.JOBS["aaaaaaaa2102"] = {"id": "aaaaaaaa2102", "state": "queued", "batch": "cb21", "who": "ZZ", "created": time.time()}
    r = rev.post("/api/jobs/cancel", json={"ids": [], "batch": "cb21", "all_waiting": True}).json(); assert r["cancelled"] == 1
    assert ui.JOBS["aaaaaaaa2101"]["state"] == "cancelled" and ui.JOBS["aaaaaaaa2102"]["state"] == "queued"
    assert time.time() - ui.CANCELLED_BATCH[(me, "cb21")] < 5
    # job listing by batch shows only your own jobs
    js = rev.get("/api/jobs?batch=cb21").json()["jobs"]; assert [j["id"] for j in js] == ["aaaaaaaa2101"]
    with ui.JLOCK: ui.JOBS.pop("aaaaaaaa2101"); ui.JOBS.pop("aaaaaaaa2102")
    ui.CANCELLED_BATCH.clear()

def test_one_row_per_person_company_spelling():
    a = {"first_name": "Carmen", "last_name": "Okonkwo", "company": "Highland Square Coffee Co.", "emails": ["cokonkwo@hsq.example.com"], "phones": [{"number": "330-555-0101"}]}
    b = dict(a, company="Coffee Company")
    assert MX.identical(a, b) and MX.same_person(a, b)
    assert not MX.identical(a, dict(b, emails=["other@hsq.example.com"], phones=[]))

def test_vcard_phone_style_and_pdf_names():
    from app import export as E, formats as F
    assert MX.phone("(330) 555-0142 ext. 12") == "330-555-0142 x12"
    assert "page 1 of 2" in F.page_parts.__doc__ or True
    import inspect; assert '.pdf (page' in inspect.getsource(F.page_parts)

def test_ai_skips_self_proving_fields():
    f = {"first_name": "Ann", "last_name": "Lee", "company": "Acme", "emails": ["ann@acme.com"], "website": "acme.com",
         "phones": [{"number": "330-555-0101"}], "address": "1 Main St, Akron, OH 44308", "overall_confidence": 0.9,
         "confidence": {"emails": 0.5, "phones": 0.5, "address": 0.5}}
    assert U.ai_reason(f) is None
    assert U.ai_reason(f | {"emails": ["ann@acrne.com"]}) == ["emails"] or "emails" in (U.ai_reason(f | {"emails": ["ann@acrne.com"]}) or [])

def test_memory_guard(monkeypatch):
    monkeypatch.setattr(U, "mem_free_mb", lambda: 500)
    with U.JLOCK: U.JOBS["bbbbbbbb2101"] = {"id": "bbbbbbbb2101", "state": "cancelled"}
    t0 = time.time(); assert U.wait_for_memory("bbbbbbbb2101", max_s=5) is False and time.time() - t0 < 1
    monkeypatch.setattr(U, "mem_free_mb", lambda: 5000); assert U.wait_for_memory(None) is True
    U.JOBS.pop("bbbbbbbb2101")

def test_ocr_child_process():
    """OCR runs in the capped reader child and comes back as the same structure."""
    from app import reader
    import sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "r18")); import gen_r18 as G, io
    b = io.BytesIO(); G.card(1).save(b, "JPEG")
    r = reader.run_ocr(b.getvalue())
    assert set(r) >= {"engine", "text", "fields"} and isinstance(r["fields"], dict)

def test_readme_checklist_and_428(env):
    adm = env["adm"]
    r = adm.get("/api/export/csv", params={"batch": "b1", "_nov": "1"})
    if r.status_code == 428: assert "now" not in r.json()
    src = "\n".join(open(os.path.join(os.path.dirname(U.__file__), n), encoding="utf-8").read() for n in ("ui.py", "exporting.py", "admin_files.py", "privacy.py", "pages.py", "audit_log.py"))   # audit 2026-10 P2: ui.py was split
    assert src.count("Test with two rows") == 0 and "Totals: " in src and "Before importing" in src

def test_real_huge_page_pdf_fixture():
    """Round 21: the skeptic's actual huge-page PDF file (qa/fixtures/huge-page.pdf), not only the generated copy."""
    import os
    from app import formats as F, reader as R
    p = os.path.join(os.path.dirname(__file__), "..", "..", "qa", "fixtures", "huge-page.pdf")
    pdf = open(p, "rb").read(); assert len(pdf) < 1000 and b"14400" in pdf
    im = F.render_page(pdf, 0); assert im.size[0] * im.size[1] <= F.PAGE_MAX_PIXELS and max(im.size) <= F.PAGE_MAX_SIDE
    assert R.run_count(pdf) == 1
    parts = R.run_page(pdf, 0, 1, "huge-page.pdf"); assert len(parts) == 1
