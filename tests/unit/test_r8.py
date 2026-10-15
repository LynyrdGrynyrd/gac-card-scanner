"""Round-8 regression tests (mctrade-r5, manager-r8, parttimer-r2, newcomer-r8, reviewer-r8)."""
import io, os, re, sys, json, csv, tarfile, sqlite3, subprocess, itertools
from test_app import mk
from openpyxl import Workbook, load_workbook
from app import mctrade_export as M, crm_source, plausibility, auth

HERE = os.path.dirname(__file__)
FAKE_REAL = os.path.join(HERE, "fake_real_contacts.csv")
SAMPLE_CSV = os.path.join(HERE, "..", "..", "data", "existing_contacts.csv")
_B = itertools.count(1)

def _contacts(tmp_path, rows):
    p = tmp_path / f"contacts{next(_B)}.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["profile_id", "first_name", "last_name", "organization", "email", "phone"]); w.writerows(rows)
    return str(p)

def _three_way(adm, batch):
    """Decisions per card from (1) the export file's summary, (2) the on-screen preview the sign-off uses, (3) the dry run."""
    r = adm.get(f"/api/export/xlsx?status=approved&batch={batch}&preview=1"); assert r.status_code == 200, r.text
    exp = json.loads(r.headers["X-Summary"])["decisions"]
    so = adm.get(f"/api/export/xlsx?status=approved&batch={batch}&preview=1&view=1").json()["decisions"]
    html = adm.get(f"/api/export/dryrun?status=approved&batch={batch}").text
    dry = dict(re.findall(r"data-card='(\d+)' data-decision='(\w+)'", html))
    return exp, so, dry, json.loads(r.headers["X-Summary"])

SCEN = [   # (fields, crm_action, expected with updates OFF, expected with updates ON)
    (dict(first_name="Maria", last_name="Delgado", company="Summit Valley Bank", emails=["maria.delgado@svb-test.example"]), "update_existing", "review", "update"),
    (dict(first_name="Maria", last_name="Delgado", company="Summit Valley Bank", emails=["maria.delgado@svb-test.example"]), "create_new", "review", "review"),
    (dict(first_name="Maria", last_name="Delgado", company="Summit Valley Bank", emails=["maria.delgado@svb-test.example"]), "", "review", "review"),
    (dict(first_name="Linda", last_name="Park", company="Akron Riverfront Realty LLC", emails=["lpark@gmail.com"]), "", "review", "review"),   # same name+org, other email
    (dict(first_name="Robert", last_name="Hughes", company="Hughes & Partners Law", emails=["rob@other.example"],
          phones=[{"type": "work", "number": "(330) 555-0190"}]), "update_existing", "review", "review"),       # name+phone, email differs
    (dict(first_name="Zed", last_name="Nobody", company="New Co", emails=["zed@newco.example"]), "", "new", "new"),
    (dict(first_name="Zoe", last_name="Newman", company="Other New Co", emails=["zoe@othernew.example"]), "create_new", "new", "new"),
    (dict(first_name="Una", last_name="Known", company="Nowhere", emails=["una@nowhere.example"]), "update_existing", "review", "review"),
    (dict(first_name="", last_name="Blank", company="X", emails=["b@x.example"]), "", "left", "left"),
]

def _approve(env, cid, act):
    ui, st = env["ui"], env["store"]
    if act: ui.set_meta(cid, crm_action=act)
    st.update(cid, status="approved", reviewer="RR", note="")

def test_export_signoff_dryrun_agree_switch_on_and_off(env, monkeypatch):
    """mctrade-r5 F2/F3, manager-r8 M-r8-2: ONE classification for export, sign-off and dry run, many fixtures, both switch states."""
    ui, st, adm = env["ui"], env["store"], env["adm"]
    monkeypatch.setenv("MCTRADE_CRM_EXPORT", FAKE_REAL)
    for on in ("0", "1"):
        auth.set_setting("mctrade_updates_enabled", on); b = f"r8agree{on}"; ids = {}
        for i, (f, act, off_exp, on_exp) in enumerate(SCEN):
            cid = mk(ui, st, **(dict(title="", website="", address="", phones=[{"type": "work", "number": f"216-555-{7000 + i + 20 * int(on)}"}]) | f))
            ui.set_meta(cid, batch=b, batch_label=b); _approve(env, cid, act); ids[cid] = on_exp if on == "1" else off_exp
        exp, so, dry, summ = _three_way(adm, b)
        got = {int(k): v for k, v in exp.items()}
        assert exp == so == dry, (on, exp, so, dry)
        assert got == ids, (on, got, ids)
        # a matched card is never in the new-profiles file
        assert summ["new_rows"] == sum(1 for v in ids.values() if v == "new") and summ["update_rows"] == sum(1 for v in ids.values() if v == "update")
    auth.set_setting("mctrade_updates_enabled", "1")

