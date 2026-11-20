"""AIFILL (2026-11-20): the AI's reading fills the review form. A reviewer with the card open and nothing typed sees the form
update when the AI finishes; with unsaved typing nothing typed is lost and the AI's values arrive as suggestions.
The model is a stub HTTP server held shut until the test lets it answer. Made-up cards only."""
import json, os, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from playwright.sync_api import TimeoutError as PWTimeout, expect
from conftest import ADMIN, ROOT, serve
from test_v045 import _db

CARDS = os.path.join(ROOT, "tests", "cards")
ANSWERS = {"Firestone": {"first_name": "Priya", "last_name": "Raman", "title": "Director of Marketing Strategy", "company": "Firestone Park Health Clinic", "department": "",
                         "emails": ["praman@fphealth.org"], "phones": [], "website": "www.fphealth.org", "address": "777 E Market St, Akron, OH 44305"},
           "Summit": {"first_name": "Maria", "last_name": "Delgado", "title": "Vice President, Commercial Lending Officer", "company": "Summit Valley Bank", "department": "",
                      "emails": ["mdelgado@summitvalleybank.com"], "phones": [], "website": "www.summitvalleybank.com", "address": "200 S Main St, Suite 400, Akron, OH 44308"}}
GATE = threading.Event()   # the stub model answers only while this is set

class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._send({"status": "ok"})
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        GATE.wait(120)
        ans = next((a for k, a in ANSWERS.items() if k in body), {})
        self._send({"choices": [{"message": {"content": json.dumps(ans)}}]})

@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub); threading.Thread(target=srv.serve_forever, daemon=True).start()
    with serve(VLM_URL=f"http://127.0.0.1:{srv.server_address[1]}") as s:
        yield s
    GATE.set(); srv.shutdown()

@pytest.fixture
def admin(new_page):
    page = new_page(); page.goto("/ui")
    if "/setup" in page.url:
        page.get_by_label("Your full name").fill(ADMIN["display"]); page.get_by_label("Initials").fill(ADMIN["initials"])
        page.get_by_label("Username").fill(ADMIN["username"]); page.get_by_label(re.compile(r"^Password")).fill(ADMIN["password"])
        page.get_by_label("Repeat password").fill(ADMIN["password"]); page.get_by_role("button", name="Create admin and sign in").click()
    else:
        page.get_by_label("Username").fill(ADMIN["username"]); page.get_by_label(re.compile(r"^Password")).fill(ADMIN["password"]); page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Scan business cards")).to_be_visible(); return page

def scan_held(page, server, name):
    """Upload one card with the AI switched on; the stub keeps the AI waiting. Returns the card id."""
    GATE.clear()
    page.goto("/ui#upload"); expect(page.get_by_role("heading", name="Scan business cards")).to_be_visible()
    page.locator("#fPhotos").set_input_files([os.path.join(CARDS, name)])
    yes = page.get_by_role("dialog", name="Who is scanning?").get_by_role("button", name=re.compile("^Yes, I am"))
    try: yes.wait_for(timeout=3000); yes.click()
    except PWTimeout: pass
    expect(page.locator("#batchSummary")).to_contain_text("1 of 1 finished", timeout=180000)
    c = _db(server); n = c.execute("SELECT MAX(id) FROM cards").fetchone()[0]; c.close(); return n

def lowf(page, fid): return page.locator(f"#{fid}").locator("xpath=ancestor::div[contains(@class,'f')][1]")

def test_clean_open_card_fills_when_the_ai_finishes(admin, server):
    page = admin; cid = scan_held(page, server, "card3_dark.jpg")
    page.goto(f"/ui#review/{cid}"); expect(page.locator("#title")).to_have_value("Directorof Marketing")
    expect(page.locator("#rAI")).to_contain_text("AI check")   # queued / running: the reviewer got here first
    GATE.set()
    expect(page.locator("#title")).to_have_value("Director of Marketing Strategy", timeout=30000)   # the form updated by itself
    expect(page.locator("#rAI")).to_contain_text("filled in the form"); expect(page.locator("#rAI")).to_contain_text("Job title")
    expect(page.locator("#fields .f.low .cf").first).to_contain_text("Check")   # the rules doubted the email and still do
    expect(page.locator("#title").locator("xpath=ancestor::div[contains(@class,'f')][1]")).to_have_class(re.compile(r"\blow\b"))   # and every field the AI set is Check
    expect(page.locator("#rDirty")).to_be_hidden()   # nothing unsaved: the AI's values are the saved card
    expect(page.locator("#rAI [data-aik]")).to_have_count(0)   # no Keep/Undo buttons: to change a filled value, edit it
    expect(page.locator("#rAI table.aidiff")).to_contain_text("Earlier value"); expect(page.locator("#rAI table.aidiff")).to_contain_text("Directorof Marketing")   # the earlier value, as plain text
    page.locator("#company").fill("Firestone Park Clinic"); page.locator("#bSave").click()   # a save that does not touch the field
    for _ in range(40):
        c = _db(server); co = json.loads(c.execute("SELECT fields FROM cards WHERE id=?", (cid,)).fetchone()[0])["company"]; c.close()
        if co == "Firestone Park Clinic": break
        time.sleep(0.25)
    page.reload(); expect(lowf(page, "title")).to_have_class(re.compile(r"\blow\b"))   # the AI's field is still Check
    page.locator("#title").fill("Director of Marketing"); page.locator("#bSave").click()   # the person edits it
    for _ in range(40):
        c = _db(server); src = json.loads(c.execute("SELECT field_sources FROM card_meta WHERE card_id=?", (cid,)).fetchone()[0]); c.close()
        if src["title"].startswith("edited:"): break
        time.sleep(0.25)
    assert src["title"].startswith("edited:")
    page.reload(); expect(page.locator("#title")).to_have_value("Director of Marketing")
    expect(lowf(page, "title")).not_to_have_class(re.compile(r"\blow\b"))   # a person's edit clears it

