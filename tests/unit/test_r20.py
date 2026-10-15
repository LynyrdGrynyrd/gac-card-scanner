"""Round 20: memory-safe file reading (skeptic C1/H1, coordinator r19 OOM), poison-job guard, owner kept on recovery,
calm AI-offline wording, SAME NAME counted on file rows, Cancel audit."""
import io, json, os, time, subprocess, pytest
from PIL import Image
from app import formats as F, reader as R
import sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "r18"))
import gen_r18 as G  # noqa: E402

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "..", "r20", "skeptic_hugepage_rendered.jpg")

def hugepage_pdf(side=14400):
    """The skeptic's 574-byte PDF: one side x side pt page with one filled rectangle."""
    content = b"0.5 g 100 100 %d %d re f" % (side // 2, side // 2)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R >>" % (side, side),
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"]
    out = b"%PDF-1.4\n"; offs = []
    for i, o in enumerate(objs, 1): offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out); out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)

def _wait(rc, jid, states=("done", "error", "split", "cancelled")):
    for _ in range(600):
        st = rc.get("/api/jobs?ids=" + jid).json()["jobs"][0]
        if st["state"] in states: return st
        time.sleep(0.2)
    return st

def _me(rc):
    me = rc.get("/api/me").json(); return (me.get("user") or me).get("initials")

# ---------------------------------------------------------------- page / photo caps
def test_huge_page_is_capped_at_12mp():
    pdf = hugepage_pdf(); assert len(pdf) < 1000
    im = F.render_page(pdf, 0); assert im.size[0] * im.size[1] <= F.PAGE_MAX_PIXELS and max(im.size) <= F.PAGE_MAX_SIDE

def test_normal_pages_render_at_200dpi():
    assert abs(F.page_scale(252, 144) - 200 / 72) < 1e-9          # a 3.5x2 in card
    s = F.page_scale(2160, 1260); assert 2160 * s * 1260 * s <= F.PAGE_MAX_PIXELS + 1   # the 30x17.5 in scanner sheet

def test_skeptic_fixture_photo_is_downscaled():
    data = open(FIX, "rb").read(); assert Image.open(io.BytesIO(data)).size == (6325, 6325)
    out = F.prepare_for_ocr(data); w, h = Image.open(io.BytesIO(out)).size
    assert w * h <= F.PHOTO_MAX_PIXELS and w == h
    small = io.BytesIO(); Image.new("RGB", (800, 500), "white").save(small, "JPEG"); assert F.prepare_for_ocr(small.getvalue()) == small.getvalue()

# ---------------------------------------------------------------- reader child process
def test_reader_child_counts_and_renders_one_page():
    pdf = G.multipage_pdf(); assert R.run_count(pdf) == 3
    parts = R.run_page(pdf, 1, 3, "cards.pdf"); assert [l for _, l in parts] == ["cards.pdf (page 2 of 3)"]
    assert Image.open(io.BytesIO(parts[0][0])).size[0] < 800

def test_reader_child_errors_are_calm():
    with pytest.raises(R.ReaderError, match="password"): R.run_count(G.encrypted_pdf())
    with pytest.raises(R.ReaderError, match="damaged"): R.run_count(G.corrupt_pdf())

def test_reader_memory_limit_kills_only_the_child(monkeypatch):
    monkeypatch.setattr(R, "MEM_MB", 120)                         # far too little to even load the libraries
    with pytest.raises(R.ReaderError) as e: R.run_page(hugepage_pdf(), 0, 1, "huge.pdf")
    assert str(e.value) == R.CALM and "Errno" not in str(e.value)

def test_reader_time_budget(monkeypatch):
    monkeypatch.setattr(R, "TIMEOUT", 0.05)
    with pytest.raises(R.ReaderError, match="couldn't be read safely"): R.run_page(hugepage_pdf(), 0, 1, "huge.pdf")

