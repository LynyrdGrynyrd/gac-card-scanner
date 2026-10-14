"""Round-10 regression tests: look-alikes without a company, one look-alike source, merge title/phone rules, address
split + confidence, preview READ-ME names, note sanitising, back-of-card website check, phone-mode address filter."""
import json
from test_app import mk

def _q(ui, store, cid):
    cs, metas = ui._active(); return ui.dupes(store.get(cid), cs, metas)

def test_name_plus_phone_without_company(env):
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="Rosalind", last_name="Okafor", company="", emails=[], phones=[{"type": "work", "number": "330-555-7781"}])
    b = mk(ui, store, first_name="Rosalind", last_name="Okafur", company="", emails=[], phones=[{"type": "mobile", "number": "(330) 555-7781"}])
    assert a in [x["card_id"] for x in _q(ui, store, b)["queue"]]

def test_name_plus_similar_email_without_company(env):
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="Teodora", last_name="Vance", company="", emails=["teodora.vance@zinc10.example"])
    b = mk(ui, store, first_name="Teodora", last_name="Vanse", company="", emails=["teodora.vanse@zinc10.example"])
    assert a in [x["card_id"] for x in _q(ui, store, b)["queue"]]

def test_cross_batch_phone_is_in_queue(env):
    """One look-alike source: an approved card in another batch with the same phone is listed in the review box."""
    ui, store = env["ui"], env["store"]
    a = mk(ui, store, first_name="Quill", last_name="One", company="Q1 Co", emails=["q1@q10.example"], phones=[{"type": "work", "number": "330-555-9911"}])
    ui.set_meta(a, batch="r10-a"); store.update(a, status="approved", reviewer="RR")
    b = mk(ui, store, first_name="Zed", last_name="Two", company="Other", emails=["z@z10.example"], phones=[{"type": "work", "number": "330-555-9911"}])
    ui.set_meta(b, batch="r10-b")
    d = _q(ui, store, b)
    hit = [x for x in d["queue"] if x["card_id"] == a]
    assert hit and "same phone" in hit[0]["why"] and not hit[0]["same_batch"] and a in d["lookalikes_elsewhere"]

def test_single_cross_batch_confirm_approves(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Ola", last_name="Once", emails=["ola@once10.example"]); ui.set_meta(a, batch="r10c-1")
    store.update(a, status="approved", reviewer="RR")
    b = mk(ui, store, first_name="Ola", last_name="Once", emails=["ola@once10.example"]); ui.set_meta(b, batch="r10c-2")
    r = rc.post(f"/api/cards/{b}", json={"status": "approved"})
    assert r.status_code == 409 and r.json()["need"] == "confirm_cross_batch"
    r = rc.post(f"/api/cards/{b}", json={"status": "approved", "confirm_cross_batch": True})
    assert r.status_code == 200, r.text
    assert store.get(b)["status"] == "approved"

def test_merge_title_longer_wins_or_goes_to_note(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Tia", last_name="Title", title="VP"); store.update(t, status="approved", reviewer="RR")
    s_ = mk(ui, store, first_name="Tia", last_name="Title", title="VP, Sales & Marketing")
    assert rc.post(f"/api/cards/{s_}", json={"status": "rejected", "merge_into": t}).status_code == 200
    assert store.get(t)["fields"]["title"] == "VP, Sales & Marketing"
    t2 = mk(ui, store, first_name="Una", last_name="Title", title="Treasurer"); store.update(t2, status="approved", reviewer="RR")
    s2 = mk(ui, store, first_name="Una", last_name="Title", title="Board Chair")
    pv = rc.post(f"/api/cards/{s2}/merge-preview", json={"into": t2}).json()
    assert any(r["field"] == "title" and r["to_note"] for r in pv["rows"])
    assert rc.post(f"/api/cards/{s2}", json={"status": "rejected", "merge_into": t2}).status_code == 200
    g = store.get(t2); assert g["fields"]["title"] == "Treasurer" and "Board Chair" in (g["note"] or "")

def test_merge_skips_truncated_phone(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Pia", last_name="Phone", phones=[{"type": "work", "number": "330-555-1201"}]); store.update(t, status="approved", reviewer="RR")
    s_ = mk(ui, store, first_name="Pia", last_name="Phone", phones=[{"type": "mobile", "number": "555-0199"}])
    assert rc.post(f"/api/cards/{s_}", json={"status": "rejected", "merge_into": t}).status_code == 200
    assert [p["number"] for p in store.get(t)["fields"]["phones"]] == ["330-555-1201"]

def test_address_split_ocr_separators():
    from app.mctrade_export import split_address as s
    assert s("3800 Embassy Pkwy.Akron.OH 44308") == {"address1": "3800 Embassy Pkwy", "address2": "", "city": "Akron", "state": "OH", "zip": "44308"}
    assert s("1 Cascade Plz;Akron;OH44308")["city"] == "Akron"
    assert s("200 S. Main St., Suite 400, Akron, OH 44308")["address1"] == "200 S. Main St."
    assert s("P.O. Box 12, Akron, OH 44309")["address1"] == "P.O. Box 12"

def test_valid_address_not_hard_to_read(env):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store, address="3800 Embassy Pkwy, Akron, OH 44308", confidence={"address": 0.5})
    c = store.get(cid); cs, metas = ui._active()
    assert "address" not in ui.low_fields(c["fields"])
    assert ui.enrich(c, cs, metas, full=True)["card"]["fields"]["confidence"]["address"] >= 0.8
    cid2 = mk(ui, store, address="smudged blur", confidence={"address": 0.5})
    cid3 = mk(ui, store, address="2300 State Rd, Akron. OH 44308", confidence={"address": 0.5})   # round 11: a misread stays flagged
    assert "address" in ui.low_fields(store.get(cid3)["fields"])
    assert "address" in ui.low_fields(store.get(cid2)["fields"])

def test_preview_readme_uses_preview_names(env):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store, first_name="Rhea", last_name="Readme"); store.update(cid, status="approved", reviewer="RR")
    cs, metas = ui._active(); sel = [store.get(cid)]
    out = ui.build_export("xlsx", sel, metas, "approved", "RR", preview=True)
    readme = out[3]["readme.txt"] if isinstance(out[3], dict) and "readme.txt" in out[3] else json.dumps(out, default=str)
    readme = readme.decode() if isinstance(readme, bytes) else readme
    assert "PREVIEW-" in readme

def test_note_sanitised(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store)
    assert rc.post(f"/api/cards/{cid}", json={"note": "=HYPERLINK(\"x\")\u200b hi"}).status_code == 200
    n = store.get(cid)["note"]; assert n.startswith("'=") and "\u200b" not in n
    assert ui.clean_note("- met at expo") == "- met at expo" and ui.clean_note("@SUM(1)") == "'@SUM(1)"

def test_back_website_plausible():
    from app import ui
    assert ui.plausible_site("www.acme.com") and ui.plausible_site("acmeco.xq", ["a@acmeco.xq"])
    assert not ui.plausible_site("wvw.c0m.xq") and not ui.plausible_site("j@nk") and not ui.plausible_site("ab.zz9")

def test_phone_candidates_hide_docker(monkeypatch):
    from app import phone
    import subprocess, socket
    class R: stdout = "2: eth0    inet 192.168.1.20/24 brd x\n3: docker0    inet 172.17.0.1/16 brd x\n4: virbr0    inet 192.168.122.1/24 x\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    c = phone.lan_candidates()
    assert "172.17.0.1" not in c and "192.168.122.1" not in c and c[0] == "192.168.1.20"