def test_ambiguous_email_two_profiles_review_everywhere(env, monkeypatch, tmp_path):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    p = _contacts(tmp_path, [["880001", "James", "Okafor", "CF Tire", "j.okafor@cft2.example", ""], ["880002", "Jim", "Okafor", "CF Tire", "j.okafor@cft2.example", ""]])
    monkeypatch.setenv("MCTRADE_CRM_EXPORT", p)
    for act in ("create_new", "update_existing", ""):
        b = "r8amb" + (act or "none")
        cid = mk(ui, st, first_name="James", last_name="Okafor", company="CF Tire", emails=["j.okafor@cft2.example"]); ui.set_meta(cid, batch=b, batch_label=b)
        _approve(env, cid, act)
        exp, so, dry, summ = _three_way(adm, b)
        assert exp[str(cid)] == so[str(cid)] == dry[str(cid)] == "review", (act, exp, dry)
        assert summ["new_rows"] == 0 and summ["update_rows"] == 0

def test_missing_companion_is_404(env):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    cid = mk(ui, st, first_name="Comp", last_name="Anion", emails=["comp@anion.example"]); ui.set_meta(cid, batch="r8comp", batch_label="R8COMP")
    _approve(env, cid, "")
    r = adm.get("/api/export/xlsx?status=approved&batch=r8comp&preview=1&companion=updates.xlsx"); assert r.status_code == 404
    r = adm.get("/api/export/xlsx?status=approved&batch=r8comp&preview=1&companion=nonsense"); assert r.status_code == 404
    assert adm.get("/api/export/xlsx?status=approved&batch=r8comp&preview=1&companion=readme.txt").status_code == 200

def test_sample_contacts_refused_as_real(env, tmp_path):
    adm = env["adm"]
    up = lambda name, data: adm.post("/api/admin/mctrade-contacts", files={"image": (name, data)})
    raw = open(SAMPLE_CSV, "rb").read()
    r = up("existing_contacts.csv", raw); assert r.status_code == 422 and "SAMPLE" in r.json()["error"]
    edited = raw.decode().replace("linda@akronriverfront.com", "linda@changed.example").encode()       # a re-saved / edited copy
    assert up("copy.csv", edited).status_code == 422
    one = b"profile_id,first_name,last_name,email\n55555,Ann,Lee,rhughes@hugheslaw.com\n"            # a sample email
    assert up("x.csv", one).status_code == 422
    ids = b"Profile ID,First Name,Last Name,Email\n1003,Ann,Lee,ann@lee.example\n"                     # a sample Profile ID
    r_ = up("x.csv", ids); assert r_.status_code == 200, r_.text   # round 9 (manager-r9 M-r9-1): one ID in common is not the SAMPLE file
    assert env["adm"].post("/api/admin/mctrade-contacts/remove", json={}).status_code == 200
    bad = up("bad.csv", b"Name,Phone\nAnn,1\n"); assert bad.status_code == 422
    msg = bad.json()["error"]; assert "/tmp" not in msg and "ALIASES" not in msg and "dryrun.py" not in msg and "Profile ID" in msg
    nofirst = up("nofirst.csv", b"Profile ID,Last Name,Email\n77,Lee,a@b.example\n"); assert nofirst.status_code == 422   # header schema
    assert crm_source.looks_like_sample(crm_source.sample_rows())

def test_remove_contacts_deletes_no_bak(env):
    adm = env["adm"]; d = crm_source.DATA
    open(os.path.join(d, "mctrade_contacts.csv.bak"), "w").write("old leftover")
    r = adm.post("/api/admin/mctrade-contacts", files={"image": ("real.csv", open(FAKE_REAL, "rb"))}); assert r.status_code == 200, r.text
    p = os.path.join(d, "mctrade_contacts.csv"); assert os.path.isfile(p) and (os.stat(p).st_mode & 0o777) == 0o600
    assert not os.path.exists(p + ".bak")                                         # the leftover was wiped by the upload
    r = adm.post("/api/admin/mctrade-contacts", files={"image": ("real2.csv", open(FAKE_REAL, "rb"))}); assert r.status_code == 200
    assert not os.path.exists(p + ".bak")                                         # replacing keeps no copy
    r = adm.post("/api/admin/mctrade-contacts/remove"); assert r.json()["deleted"] == 1
    assert not any(f.startswith("mctrade_contacts") for f in os.listdir(d)) and crm_source.real() is None
    assert any("overwritten and deleted" in x["what"] for x in adm.get("/api/admin/audit?q=contacts").json())