# ---------------------------------------------------------------- server: background PDF jobs, Cancel, recovery
def test_huge_pdf_upload_is_read_in_background(env):
    rc = env["rev"]
    r = rc.post("/api/jobs", data={"batch": "r20-h"}, files={"image": ("hugepage.pdf", hugepage_pdf(), "application/pdf")})
    assert r.status_code == 200 and r.json()["pdf"] and r.json()["pages"] == 1
    st = _wait(rc, r.json()["job"]); assert st["state"] in ("split", "error"), st
    for c in st.get("children") or []:
        if c.get("job"):
            ch = _wait(rc, c["job"]); assert ch["state"] in ("done", "error")
            if ch["state"] == "done":
                fn = env["ui"].meta(ch["card"]["id"])["filename"]; assert fn.startswith("hugepage.pdf (page 1 of 1")

def test_page_limit_checked_before_any_job(env):
    many = G.pdf([Image.new("RGB", (100, 60), "white")] * 201, 72)
    n = len(env["ui"].JOBS)
    r = env["rev"].post("/api/jobs", files={"image": ("many.pdf", many, "application/pdf")})
    assert r.status_code == 422 and "limit is 200" in r.json()["error"] and len(env["ui"].JOBS) == n

def test_cancel_stops_pdf_rendering(env, monkeypatch):
    ui, rc = env["ui"], env["rev"]
    monkeypatch.setattr(ui, "_split_pdf", lambda jid: None)        # keep it 'queued' so the test is not a race
    pdf = G.pdf([G.card(i) for i in range(6)], 150)
    r = rc.post("/api/jobs", data={"batch": "r20-c", "batch_label": "R20 C"}, files={"image": ("six.pdf", pdf, "application/pdf")}); jid = r.json()["job"]
    assert env["rev2"].post("/api/jobs/cancel", json={"ids": [jid]}).json()["cancelled"] == 0      # not theirs
    assert rc.post("/api/jobs/cancel", json={"ids": [jid], "batch_label": "R20 C"}).json()["cancelled"] == 1
    monkeypatch.undo(); ui._split_pdf(jid)                                                         # the worker skips it
    assert ui.JOBS[jid]["state"] == "cancelled" and not ui.JOBS[jid]["children"]
    assert not any(os.path.exists(os.path.join(ui.INBOX, jid + x)) for x in (".pdf", ".json", ".reading"))
    rows = ui.db().execute("SELECT reviewer, detail FROM card_history WHERE action='upload_cancelled' ORDER BY id DESC LIMIT 1").fetchone()
    assert rows and json.loads(rows[1])["not_scanned"] == 1 and json.loads(rows[1])["batch"] == "R20 C"
    assert "0 kept, 1 not scanned" in ui._audit_text("upload_cancelled", None, None, json.loads(rows[1]))

def test_cancel_mid_render_kills_reader(env):
    ui = env["ui"]
    called = []
    class P:
        def poll(self): return None
        def kill(self): called.append(1)
    R.RUNNING["r20midrender"] = P(); R.stop("r20midrender"); R.RUNNING.pop("r20midrender"); R.CANCELLED.discard("r20midrender")
    assert called == [1]

def _inbox_job(ui, jid, args, ext=".bin", reading=False):
    open(os.path.join(ui.INBOX, jid + ext), "wb").write(b"x")
    json.dump(args, open(os.path.join(ui.INBOX, jid + ".json"), "w"))
    if reading: open(os.path.join(ui.INBOX, jid + ".reading"), "w").close()

