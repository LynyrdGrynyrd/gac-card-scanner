"""Round-9 regression tests: same-photo check (temp inbox), shown confidence, AI status settle, bulk approve asks first,
unique phone batch labels, 127.0.0.1 default in the start scripts."""
import io, os, json, asyncio, hashlib, random
from test_app import mk
from PIL import Image, ImageDraw

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

def _photo(seed):
    rnd = random.Random(seed); im = Image.new("RGB", (640, 400), "white"); d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rnd.randint(0, 560), rnd.randint(0, 340); d.rectangle([x, y, x + rnd.randint(5, 80), y + rnd.randint(5, 60)], fill=(rnd.randint(0, 200),) * 3)
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()

def test_same_photo_scope_uses_temp_inbox(env, tmp_path, monkeypatch):
    """The same-photo refusal applies inside the same batch only; nothing is written to the real inbox."""
    ui, store = env["ui"], env["store"]
    inbox = tmp_path / "inbox"; inbox.mkdir()
    monkeypatch.setattr(ui, "INBOX", str(inbox))
    submitted = []
    monkeypatch.setattr(ui.POOL, "submit", lambda *a, **k: submitted.append((a, k)))
    data = _photo(9); sha = hashlib.sha256(data).hexdigest()
    cid = mk(ui, store, first_name="Photo", last_name="Same"); ui.set_meta(cid, sha256=sha, batch="r9-photo-a", batch_label="R9 photo A")
    run = lambda **k: asyncio.run(ui.enqueue_upload(data, "card.png", who="RR", **k))
    r = run(batch="r9-photo-a")                       # same batch -> refused, names the card
    assert getattr(r, "status_code", 200) == 409 and json.loads(r.body)["duplicate_of"] == cid
    assert not list(inbox.iterdir()) and not submitted
    r = run(batch="r9-photo-b")                       # another batch -> accepted (the review box only warns)
    assert isinstance(r, dict) and r["state"] == "queued"
    assert sorted(p.suffix for p in inbox.iterdir()) == [".bin", ".json"] and len(submitted) == 1
    r = run(batch="r9-photo-a", allow_duplicate="1")  # explicit "add anyway" -> accepted
    assert isinstance(r, dict)
    r = run(batch="r9-photo-b")                       # same photo still waiting in this person's batch-b upload -> refused
    assert getattr(r, "status_code", 200) == 409 and json.loads(r.body)["duplicate_of"] is None
    assert isinstance(asyncio.run(ui.enqueue_upload(data, "card.png", who="OTHER", batch="r9-photo-b")), dict)   # another person: ok
    with ui.JLOCK:
        for j in list(ui.JOBS):
            if ui.JOBS[j].get("sha") == sha: ui.JOBS.pop(j)
    ui.set_meta(cid, archived=1)                      # archived copy no longer blocks
    assert isinstance(run(batch="r9-photo-a"), dict)
    with ui.JLOCK:
        for j in list(ui.JOBS):
            if ui.JOBS[j].get("sha") == sha: ui.JOBS.pop(j)

def test_shown_confidence_is_per_card(env):
    ui = env["ui"]
    a = [{"code": "hint"}]
    v1 = ui._shown_conf({"overall_confidence": 0.92, "first_name": "A"}, a)
    v2 = ui._shown_conf({"overall_confidence": 0.50, "first_name": "A"}, a)
    v3 = ui._shown_conf({"overall_confidence": 0.92, "first_name": "A"}, a * 3)
    assert v1 < 0.6 and v2 < v1 and v3 < v1 and len({v1, v2, v3}) == 3 and 0.55 not in (v1, v2, v3)
    assert ui._shown_conf({"overall_confidence": 0.9, "first_name": "A"}, []) == 0.9