def test_unsaved_typing_survives_and_the_ai_arrives_as_suggestions(admin, server):
    page = admin; cid = scan_held(page, server, "card1_left.jpg")
    page.goto(f"/ui#review/{cid}"); expect(page.locator("#title")).to_have_value("Vice President, Commercial Lending")
    page.locator("#company").fill("Typed Co"); expect(page.locator("#rDirty")).to_be_visible()
    for _ in range(60):   # the draft reaches the server a moment after typing: that is what keeps the AI from touching the card
        c = _db(server); n = c.execute("SELECT COUNT(*) FROM drafts WHERE card_id=?", (cid,)).fetchone()[0]; c.close()
        if n: break
        time.sleep(0.25)
    assert n
    GATE.set()
    expect(page.locator("#rAI")).to_contain_text("AI suggestions", timeout=30000)
    expect(page.locator("#company")).to_have_value("Typed Co")   # nothing typed was lost
    expect(page.locator("#title")).to_have_value("Vice President, Commercial Lending")   # the card itself did not change
    expect(page.locator("#rAI")).to_contain_text("Commercial Lending Officer")
    c = _db(server); f = json.loads(c.execute("SELECT fields FROM cards WHERE id=?", (cid,)).fetchone()[0]); c.close()
    assert f["title"] == "Vice President, Commercial Lending" and f["company"] == "Summit Valley Bank"


# ---- review round 1 (2026-11-20)

def test_blocked_draft_request_loses_no_typing_when_the_ai_applies(admin, server):
    page = admin; cid = scan_held(page, server, "card3_dark.jpg")
    page.route("**/api/cards/*/draft", lambda route: route.fulfill(status=429, content_type="application/json", body='{"error": "blocked"}'))   # the mirror is refused (and so is its retry); a 4xx is not logged as a page error
    page.goto(f"/ui#review/{cid}"); expect(page.locator("#title")).to_have_value("Directorof Marketing")
    page.locator("#company").fill("Typed Co"); time.sleep(3.5)   # the 0.4 s mirror and the 2 s retry have both failed
    c = _db(server); assert c.execute("SELECT COUNT(*) FROM drafts WHERE card_id=?", (cid,)).fetchone()[0] == 0; c.close()
    GATE.set()   # the server sees no draft and applies the reading
    for _ in range(80):
        c = _db(server); st = c.execute("SELECT ai_status FROM card_meta WHERE card_id=?", (cid,)).fetchone()[0]; c.close()
        if st == "checked": break
        time.sleep(0.5)
    assert st == "checked"
    expect(page.locator("#title")).to_have_value("Director of Marketing Strategy", timeout=30000)   # the page picked the result up ...
    expect(page.locator("#company")).to_have_value("Typed Co")   # ... and the typed text is still there
    page.locator("#bSave").click()
    for _ in range(40):
        c = _db(server); co = json.loads(c.execute("SELECT fields FROM cards WHERE id=?", (cid,)).fetchone()[0])["company"]; c.close()
        if co == "Typed Co": break
        time.sleep(0.5)
    assert co == "Typed Co"   # the reviewer's save succeeded with it


def test_failed_clear_of_the_draft_is_retried(admin, server):
    page = admin; cid = scan_held(page, server, "card3_dark.jpg")
    page.goto(f"/ui#review/{cid}"); expect(page.locator("#company")).not_to_have_value(""); orig = page.locator("#company").input_value()
    def drafts():
        c = _db(server); n = c.execute("SELECT COUNT(*) FROM drafts WHERE card_id=?", (cid,)).fetchone()[0]; c.close(); return n
    page.locator("#company").fill("Typed Co")
    for _ in range(40):
        if drafts(): break
        time.sleep(0.25)
    assert drafts() == 1   # the typing was mirrored
    page.route("**/api/cards/*/draft", lambda route: route.fulfill(status=429, content_type="application/json", body='{"error": "blocked"}'))
    page.locator("#company").fill(orig); expect(page.locator("#rDirty")).to_be_hidden()   # typing gone: the clear is refused ...
    time.sleep(1.2); page.unroute("**/api/cards/*/draft")   # ... and goes through when the retry (about 2 s later) is sent
    for _ in range(40):
        if not drafts(): break
        time.sleep(0.25)
    assert drafts() == 0