def test_recover_sets_aside_poison_job_and_keeps_owner(env, monkeypatch):
    ui = env["ui"]; ran = []
    monkeypatch.setattr(ui.POOL, "submit", lambda *a, **k: ran.append(a[1]))
    monkeypatch.setattr(ui.SPLIT_POOL, "submit", lambda *a, **k: ran.append(a[1]))
    base = {"engine": "auto", "ext": ".jpg", "batch": "r20-r", "label": "R20 R", "fname": "a.jpg", "sha": "s", "who": "QS"}
    _inbox_job(ui, "a20000000001", base, reading=True)                 # was being read when the server died
    _inbox_job(ui, "a20000000002", base)                               # still waiting: re-queued, owner kept
    _inbox_job(ui, "a20000000003", {"kind": "pdf", "engine": "auto", "batch": "r20-r", "label": "", "fname": "p.pdf", "pages": 2, "allow_duplicate": "", "who": "QS"}, ext=".pdf")
    ui.recover()
    assert "a20000000001" not in ran and "a20000000002" in ran and "a20000000003" in ran
    assert ui.JOBS["a20000000002"]["who"] == "QS" and ui.JOBS["a20000000003"]["who"] == "QS"
    assert not os.path.exists(os.path.join(ui.INBOX, "a20000000001.bin"))
    rec = json.load(open(os.path.join(ui.DONE, "a20000000001.json"))); assert rec["state"] == "error" and "set aside" in rec["error"]
    st = env["rev"].get("/api/jobs?ids=a20000000001").json()["jobs"][0]; assert st["state"] == "error"
    # skeptic M1: someone else can't cancel a recovered job any more
    assert env["rev"].post("/api/jobs/cancel", json={"ids": ["a20000000002"]}).json()["cancelled"] == 0
    for j in ("a20000000002", "a20000000003"):
        ui.JOBS.pop(j, None); ui._inbox_clear(j)

def test_run_marks_reading_and_cleans_up(env):
    ui, rc = env["ui"], env["rev"]
    b = io.BytesIO(); G.card(2).save(b, "JPEG")
    st = _wait(rc, rc.post("/api/jobs", data={"batch": "r20-m"}, files={"image": ("m.jpg", b.getvalue(), "image/jpeg")}).json()["job"])
    assert st["state"] == "done" and not os.path.exists(os.path.join(ui.INBOX, st["id"] + ".reading"))

# ---------------------------------------------------------------- (a) AI offline
def test_health_offline_when_nothing_answers(env):
    from app import main
    main._AI.update(t=time.time(), up=True)                   # a stale 'online' from before the AI stopped
    main._AI["t"] -= 6
    j = env["rev"].get("/health").json(); assert j["ai_checker"] == "offline" and j["ai_note"] == "AI check is off right now. Scanning still works."
    assert "Errno" not in json.dumps(j)

def test_ai_refused_error_is_calm(env, monkeypatch):
    ui = env["ui"]
    assert ui.calm_ai_detail({"error": "URLError: <urlopen error [Errno 111] Connection refused>"})["error"] == ui.AI_OFF
    assert ui.calm_ai_detail({"error": "The AI was too busy to answer."})["error"].startswith("The AI was too busy")

# ---------------------------------------------------------------- (c) SAME NAME
def test_same_name_counts_file_rows_only(env):
    ui = env["ui"]
    a = {"id": 1, "fields": {"first_name": "Avery", "last_name": "Abernathy"}}
    b = {"id": 2, "fields": {"first_name": "Avery", "last_name": "Abernathy"}}
    c = {"id": 3, "fields": {"first_name": "Ophelia", "last_name": "Strand"}}
    d = {"id": 4, "fields": {"first_name": "Ophelia", "last_name": "Strand"}}
    g = ui.same_names([a, c, d], contacts_from=[a, b, c, d])      # card 2 was merged into card 1's row
    assert [x["name"] for x in g if x["with"] == "export"] == ["Ophelia Strand"]
    assert ui.ids3([1, 2, 3, 4, 5]) == "#1, #2, #3 and 2 more" and ui.ids3([7]) == "#7"

# ---------------------------------------------------------------- (e) Scan screen / banner
def test_scan_screen_and_update_banner(env):
    html = env["rev"].get("/static/ui/index.html").text
    assert "One card per photo" not in html
    assert env["rev"].get("/api/update").json()["show_banner"] is False

