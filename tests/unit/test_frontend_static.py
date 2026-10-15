"""audit 2026-10: static checks over the browser code (there is no JS test runner). The CSP is script-src 'self', so inline
event handlers and javascript: URLs silently do nothing; these tests keep them out of every served page and script."""
import glob, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UI = os.path.join(ROOT, "app", "static", "ui")
PHONE = os.path.join(ROOT, "app", "static", "phone")
SERVED = sorted(glob.glob(os.path.join(UI, "*.html")) + glob.glob(os.path.join(UI, "*.js")) +
                glob.glob(os.path.join(PHONE, "*.html")) + glob.glob(os.path.join(PHONE, "*.js")))

def _src(p): return open(p, encoding="utf-8").read()
def _strip_js_comments(s):   # good enough for this code base: // comments that start a line or follow whitespace
    return re.sub(r"(^|\s)//[^\n]*", r"\1", s)

INLINE = re.compile(r"<[a-z][^<>]*?\son[a-z]+\s*=", re.I)   # <a ... onclick=  inside HTML or an HTML string in JS

def test_served_files_exist():
    names = {os.path.basename(p) for p in SERVED}
    assert {"index.html", "ui.js", "login.js", "login.html", "desktop.js", "phone.js", "sw.js"} <= names

def test_no_inline_event_handlers():
    bad = [(os.path.basename(p), m.group(0)[:80]) for p in SERVED for m in INLINE.finditer(_src(p))]
    assert not bad, bad

def test_no_javascript_urls():
    # a javascript: URL in an href/src/action (the CSP blocks it); the word inside a validation regex is fine
    pat = re.compile(r"""(href|src|action)\s*=\s*["'`]?\s*javascript:""", re.I)
    bad = [os.path.basename(p) for p in SERVED if pat.search(_strip_js_comments(_src(p)))]
    assert not bad, bad

def test_no_inline_scripts_in_html():
    for p in SERVED:
        if not p.endswith(".html"): continue
        for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", _src(p), re.S | re.I):
            assert "src=" in m.group(1) and not m.group(2).strip(), (os.path.basename(p), m.group(0)[:80])

def test_export_it_link_uses_a_delegated_listener():
    js = _src(os.path.join(UI, "ui.js"))
    assert "data-export-from=" in js and 'closest("a[data-export-from]")' in js

def test_audit_csv_link_is_routed_in_the_desktop_app():
    html = _src(os.path.join(UI, "index.html"))
    assert re.search(r'<a[^>]*id="aCsv"[^>]*\sdownload[\s>]', html)
    assert "fmt=csv" in _src(os.path.join(UI, "desktop.js"))

def test_every_api_fetch_goes_through_the_shared_auth_handling():
    # audit 2026-10: dl()/tileExport used raw fetch and skipped call()'s 401 handling; only call(), fetchOk() and the
    # public /api/auth/state + /health checks may call fetch() directly
    js = _src(os.path.join(UI, "ui.js"))
    raw = [ln.strip()[:90] for ln in js.splitlines() if re.search(r"(?<![\w.])fetch\(", ln)]
    allowed = ("const r = await fetch(u, o)", "const r = await fetch(u, {credentials", "fetch(\"/api/auth/state\"", "fetch(\"/health\")")
    assert all(any(a in ln for a in allowed) for ln in raw), raw
    assert "function handleAuth(" in js and js.count("handleAuth(") >= 3

def test_upload_401_pauses_instead_of_failing():
    js = _src(os.path.join(UI, "ui.js"))
    assert "x.status === 401" in js and "authPause()" in js and "/api/auth/state" in js
    assert "data-retry=" in js
    assert "Please sign in" not in js.split("function upload(")[1].split("function conn(")[0]

def test_upload_thumbnails_are_small_and_revoked():
    js = _src(os.path.join(UI, "ui.js"))
    assert "resizeWidth: 96" in js and "URL.revokeObjectURL(r.thumb)" in js
    assert "row.thumb = isPdf(f)" not in js                      # no full-resolution blob URL per row any more

def test_queue_render_is_debounced_and_keeps_focus():
    js = _src(os.path.join(UI, "ui.js"))
    assert re.search(r'\$\("#fText"\)\.oninput = .*setTimeout\(.*150\)', js)
    assert "vis.includes(" not in js and "focus({preventScroll: true})" in js.split("function renderQueue(")[1].split("\n}\n")[0]

def test_a11y_tabs_toast_ai_box_and_dialogs():
    html, js = _src(os.path.join(UI, "index.html")), _src(os.path.join(UI, "ui.js"))
    assert 'role="tab' not in html and "aria-selected" not in js           # toggle buttons, not tabs without tabpanels
    assert html.count('aria-pressed="true"') == 2
    assert not re.search(r'id="rAI"[^>]*role=', html) and 'role="status">${p.eta' not in js
    assert ".toastbtn\").forEach(b => b.remove())" in js and '"focusin"' in js
    assert not re.search(r"(?<![\w.])confirm\(", _strip_js_comments(js))   # the app's ask() dialog, not window.confirm

def test_polling_skips_work_while_hidden_and_toast_does_not_poll_undo():
    js = _src(os.path.join(UI, "ui.js"))
    for fn in ("async function phoneRefresh()", "async function aiQueueTick()", "async function aiHelperRefresh()"):
        assert "document.hidden" in js.split(fn)[1].split("\n}\n")[0][:300], fn
    toast = js.split("const toast = ")[1].split("\n{ const t")[0]
    assert "if (undo) refreshUndo()" in toast
