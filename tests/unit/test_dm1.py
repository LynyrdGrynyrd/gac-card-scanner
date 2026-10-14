"""Data-manager r1 regression tests (qa/manager-r1.md)."""
import json
from test_app import mk

def _approve(c, cid, **kw): return c.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"} | kw)

def test_delete_keeps_redacted_audit_rows(env):
    ui, st, adm, rev = env["ui"], env["store"], env["adm"], env["rev"]
    cid = mk(ui, st, first_name="Priv", last_name="Acy", emails=["priv@acy.io"])
    assert rev.post(f"/api/cards/{cid}", json={"fields": {"title": "Secret Title"}}).status_code == 200
    assert _approve(rev, cid).status_code == 200
    assert adm.post(f"/api/admin/cards/{cid}/delete", json={"confirm": cid}).status_code == 200
    with st.db() as c: rows = c.execute("SELECT action, reviewer, ts, detail FROM card_history WHERE card_id=?", (cid,)).fetchall()
    acts = [r[0] for r in rows]
    assert "edited" in acts and "decision" in acts and "deleted_on_request" in acts
    blob = json.dumps([list(r) for r in rows])
    assert "Secret Title" not in blob and "priv@acy.io" not in blob and "Priv" not in blob
    a = adm.get("/api/admin/audit", params={"q": f"#{cid}"}).json()
    txt = " ".join(r["what"] for r in a)
    assert "pending → approved" in txt and "personal details removed" in txt and "Secret" not in txt
    assert any(r["kind"] == "card" and r["card"] == cid and "deleted card" in r["what"] for r in a)

def test_settings_diff_only(env):
    adm = env["adm"]; aud = lambda: [r for r in adm.get("/api/admin/audit").json() if r["kind"] == "settings"]
    n0 = len(aud())
    adm.post("/api/admin/settings", json=adm.get("/api/admin/settings").json())
    assert len(aud()) == n0, "no-op save is not logged"
    cur = adm.get("/api/admin/settings").json()["ai_check_enabled"]
    adm.post("/api/admin/settings", json={"ai_check_enabled": "0" if cur == "1" else "1"})
    rows = aud(); assert len(rows) == n0 + 1
    w = rows[0]["what"]; assert "AI double-check:" in w and "→" in w and "{" not in w and "retention" not in w.lower()
    adm.post("/api/admin/settings", json={"ai_check_enabled": cur})

def test_corrections_default_off(env):
    from app import auth
    assert auth.DEFAULTS["corrections_enabled"] == "0"

def test_edit_phone_text_readable(env):
    t = env["ui"]._audit_text("edited", None, None, {"phones": {"from": [{"type": "work", "number": "330-555-0101", "valid": True}], "to": []}})
    assert "work: 330-555-0101" in t and "valid" not in t and "{" not in t

def test_redownload_logged_per_card(env):
    ui, st, adm, rev = env["ui"], env["store"], env["adm"], env["rev"]
    cid = mk(ui, st, first_name="Redo", last_name="Wnld", emails=["redo@wnld.io"], phones=[{"type": "work", "number": "330-555-0919"}])
    ui.set_meta(cid, batch="bRD", batch_label="RD")
    assert _approve(rev, cid).status_code == 200
    r = rev.get("/api/export/csv", params={"status": "approved_new", "batch": "bRD"}); assert r.status_code == 200, r.text
    eid = r.headers["X-Export-Id"]
    assert adm.get(f"/api/exports/{eid}/download").status_code == 200
    a = adm.get("/api/admin/audit", params={"q": f"#{cid}"}).json()
    assert any(x["card"] == cid and "re-downloaded" in x["what"] for x in a)
    assert any(x["kind"] == "export" and "re-downloaded" in x["what"] and f"#{cid}" in x["what"] for x in a)

def test_all_batches_block_lists_ok_batches(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = mk(ui, st, first_name="Dup", last_name="Pair", emails=["dup@pair.io"]); ui.set_meta(a, batch="bX", batch_label="X")
    b = mk(ui, st, first_name="Dup", last_name="Pair", emails=["dup@pair.io"]); ui.set_meta(b, batch="bY", batch_label="Y")   # pending, other batch
    c = mk(ui, st, first_name="Solo", last_name="Card", emails=["solo@card.io"], phones=[{"type": "work", "number": "330-555-0777"}]); ui.set_meta(c, batch="bZ", batch_label="Z")
    assert _approve(rev, a, keep_apart=[]).status_code in (200, 409)
    ui.set_meta(a, batch="bX"); st_ = st.get(a)
    if st_["status"] != "approved":
        with st.db() as x: x.execute("UPDATE cards SET status='approved' WHERE id=?", (a,))
    assert _approve(rev, c).status_code == 200
    allb = rev.get("/api/export/check", params={"status": "approved_new"}).json()
    assert any(p["id"] == a and b in p["with"] for p in allb["duplicates"])
    assert any(o["batch"] == "bZ" for o in allb["ok_batches"])
    one = rev.get("/api/export/check", params={"status": "approved_new", "batch": "bX"}).json()
    assert not one["duplicates"] and one["count"] == 1
    r = rev.post(f"/api/cards/{a}", json={"keep_apart": [b]}); assert r.status_code == 200, r.text
    assert not [p for p in rev.get("/api/export/check", params={"status": "approved_new"}).json()["duplicates"] if p["id"] == a]
