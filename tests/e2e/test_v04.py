"""v0.4 screens: tap-to-zoom, review layout, keyboard safety, export summary, duplicate view, theme. Made-up cards only."""
import os, re
from playwright.sync_api import expect
from test_flows import answer_dialogs, card_json, scan, signed_in_admin, wait_card


def _open_first(page):
    a = page.locator("#qBody a[href^='#review/']").first; cid = int(a.get_attribute("href").split("/")[-1]); a.click(); wait_card(page, cid); return cid


def test_tap_field_zooms_photo(new_page):
    page = signed_in_admin(new_page)
    scan(page, "card6_center.jpg", batch="E2E zoom")
    cid = _open_first(page)
    assert card_json(page, cid)["card"]["fields"]["boxes"].get("company")
    img = page.locator("#rImg"); expect(page.locator("#zHint")).to_have_text("Tap a field to zoom")
    page.locator("#company").click()
    expect(img).to_have_attribute("data-zoom", "company"); assert "scale(" in img.evaluate("e => e.style.transform")
    page.keyboard.press("Escape")   # leaves the field and shows the whole photo again
    expect(img).not_to_have_attribute("data-zoom", re.compile(".")); assert img.evaluate("e => e.style.transform") == ""


def test_enter_approves_only_when_safe(new_page):
    page = signed_in_admin(new_page)
    scan(page, "hard1_twocol.jpg", "hard2_photo.jpg", batch="E2E enter")   # cards no other e2e test scans (a look-alike would block Enter)
    ids = [int(a.get_attribute("href").split("/")[-1]) for a in page.locator("#qBody a[href^='#review/']").all()]
    page.locator("#qBody a[href^='#review/']").first.click(); wait_card(page, ids[0])
    expect(page.locator("#rKeys")).to_contain_text("Approve")
    # unsaved edits: Enter does nothing to the card
    page.locator("#title").fill("Chief Enter Tester"); page.keyboard.press("Enter")
    expect(page.locator("#toast")).to_contain_text("Unsaved"); assert card_json(page, ids[0])["status"] == "pending"
    page.locator("#bDiscard").click(); page.locator("#dlg[open]").get_by_role("button", name="Discard my edits").click()
    wait_card(page, ids[0]); expect(page.locator("#rDirty")).to_be_hidden()
    # a dialog is open: Enter belongs to the dialog, never approves the card behind it
    page.locator("#zoom").click(); expect(page.locator("#zoomDlg")).to_be_visible(); page.keyboard.press("Enter")
    page.keyboard.press("Escape"); assert card_json(page, ids[0])["status"] == "pending"
    # arrows move between cards; Skip goes to the next one
    page.locator("#h-r").focus(); page.keyboard.press("ArrowRight"); wait_card(page, ids[1])
    page.keyboard.press("ArrowLeft"); wait_card(page, ids[0])
    page.locator("#bSkip").click(); wait_card(page, ids[1]); page.keyboard.press("ArrowLeft"); wait_card(page, ids[0])
    # clean card, no dialog: Enter approves
    wait_card(page, ids[0]); page.wait_for_timeout(700); page.locator("#h-r").focus(); page.keyboard.press("Enter"); answer_dialogs(page, timeout=15000)
    for _ in range(60):
        if card_json(page, ids[0])["status"] == "approved": break
        page.wait_for_timeout(500)
    assert card_json(page, ids[0])["status"] == "approved"


def test_more_holds_reject_and_theme_toggle(new_page):
    page = signed_in_admin(new_page)
    scan(page, "card3_dark.jpg", batch="E2E more")
    cid = _open_first(page)
    expect(page.locator("#bReject")).to_be_visible(); expect(page.locator("#bSave")).to_be_visible()   # v0.4.1 #8: on the bar, not under More
    before = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.locator("#themeBtn").click(); after = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert before != after and page.evaluate("document.documentElement.dataset.theme") in ("dark", "light")
    page.reload(); wait_card(page, cid); assert page.evaluate("getComputedStyle(document.body).backgroundColor") == after   # kept
    page.locator("#themeBtn").click()


def test_duplicate_side_by_side(new_page, tmp_path):
    from PIL import Image, ImageOps
    from test_flows import CARDS
    # the same made-up card photographed twice (a slightly different photo, so it is not the same file)
    im = Image.open(os.path.join(CARDS, "card4_noisy_rot.jpg")).convert("RGB"); p2 = str(tmp_path / "again.jpg")
    ImageOps.autocontrast(im.resize((int(im.width * .9), int(im.height * .9)))).save(p2, quality=88)
    page = signed_in_admin(new_page)
    scan(page, "card4_noisy_rot.jpg", p2, batch="E2E dup")
    _open_first(page)
    box = page.locator("#rDupQ"); expect(box).to_contain_text("Same person?")
    expect(page.locator("#dGrid .mini")).to_have_count(2); expect(page.locator("#dGrid .mini").nth(1)).not_to_contain_text("Loading")
    expect(page.locator("#dSame")).to_have_text("Same")
