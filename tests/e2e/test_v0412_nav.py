"""v0.4.12: a late 'card not found' on the Review page no longer pulls the person off the page they moved to. Made-up data."""
from playwright.sync_api import expect
from test_flows import signed_in_admin


def test_late_card_not_found_does_not_leave_export(new_page, server):
    page = signed_in_admin(new_page)
    page.goto("/ui#upload"); expect(page.locator("#v-upload")).to_be_visible(timeout=15000)
    # the card request for '#review' (no card number) answers 404 only after the person has already gone to Export; delayed
    # inside the page so the test itself is not blocked while it waits
    page.evaluate("""() => { const f = window.fetch; window.fetch = (u, o) => String(u).endsWith('/api/cards/NaN')
        ? new Promise(r => setTimeout(() => r(new Response('{"detail": "Card not found"}', {status: 404, headers: {'Content-Type': 'application/json'}})), 1500))
        : f(u, o); }""")
    page.evaluate("location.hash = 'review'"); page.evaluate("location.hash = 'export'")
    expect(page.locator("#v-export")).to_be_visible()
    page.wait_for_timeout(2500)   # the late 404 has arrived by now
    assert page.url.endswith("#export"), page.url
    expect(page.locator("#v-export")).to_be_visible()
