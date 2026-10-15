import os, sys, pytest
os.environ.setdefault("OCR_CHILD", "0")   # round 21: unit tests patch pipeline.scan in-process; test_r21 covers the child
os.environ["GAC_ALLOW_REMOTE_SETUP"] = "1"; os.environ.setdefault("GAC_ALLOWED_HOSTS", "testserver"); os.environ["VLM_URL"] = "http://127.0.0.1:9"
import tempfile as _tf   # round 7: the tests never read or replace the data folder's real template / contacts export
# audit 2026-10 P0-10: ALL runtime data (photos, exports, inbox, job records, thumbnails) goes to a temp folder, set before
# any app module is imported, so the tests no longer write into the repo's data/ (and no longer need "run from a copy")
os.environ["GAC_DATA_DIR"] = _tf.mkdtemp(prefix="gac-data-")
os.environ["MCTRADE_TEMPLATE"] = os.path.join(_tf.mkdtemp(prefix="gac-tpl-"), "mctrade_template.xlsx")
sys.path.insert(0, os.path.dirname(__file__))
from fastapi.testclient import TestClient

class Client(TestClient):
    """Behaves like the browser page: same-origin Origin header and the per-session CSRF token on state changes."""
    def request(self, method, url, **kw):
        h = dict(kw.pop("headers", None) or {})
        # round 7: saves need the card version (optimistic locking); fill in the current one like the page does, unless
        # the test sends "_nov": True (then the body goes as-is, to test the refusal)
        import re as _re
        js = kw.get("json")
        if method.upper() == "POST" and isinstance(js, dict):
            path = str(url).split("?")[0]
            if js.get("_nov"): kw["json"] = {k: v for k, v in js.items() if k != "_nov"}
            else:
                m_ = _re.fullmatch(r"(?:http://testserver)?/api/cards/(\d+)(/ai-decide)?", path)
                if m_ and "version" not in js:
                    g = super().request("GET", f"/api/cards/{m_.group(1)}")
                    if g.status_code == 200: kw["json"] = dict(js, version=g.json().get("version"))
                if path.endswith("/api/cards-bulk") and "versions" not in js:
                    vs = {}
                    for i in js.get("ids") or []:
                        g = super().request("GET", f"/api/cards/{i}")
                        if g.status_code == 200: vs[str(i)] = g.json().get("version")
                    kw["json"] = dict(js, versions=vs)
        # round 16: settings saves need "_seen" and template/contacts changes need expected_version (no blind overwrite);
        # like the Settings page, fill in what is current unless the test sends "_nov" (then it tests the refusal)
        if method.upper() == "POST":
            import urllib.parse as _up
            path = str(url).split("?")[0].replace("http://testserver", "")
            if path == "/api/admin/settings" and isinstance(kw.get("json"), dict) and "_seen" not in kw["json"] and not (isinstance(js, dict) and js.get("_nov")):
                g = super().request("GET", "/api/admin/settings")
                if g.status_code == 200: kw["json"] = dict(kw["json"], _seen={k: v for k, v in g.json().items() if not k.startswith("_")})
            if isinstance(kw.get("json"), dict) and "_nov" in kw["json"] and path == "/api/admin/settings": kw["json"] = {k: v for k, v in kw["json"].items() if k != "_nov"}
            info = {"/api/admin/mctrade-template": "/api/admin/mctrade-template", "/api/admin/mctrade-template/revert": "/api/admin/mctrade-template",
                    "/api/admin/mctrade-contacts": "/api/admin/mctrade-contacts", "/api/admin/mctrade-contacts/remove": "/api/admin/mctrade-contacts"}.get(path)
            qd = dict(_up.parse_qsl(str(url).split("?", 1)[1])) if "?" in str(url) else {}
            prm = kw.get("params") or {}
            dat = kw.get("data") if isinstance(kw.get("data"), dict) else {}
            if info and "expected_version" not in qd and "expected_version" not in prm and "expected_version" not in dat and not qd.get("_nov") and not prm.get("_nov"):
                g = super().request("GET", info)
                if g.status_code == 200: kw["params"] = dict(qd, **prm, expected_version=g.json().get("version")); url = str(url).split("?")[0]
            if "_nov" in prm: kw["params"] = {k: v for k, v in prm.items() if k != "_nov"}
        # round 17: a real export needs the sign-off versions (seen_*), like the Export page sends them from /api/export/check;
        # fill them in unless the test asks for the refusal (_nov=1 in the query)
        if method.upper() == "GET":
            import urllib.parse as _up, re as _re2
            path = str(url).split("?")[0].replace("http://testserver", "")
            qd = dict(_up.parse_qsl(str(url).split("?", 1)[1], keep_blank_values=True)) if "?" in str(url) else {}
            qd.update(kw.pop("params", None) or {})
            if _re2.fullmatch(r"/api/export/(csv|xlsx|vcf)", path) and qd.get("preview") not in ("1", "true") and not any(k.startswith("seen_") for k in qd):
                if qd.pop("_nov", None) is None:
                    g = super().request("GET", "/api/export/check", params={k: qd[k] for k in ("status", "batch") if k in qd})
                    if g.status_code == 200 and isinstance(g.json(), dict) and g.json().get("versions"):
                        qd.update({"seen_" + k: v for k, v in g.json()["versions"].items()})
            if qd: kw["params"] = qd; url = str(url).split("?")[0]
        if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            h.setdefault("Origin", "http://testserver")
            if self.cookies.get("gac_csrf"): h.setdefault("X-CSRF-Token", self.cookies.get("gac_csrf"))
            if h.get("Origin") == "": h.pop("Origin")
        return super().request(method, url, headers=h, **kw)

@pytest.fixture(scope="session")
def env(tmp_path_factory):
    from app import store
    tmp = tmp_path_factory.mktemp("db"); store.DB = str(tmp / "t.db")
    from app import crm_source; crm_source.DATA = str(tmp)   # uploaded MC Trade contacts go to the temp folder
    from app import main, ui
    c = Client(main.app)
    r = c.post("/api/auth/setup", json={"username": "adm", "display": "Ada Admin", "password": "admin-pass-123"}); assert r.status_code == 200
    from app import auth as _auth; _auth.set_setting("mctrade_updates_enabled", "1")   # older tests use 'update existing' (round 7: admin switch)
    r = c.post("/api/admin/users", json={"username": "rev", "display": "Rita Rev", "password": "temp-pass-1234"}); assert r.status_code == 200, r.text
    r = c.post("/api/admin/users", json={"username": "rev2", "display": "Ray Two", "password": "temp-pass-1234"}); assert r.status_code == 200
    rc = Client(main.app); assert rc.post("/api/auth/login", json={"username": "rev", "password": "temp-pass-1234"}).status_code == 200
    r2 = Client(main.app); assert r2.post("/api/auth/login", json={"username": "rev2", "password": "temp-pass-1234"}).status_code == 200
    return {"adm": c, "rev": rc, "rev2": r2, "ui": ui, "store": store}