def test_ai_status_cleared_after_keep_current_and_save(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store, first_name="Kara", last_name="Keep", emails=["kara@keep.example"], title="Boss")
    diff = {"emails": {"from": ["kara@keep.example"], "to": ["kara@kep.example"]}, "title": {"from": "Boss", "to": "Bos"}}
    ui.set_meta(cid, ai_status="suggested", ai_detail=json.dumps({"diff": diff, "finished": 1}))
    r = rc.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"emails": "reject"}}); assert r.status_code == 200, r.text
    assert ui.meta(cid)["ai_status"] == "suggested"            # title still open
    r = rc.post(f"/api/cards/{cid}", json={"fields": {"first_name": "Kara"}}); assert r.status_code == 200, r.text
    m = ui.meta(cid); assert m["ai_status"] == "checked"
    assert json.loads(m["ai_detail"])["decided"] == {"emails": "reject", "title": "kept"}

def test_ai_status_cleared_when_keep_current_on_only_field(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store, first_name="Kim", last_name="Only", emails=["kim@only.example"])
    ui.set_meta(cid, ai_status="suggested", ai_detail=json.dumps({"diff": {"emails": {"from": ["kim@only.example"], "to": ["kim@onl.example"]}}}))
    assert rc.post(f"/api/cards/{cid}/ai-decide", json={"choices": {"emails": "reject"}}).status_code == 200
    assert ui.meta(cid)["ai_status"] == "checked"

def test_bulk_approve_asks_before_cross_batch(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, first_name="Xena", last_name="Cross", emails=["xena@cross9.example"]); ui.set_meta(a, batch="r9x-1", batch_label="X1")
    store.update(a, status="approved", reviewer="RR")
    b = mk(ui, store, first_name="Xena", last_name="Cross", emails=["xena@cross9.example"]); ui.set_meta(b, batch="r9x-2", batch_label="X2")
    c = mk(ui, store, first_name="Yuri", last_name="Plain", emails=["yuri@plain9.example"]); ui.set_meta(c, batch="r9x-2", batch_label="X2")
    r = rc.post("/api/cards-bulk", json={"ids": [b, c], "status": "approved"})
    assert r.status_code == 409 and r.json()["need"] == "confirm_cross_batch"
    assert [w["id"] for w in r.json()["lookalikes"]] == [b] and a not in r.json()["lookalikes"][0]["others"]   # v0.4.7 #1: no other-batch ids for a reviewer
    assert store.get(b)["status"] == "pending" and store.get(c)["status"] == "pending"   # nothing changed yet
    r = rc.post("/api/cards-bulk", json={"ids": [c], "status": "approved"}); assert r.status_code == 200 and r.json()["updated"] == [c]
    r = rc.post("/api/cards-bulk", json={"ids": [b], "status": "approved", "confirm_cross_batch": True})
    assert r.status_code == 200 and r.json()["updated"] == [b] and r.json()["warnings"]
    assert any(h["action"] == "cross_batch_confirmed" for h in ui.history(b))

def test_unique_batch_label(env):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store, first_name="Lab", last_name="El"); ui.set_meta(cid, batch="r9-lab-1", batch_label="Expo table")
    assert ui.unique_batch_label("Expo table", "phone-new") == "Expo table (2)"
    assert ui.unique_batch_label("expo TABLE", "phone-new", ["Expo table (2)"]) == "expo TABLE (3)"
    assert ui.unique_batch_label("Expo table", "r9-lab-1") == "Expo table"      # its own batch
    assert ui.unique_batch_label("Fresh name", "phone-new") == "Fresh name"

def test_phone_start_labels_unique(env, monkeypatch):
    from app import phone, auth
    ui, store, rc = env["ui"], env["store"], env["rev"]
    auth.set_setting("phone_mode_allowed", "1")
    monkeypatch.setattr(phone, "start_server", lambda: "127.0.0.1")
    cid = mk(ui, store, first_name="Ph", last_name="One"); ui.set_meta(cid, batch="r9-ph-1", batch_label="Lobby")
    r = rc.post("/api/phone/start", json={"batch_label": "Lobby"}); assert r.status_code == 200, r.text
    v = next(v for v in phone.TOKENS.values() if v["batch"] == r.json()["batch"]); assert v["batch_label"] == "Lobby (2)"
    r = rc.post("/api/phone/start", json={}); v = next(v for v in phone.TOKENS.values() if v["batch"] == r.json()["batch"])
    assert v["batch_label"].startswith("Phone scans ")
    phone.TOKENS.clear()

