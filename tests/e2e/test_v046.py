"""v0.4.6: a reviewer sees another person's look-alike only as a count (no link, no id), the toast names the real next step
('Pick Different first.'), Different answers it, and the other card's page and photo are 404. Made-up cards only."""
import os, re
from playwright.sync_api import expect
from test_flows import card_json, signed_in_admin
from test_v045 import CLEAN, _open, _scan_one, _set


def _shot(page, name):   # GAC_SHOTS=dir: save the state for the UX audit (docs/screenshots/v0.4.6)
    d = os.environ.get("GAC_SHOTS")
    if d: os.makedirs(d, exist_ok=True); page.wait_for_timeout(300); page.screenshot(path=os.path.join(d, name + ".png"), full_page=False)


def _reviewer(adm, new_page, user="rhea46", pw="temp-pass-46046"):
    adm.goto("/ui#admin"); expect(adm.get_by_role("heading", name="Reviewers")).to_be_visible()
    adm.get_by_label("Full name").fill("Rhea Fortysix"); adm.get_by_label("Username").fill(user)
    adm.get_by_label("Temporary password").fill(pw); adm.get_by_role("button", name="Add reviewer").click()
    expect(adm.locator("#uBody")).to_contain_text(user)
    page = new_page(); page.goto("/login")
    page.get_by_label("Username").fill(user); page.get_by_label(re.compile(r"^Password")).fill(pw)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Change password")).to_be_visible(); page.get_by_role("button", name="Later").click()
    return page


def test_other_batch_lookalike_is_a_count_and_different_answers_it(new_page, server):
    adm = signed_in_admin(new_page)
    a = _scan_one(adm, server, "s2_14_left_dark.jpg", "E2E v046 admin")
    rv = _reviewer(adm, new_page)
    b = _scan_one(rv, server, "s2_16_right_dark.jpg", "E2E v046 mine")
    same = dict(CLEAN, first_name="Wren", last_name="Okafor", emails=["wren@okafor-design.com"], website="okafor-design.com",
                company="Okafor Design", phones=[{"type": "work", "number": "(330) 555-0984"}])
    _set(server, a, fields=same); _set(server, b, fields=dict(same, title="Partner"))
    _open(rv, b)
    box = rv.locator("#rDupQ"); expect(box).to_contain_text("Looks like 1 card in another batch"); _shot(rv, "01_count_only_lookalike")
    assert f"#{a}" not in box.inner_text() and not rv.locator(f'#rDupQ a[href="#review/{a}"]').count()
    rv.locator("#bApprove").click(); expect(rv.locator("#toast")).to_contain_text("Pick Different first."); _shot(rv, "02_pick_different_toast")
    rv.locator("#dDiff").click(); expect(rv.locator("#toast")).to_contain_text("Marked different.")
    assert rv.request.get(f"/api/cards/{a}").status == 404 and rv.request.get(f"/api/cards/{b}").status == 200
    assert rv.request.get("/api/cards?batch=__none__").status == 200


def test_reviewer_blocked_card_says_admin_and_needs_admin_flag(new_page, server):
    adm = signed_in_admin(new_page)
    rv = _reviewer(adm, new_page, user="rhea46b")
    c = _scan_one(rv, server, "s2_18_footer-row_light.jpg", "E2E v046 blocked")
    _set(server, c, fields=dict(CLEAN, first_name="Morg4n", last_name="Pike", emails=["mp@pike-co.com"], website="pike-co.com",
                                company="Pike Co", phones=[{"type": "work", "number": "(330) 555-0993"}]))
    _open(rv, c)
    expect(rv.locator("#rErr")).to_contain_text("Morg4n"); _shot(rv, "03_misread_blocked")
    rv.locator("#bApprove").click(); expect(rv.locator("#toast")).to_contain_text('An admin needs to confirm this. "Morg4n" looks misread. Fix it or click Needs admin.'); _shot(rv, "04_approve_blocked_toast")
    assert card_json(rv, c)["status"] == "pending"
    rv.locator("#bNeedsAdmin").click(); expect(rv.locator("#toast")).to_contain_text("Flagged for an admin.")
    expect(rv.locator("#rErr")).to_contain_text("Flagged for an admin."); _shot(rv, "05_flagged")
    adm.goto("/ui#queue"); expect(adm.locator("#naBadge")).to_contain_text("1 needs admin"); _shot(adm, "06_admin_badge")
