"""AICLOUD (2026-11-20): the Settings page. "Where cards are read" is "On this computer" until an admin picks the cloud service,
reads the notice, ticks the box and enters a key. A stand-in HTTP server plays the provider; nothing real is called."""
import json, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from playwright.sync_api import expect
from conftest import ADMIN, serve

KEY = "sk-e2e-0123456789abcdef"
SEEN = []

class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        SEEN.append((self.path, self.rfile.read(int(self.headers.get("Content-Length") or 0))))
        b = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

@pytest.fixture(scope="module")
def server():   # its own app, so the shared first-run test of test_flows still finds a fresh one
    with serve() as s: yield s

@pytest.fixture
def admin(new_page):
    page = new_page(); page.goto("/ui")
    if "/setup" in page.url:
        page.get_by_label("Your full name").fill(ADMIN["display"]); page.get_by_label("Initials").fill(ADMIN["initials"])
        page.get_by_label("Username").fill(ADMIN["username"]); page.get_by_label(re.compile(r"^Password")).fill(ADMIN["password"])
        page.get_by_label("Repeat password").fill(ADMIN["password"]); page.get_by_role("button", name="Create admin and sign in").click()
    expect(page.get_by_role("heading", name="Scan business cards")).to_be_visible(); return page

def settings(page):
    page.goto("/ui#admin"); page.reload(); page.locator("#adminTabs button[data-t=settings]").click();   # (a fresh page: its values are filled in once, after a short load)
    expect(page.locator("#sSrc")).to_be_visible(); expect(page.locator("#sCBase")).not_to_have_value("")   # the page has filled its values

def test_settings_page_cloud_flow(admin, server):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub); threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        page = admin; settings(page)
        src = page.locator("#sSrc"); expect(src).to_have_value("local"); expect(page.locator("#cloudFields")).to_be_hidden()   # off by default
        src.select_option("cloud"); expect(page.locator("#cloudNotice")).to_contain_text("sent to this service")
        expect(page.locator("#cloudNotice")).to_contain_text("free tier"); expect(page.locator("#sCConsent")).not_to_be_checked()
        page.locator("#sCBase").fill(base); page.locator("#sCKey").fill(KEY)
        page.locator("#sSave").click()   # no tick: refused, nothing sent
        expect(page.locator("#toast")).to_contain_text("Tick the box"); assert not SEEN
        settings(page); expect(page.locator("#sSrc")).to_have_value("local")
        page.locator("#sSrc").select_option("cloud"); page.locator("#sCBase").fill(base); page.locator("#sCKey").fill(KEY); page.locator("#sCConsent").check()
        page.locator("#sSave").click()
        expect(page.locator("#toast")).to_contain_text("Cloud service: OK", timeout=20000); assert len(SEEN) == 1 and b"image_url" not in SEEN[0][1]
        settings(page); expect(page.locator("#sSrc")).to_have_value("cloud")
        expect(page.locator("#sCKey")).to_have_value(""); expect(page.locator("#sCKeyNote")).to_contain_text("A key is saved")   # the key is never shown again
        assert KEY not in page.content()
        page.locator("#sSrc").select_option("local")   # back to the default (other tests share this server)
        with page.expect_response(lambda r: r.url.endswith("/api/admin/settings") and r.request.method == "POST") as done: page.locator("#sSave").click()
        assert done.value.status == 200; settings(page); expect(page.locator("#sSrc")).to_have_value("local")
        page.locator("#sSrc").select_option("cloud"); page.locator("#sCKeyClear").click();   # (shown with the cloud fields) expect(page.locator("#toast")).to_contain_text("Saved key removed")
    finally: srv.shutdown()
