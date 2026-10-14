"""Unit/integration tests (pytest). Uses a temporary database: run from a COPY of the project, never next to live data:
   cd <copy> && .venv/bin/python -m pytest tests/unit --cov=app"""
import io, os, json, time
from conftest import Client

import itertools
_PH = itertools.count(2000)
def mk(ui, store, **f):
    # round 7: a unique phone per test card by default (approved cards in other batches with the same phone now ask for a
    # cross-batch confirm, skeptic R7-4); pass phones=... to share one on purpose
    base = {"first_name": "Ann", "last_name": "Lee", "title": "CFO", "company": "Acme Inc", "emails": ["ann@acme.com"],
            "phones": [{"type": "work", "number": f"330-555-{next(_PH):04d}"}], "website": "acme.com", "address": "1 Main St, Akron, OH 44308", "social": []}
    base.update(f); cid = store.add("test", "raw", base, ""); ui.set_meta(cid, batch="b1", batch_label="B1"); return cid

def test_validate_rules(env):
    ui = env["ui"]
    assert "name" in ui.validate({"first_name": "", "last_name": "Lee", "emails": ["a@b.co"]})
    assert ui.validate({"first_name": "A", "emails": ["a@b.co"], "phones": []}) == {}
    assert "phones" in ui.hard_errors({"phones": [{"number": "12"}]})
    assert "emails" in ui.hard_errors({"emails": ["not-an-email@@"]})
    assert "emails" in ui.hard_errors({"first_name": "Jane", "emails": ["jane@example"]})   # round 7: no TLD is a hard error
    assert ui.hard_errors({"first_name": "Jane", "emails": [], "phones": []}) == {}             # 'no email or phone' stays soft
    assert "name" in ui.hard_errors({"first_name": " ", "last_name": "Roe", "emails": ["jane@example.com"]})   # blank first name: hard block          # soft only: can be overridden with a reason
    assert ui.phone_ok("+1 (330) 555-0101") and not ui.phone_ok("555-01")

