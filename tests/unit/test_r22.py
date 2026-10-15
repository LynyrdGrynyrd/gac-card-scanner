"""Round 22: PDF regression (RSS cap instead of RLIMIT_AS), garbled company/address/department, versioned 'This is correct',
one source for README counts, domain-check false flags, override reason rules, memory guard, l/I name fix, acronyms."""
import json, os, time
from test_app import mk
from app import ui as U, mctrade_export as MX, plausibility as P, consistency as C, parser as PZ

HERE = os.path.dirname(__file__)
def H(**f): return U.hard_errors({"first_name": "Ann"} | f)

def test_multipage_pdf_gives_three_cards():
    """r21 regression: every page of qa/fixtures/multipage_07_08_10.pdf failed with ReaderError (virtual-memory cap)."""
    from app import reader
    p = os.path.join(HERE, "..", "..", "qa", "fixtures", "multipage_07_08_10.pdf")
    d = open(p, "rb").read(); n = reader.run_count(d); assert n == 3
    names = []
    for i in range(n):
        parts = reader.run_page(d, i, n, "multipage_07_08_10.pdf"); assert len(parts) == 1
        names.append(reader.run_ocr(parts[0][0])["fields"].get("last_name"))
    assert names == ["Castellano", "Jorgensen", "Dunleavy"], names

def test_read_error_is_calm():
    from app import reader
    for ex in (reader.ReaderError(reader.CALM), RuntimeError("x"), MemoryError()):
        m = U._calm_read_error(ex); assert "Error" not in m and "(" not in m, m
    assert U._calm_read_error(reader.ReaderError("Cancelled.")) == "Cancelled."

def test_garbled_company_address_department_block():
    assert "company" in H(company="Law¦¦son Br0thers ~~ C0nstr|ction") and "company" in H(company="Acme Gr0up")
    assert "address" in H(address="g W Exchange St, Akron, OH 44308") and "department" in H(department="Sa|es ~~")
    for ok in ("Yahoo!", "IO Tech", "L1 Systems", "3M", "AT&T", "One Cascade Plaza Partners"): assert "company" not in H(company=ok), ok
    for ok in ("Suite #100, 10 Main St", "1 W Exchange St, Akron, OH 44308", "PO Box 10"): assert "address" not in H(address=ok), ok

def test_overridable_never_phones_or_formulas():
    assert "phones" not in U.OVERRIDABLE
    assert U.overridable({"last_name": '=HYPERLINK("x")'}) == [] and U.overridable({"title": "@SUM(A1)"}) == []
    assert U.overridable({"company": "Acme Gr0up"}) == ["company"]

def test_confirm_correct_versioned_archived_role_audit(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Ann", last_name="Lee", company="Acme Gr0up", emails=["ann@acme.com"])
    v = rev.get(f"/api/cards/{cid}").json()["version"]
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "company", "value": "Acme Gr0up"}).status_code == 409   # no version
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "company", "value": "Acme Group", "version": v}).status_code == 409   # other value
    assert rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "company", "value": "Acme Gr0up", "version": "x"}).status_code == 409   # stale
    r = rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "company", "value": "Acme Gr0up", "version": v, "reason": "printed like this"}); assert r.status_code == 200, r.text
    r2 = rev.post(f"/api/cards/{cid}/confirm-correct", json={"field": "company", "value": "Acme Gr0up", "version": r.json()["version"]}); assert r2.json().get("already")
    with st.db() as c:
        assert c.execute("SELECT COUNT(*) FROM card_history WHERE card_id=? AND action='hard_check_override'", (cid,)).fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM auth_log WHERE event LIKE ?", (f"confirmed as correct on card #{cid}:%",)).fetchone()[0] == 0   # round 24: one audit row (card history) per confirm
    assert U.confirmed_lines(st.get(cid)["fields"]) and "Company confirmed by RR: Acme Gr0up" in U.confirmed_lines(st.get(cid)["fields"])[0]
    c2 = mk(ui, st, first_name="Bo", last_name="Li", company="Beta Gr0up", emails=["bo@beta.com"]); ui.set_meta(c2, archived=1)
    v2 = rev.get(f"/api/cards/{c2}").json()["version"]
    r = rev.post(f"/api/cards/{c2}/confirm-correct", json={"field": "company", "value": "Beta Gr0up", "version": v2}); assert r.status_code == 409 and r.json()["need"] == "archived"

def test_readme_totals_match_counts():
    src = "\n".join(open(os.path.join(os.path.dirname(U.__file__), n), encoding="utf-8").read() for n in ("ui.py", "exporting.py", "admin_files.py", "privacy.py", "pages.py", "audit_log.py"))   # audit 2026-10 P2: ui.py was split
    assert "v_ == k_" not in src
    cnt = MX.counts({1: (MX.NEW, ""), 2: (MX.NEW, ""), 3: (MX.REVIEW, ""), 4: (MX.LEFT, "")})
    assert U.readme_totals(cnt) == "Totals: 2 new · 0 updates · 1 to review · 1 left out."