def test_secure_delete_overwrites(tmp_path):
    p = tmp_path / "x.csv"; p.write_bytes(b"secret member list")
    assert crm_source.secure_delete(str(p)) and not p.exists() and not crm_source.secure_delete(str(p))

def test_dryrun_audit_counts_and_left_out(env, monkeypatch):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    monkeypatch.setenv("MCTRADE_CRM_EXPORT", FAKE_REAL); auth.set_setting("mctrade_updates_enabled", "0")
    a = mk(ui, st, first_name="Aud", last_name="One", emails=["aud1@x.example"]); b = mk(ui, st, first_name="Sarah", last_name="Whitman", company="Portage Lakes Consulting Group", emails=["sarah.whitman@plc-test.example"])
    for c in (a, b): ui.set_meta(c, batch="r8aud", batch_label="R8 audit batch"); _approve(env, c, "")
    assert adm.get("/api/export/dryrun?status=approved&batch=r8aud").status_code == 200
    row = next(x for x in adm.get("/api/admin/audit?q=R8+audit+batch").json() if x["what"].startswith("dry run: ran"))
    assert "UPDATE 0, CREATE 1, NEEDS REVIEW 1, LEFT OUT 0" in row["what"], row["what"]
    seg = row["what"].split("not in either file")[1].split("; cards checked")[0]   # round 9 (manager-r9 L-r9-1/2)
    assert f"1 (NEEDS REVIEW + LEFT OUT): #{b}" in seg and f"#{a}" not in seg and f"#{a}" in row["what"].split("cards checked")[1]
    r = adm.get("/api/export/dryrun?status=approved&batch=r8nope")
    assert r.status_code == 404
    auth.set_setting("mctrade_updates_enabled", "1")

