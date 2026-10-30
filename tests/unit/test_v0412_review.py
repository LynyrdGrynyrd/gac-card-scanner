"""v0.4.12: the data-integrity and privacy findings of the v0.4.x review (exported cards rejected via bulk/merge, edits lost
after back-to-pending, Undo racing an export, delete-on-request leaving copies, sign-off ignoring card settings). Made-up data."""
import json, uuid
from test_app import mk as _mk

def mk(ui, st, **f):
    """A card in this test's own batch: other tests' cards in the shared test DB must not block its exports."""
    cid = _mk(ui, st, **f); ui.set_meta(cid, batch=B["id"], batch_label=B["id"]); return cid

B = {"id": "b1"}
import pytest
@pytest.fixture(autouse=True)
def _own_batch():
    B["id"] = "v0412-" + uuid.uuid4().hex[:8]; yield

def _approve(c, cid):
    r = c.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"}); assert r.status_code == 200, r.text

def _export_xlsx(adm, batch=None):
    r = adm.get(f"/api/export/xlsx?status=approved_new&batch={batch or B['id']}"); assert r.status_code == 200, r.text
    return r

# F1: bulk reject of an exported card is not refused (single-card save refuses it: 'exported_reject')
def test_bulk_rejects_exported_card(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Bulk", last_name="Rejecto", emails=["bulk.rejecto@rejecto-co.com"], company="Rejecto Co")
    _approve(rev, cid); _export_xlsx(adm)
    assert cid in ui.sent_ids()
    single = rev.post(f"/api/cards/{cid}", json={"status": "rejected", "confirm_redecide": True})
    assert single.status_code == 409 and single.json()["need"] == "exported_reject"
    r = rev.post("/api/cards-bulk", json={"ids": [cid], "status": "rejected", "confirm_redecide": True, "batch": B["id"]})
    assert cid not in r.json().get("updated", []), "bulk rejected a card that is already in an MC Trade import file"

def test_merge_rejects_exported_card(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    a = mk(ui, st, first_name="Mona", last_name="Merger", emails=["mona@mergeco.com"], company="Merge Co")
    _approve(rev, a); _export_xlsx(adm)
    b = mk(ui, st, first_name="Mona", last_name="Merger", emails=["mona@mergeco.com"], company="Merge Co", title="VP Sales")
    single = rev.post(f"/api/cards/{a}", json={"status": "rejected", "confirm_redecide": True})
    assert single.status_code == 409 and single.json()["need"] == "exported_reject"
    r = rev.post(f"/api/cards/{a}", json={"merge_into": b, "confirm_redecide": True})
    assert not (r.status_code == 200 and st.get(a)["status"] == "rejected"), f"exported card #{a} rejected through a merge: {r.status_code}"

# F2: move an exported card back to pending, edit it, approve it again: no 'reexport' mark, so the edit never reaches MC Trade
def test_pending_after_export_edit_is_lost(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Penny", last_name="Pending", emails=["penny@pendco.com"], company="Pend Co")
    _approve(rev, cid); _export_xlsx(adm)
    assert rev.post(f"/api/cards/{cid}", json={"status": "pending", "confirm_redecide": True}).status_code == 200
    assert rev.post(f"/api/cards/{cid}", json={"fields": {"title": "Chief Revenue Officer"}}).status_code == 200
    assert rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    assert ui.meta(cid).get("reexport"), "edited after export but not marked for re-export"

def test_pending_after_export_not_in_next_export(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Paula", last_name="Again", emails=["paula@againco.com"], company="Again Co")
    _approve(rev, cid); _export_xlsx(adm)
    rev.post(f"/api/cards/{cid}", json={"status": "pending", "confirm_redecide": True})
    rev.post(f"/api/cards/{cid}", json={"fields": {"emails": ["paula.new@againco.com"]}})
    rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"})
    chk = adm.get(f"/api/export/check?status=approved_new&batch={B['id']}").json()
    assert cid in [c["id"] for c in chk["cards"]], f"edited card not offered again: {chk['why']!r}"

# F4: Undo's 'exported after this action?' check runs BEFORE it takes WRITE_LOCK; an export that commits in between is undone silently
def test_undo_races_export(env, monkeypatch):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Rachel", last_name="Racer", emails=["rachel@raceco.com"], company="Race Co")
    _approve(rev, cid)
    orig = ui._undo_exported; calls = []
    def patched(a):
        import sys
        res = orig(a)
        if sys._getframe(1).f_code.co_name == "undo" and not calls:   # undo()'s own last check; an export lands right after it, before WRITE_LOCK
            calls.append(1)
            _export_xlsx(adm)
        return res
    monkeypatch.setattr(ui, "_undo_exported", patched)
    r = rev.post("/api/undo", json={"batch": B["id"]})
    monkeypatch.setattr(ui, "_undo_exported", orig)
    assert cid in ui.sent_ids()
    assert r.status_code == 409 or ui.meta(cid).get("reexport"), \
        f"undo {r.status_code} after the card was exported: card is now {st.get(cid)['status']}, reexport={ui.meta(cid).get('reexport')}"

# F3b: since v0.4.8 exports.card_ids lists only cards IN the import file, but the stored companions (extra-columns CSV,
# READ-ME, SUMMARY) list every card of the export, left-out ones included -> delete on request misses those copies
def test_hard_delete_misses_companion_of_left_out_card(env):
    import os
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    a = mk(ui, st, first_name="Lefty", last_name="Outman", emails=["lefty.outman@leftout-test.io"], company="Leftout LLC")
    _approve(rev, a); _export_xlsx(adm)
    assert rev.post(f"/api/cards/{a}", json={"fields": {"title": "Secret New Title"}}).status_code == 200   # edited after export: held next time
    assert ui.meta(a).get("reexport")
    b = mk(ui, st, first_name="Newbie", last_name="Inthefile", emails=["newbie@inthefile-test.io"], company="Infile Co")
    _approve(rev, b)
    r = _export_xlsx(adm); eid = int(r.headers["X-Export-Id"])
    row = ui.db().execute("SELECT card_ids, stored FROM exports WHERE id=?", (eid,)).fetchone()
    extra = os.path.join(ui.EXP, row["stored"] + ".extra.csv")
    assert a not in json.loads(row["card_ids"]) and "lefty.outman@leftout-test.io" in open(extra, encoding="utf-8-sig").read()
    assert adm.post(f"/api/admin/cards/{a}/delete", json={"confirm": a}).status_code == 200
    leaked = os.path.isfile(extra) and "lefty.outman@leftout-test.io" in open(extra, encoding="utf-8-sig").read()
    dl = adm.get(f"/api/exports/{eid}/companion/extra.csv")
    assert not leaked, f"deleted card's email still in stored companion (download status {dl.status_code}, contains: {'lefty.outman' in dl.text})"

# F3: delete on request leaves the person's email + name|company in exports.people, and drafts of the card
def test_hard_delete_leaves_people_keys_and_drafts(env):
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    cid = mk(ui, st, first_name="Zelda", last_name="Forgetme", emails=["zelda.forgetme@privacy-test.io"], company="Forget Inc")
    _approve(rev, cid); _export_xlsx(adm)
    assert rev.post(f"/api/cards/{cid}/draft", json={"vals": {"title": "Zelda's private draft title"}}).status_code == 200
    r = adm.post(f"/api/admin/cards/{cid}/delete", json={"confirm": cid}); assert r.status_code == 200, r.text
    ppl = " ".join(str(x[0] or "") for x in ui.db().execute("SELECT people FROM exports"))
    drafts = ui.db().execute("SELECT vals FROM drafts WHERE card_id=?", (cid,)).fetchall()
    assert not drafts, f"draft of a deleted card still stored: {[d[0] for d in drafts]}"
    assert "zelda.forgetme@privacy-test.io" not in ppl and "forgetme" not in ppl, "deleted person's email/name still stored in exports.people: " + ppl[:200]


def test_hard_delete_finds_left_out_card_in_exports_made_before_listed_ids(env):
    """Exports made by 0.4.8-0.4.11 have no listed_ids: their stored extra-columns CSV is searched instead."""
    import os
    ui, st, rev, adm = env["ui"], env["store"], env["rev"], env["adm"]
    a = mk(ui, st, first_name="Olga", last_name="Oldexport", emails=["olga.oldexport@legacy-test.io"], company="Legacy LLC")
    _approve(rev, a); _export_xlsx(adm)
    rev.post(f"/api/cards/{a}", json={"fields": {"title": "Changed After Export"}})
    b = mk(ui, st, first_name="Otto", last_name="Infile", emails=["otto.infile@legacy-test.io"], company="Infile Two")
    _approve(rev, b)
    eid = int(_export_xlsx(adm).headers["X-Export-Id"])
    with ui.db() as c: c.execute("UPDATE exports SET listed_ids=NULL WHERE id=?", (eid,))   # as an older version stored it
    row = ui.db().execute("SELECT stored FROM exports WHERE id=?", (eid,)).fetchone()
    extra = os.path.join(ui.EXP, row["stored"] + ".extra.csv")
    assert "olga.oldexport@legacy-test.io" in open(extra, encoding="utf-8-sig").read()
    assert adm.post(f"/api/admin/cards/{a}/delete", json={"confirm": a}).status_code == 200
    assert not os.path.isfile(extra) and ui.db().execute("SELECT stored FROM exports WHERE id=?", (eid,)).fetchone()["stored"] is None


def test_signoff_sees_a_changed_mc_trade_choice(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    from app import exporting
    cid = mk(ui, st, first_name="Sigrid", last_name="Signoff", emails=["sigrid@signoff-test.io"], company="Signoff Co")
    _approve(rev, cid)
    before = exporting.export_versions([st.get(cid)])
    ui.set_meta(cid, crm_action="update_existing")   # e.g. changed in another tab between the check and the export
    assert exporting.export_versions([st.get(cid)])["cards"] != before["cards"]