# ---------------------------------------------------------------- (b) supervised restart
@pytest.mark.skipif(os.name == "nt", reason="scripts/serve.sh is the POSIX (Linux/macOS server) launcher; Windows uses start.bat")
def test_serve_sh_restarts_a_dead_server(tmp_path):
    fake = tmp_path / "py"; cnt = tmp_path / "n"
    fake.write_text(f"#!/bin/bash\necho run >> {cnt}\nexit 1\n"); fake.chmod(0o755)
    root = os.path.join(HERE, "..", "..")
    p = subprocess.Popen(["bash", os.path.join(root, "scripts", "serve.sh")], env=dict(os.environ, GAC_PYTHON=str(fake), PORT="1"),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(7.5); p.terminate(); p.wait(5)
    assert cnt.read_text().count("run") >= 2

# ---------------------------------------------------------------- coordinator r19: hard checks for misreads
def test_garbled_values_are_hard_errors(env):
    ui = env["ui"]
    e = ui.hard_errors({"first_name": "Dmitri", "address": "118o S Main St, Akron, OH 44308", "emails": [], "phones": []})
    assert "118o" in e["address"]
    e = ui.hard_errors({"first_name": "F", "website": "wwwsummitcap.com", "emails": [], "phones": []}); assert "website" in e
    e = ui.hard_errors({"first_name": "F", "website": "www.pemberton.com", "emails": ["f@pembertn.com"], "phones": []}); assert "emails" in e
    ok = {"first_name": "A", "address": "1180 S Main St Suite 2B, Akron, OH 44308", "website": "www.acme.com", "emails": ["a@acme.com"], "phones": []}
    assert not ui.hard_errors(ok)
    assert not ui.hard_errors({"first_name": "K", "website": "acme.com", "emails": ["k@same.example"], "phones": []})   # two different names

def test_approve_blocked_until_fixed(env):
    ui, st, rc = env["ui"], env["store"], env["rev"]
    cid = st.add("t", "", {"first_name": "Dmitri", "last_name": "Bosco", "company": "Bosco Co", "address": "118o S Main St, Akron, OH 44308",
                           "emails": ["d@bosco.example"], "phones": [], "website": ""}, "x.jpg")
    r = rc.post(f"/api/cards/{cid}", json={"status": "approved", "override_reason": "looks fine"}); assert r.status_code == 422 and "118o" in r.text
    f = st.get(cid)["fields"]; f["address"] = "1180 S Main St, Akron, OH 44308"
    r = rc.post(f"/api/cards/{cid}", json={"fields": f, "status": "approved"}); assert r.status_code == 200, r.text

def test_merge_never_takes_garbled_value(env):
    ui = env["ui"]
    assert ui.merge_pick({"address": "1180 S Main St, Akron, OH 44308"}, {"address": "118o S Main St, Akron, OH 44308"}, "address") == "tgt"
    assert ui.merge_pick({"address": ""}, {"address": "118o S Main St"}, "address") is None

def test_one_website_line():
    from app import plausibility as p
    h = [x for x in p.check({"first_name": "A", "last_name": "B", "company": "Acme Tire", "emails": ["a@acmetire.com"], "website": "www.evil-phish.com"}) if x["field"] == "website"]
    assert len(h) == 1 and "looks misread" in h[0]["text"]

def test_edited_card_not_unclear(env):
    ui = env["ui"]
    assert ui._shown_conf({"overall_confidence": 0.4, "first_name": "A"}, [], {"emails": "edited:RR"}) == 0.8
    assert ui._shown_conf({"overall_confidence": 0.4, "first_name": "A"}, [], {}) == 0.4

def test_bulk_adds_as_new_when_updates_off(env):
    ui, st, rc = env["ui"], env["store"], env["rev"]
    from app import auth
    auth.set_setting("mctrade_updates_enabled", "0")
    try:
        r = rc.get("/api/cards").json()
        cid = st.add("t", "", {"first_name": "Sam", "last_name": "Sample", "company": "Sample Co", "emails": ["sam@sample.example"], "phones": [], "website": ""}, "y.jpg")
        orig = ui.approval_check
        def fake(c, f, b):
            if c["id"] == cid and not ui.meta(cid).get("crm_action"):
                return ui.JSONResponse({"error": "x", "need": "crm_choice"}, 409)
            return None
        ui.approval_check = fake
        try: res = rc.post("/api/cards-bulk", json={"ids": [cid], "status": "approved"}).json()
        finally: ui.approval_check = orig
        assert cid in res["updated"] and ui.meta(cid)["crm_action"] == "create_new"
    finally: auth.set_setting("mctrade_updates_enabled", "1")

def test_cross_batch_readme_ids_capped(env):
    assert env["ui"].ids3(list(range(1, 31))) == "#1, #2, #3 and 27 more"