def test_mc_trade_choice_in_history(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    monkeypatch.setenv("MCTRADE_CRM_EXPORT", FAKE_REAL)
    cid = mk(ui, st, first_name="James", last_name="Okafor", company="Cuyahoga Falls Tire Co.", emails=["james.okafor@cft-test.example"]); ui.set_meta(cid, batch="r8ch", batch_label="R8CH")
    r = rev.post(f"/api/cards/{cid}", json={"crm_action": "create_new"}); assert r.status_code == 200, r.text
    assert any(h["action"] == "mc_trade_choice" and h["detail"] == "create_new" for h in ui.history(cid))

def _tpl(cols):
    wb = Workbook(); wb.active.append(cols); b = io.BytesIO(); wb.save(b); return b.getvalue()
def test_template_header_limits(env, tmp_path, monkeypatch):
    adm = env["adm"]; monkeypatch.setattr(M, "TEMPLATE_XLSX", str(tmp_path / "mctrade_template.xlsx"))
    up = lambda cols: adm.post("/api/admin/mctrade-template", files={"image": ("t.xlsx", _tpl(cols))})
    base = ["ProfileID", "IndFirstName", "IndLastName", "IndEmail", "AffCode1"]
    r = up(base + ["X" * 201]); assert r.status_code == 422 and "200" in r.json()["error"]
    r = up(base[:2] + [""] + base[2:]); assert r.status_code == 422 and "blank" in r.json()["error"]
    assert up(base + ["", "", ""]).status_code == 200                                  # trailing empty cells are not columns
    assert up(base + ["Y" * 200]).status_code == 200
    # a lone first template can be removed in Settings (revert ?to_none=1); the API says so via can_revert=False + present
    os.remove(M.TEMPLATE_XLSX + ".bak") if os.path.exists(M.TEMPLATE_XLSX + ".bak") else None
    i = adm.get("/api/admin/mctrade-template").json(); assert i["present"] and not i["can_revert"]
    assert adm.post("/api/admin/mctrade-template/revert?to_none=1").json()["present"] is False

def test_website_in_export_when_template_has_column(env, tmp_path, monkeypatch):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    cid = mk(ui, st, first_name="Web", last_name="Site", emails=["web@site.example"], website="www.site.example"); ui.set_meta(cid, batch="r8web", batch_label="R8WEB")
    _approve(env, cid, "")
    v = adm.get("/api/export/xlsx?status=approved&batch=r8web&preview=1&view=1").json()
    assert v["rows"][0][v["headers"].index("Website")] == "www.site.example"
    monkeypatch.setattr(M, "TEMPLATE_XLSX", str(tmp_path / "mctrade_template.xlsx"))
    open(M.TEMPLATE_XLSX, "wb").write(_tpl(["ProfileID", "IndFirstName", "IndLastName", "IndEmail", "AffCode1"]))
    rd = adm.get("/api/export/xlsx?status=approved&batch=r8web&preview=1&companion=readme.txt").text
    assert "NO website column" in rd

def test_merge_prefers_value_that_passes_checks(env):
    ui, st = env["ui"], env["store"]
    assert any(s["code"] == "addr_punct" for s in plausibility.check({"address": "12 Oak St, Akron. OH 44308"}))
    assert ui.merge_pick({"address": "12 Oak St, Akron. OH 44308"}, {"address": "12 Oak St, Akron, OH 44308"}, "address") == "src"
    assert ui.merge_pick({"address": "12 Oak St, Akron, OH 44308"}, {"address": "12 Oak St, Akron. OH 44308"}, "address") == "tgt"
    assert ui.merge_pick({"title": ""}, {"title": "CEO"}, "title") == "src" and ui.merge_pick({"title": "CEO"}, {"title": ""}, "title") is None
    t = mk(ui, st, first_name="Merge", last_name="Pref", address="12 Oak St, Akron. OH 44308"); s_ = mk(ui, st, first_name="Merge", last_name="Pref", address="12 Oak St, Akron, OH 44308")
    r = env["rev"].post(f"/api/cards/{s_}/merge-preview", json={"into": t}).json()["rows"]
    assert any(x["field"] == "address" and x["keep"] == "src" for x in r)

def test_batch_names_kept_as_typed(env):
    ui = env["ui"]
    assert ui.clean_batch_label("R8 QA newcomer · Oct 13 11:50 PM · QN") == "R8 QA newcomer · Oct 13 11:50 PM · QN"
    assert ui.clean_batch_label("  Expo\t<b>2026</b>  ") == "Expob2026/b"
    assert ui._bname("Expo · Oct 13, 11:46 PM · QN") == "Expo" and ui._bname("R8 · keep · this") == "R8 · keep · this"

def test_ai_no_change_does_not_clear_rule_hint(env):
    ui, st = env["ui"], env["store"]
    cid = mk(ui, st, company="Akron Rnbber Works", address="1 Mian St, Akron, OH 44308")
    f = st.get(cid)["fields"]; f["confidence"] = {"company": 0.3, "address": 0.3}; f["overall_confidence"] = 0.4
    m = {"ai_status": "checked", "ai_detail": json.dumps({"diff": {}, "finished": 1})}
    low = ui._low_after_ai(f, {}, m); assert "company" in low and "address" in low

def test_keep_current_and_crm_email_block_looks_good(env, monkeypatch):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Pnya", last_name="Rarnan"); ui.set_meta(cid, ai_rejected=json.dumps({"first_name": "Priya"}))
    assert any(a["code"] == "ai_overridden" for a in rev.get(f"/api/cards/{cid}").json()["attention"])
    monkeypatch.setenv("MCTRADE_CRM_EXPORT", FAKE_REAL)
    c2 = mk(ui, st, first_name="Robert", last_name="Hughes", company="Hughes & Partners Law", emails=["robert.hughes@hpl-test.example"]); ui.set_meta(c2, crm_action="create_new")
    assert any(a["code"] == "dup_crm" for a in rev.get(f"/api/cards/{c2}").json()["attention"])

def test_approve_cancels_running_ai_check(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Ai", last_name="Running", emails=["ai.run@x.example"]); ui.set_meta(cid, batch="r8ai", ai_status="checking", ai_detail=json.dumps({"started": 1}))
    r = rev.post(f"/api/cards/{cid}", json={"status": "approved", "confirm_cross_batch": True}); assert r.status_code == 200, r.text
    assert ui.meta(cid)["ai_status"] == "skipped"

def test_phone_lan_prefers_private():
    from app import phone
    order = sorted(["8.8.8.8", "172.17.0.1", "10.0.0.5", "192.168.1.20", "127.0.0.1", "169.254.1.1", "100.100.1.1"], key=phone._rank)
    assert order[:2] == ["192.168.1.20", "10.0.0.5"] and phone._rank("127.0.0.1") == 99 and phone._rank("169.254.1.1") == 99

def test_help_pdf_inline(env):
    for n in ("Reviewer", "Admin", "Help"):
        r = env["rev"].get(f"/static/ui/GAC-Card-Scanner-{n}-Guide.pdf")
        assert r.status_code == 200 and r.headers["content-disposition"].startswith("inline") and r.content[:4] == b"%PDF"
    assert env["rev"].get("/static/ui/GAC-Card-Scanner-Nope-Guide.pdf").status_code == 404

def test_audit_card_cap_raised(env):
    ui, st, adm = env["ui"], env["store"], env["adm"]
    ids = [mk(ui, st, first_name=f"Cap{i}", last_name="Many", emails=[f"cap{i}@many.example"]) for i in range(55)]
    for c in ids: ui.set_meta(c, batch="r8cap", batch_label="R8CAP"); _approve(env, c, "")
    assert adm.get("/api/export/xlsx?status=approved&batch=r8cap&preview=1&view=1").status_code == 200
    row = next(x for x in adm.get("/api/admin/audit?q=R8CAP").json() if "viewed the PREVIEW" in x["what"])
    assert set(ids) <= set(row["cards"])

def test_backup_and_restore_roundtrip(tmp_path):
    from app import backup
    data = tmp_path / "data"; (data / "uploads").mkdir(parents=True); (data / "thumbs").mkdir()
    db = data / "cards.db"; c = sqlite3.connect(db); c.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY, x TEXT)"); c.execute("INSERT INTO cards(x) VALUES('a'),('b')"); c.commit(); c.close()
    (data / "uploads" / "p.jpg").write_bytes(b"photo"); (data / "thumbs" / "t.jpg").write_bytes(b"t"); (data / "mctrade_contacts.csv").write_text("members")
    dest = tmp_path / "bk"
    p = backup.make(dest=str(dest), data=str(data), db=str(db))
    names = tarfile.open(p).getnames(); assert "cards.db" in names and "data/uploads/p.jpg" in names
    assert not any("mctrade_contacts" in n or "thumbs" in n for n in names)
    assert backup.verify(p)["cards"] == 2
    c = sqlite3.connect(db); c.execute("DELETE FROM cards"); c.commit(); c.close(); (data / "uploads" / "p.jpg").unlink()
    r = backup.restore(p, data=str(data), db=str(db))
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2 and (data / "uploads" / "p.jpg").read_bytes() == b"photo"
    assert (data / "mctrade_contacts.csv").read_text() == "members" and os.path.isdir(r["moved_aside"])
    for i in range(9): last = backup.make(dest=str(dest), data=str(data), db=str(db), keep=7)
    assert last in backup.listing(str(dest))
    assert len(backup.listing(str(dest))) == 7

def test_restore_script(tmp_path):
    root = os.path.abspath(os.path.join(HERE, "..", ".."))
    data = tmp_path / "data"; data.mkdir(); db = data / "cards.db"
    c = sqlite3.connect(db); c.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY)"); c.execute("INSERT INTO cards DEFAULT VALUES"); c.commit(); c.close()
    env_ = dict(os.environ, GAC_DATA_DIR=str(data), GAC_BACKUP_DIR=str(tmp_path / "bk"), GAC_RESTORE_YES="1")
    py = "import sys; sys.argv=['x']+sys.argv[1:]; from app import store; store.DB=%r; import runpy; runpy.run_module('app.backup', run_name='__main__')" % str(db)
    exe = os.path.join(root, ".venv", "bin", "python")
    if not os.path.exists(exe): exe = sys.executable   # CI / checkouts without a .venv
    out = subprocess.run([exe, "-c", py], cwd=root, env=env_, capture_output=True, text=True); assert out.returncode == 0, out.stderr
    bk = out.stdout.strip().splitlines()[-1]; assert bk.endswith(".tgz")
    sqlite3.connect(db).execute("DELETE FROM cards").connection.commit()
    out = subprocess.run(["sh", os.path.join(root, "scripts", "restore_backup.sh"), bk], cwd=root, env=env_ | {"GAC_DB": str(db)}, capture_output=True, text=True)
    assert out.returncode == 0 and "restored" in out.stdout, out.stdout + out.stderr
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
    assert subprocess.run(["sh", os.path.join(root, "scripts", "restore_backup.sh"), str(tmp_path / "nope.tgz")], cwd=root, env=env_, capture_output=True).returncode != 0

