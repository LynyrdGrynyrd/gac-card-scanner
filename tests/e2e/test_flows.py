"""Browser flows a pilot user goes through: first-run admin, scan a card photo, review + edit + approve, export CSV; a reviewer
can't open Admin; keyboard review (J/K/A). No console errors or uncaught page errors anywhere (see conftest.new_page)."""
import os, re
from conftest import ADMIN, ROOT
from playwright.sync_api import TimeoutError as PWTimeout, expect

CARDS = os.path.join(ROOT, "tests", "cards")
STATE = {}   # the admin's sign-in cookies, made once by the first-run test (or by signed_in_admin when run alone)

def first_run_setup(page):
    page.goto("/ui")
    expect(page).to_have_url(re.compile(r"/setup"))   # no account yet: the app sends you to first-time setup
    expect(page.get_by_role("heading", name="First-time setup")).to_be_visible()
    page.get_by_label("Your full name").fill(ADMIN["display"]); page.get_by_label("Initials").fill(ADMIN["initials"])
    page.get_by_label("Username").fill(ADMIN["username"]); page.get_by_label(re.compile(r"^Password")).fill(ADMIN["password"])
    page.get_by_label("Repeat password").fill(ADMIN["password"])
    page.get_by_role("button", name="Create admin and sign in").click()
    expect(page).to_have_url(re.compile(r"/ui")); expect(page.get_by_role("heading", name="Scan business cards")).to_be_visible()
    STATE["admin"] = page.context.storage_state()

def signed_in_admin(new_page):
    if "admin" not in STATE: first_run_setup(new_page())
    page = new_page(); page.context.add_cookies(STATE["admin"]["cookies"]); return page

def scan(page, *names, batch):
    """Upload card photos on the Scan page and wait until every one is read (real OCR in the server)."""
    page.goto("/ui#upload"); expect(page.get_by_role("heading", name="Scan business cards")).to_be_visible()
    page.get_by_label("Batch name").fill(batch); page.get_by_label("Skip AI").check()   # no AI helper in tests: don't queue cards for it
    page.locator("#fPhotos").set_input_files([os.path.join(CARDS, n) for n in names])
    # a session that was not signed in in THIS tab is asked who is scanning first (shared computers)
    yes = page.get_by_role("dialog", name="Who is scanning?").get_by_role("button", name=re.compile("^Yes, I am"))
    try: yes.wait_for(timeout=3000); yes.click()
    except PWTimeout: pass
    n = len(names)
    expect(page.locator("#batchSummary")).to_contain_text(f"{n} of {n} finished · {n} added", timeout=180000)
    page.get_by_role("link", name="Review batch →").click()
    expect(page.locator("#qBody a[href^='#review/']")).to_have_count(n)

def wait_card(page, cid):
    expect(page.get_by_role("heading", name=f"Review card #{cid}")).to_be_visible(); expect(page.locator("#bApprove")).to_be_enabled()

def answer_dialogs(page, timeout=5000):
    """Approving asks when the card looks like someone in the MC Trade contacts (the 5 SAMPLE contacts here, which include
    Maria Delgado): answer 'different person'. Cards with no look-alike get no question."""
    b = page.locator("#dlg[open]").get_by_role("button", name="Different person: add as new")
    try: b.wait_for(timeout=timeout)
    except PWTimeout: return
    b.click()

def card_json(page, cid):
    r = page.request.get(f"/api/cards/{cid}"); assert r.ok, r.text(); return r.json()

def test_first_run_scan_review_approve_export(new_page):
    page = new_page()
    first_run_setup(page)
    scan(page, "card1_left.jpg", batch="E2E one")
    link = page.locator("#qBody a[href^='#review/']").first
    cid = int(link.get_attribute("href").split("/")[-1]); link.click()
    wait_card(page, cid)
    expect(page.get_by_label("Last name")).to_have_value("Delgado")   # read from the photo
    page.get_by_label("Job title").fill("Head of E2E Lending")
    expect(page.locator("#rDirty")).to_be_visible()
    page.locator("#bApprove").click()
    expect(page.get_by_role("dialog", name="Already in MC Trade?")).to_be_visible(); answer_dialogs(page)
    # the last pending card of the batch: back to the batch's queue, with an 'All done' note
    expect(page).to_have_url(re.compile(r"#queue\?s=pending"), timeout=30000); expect(page.locator("#toast")).to_contain_text("All done")
    c = card_json(page, cid); assert c["status"] == "approved" and c["card"]["fields"]["title"] == "Head of E2E Lending"
    page.get_by_role("navigation", name="Main").get_by_role("link", name="Export").click()
    tile = page.get_by_role("button", name=re.compile(r"^Spreadsheet \(CSV\)"))
    expect(tile).to_be_enabled(); expect(page.locator("#exInfo")).to_contain_text("1")
    tile.click()
    dlg = page.locator("#dlg[open]"); expect(dlg.get_by_role("heading")).to_have_text("Export 1 card?")
    with page.expect_download() as dl:
        dlg.get_by_role("button", name="Export", exact=True).click()
    text = open(dl.value.path(), encoding="utf-8-sig").read()
    assert "Head of E2E Lending" in text and "Delgado" in text, text[:2000]
    expect(page.locator("#exDone")).to_contain_text("1 card")

def test_reviewer_cannot_open_admin(new_page):
    adm = signed_in_admin(new_page)
    adm.goto("/ui#admin"); expect(adm.get_by_role("heading", name="Reviewers")).to_be_visible()
    adm.get_by_label("Full name").fill("Rita Review"); adm.get_by_label("Username").fill("rita")
    adm.get_by_label("Temporary password").fill("temp-pass-12345"); adm.get_by_role("button", name="Add reviewer").click()
    expect(adm.locator("#uBody")).to_contain_text("rita")
    page = new_page(); page.goto("/login")
    page.get_by_label("Username").fill("rita"); page.get_by_label(re.compile(r"^Password")).fill("temp-pass-12345")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Change password")).to_be_visible()   # the given password is temporary
    page.get_by_role("button", name="Later").click()
    expect(page.get_by_role("navigation", name="Main").get_by_role("link", name="Admin")).to_be_hidden()
    page.goto("/ui#admin")
    expect(page.locator("#toast")).to_contain_text("Only admins can open the Admin page.")
    expect(page.get_by_role("heading", name="Reviewers")).to_have_count(0)   # the reviewer's page doesn't even contain the admin tables
    assert "Add a reviewer" not in page.content()
    assert page.request.get("/api/admin/users").status == 403 and page.request.get("/api/admin/settings").status == 403

def test_keyboard_review_queue(new_page):
    page = signed_in_admin(new_page)
    scan(page, "card2_center.jpg", "card5_left.jpg", batch="E2E keys")
    ids = [int(a.get_attribute("href").split("/")[-1]) for a in page.locator("#qBody a[href^='#review/']").all()]
    page.locator("#qBody a[href^='#review/']").first.focus(); page.keyboard.press("Enter")   # a row link opens with the keyboard
    wait_card(page, ids[0]); page.keyboard.press("Escape")
    page.keyboard.press("j"); wait_card(page, ids[1])   # J: next card
    page.keyboard.press("k"); wait_card(page, ids[0])   # K: previous card
    page.keyboard.press("a"); answer_dialogs(page)        # A: approve; the next pending card of the batch opens
    wait_card(page, ids[1])
    assert card_json(page, ids[0])["status"] == "approved" and card_json(page, ids[1])["status"] == "pending"
