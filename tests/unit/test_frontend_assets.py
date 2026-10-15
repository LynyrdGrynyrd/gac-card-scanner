"""audit 2026-10 P2: the page scripts are fingerprinted as a whole (any script under static/ui changes the version) and
revalidated on every load (Cache-Control: no-cache + ETag), because ES-module imports carry no ?v= (an import map would
have to be an inline script, which the CSP script-src 'self' blocks)."""
import os

UI = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui"))
def _src(p): return open(p, encoding="utf-8").read()

def test_static_ui_scripts_are_revalidated_and_fingerprinted():
    from fastapi.testclient import TestClient
    from app.main import app
    from app import auth
    c = TestClient(app)
    for u in ("/static/ui/main.js", "/static/ui/core/api.js", "/static/ui/views/review.js", "/static/ui/login.js", "/static/ui/desktop.js", "/static/ui/ui.css"):
        r = c.get(u); assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache", (u, r.headers.get("cache-control"))
        assert r.headers.get("etag")
        assert c.get(u, headers={"If-None-Match": r.headers["etag"]}).status_code == 304

def test_any_script_under_static_ui_changes_the_version(tmp_path, monkeypatch):
    from app import auth
    ui = tmp_path / "ui"; (ui / "views").mkdir(parents=True)
    for n in ("ui.css", "login.js", "desktop.js"): (ui / n).write_text(_src(os.path.join(UI, n)))
    (ui / "views" / "page.js").write_text("export const a = 1;\n")
    monkeypatch.setattr(auth, "STATIC", str(tmp_path)); monkeypatch.setattr(auth, "_AV", {})
    v = auth.asset_version(); assert v == auth.asset_version()
    st = os.stat(ui / "views" / "page.js")
    (ui / "views" / "page.js").write_text("export const a = 2;\n"); os.utime(ui / "views" / "page.js", (st.st_atime + 5, st.st_mtime + 5))
    assert auth.asset_version() != v                                   # a nested module counts, not just ui.js/login.js
    (ui / "help.html").write_text("x")
    v2 = auth.asset_version(); (ui / "help.html").write_text("y"); assert auth.asset_version() == v2   # HTML help pages don't