# ---------------------------------------------------------------- skeptic-r8 / coordinator-r2
def test_keep_apart_does_not_skip_cross_batch_confirm(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    ph = [{"type": "work", "number": "(330) 555-0918"}]
    o = mk(ui, st, first_name="Xb", last_name="Twin", company="Elsewhere", emails=["xb.other@x.example"], phones=ph); ui.set_meta(o, batch="r8xbA")
    st.update(o, status="approved", reviewer="RR", note="")
    a = mk(ui, st, first_name="Kay", last_name="Apart", company="Same Co", emails=["kay1@same.example"], phones=ph); ui.set_meta(a, batch="r8xbB")
    b = mk(ui, st, first_name="Kay", last_name="Apart", company="Same Co", emails=["kay2@same.example"]); ui.set_meta(b, batch="r8xbB")
    r = rev.post(f"/api/cards/{a}", json={"status": "approved", "keep_apart": [str(b)]})
    assert r.status_code == 409 and r.json()["need"] == "confirm_cross_batch", r.text
    r = rev.post(f"/api/cards/{a}", json={"status": "approved", "keep_apart": [str(b)], "confirm_cross_batch": True}); assert r.status_code == 200, r.text

def test_note_html_refused_and_note_edit_flags_reexport(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    assert "note" in ui.payload_problems({"note": "<svg onload=alert(1)>"})
    cid = mk(ui, st, first_name="Note", last_name="Check", emails=["note.check@x.example"])
    r = rev.post(f"/api/cards/{cid}", json={"status": "approved", "note": "<img src=x onerror=1>", "confirm_cross_batch": True})
    assert r.status_code == 422, r.text
    st.update(cid, status="approved", reviewer="RR", note=""); ui.set_meta(cid, exported=1.0)
    r = rev.post(f"/api/cards/{cid}", json={"note": "called back"}); assert r.status_code == 200, r.text
    assert ui.meta(cid).get("reexport")

def test_csv_guard_phone_extension_forms(env):
    ui = env["ui"]
    assert ui.safe_cell("+1 330-555-0779 #204") == "+1 330-555-0779 #204"
    assert ui.safe_cell("+1 (330) 555-0181 extension 3") == "+1 (330) 555-0181 extension 3"
    assert ui.safe_cell("+SUM(1)") == "'+SUM(1)" and ui.safe_cell("=1+1") == "'=1+1"

def test_ai_reject_after_accept_is_stale(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, first_name="Ai", last_name="Strnad", emails=["ai.strnad@x.example"])
    ui.set_meta(cid, ai_status="suggested", ai_detail=json.dumps({"diff": {"last_name": {"from": "Strnad", "to": "Strand"}}}))
    assert rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"last_name": "accept"}}).status_code == 200
    r = rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"last_name": "reject"}}); assert r.status_code == 409, r.text
    assert st.get(cid)["fields"]["last_name"] == "Strand"
    assert rev.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"zz": "reject"}}).status_code == 409