def test_readme_totals_match_dry_run(env):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    for fn, ln, co, ph in (("Alma", "Quintero", "Riverbend Bakery", "330-555-2210"), ("Bertrand", "Okafor", "Lakeside Optics", "216-555-4471")):
        c = mk(ui, st, first_name=fn, last_name=ln, emails=[f"{fn.lower()}@{co.split()[0].lower()}22.com"], phones=[{"number": ph}], company=co)
        ui.set_meta(c, batch="tot22", batch_label="Tot22"); r = adm.post(f"/api/cards/{c}", json={"status": "approved", "crm_action": "create_new"}); assert r.status_code == 200, r.text
    sel = [st.get(c["id"]) for c in st.all_() if (ui.meta(c["id"]) or {}).get("batch") == "tot22"]
    _, _, _, comp, summ = ui.build_export("xlsx", sel, {c["id"]: ui.meta(c["id"]) for c in sel}, "approved", "AA", "Tot22", preview=True)
    rd = comp["readme.txt"].decode(); cnt = summ["counts"]
    assert ui.readme_totals(cnt) in rd and cnt[MX.NEW] == 2
    assert "CROSS-BATCH lines below" not in rd and "Overrides: none." in rd

def test_domain_checks():
    assert "emails" in H(emails=["bhollis@firestoneparkhardwexample.com"])   # no website: still caught
    assert "emails" not in H(emails=["x@telecom.com"]) and "emails" not in H(emails=["ann@example.com"])
    f1 = {"emails": ["blake.hollis@gmail.com"], "website": "firestoneparkhardw.example.com", "company": "Firestone Park Hardware"}
    f2 = {"emails": ["b@mail.firestoneparkhardw.example.com"], "website": "https://shop.firestoneparkhardw.example.com/"}
    for f in (f1, f2):
        assert not P.website_check(f) and not C.check(json.loads(json.dumps(f)))[1], f
        assert "emails" not in H(**f) and "website" not in H(**f)

def test_override_reason_rules(env):
    for bad in ("\u200b\u200b", "-", "<img src=x onerror=alert(1)>", '=HYPERLINK("x")', "x" * 400): assert U.clean_reason(bad)[1], bad
    assert U.clean_reason(" no\u200b email on the card ") == ("no email on the card", None)
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Quillon", last_name="Varga", company="Varga Kilns 22", emails=[], phones=[])   # no email, no phone: soft problem (r22: a bad reason is refused only where a reason is needed)
    r = rev.post(f"/api/cards/{cid}", json={"status": "approved", "override_reason": "\u200b-", "crm_action": "create_new"}); assert r.status_code == 422 and r.json()["need"] == "reason"
    r = rev.post(f"/api/cards/{cid}", json={"status": "approved", "override_reason": "card has only a name", "crm_action": "create_new"}); assert r.status_code == 200, r.text

def test_memory_guard_never_reads_anyway(monkeypatch):
    monkeypatch.setattr(U, "mem_free_mb", lambda: 100); monkeypatch.setattr(U.time, "sleep", lambda s: None)
    assert U.wait_for_memory(None, max_s=0) is False
    import inspect; assert "max_s=None" in str(inspect.signature(U.wait_for_memory))

def test_name_l_for_I_and_acronyms():
    r = PZ.parse("Elena lbarra\nSales Director\nAcme Corp\nelena@acme.com\n330-555-0101")
    assert (r["first_name"], r["last_name"]) == ("Elena", "Ibarra") and r["confidence"]["name"] < 0.6
    assert PZ._tc("CFO") == "CFO" and PZ._tc("CHIEF FINANCIAL OFFICER") == "Chief Financial Officer"

def test_title_cut_off_hint_and_one_low_line(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Cut", last_name="Off", title="Director of", emails=["cut@off22.com"], phones=[{"number": "330-555-0123"}])
    a = rev.get(f"/api/cards/{cid}").json()["attention"]
    assert any("looks cut off" in x["text"] for x in a)
    assert len([x for x in a if x["code"] in ("low", "missing")]) <= 1

def test_admin_skip_ai(env):
    assert env["rev"].post("/api/admin/ai/skip-waiting", json={}).status_code == 403
    U.AI_WAIT[999999] = (1, 1); r = env["adm"].post("/api/admin/ai/skip-waiting", json={}).json()
    assert r["skipped"] >= 1 and 999999 not in U.AI_WAIT

def test_cancel_is_atomic_no_card_after_cancel(env, monkeypatch):
    """newcomer r21 HIGH: Cancel said '3 not scanned' but cards were created. A job cancelled while it was being read
    creates no card, and Cancel can no longer 'cancel' a job whose card exists."""
    ui, st, rev = env["ui"], env["store"], env["rev"]
    me = rev.get("/api/me").json(); me = (me.get("user") or me).get("initials")
    def fake_scan(*a, **k):
        r = rev.post("/api/jobs/cancel", json={"ids": ["cccccccc2201"], "batch": "cx22"}).json(); assert r["cancelled"] == 1
        return {"engine": "t", "text": "x", "fields": {"first_name": "Can", "last_name": "Cel", "emails": [], "phones": []}}
    monkeypatch.setattr(ui, "scan_limited", fake_scan)
    n0 = len(st.all_())
    with ui.JLOCK: ui.JOBS["cccccccc2201"] = {"id": "cccccccc2201", "state": "reading", "batch": "cx22", "who": me, "created": time.time()}
    import pytest
    with pytest.raises(ui._Cancelled): ui.ingest(b"\xff\xd8x", "auto", ".jpg", jid="cccccccc2201", meta_kw={"batch": "cx22"})
    assert len(st.all_()) == n0
    # a job that already has its card is not cancelled
    with ui.JLOCK: ui.JOBS["cccccccc2202"] = {"id": "cccccccc2202", "state": "reading", "batch": "cx22", "who": me, "card_id": 1, "created": time.time()}
    assert rev.post("/api/jobs/cancel", json={"ids": ["cccccccc2202"], "batch": "cx22"}).json()["cancelled"] == 0
    with ui.JLOCK: ui.JOBS.pop("cccccccc2201"); ui.JOBS.pop("cccccccc2202")
    ui.CANCELLED_BATCH.clear()
