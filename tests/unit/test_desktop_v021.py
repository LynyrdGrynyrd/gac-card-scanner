import importlib, os, subprocess, sys

def _csp(env):
    code = "import app.auth as a, app.phone as p; print(a.SEC_HEADERS['Content-Security-Policy']); print('PHONE', getattr(p,'PHONE_CSP', ''))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, **env}, cwd=os.path.join(os.path.dirname(__file__), "..", ".."))
    assert out.returncode == 0, out.stderr
    return out.stdout

def test_desktop_csp_allows_eval_for_pywebview():
    assert "'unsafe-eval'" in _csp({"GAC_DESKTOP": "1"}).splitlines()[0]

def test_server_csp_has_no_eval():
    assert "'unsafe-eval'" not in _csp({"GAC_DESKTOP": "0"}).splitlines()[0]

def test_launcher_enables_downloads():
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "packaging", "launcher.py")).read()
    assert 'settings["ALLOW_DOWNLOADS"] = True' in src

def test_demo_pages_carry_asset_fingerprint(tmp_path):
    # v0.2.1: the demo /ui page used ui.js?v=8 while the API sent the real fingerprint, so ui.js reloaded in a loop
    from app import demo, auth
    p = os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui", "index.html")
    assert f"ui.js?v={auth.asset_version()}" in demo.page(p).body.decode()

def test_open_url_only_opens_local_static_paths(monkeypatch):
    import importlib.util, webbrowser
    spec = importlib.util.spec_from_file_location("launcher", os.path.join(os.path.dirname(__file__), "..", "..", "packaging", "launcher.py"))
    L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
    opened = []; monkeypatch.setattr(webbrowser, "open", opened.append)
    api = L.Api("http://127.0.0.1:1234/ui", "/tmp")
    assert api.open_url("/static/ui/GAC-Card-Scanner-Help-Guide.pdf") is True
    for bad in ("https://evil.example/x.pdf", "//evil.example/x", "/static/../app/auth.py", "/api/export/xlsx", "javascript:alert(1)"):
        assert api.open_url(bad) is False
    assert opened == ["http://127.0.0.1:1234/static/ui/GAC-Card-Scanner-Help-Guide.pdf"]
