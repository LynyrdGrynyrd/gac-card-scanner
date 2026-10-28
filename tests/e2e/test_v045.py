"""v0.4.5: Approve after Different still warns 'exported before' in ONE dialog; no dialog when nothing was exported; the
'AI check not finished' dialog focuses Cancel and Enter never approves. Made-up cards only (public synth photos)."""
import json, os, sqlite3, time
from playwright.sync_api import expect
from test_flows import card_json, scan, signed_in_admin, wait_card

SYN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "synth2")
CLEAN = {"first_name": "Tessa", "last_name": "Quill", "company": "Quill Labs", "title": "Owner", "emails": ["tessa@quill-labs.com"],
         "phones": [{"type": "work", "number": "(330) 555-0142"}], "website": "quill-labs.com", "address": "", "confidence": {}}


def _db(server):
    c = sqlite3.connect(os.path.join(server["data"], "cards.db"), timeout=30); return c


def _scan_one(page, server, photo, batch):
    scan(page, os.path.join(SYN, photo), batch=batch)
    # the newest card id from the DB: #qBody can still hold the previous batch's rows for a moment (the first card came back twice)
    c = _db(server); n = c.execute("SELECT MAX(id) FROM cards").fetchone()[0]; c.close(); return n


def _set(server, cid, fields=None, status=None, exported=False, ai=None):
    c = _db(server)
    with c:
        if fields is not None: c.execute("UPDATE cards SET fields=? WHERE id=?", (json.dumps(fields), cid))
        if status: c.execute("UPDATE cards SET status=?, decided=? WHERE id=?", (status, time.time(), cid))
        if exported:
            c.execute("UPDATE card_meta SET exported=? WHERE card_id=?", (time.time(), cid))
            c.execute("INSERT INTO card_history(card_id,ts,reviewer,action,detail) VALUES(?,?,?,?,?)", (cid, time.time(), "EA", "exported", json.dumps({"file": "x.xlsx"})))
        if ai: c.execute("UPDATE card_meta SET ai_status=? WHERE card_id=?", (ai, cid))
    c.close()


def _open(page, cid):
    page.goto(f"/ui#review/{cid}"); wait_card(page, cid); page.wait_for_timeout(600)


def test_different_then_approve_warns_exported_once(new_page, server):
    page = signed_in_admin(new_page)
    a = _scan_one(page, server, "s2_04_footer-row_light.jpg", "E2E v045 first")
    b = _scan_one(page, server, "s2_02_right_light.jpg", "E2E v045 second")
    _set(server, a, fields=CLEAN, status="approved", exported=True)
    _set(server, b, fields=dict(CLEAN, title="Founder"))
    _open(page, b); expect(page.locator("#first_name")).not_to_have_value("")
    if page.locator("#dDiff").count() and page.locator("#dDiff").is_visible():
        page.locator("#dDiff").click(); page.wait_for_timeout(800)
        dl = page.locator("#dlg[open]")
        if dl.count(): dl.get_by_role("button").filter(has_text="Different").first.click(); page.wait_for_timeout(800)
    page.locator("#bApprove").click()
    dlg = page.locator("#dlg[open]"); expect(dlg).to_be_visible(); expect(dlg).to_contain_text(f"#{a}"); expect(dlg).to_contain_text("exported before")
    page.keyboard.press("Enter")                       # Cancel has the focus: Enter never approves through the warning
    page.wait_for_timeout(800); assert card_json(page, b)["status"] == "pending"
    page.locator("#bApprove").click()
    dlg = page.locator("#dlg[open]"); expect(dlg).to_be_visible()
    dlg.get_by_role("button", name="Approve anyway").click()
    page.wait_for_timeout(1500)
    expect(page.locator("#dlg[open]")).to_have_count(0)   # ONE dialog only
    for _ in range(20):
        if card_json(page, b)["status"] == "approved": break
        page.wait_for_timeout(500)
    assert card_json(page, b)["status"] == "approved"


def test_nothing_exported_no_dialog(new_page, server):
    page = signed_in_admin(new_page)   # each card its own photo: a photo scanned twice opens 'Same person?' and Approve waits for that answer
    c = _scan_one(page, server, "s2_06_logo-band_light.jpg", "E2E v045 plain")
    _set(server, c, fields=dict(CLEAN, first_name="Ulrich", last_name="Vance", emails=["uv@vance-co.com"], website="vance-co.com",
                                phones=[{"type": "work", "number": "(330) 555-0177"}], company="Vance Co"))
    _open(page, c); expect(page.locator("#first_name")).not_to_have_value("")
    page.locator("#bApprove").click()
    for _ in range(20):
        assert not page.locator("#dlg[open]").count(), "no dialog when nothing was exported before"
        if card_json(page, c)["status"] == "approved": break
        page.wait_for_timeout(300)
    assert card_json(page, c)["status"] == "approved"


def test_ai_dialog_cancel_focused_enter_never_approves(new_page, server):
    page = signed_in_admin(new_page)
    c = _scan_one(page, server, "s2_08_center_light.jpg", "E2E v045 ai")
    _set(server, c, fields=dict(CLEAN, first_name="Wanda", last_name="Xu", emails=["wx@xu-studio.com"], website="xu-studio.com",
                                phones=[{"type": "work", "number": "(330) 555-0188"}], company="Xu Studio"), ai="queued")
    _open(page, c); expect(page.locator("#first_name")).not_to_have_value("")
    page.locator("#bApprove").click()
    dlg = page.locator("#dlg[open]"); expect(dlg).to_contain_text("AI check not finished")
    expect(dlg.get_by_role("button", name="Cancel")).to_be_focused()
    page.keyboard.press("Enter"); page.wait_for_timeout(1000)
    assert card_json(page, c)["status"] == "pending"
