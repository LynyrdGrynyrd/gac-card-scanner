"""v0.4.9: one count and one 'why' line on the Export page; a typed batch name survives New batch. Made-up cards only."""
import os
from playwright.sync_api import expect
from test_flows import signed_in_admin
from test_v045 import CLEAN, SYN, _db, _set
from test_v046 import _shot


def test_export_page_says_why_when_nothing_is_new(new_page, server):
    page = signed_in_admin(new_page)
    from test_v045 import _scan_one
    a = _scan_one(page, server, "s2_08_center_light.jpg", "E2E v049 why")
    _set(server, a, fields=dict(CLEAN, first_name="Wanda", last_name="Why", emails=["wanda@why-co.com"], website="why-co.com", company="Why Co"), status="approved")
    page.goto("/ui#export"); go = page.locator("#exGo"); expect(go).to_be_enabled(timeout=15000)
    expect(page.locator("#exBig")).to_have_text("1"); expect(page.locator("#exBigT")).to_have_text("row ready")
    go.click(); dlg = page.locator("#dlg[open]"); expect(dlg).to_contain_text("1 row"); _shot(page, "00_save_dialog_count")   # the Save dialog says the same count
    with page.expect_download():
        dlg.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#exNext")).to_contain_text("Import this one file into MC Trade"); _shot(page, "01_next_steps")
    page.goto("/ui#review"); page.goto("/ui#export"); page.reload()
    expect(page.locator("#exBigT")).to_have_text("Nothing new to import.", timeout=15000)
    expect(page.locator("#exWhy")).to_have_text("1 card already exported. Nothing new to import."); _shot(page, "02_nothing_new_why")
    c = _db(server); assert c.execute("SELECT COUNT(*) FROM exports WHERE kind='xlsx' AND card_ids LIKE ?", (f"%{a}%",)).fetchone()[0] >= 1; c.close()


def test_typed_batch_name_survives_new_batch(new_page, server):
    page = signed_in_admin(new_page)
    from test_v045 import _scan_one
    _scan_one(page, server, "s2_10_two-column_light.jpg", "E2E v049 first")
    page.goto("/ui#upload"); nb = page.locator("#clearBatch"); expect(nb).to_be_visible(timeout=15000)
    if not page.locator("#batchName").is_visible(): page.locator("#upMore > summary").click()
    page.locator("#batchName").fill("E2E v049 second"); nb.click()
    expect(page.locator("#batchName")).to_have_value("E2E v049 second")
    expect(page.locator("#toast")).to_contain_text("Ready for a new batch: “E2E v049 second”."); _shot(page, "03_new_batch_keeps_name")
    page.get_by_label("Skip the AI double-check").check()
    page.locator("#fPhotos").set_input_files([os.path.join(SYN, "s2_12_vertical_light.jpg")])
    expect(page.locator("#batchSummary")).to_contain_text("1 of 1 finished", timeout=180000)
    c = _db(server); lb = c.execute("SELECT batch_label FROM card_meta ORDER BY card_id DESC LIMIT 1").fetchone()[0]; c.close()
    assert lb.startswith("E2E v049 second"), lb
