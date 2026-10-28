"""v0.4.8: an export that would only hold an edited-after-export card makes no file and says "Nothing new to import.";
saving an exported card says so; the sign-in page says why you are there; Undo names the action. Made-up cards only."""
from playwright.sync_api import expect
from test_flows import signed_in_admin
from test_v045 import CLEAN, _db, _open, _scan_one, _set
from test_v046 import _reviewer, _shot


def test_edited_after_export_alone_says_nothing_new(new_page, server):
    page = signed_in_admin(new_page)
    a = _scan_one(page, server, "s2_04_footer-row_light.jpg", "E2E v048 held")
    _set(server, a, fields=dict(CLEAN, first_name="Hedda", last_name="Held", emails=["hedda@held-co.com"], website="held-co.com", company="Held Co"), status="approved")
    c = _db(server); bt = c.execute("SELECT batch FROM card_meta WHERE card_id=?", (a,)).fetchone()[0]; c.close()
    page.goto("/ui#export"); go = page.locator("#exGo"); expect(go).to_be_enabled(timeout=15000); go.click()
    dlg = page.locator("#dlg[open]"); expect(dlg.get_by_role("heading")).to_have_text("Ready to save")
    with page.expect_download():
        dlg.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#exDone")).to_be_visible()
    c = _db(server); assert c.execute("SELECT exported FROM card_meta WHERE card_id=?", (a,)).fetchone()[0]; c.close()
    _open(page, a); page.locator("#title").fill("Boss")
    page.locator("#bSave").click()
    expect(page.locator("#toast")).to_contain_text("won't be exported again unless an admin includes it"); _shot(page, "01_exported_edit_notice")
    page.goto("/ui#export")
    expect(page.locator("#exBigT")).to_have_text("Nothing new to import.", timeout=15000); _shot(page, "02_nothing_new")
    expect(page.locator("#exBigT")).not_to_contain_text("ready")
    c = _db(server); n0 = c.execute("SELECT COUNT(*) FROM exports").fetchone()[0]
    assert c.execute("SELECT reexport FROM card_meta WHERE card_id=?", (a,)).fetchone()[0]   # the warning stays
    c.close()
    expect(go).to_be_enabled()   # an admin may still include it
    go.click(); dlg = page.locator("#dlg[open]"); expect(dlg).to_contain_text("Edited after export, so not in this file"); expect(dlg).not_to_contain_text("combined with another row"); expect(dlg).to_contain_text("no file is made")
    expect(dlg.locator("#exIncChg")).to_be_visible(); _shot(page, "02b_save_dialog_left_out")
    dlg.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#exDone")).to_contain_text("Nothing new to import."); expect(page.locator("#exDone")).to_contain_text("No file was made.")
    c = _db(server); assert c.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == n0; c.close()


def test_sign_in_page_says_30_minutes_and_signed_out(new_page, server):
    page = _reviewer(signed_in_admin(new_page), new_page, user="rhea48")   # never sign out the shared admin session
    page.goto("/ui#upload"); page.locator("#logout").click()
    expect(page.locator("#outMsg")).to_have_text("You are signed out.")
    expect(page.locator("#idleNote")).to_contain_text("30 minutes"); _shot(page, "03_signed_out")
    page.goto("/login?out=idle"); expect(page.locator("#outMsg")).to_contain_text("after 30 minutes with no use")


def test_undo_button_names_action_and_batch(new_page, server):
    page = signed_in_admin(new_page)
    a = _scan_one(page, server, "s2_02_right_light.jpg", "E2E v048 undo")
    _set(server, a, fields=dict(CLEAN, first_name="Ulf", last_name="Undo", emails=["ulf@undo-co.com"], website="undo-co.com", company="Undo Co"))
    _open(page, a); page.locator("#title").fill("Changed"); page.locator("#bSave").click()
    btn = page.locator("#undoBtn"); expect(btn).to_be_visible(timeout=10000)
    expect(btn).to_contain_text(f"Undo Edit #{a}"); expect(btn).to_contain_text("E2E v048 undo")
    btn.hover(); assert "2 hours" in (btn.get_attribute("title") or ""); _shot(page, "04_undo_label")