def test_back_of_card_keeps_concurrent_save(env, monkeypatch):
    ui, st = env["ui"], env["store"]
    cid = mk(ui, st, first_name="Back", last_name="Race", website="", emails=["back.race@backrace.example"])
    def slow_scan(data, *a):   # a save lands while the OCR runs
        f = st.get(cid)["fields"]; f["title"] = "RACE-EDIT-TITLE"; st.update(cid, fields=f)
        return {"fields": {"website": "backrace.example", "title": "Old"}, "text": "back www.backrace.example"}
    monkeypatch.setattr(ui, "scan_limited", slow_scan)
    r = ui.attach_back(cid, b"x", ".jpg", "RR")
    f = st.get(cid)["fields"]; assert f["title"] == "RACE-EDIT-TITLE" and f["website"] == "backrace.example", r

def test_phone_link_single_use(env):
    from app import phone
    from fastapi.testclient import TestClient
    tok = "r8tok-single"; phone.TOKENS[tok] = {"user": 1, "initials": "AD", "display": "A", "expires": 9e12, "batch": "phone-x", "batch_label": "", "uploads": 0, "times": [], "jobs": []}
    try:
        a = TestClient(phone.phone_app); b = TestClient(phone.phone_app)
        assert a.get(f"/m?t={tok}", follow_redirects=False).status_code == 303
        assert b.get(f"/m?t={tok}", follow_redirects=False).status_code == 403
    finally: phone.TOKENS.pop(tok, None)
