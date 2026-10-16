"""v0.4 screens: tap-to-zoom, review layout, keyboard safety, export summary, duplicate view, theme. Made-up cards only."""
import re
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
