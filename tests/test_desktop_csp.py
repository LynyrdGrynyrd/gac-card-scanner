import importlib, os, subprocess, sys

def _csp(env):
    code = "import app.auth as a, app.phone as p; print(a.SEC_HEADERS['Content-Security-Policy']); print('PHONE', getattr(p,'PHONE_CSP', ''))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, **env}, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert out.returncode == 0, out.stderr
    return out.stdout

def test_desktop_csp_allows_eval_for_pywebview():
    assert "'unsafe-eval'" in _csp({"GAC_DESKTOP": "1"}).splitlines()[0]

def test_server_csp_has_no_eval():
    assert "'unsafe-eval'" not in _csp({"GAC_DESKTOP": "0"}).splitlines()[0]

def test_launcher_enables_downloads():
    src = open(os.path.join(os.path.dirname(__file__), "..", "packaging", "launcher.py")).read()
    assert 'settings["ALLOW_DOWNLOADS"] = True' in src