def test_security_headers_and_csrf(env):
    c = env["rev"]; r = c.get("/api/cards")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store" and r.headers["x-gac-user"]
    assert c.post("/api/cards-bulk", json={"ids": [], "status": "rejected"}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.post("/api/cards-bulk", json={"ids": [], "status": "rejected"}).status_code == 200            # Origin + token (Client adds them)
    assert c.post("/api/cards-bulk", json={"ids": [], "status": "rejected"}, headers={"Origin": "", "X-CSRF-Token": c.cookies.get("gac_csrf")}).status_code == 403   # no Origin/Referer
    assert c.post("/api/cards-bulk", json={"ids": [], "status": "rejected"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403          # bad token
    assert c.get("/docs").status_code == 404

def test_roles(env):
    rev = env["rev"]
    assert rev.get("/api/admin/users").status_code == 403
    assert rev.post("/api/batches/archive", json={"batch": "b1"}).status_code == 403
    assert rev.get("/api/export/csv?status=pending").status_code == 403
    from app import main
    assert Client(main.app).get("/api/cards").status_code == 401

def test_upload_guards(env):
    from PIL import Image
    rev = env["rev"]; b = io.BytesIO(); Image.new("1", (20000, 20000)).save(b, "PNG")
    r = rev.post("/api/jobs", files={"image": ("x.png", b.getvalue(), "image/png")}); assert r.status_code == 422 and "too large" in r.json()["error"]
    r = rev.post("/api/jobs", files={"image": ("x.jpg", b"%!PS-Adobe-3.0 EPSF-3.0\nshowpage\n", "image/jpeg")}); assert r.status_code == 422

def test_override_flag_and_export(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, emails=[], first_name="Jane", last_name="Roe", company="Roe LLC", phones=[], credentials="CPA", department="Tax")
    r = rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"}); assert r.status_code == 422
    r = rev.post(f"/api/cards/{cid}", json={"status": "approved", "override_reason": "confirmed", "crm_action": "create_new"}); assert r.status_code == 200, r.text
    assert any(a["code"] == "override" for a in r.json()["attention"])
    r = adm.get("/api/export/csv?status=approved&batch=b1"); assert r.status_code == 200, r.text
    row = [l for l in r.text.splitlines() if l.startswith(str(cid) + ",")][0]
    assert "APPROVED ANYWAY" in row and "CPA" in row and "Tax" in row

def test_export_blocked_by_pending_lookalike(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = mk(ui, st, first_name="Bob", last_name="Stone", emails=["bob@stone.io"], company="Stone Co")
    rev.post(f"/api/cards/{a}", json={"status": "approved", "crm_action": "create_new"})
    b = mk(ui, st, first_name="Bob", last_name="Stone", emails=["bob@stone.io"], company="Stone Co")
    d = rev.get("/api/export/check?status=approved_new&batch=b1").json()
    assert any(x["id"] == a and b in x["with"] for x in d["duplicates"])
    rev.post(f"/api/cards/{b}", json={"merge_into": a}); ui.set_meta(a, exported=time.time())

def test_ai_no_change_keeps_card_and_suggestions_when_reviewed(env, monkeypatch, tmp_path):
    ui, st = env["ui"], env["store"]
    from app import vlm, merge
    cid = mk(ui, st, title="Mgr"); f0 = st.get(cid)["fields"]
    p = os.path.join(ui.UP, "t_ai.jpg"); open(p, "wb").write(b"x")
    with env["store"].db() as c: c.execute("UPDATE cards SET image='t_ai.jpg' WHERE id=?", (cid,))
    monkeypatch.setattr(vlm, "extract", lambda *a, **k: {})
    monkeypatch.setattr(merge, "merge", lambda f, v, raw: dict(f) | {"overall_confidence": 0.1})   # lowers conf only
    ui._ai_run(cid, ["overall"]); assert st.get(cid)["fields"] == f0                            # unchanged card
    monkeypatch.setattr(merge, "merge", lambda f, v, raw: dict(f) | {"title": "Manager"})
    st.update(cid, status="approved", reviewer="RR", note="")
    ui._ai_run(cid, ["title"]); m = ui.meta(cid); det = json.loads(m["ai_detail"])
    assert m["ai_status"] == "suggested" and det["diff"]["title"]["to"] == "Manager" and st.get(cid)["fields"]["title"] == "Mgr"
    # round 6 (skeptic R6-6): a suggestion never overwrites an APPROVED card's value
    r = env["rev"].post(f"/api/cards/{cid}/ai-decide", json={"choices": {"title": "accept"}}); assert r.status_code == 409
    assert st.get(cid)["fields"]["title"] == "Mgr"
    os.remove(p)

def test_recover_requeues_inbox(env, monkeypatch):
    ui = env["ui"]; ran = []
    monkeypatch.setattr(ui.POOL, "submit", lambda fn, jid, data, **kw: ran.append(jid))
    open(os.path.join(ui.INBOX, "abcdef123456.bin"), "wb").write(b"x")
    json.dump({"engine": "auto", "ext": ".jpg", "batch": None, "label": None, "fname": "f.jpg", "sha": "s", "who": "RR"}, open(os.path.join(ui.INBOX, "abcdef123456.json"), "w"))
    assert ui.recover() == 1 and ran == ["abcdef123456"] and ui.JOBS["abcdef123456"]["recovered"]
    for x in (".bin", ".json"): os.remove(os.path.join(ui.INBOX, "abcdef123456" + x))

def test_hard_delete(env):
    ui, st, adm, rev = env["ui"], env["store"], env["adm"], env["rev"]
    cid = mk(ui, st, first_name="Del", last_name="Me", emails=["del@me.org"])
    rev.post(f"/api/cards/{cid}", json={"fields": {"title": "x"}})
    assert rev.post(f"/api/admin/cards/{cid}/delete", json={"confirm": cid}).status_code == 403
    assert adm.post(f"/api/admin/cards/{cid}/delete", json={"confirm": cid}).status_code == 200
    with st.db() as c:
        assert not c.execute("SELECT 1 FROM cards WHERE id=?", (cid,)).fetchone()
        hist = c.execute("SELECT action, detail FROM card_history WHERE card_id=?", (cid,)).fetchall()   # DM1: kept, redacted
        assert hist and not [h for h in hist if h[1] and ("del@me.org" in h[1] or '"Del"' in h[1])]
        assert not [a for a in c.execute("SELECT snapshot FROM actions") if '"del@me.org"' in a[0]]

def test_password_change_revokes_other_sessions(env):
    from app import main
    a, b = Client(main.app), Client(main.app)
    for x in (a, b): assert x.post("/api/auth/login", json={"username": "rev", "password": "temp-pass-1234"}).status_code == 200
    assert a.post("/api/me/password", json={"old": "temp-pass-1234", "new": "temp-pass-1234"}).status_code == 200
    assert a.get("/api/me").status_code == 200 and b.get("/api/me").status_code == 401
    assert env["rev"].post("/api/auth/login", json={"username": "rev", "password": "temp-pass-1234"}).status_code == 200   # later tests reuse it

def test_parser_smoke():
    from app import parser
    f = parser.parse("Jane Doe\nChief Financial Officer\nAcme Widgets Inc.\njane.doe@acmewidgets.com\n(330) 555-0142\nwww.acmewidgets.com")
    assert f["emails"] == ["jane.doe@acmewidgets.com"] and f["first_name"] == "Jane"
