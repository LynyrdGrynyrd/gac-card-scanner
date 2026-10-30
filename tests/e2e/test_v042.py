"""v0.4.2: 'You are' banner on every screen, public help, on-screen Undo after Approve, batch name first. Made-up cards only."""
import os
from playwright.sync_api import expect
from test_flows import answer_dialogs, card_json, scan, signed_in_admin, wait_card

SYN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "synth2")


def test_banner_every_screen_and_public_help(new_page):
    page = signed_in_admin(new_page)
    for h in ("#upload", "#queue", "#export", "#admin"):
        page.goto("/ui" + h); expect(page.locator("#youAre")).to_contain_text("You are:")
    page.goto("/ui#upload"); expect(page.locator("#batchName")).to_be_visible()   # the batch name is first on the Scan page, not under More
    anon = new_page()
    r = anon.goto("/help"); assert r.ok and anon.url.endswith("/static/ui/help.html")


def test_undo_on_screen_after_approve(new_page):
    page = signed_in_admin(new_page)
    scan(page, os.path.join(SYN, "s2_04_footer-row_light.jpg"), batch="E2E v042 undo")   # a public synth card (CI has no private fixtures)
    a = page.locator("#qBody a[href^='#review/']").first; cid = int(a.get_attribute("href").split("/")[-1]); a.click(); wait_card(page, cid)
    d = card_json(page, cid)
    if d.get("hard"): return   # a blocked read can't be approved; nothing to undo
    for b in ("#dDiff",):
        if page.locator(b).count() and page.locator(b).is_visible(): page.locator(b).click(); page.wait_for_timeout(800)
    page.locator("#bApprove").click()
    for _ in range(3):
        dl = page.locator("#dlg[open]")
        if not dl.count(): break
        btn = dl.get_by_role("button").filter(has_text="Approve").or_(dl.get_by_role("button", name="Add as new contact"))
        if btn.count(): btn.first.click()
        else: answer_dialogs(page, timeout=1000); break
        page.wait_for_timeout(500)
    expect(page.locator("#toast .toastbtn", has_text="Undo")).to_be_visible(timeout=15000)
    page.locator("#toast .toastbtn", has_text="Undo").click()
    for _ in range(40):
        if card_json(page, cid)["status"] == "pending": break
        page.wait_for_timeout(250)
    assert card_json(page, cid)["status"] == "pending"
