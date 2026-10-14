"""Audit-merge regression tests (qa/AUDIT-MERGE.md): queue thumbnails, scan concurrency cap, name-lexicon guard."""
import io, os, threading, time
from PIL import Image

def _photo(ui, w=1600, h=1000):
    im = Image.new("RGB", (w, h), (240, 240, 240))
    for x in range(0, w, 40): im.paste((20, 20, 20), (x, 0, x + 8, h))
    name = f"t_{os.getpid()}_{time.time_ns()}.jpg"; im.save(os.path.join(ui.UP, name), "JPEG", quality=90); return name

def test_thumbnail_small_cached_and_deleted(env):
    ui, adm = env["ui"], env["adm"]; name = _photo(ui)
    r = adm.get(f"/img/{name}?w=160"); assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    im = Image.open(io.BytesIO(r.content)); assert im.size[0] == 160 and len(r.content) < 20_000
    assert len(r.content) < len(adm.get(f"/img/{name}").content) / 5
    t = os.path.join(ui.THUMBS, f"{name}.160.webp"); assert os.path.isfile(t)
    m = os.path.getmtime(t); adm.get(f"/img/{name}?w=150"); assert os.path.getmtime(t) == m, "cached, size snapped to 160"
    os.remove(os.path.join(ui.UP, name))
    r = adm.get(f"/img/{name}?w=160"); assert r.headers["content-type"].startswith("image/svg"); assert not os.path.exists(t)

def test_thumbnail_needs_sign_in(env):
    from fastapi.testclient import TestClient
    from app import main
    assert TestClient(main.app).get("/img/x.jpg?w=160", follow_redirects=False).status_code in (302, 303, 307, 401, 403)

def test_scan_semaphore_caps_concurrency(env, monkeypatch):
    ui = env["ui"]; from app import pipeline
    live = {"n": 0, "max": 0}; lk = threading.Lock()
    def fake(*a, **k):
        with lk: live["n"] += 1; live["max"] = max(live["max"], live["n"])
        time.sleep(0.05)
        with lk: live["n"] -= 1
        return {}
    monkeypatch.setattr(pipeline, "scan", fake)
    ts = [threading.Thread(target=ui.scan_limited, args=(b"",)) for _ in range(6)]; [t.start() for t in ts]; [t.join() for t in ts]
    assert live["max"] == ui.SCAN_WORKERS

def test_api_scan_uses_limiter():
    import inspect
    from app import main
    assert "scan_limited" in inspect.getsource(main._ingest)

def test_name_lexicon_present_and_declared():
    from app import parser
    assert parser.NAME_LEXICON_ERROR is None and parser._GD is not None
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    assert "gender-guesser" in open(os.path.join(root, "requirements.txt")).read()
    assert "gender-guesser==" in open(os.path.join(root, "requirements.lock.txt")).read()
    assert "GPL-3.0" in open(os.path.join(root, "THIRD-PARTY-NOTICES.md")).read()