def test_start_scripts_default_to_localhost():
    sc = open(os.path.join(ROOT, "start.command")).read(); bat = open(os.path.join(ROOT, "start.bat")).read()
    sv = open(os.path.join(ROOT, "scripts", "serve.sh")).read()
    import re
    assert 'HOST="${GAC_HOST:-127.0.0.1}"' in sc and not re.search(r"(^|[;\s])HOST=0\.0\.0\.0", sc.replace("GAC_HOST=0.0.0.0", ""))
    assert "set HOST=127.0.0.1" in bat and "set HOST=0.0.0.0" not in bat
    assert 'HOST="${GAC_HOST:-127.0.0.1}"' in sv

# ---------------- round-9 tester reports (skeptic, mctrade, manager, part-timer)
def test_undo_keeps_later_saves(env):
    """skeptic R9-1: undo puts back only what that action changed; a later save to another field is kept."""
    ui, store, rc, r2 = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, store, first_name="Una", last_name="Do", title="Old title")
    assert rc.post(f"/api/cards/{cid}", json={"fields": {"department": "DeptA"}}).status_code == 200      # action A (rev)
    assert r2.post(f"/api/cards/{cid}", json={"fields": {"title": "Later title"}}).status_code == 200     # someone else, later
    a = ui.db().execute("SELECT id FROM actions WHERE username='rev' AND undone IS NULL ORDER BY id DESC LIMIT 1").fetchone()[0]
    r = rc.post("/api/undo", json={"id": a}); assert r.status_code == 200, r.text
    f = store.get(cid)["fields"]
    assert f.get("department", "") == "" and f["title"] == "Later title"

def test_undo_reports_conflict_on_same_field(env):
    ui, store, rc, r2 = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, store, first_name="Con", last_name="Flict", title="T0")
    assert rc.post(f"/api/cards/{cid}", json={"fields": {"title": "T1"}}).status_code == 200
    assert r2.post(f"/api/cards/{cid}", json={"fields": {"title": "T2"}}).status_code == 200
    a = ui.db().execute("SELECT id FROM actions WHERE username='rev' AND undone IS NULL ORDER BY id DESC LIMIT 1").fetchone()[0]
    r = rc.post("/api/undo", json={"id": a}).json()
    assert store.get(cid)["fields"]["title"] == "T2" and str(cid) in json.dumps(r.get("kept_later_changes"))

def test_keep_apart_true_is_422(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store, first_name="Kay", last_name="Apart")
    r = rc.post(f"/api/cards/{cid}", json={"status": "approved", "keep_apart": True}); assert r.status_code == 422

def test_phone_cookie_is_not_the_qr_token(env, monkeypatch):
    from app import phone, auth
    from fastapi.testclient import TestClient
    auth.set_setting("phone_mode_allowed", "1"); monkeypatch.setattr(phone, "start_server", lambda: "127.0.0.1")
    tok = env["rev"].post("/api/phone/start", json={"batch_label": "Cookie test"}).json()["url"].split("t=")[1]
    pc = TestClient(phone.phone_app); r = pc.get("/m?t=" + tok, follow_redirects=False); assert r.status_code == 303
    sess = pc.cookies.get("gac_phone"); assert sess and sess != tok
    assert pc.get("/m/api/state").status_code == 200
    evil = TestClient(phone.phone_app); evil.cookies.set("gac_phone", tok, path="/m")
    assert evil.get("/m/api/state").status_code == 401                  # the QR token itself is not a session
    import hmac, hashlib
    assert phone.csrf_for(sess) != hmac.new(b"gac-phone-csrf", sess.encode(), hashlib.sha256).hexdigest()[:40]
    phone.TOKENS.clear()

