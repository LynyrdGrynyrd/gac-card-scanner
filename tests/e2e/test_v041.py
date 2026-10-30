"""v0.4.1: Enter safety (held key, key-up, field focus), Reject asks and keeps the note, layout at 1280 px, names and
tap targets. Made-up cards only."""
import os
import re
from playwright.sync_api import expect
from test_flows import answer_dialogs, card_json, scan, signed_in_admin, wait_card


def _ids(page):
    return [int(a.get_attribute("href").split("/")[-1]) for a in page.locator("#qBody a[href^='#review/']").all()]


def _status(page, cid, want, tries=40):
    for _ in range(tries):
        if card_json(page, cid)["status"] == want: return True
        page.wait_for_timeout(250)
    return card_json(page, cid)["status"] == want


REPEAT = """n => { for (let i = 0; i < n; i++) (document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', repeat: true, bubbles: true})); }"""
FRESH = """() => (document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))"""


def test_held_enter_approves_one_card_only(new_page):
    page = signed_in_admin(new_page)
    scan(page, "hard3_lowres_italic.jpg", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "synth2", "s2_02_right_light.jpg"), batch="E2E v041 enter")
    ids = _ids(page); page.locator("#qBody a[href^='#review/']").first.click(); wait_card(page, ids[0])
    page.wait_for_timeout(700)
    first = card_json(page, ids[0]); clean = not first.get("hard") and not (first.get("dupes") or {}).get("queue")
    page.locator("#h-r").focus()
    page.keyboard.down("Enter")                    # the first press may approve (when the card is clean) ...
    page.evaluate(REPEAT, 30)                      # ... a held key (repeat) never does anything more
    answer_dialogs(page, timeout=3000)
    if clean: assert _status(page, ids[0], "approved")
    page.wait_for_timeout(1500)
    page.evaluate(FRESH)                           # no key-up yet: still nothing
    page.wait_for_timeout(800)
    assert card_json(page, ids[1])["status"] == "pending"
    page.keyboard.up("Enter")


def test_enter_in_a_field_never_approves(new_page):
    page = signed_in_admin(new_page)
    scan(page, "card2_center.jpg", batch="E2E v041 field")
    cid = _ids(page)[0]; page.locator("#qBody a[href^='#review/']").first.click(); wait_card(page, cid)
    page.wait_for_timeout(700)
    page.locator("#title").click(); page.keyboard.press("Enter")
    expect(page.locator("#toast")).to_contain_text("Esc, then Enter"); page.wait_for_timeout(500)
    assert card_json(page, cid)["status"] == "pending"


def test_reject_asks_first_and_keeps_the_note(new_page):
    page = signed_in_admin(new_page)
    scan(page, "card5_left.jpg", batch="E2E v041 reject")
    cid = _ids(page)[0]; page.locator("#qBody a[href^='#review/']").first.click(); wait_card(page, cid)
    page.locator("#note").fill("call back Monday"); page.keyboard.press("Escape"); page.locator("#h-r").focus()
    page.keyboard.press("r")
    dlg = page.locator("#dlg[open]"); expect(dlg).to_contain_text(f"Reject card #{cid}?"); expect(dlg).to_contain_text("Note")
    page.keyboard.press("Enter")                   # Cancel is the default
    expect(page.locator("#dlg[open]")).to_have_count(0); assert card_json(page, cid)["status"] == "pending"
    page.locator("#bReject").click(); page.locator("#dlg[open]").get_by_role("button", name="Reject", exact=True).click()
    assert _status(page, cid, "rejected")
    assert card_json(page, cid)["card"]["note"] == "call back Monday"


def test_review_fits_1280_names_and_targets(new_page):
    page = signed_in_admin(new_page); page.set_viewport_size({"width": 1280, "height": 900})
    scan(page, "card6_center.jpg", batch="E2E v041 layout")
    cid = _ids(page)[0]; page.locator("#qBody a[href^='#review/']").first.click(); wait_card(page, cid)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    unnamed = page.evaluate("""() => [...document.querySelectorAll('#v-review a, #v-review button')].filter(e => e.offsetParent &&
        !((e.getAttribute('aria-label') || e.textContent || e.title || (e.querySelector('img') || {}).alt || '').trim())).map(e => e.outerHTML.slice(0, 80))""")
    assert unnamed == [], unnamed
    small = page.evaluate("""() => [...document.querySelectorAll('#v-review button, #v-review .btn, #v-review summary')].filter(e => e.offsetParent)
        .map(e => [e.id || e.textContent.trim().slice(0, 20), e.getBoundingClientRect().height]).filter(x => x[1] < 43.5)""")
    assert small == [], small
    # zoom: a field with no box shows the whole photo
    page.locator("#note").click(); img = page.locator("#rImg")
    expect(img).not_to_have_attribute("data-zoom", re.compile("."))
