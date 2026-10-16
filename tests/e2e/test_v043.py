"""v0.4.3: the signed-out help page has no app menu; signed in it does. Made-up data only."""
from playwright.sync_api import expect
from test_flows import signed_in_admin


def test_help_menu_only_when_signed_in(new_page):
    anon = new_page()
    anon.goto("/help"); anon.wait_for_timeout(500)
    expect(anon.locator("#helpNav")).to_be_hidden(); expect(anon.locator("#helpBack")).to_have_text("Sign in")
    page = signed_in_admin(new_page)
    page.goto("/help"); expect(page.locator("#helpNav")).to_be_visible(); expect(page.locator("#helpBack")).to_contain_text("Back to the scanner")
