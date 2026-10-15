"""End-to-end browser tests (Playwright, Chromium): the real app (uvicorn app.main:app, like start.command) on a free
localhost port in a subprocess, with ALL data in a temp folder. Run: python -m pytest -q tests/e2e
Needs: pip install -r requirements-dev.txt; python -m playwright install chromium (CI: --with-deps); Tesseract."""
import glob, os, re, socket, subprocess, sys, tempfile, time, urllib.request
import pytest

try: from playwright import sync_api as pw
except ImportError: pw = None; collect_ignore_glob = ["test_*.py"]   # playwright not installed (pip install -r requirements-dev.txt)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ADMIN = {"username": "erin", "display": "Erin Admin", "initials": "EA", "password": "e2e-admin-pass-1"}

def _free_port():
    with socket.socket() as s: s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

@pytest.fixture(scope="session")
def server():
    data = tempfile.mkdtemp(prefix="gac-e2e-"); port = _free_port(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, GAC_DATA_DIR=data, GAC_DB=os.path.join(data, "cards.db"), GAC_BACKUP="0", GAC_UPDATE_CHECK="0",
               VLM_URL="http://127.0.0.1:9", MCTRADE_TEMPLATE=os.path.join(data, "mctrade_template.xlsx"), PYTHONUNBUFFERED="1")
    log = open(os.path.join(data, "server.log"), "w")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                         cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            if p.poll() is not None: break
            try:
                if urllib.request.urlopen(base + "/health", timeout=2).status == 200: break
            except OSError: time.sleep(0.5)
        else: pytest.fail("the server did not start")
        if p.poll() is not None: pytest.fail("the server exited:\n" + open(log.name).read()[-3000:])
        yield {"base": base, "data": data, "log": log.name}
    finally:
        p.terminate()
        try: p.wait(10)
        except subprocess.TimeoutExpired: p.kill()
        log.close()

def _chromium_fallback():
    """Locally a newer playwright may not find its own browser build; use one already in PLAYWRIGHT_BROWSERS_PATH."""
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expanduser("~/.cache/ms-playwright")
    exe = sorted(glob.glob(os.path.join(root, "chromium_headless_shell-*", "chrome-linux", "headless_shell")) +
                 glob.glob(os.path.join(root, "chromium-*", "chrome-linux", "chrome")))
    return exe[-1] if exe else None

@pytest.fixture(scope="session")
def browser():
    with pw.sync_playwright() as p:
        try: b = p.chromium.launch()
        except pw.Error as e:
            exe = _chromium_fallback()
            if not exe or "Executable doesn't exist" not in str(e): raise
            b = p.chromium.launch(executable_path=exe)
        yield b
        b.close()

@pytest.fixture
def new_page(browser, server):
    """A fresh browser context per call (own cookies). Console errors and uncaught page errors are collected and checked
    at the end of the test: the flows must run without any."""
    ctxs, errors = [], []
    def make():
        ctx = browser.new_context(base_url=server["base"], accept_downloads=True); ctx.set_default_timeout(20000); ctxs.append(ctx)
        pg = ctx.new_page()
        # Chromium logs every 4xx answer as a console error ("Failed to load resource ... status of 401"); the page asks for some
        # on purpose (e.g. /api/me before sign-in). Those are answers, not script errors; a 5xx still counts.
        pg.on("console", lambda m: m.type == "error" and not re.search(r"status of 4\d\d", m.text) and errors.append(f"console: {m.text}"))
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        return pg
    yield make
    for c in ctxs: c.close()
    assert not errors, "\n".join(errors)