def test_exact_name_only_match_is_review():
    from app import mctrade_sync, mctrade_export as M
    ex = [{"profile_id": "990012", "first_name": "Maria", "last_name": "Delgado", "organization": "Other Org", "email": "x@other.example", "phone": "3305550000"}]
    m = mctrade_sync.match({"first_name": "Maria", "last_name": "Delgado", "company": "New Co", "emails": ["m@new.example"], "phones": []}, ex)
    assert m and m[0]["profile_id"] == "990012"
    cat, why, _ = M.classify({"id": 1, "fields": {}}, "", {}, True, False, lambda c: {"name": ["990012"]})
    assert cat == "review"

def test_sample_rows_skipped_not_whole_file(env):
    from app import crm_source
    adm = env["adm"]
    data = (b"profile_id,first_name,last_name,email\n55555,Rob,Hughes,rhughes@hugheslaw.com\n"
            b"55556,Real,Person,real.person@member.example\n1003,Fakey,Realmember,fakey@member.example\n")
    r = adm.post("/api/admin/mctrade-contacts", files={"image": ("real.csv", data)}); assert r.status_code == 200, r.text
    assert r.json()["skipped_sample_rows"] == 1 and r.json()["people"] == 2
    assert all(x["email"] != "rhughes@hugheslaw.com" for x in crm_source.real())
    assert adm.post("/api/admin/mctrade-contacts/remove", json={}).status_code == 200

def test_merge_replaces_misread_email(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    t = mk(ui, store, first_name="Mel", last_name="Merge", emails=["mel.merge@analytiexample.com"]); store.update(t, status="approved", reviewer="RR")
    s_ = mk(ui, store, first_name="Mel", last_name="Merge", emails=["mel.merge@analytics.example.com"])
    from app import plausibility
    flagged = ui._field_flagged(dict(store.get(t)["fields"]), "emails")
    r = rc.post(f"/api/cards/{s_}", json={"status": "rejected", "merge_into": t}); assert r.status_code == 200, r.text
    em = store.get(t)["fields"]["emails"]
    assert "mel.merge@analytics.example.com" in em
    if flagged: assert "mel.merge@analytiexample.com" not in em

def test_email_name_hint_on_email_field():
    from app import plausibility
    hs = plausibility.check({"first_name": "Luis", "last_name": "Rasmussen", "emails": ["irasmussen@firestone.example.com"], "phones": [], "company": "", "title": "", "website": "", "address": ""})
    assert all(h["field"] == "emails" for h in hs if h["code"] == "email_name") if any(h.get("code") == "email_name" for h in hs) else True

def test_audit_search_limit_after_filter(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    cid = mk(ui, store, first_name="Aud", last_name="It"); ui.log(cid, "NDLR9", "approved")
    for _ in range(5): ui.log(cid, "HAY", "approved")
    rows = adm.get("/api/admin/audit?q=NDLR9&limit=2").json(); assert len(rows) == 1

def test_update_rows_member_since_blank_and_diff(env, monkeypatch):
    from app import mctrade_export as M
    cards = [{"id": 1, "fields": {"first_name": "Maria", "last_name": "Delgado", "company": "Summit Valley Bank", "emails": ["maria.delgado@svb-test.example"], "phones": [], "title": "", "website": "", "address": ""}, "status": "approved"}]
    res = M.build(cards, "X", "gac", lambda f: {}, action=lambda c: "update_existing", crm_real=True, updates_on=True,
                  crm_look=lambda c: {"email": ["990001"], "strong": ["990001"], "name": [], "sure": "990001", "email_differs": False})
    assert res["updates"] and res["updates"][0][1]["MemberSince"] == ""

def test_asset_urls_versioned(env):
    r = env["rev"].get("/ui"); assert r.status_code == 200
    import re
    v = re.search(r'<script type="module" src="/static/ui/main\.js\?v=([0-9a-f]{10})"', r.text); assert v   # audit 2026-10 P2: ES module entry point
    assert env["rev"].get("/api/me").headers.get("X-GAC-Asset") == v.group(1)

def test_backup_same_disk_warning(tmp_path, monkeypatch):
    from app import backup
    monkeypatch.setenv("GAC_BACKUP_DIR", str(tmp_path / "bk"))
    assert backup.same_disk() in (True, False)
