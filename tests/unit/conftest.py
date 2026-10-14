import os, sys, pytest
os.environ["GAC_ALLOW_REMOTE_SETUP"] = "1"; os.environ["VLM_URL"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.dirname(__file__))
from fastapi.testclient import TestClient

class Client(TestClient):
    """Behaves like the browser page: same-origin Origin header and the per-session CSRF token on state changes."""
    def request(self, method, url, **kw):
        h = dict(kw.pop("headers", None) or {})
        if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            h.setdefault("Origin", "http://testserver")
            if self.cookies.get("gac_csrf"): h.setdefault("X-CSRF-Token", self.cookies.get("gac_csrf"))
            if h.get("Origin") == "": h.pop("Origin")
        return super().request(method, url, headers=h, **kw)

@pytest.fixture(scope="session")
def env(tmp_path_factory):
    from app import store
    tmp = tmp_path_factory.mktemp("db"); store.DB = str(tmp / "t.db")
    from app import main, ui
    c = Client(main.app)
    r = c.post("/api/auth/setup", json={"username": "adm", "display": "Ada Admin", "password": "admin-pass-123"}); assert r.status_code == 200
    r = c.post("/api/admin/users", json={"username": "rev", "display": "Rita Rev", "password": "temp-pass-1234"}); assert r.status_code == 200, r.text
    r = c.post("/api/admin/users", json={"username": "rev2", "display": "Ray Two", "password": "temp-pass-1234"}); assert r.status_code == 200
    rc = Client(main.app); assert rc.post("/api/auth/login", json={"username": "rev", "password": "temp-pass-1234"}).status_code == 200
    r2 = Client(main.app); assert r2.post("/api/auth/login", json={"username": "rev2", "password": "temp-pass-1234"}).status_code == 200
    return {"adm": c, "rev": rc, "rev2": r2, "ui": ui, "store": store}
