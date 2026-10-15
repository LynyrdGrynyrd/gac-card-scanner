"""audit 2026-10: desktop bridge (packaging/launcher.py) helpers used by desktop.js: per-file save results, folder-pick caps
(PDF/HEIC included), and app.log rotation."""
import base64, importlib.util, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def _launcher():
    spec = importlib.util.spec_from_file_location("launcher_t", os.path.join(ROOT, "packaging", "launcher.py"))
    L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L); return L

class _Win:
    def __init__(self, answer): self.answer, self.calls = answer, []
    def create_file_dialog(self, kind, **kw):
        self.calls.append((kind, kw))
        if isinstance(self.answer, Exception): raise self.answer
        return self.answer

def test_save_file_reports_saved_cancelled_and_error(tmp_path):
    L = _launcher(); api = L.Api("http://127.0.0.1:1/ui", str(tmp_path)); data = base64.b64encode(b"hello").decode()
    dest = tmp_path / "out.csv"
    api.win = _Win((str(dest),))
    r = api.save_file("../../evil/out.csv", data)
    assert r == {"path": str(dest), "name": "out.csv"} and dest.read_bytes() == b"hello"
    assert api.win.calls[0][1]["save_filename"] == "out.csv"                      # no path parts from the page
    api.win = _Win(None)
    assert api.save_file("x.xlsx", data) == {"cancelled": True, "name": "x.xlsx"}
    api.win = _Win(str(tmp_path / "missing-dir" / "x.xlsx"))                       # the write fails
    r = api.save_file("x.xlsx", data); assert r["name"] == "x.xlsx" and r["error"] and "path" not in r
    api.win = _Win(RuntimeError("dialog broke"))
    assert api.save_file("y.vcf", data) == {"error": "dialog broke", "name": "y.vcf"}

def test_folder_pick_includes_pdf_and_heic_and_skips_hidden(tmp_path):
    L = _launcher()
    (tmp_path / "a.jpg").write_bytes(b"j"); (tmp_path / "b.PDF").write_bytes(b"%PDF-1.4"); (tmp_path / "c.heic").write_bytes(b"h")
    (tmp_path / "notes.txt").write_text("x"); (tmp_path / ".hidden.jpg").write_bytes(b"x")
    (tmp_path / ".git").mkdir(); (tmp_path / ".git" / "z.jpg").write_bytes(b"x")
    (tmp_path / "sub").mkdir(); (tmp_path / "sub" / "d.png").write_bytes(b"p")
    r = L.collect_folder(str(tmp_path))
    assert [f["name"] for f in r["files"]] == ["a.jpg", "b.PDF", "c.heic", "d.png"]
    types = {f["name"]: f["type"] for f in r["files"]}
    assert types["b.PDF"] == "application/pdf" and types["c.heic"] == "image/heic"
    assert base64.b64decode(r["files"][1]["b64"]) == b"%PDF-1.4"
    assert r["skipped_big"] == 0 and r["capped"] is False

def test_folder_pick_caps_file_size_total_bytes_and_count(tmp_path):
    L = _launcher()
    for i in range(6): (tmp_path / f"p{i}.jpg").write_bytes(b"x" * 100)
    (tmp_path / "huge.jpg").write_bytes(b"x" * 1000)
    r = L.collect_folder(str(tmp_path), max_files=500, max_file=500, max_total=350)
    assert r["skipped_big"] == 1 and r["capped"] is True and len(r["files"]) == 3 and r["bytes"] == 300
    r = L.collect_folder(str(tmp_path), max_files=2, max_file=5000, max_total=10 ** 6)
    assert len(r["files"]) == 2 and r["capped"] is True
    assert L.PICK_MAX_FILE == 25 * 1024 * 1024 and L.PICK_MAX_TOTAL == 300 * 1024 * 1024

def test_pick_folder_cancelled_returns_no_files(tmp_path):
    L = _launcher(); api = L.Api("http://127.0.0.1:1/ui", str(tmp_path)); api.win = _Win(None)
    assert api.pick_folder() == {"files": []}
    (tmp_path / "a.jpg").write_bytes(b"j"); api.win = _Win([str(tmp_path)])
    assert [f["name"] for f in api.pick_folder()["files"]] == ["a.jpg"]

def test_app_log_is_rotated_when_too_big(tmp_path):
    L = _launcher(); log = tmp_path / "app.log"
    L._rotate_log(str(log), limit=10)                       # no log yet: nothing happens
    assert not log.exists() and not (tmp_path / "app.log.1").exists()
    log.write_text("small"); L._rotate_log(str(log), limit=10)
    assert log.read_text() == "small"
    log.write_text("x" * 50); (tmp_path / "app.log.1").write_text("older")
    L._rotate_log(str(log), limit=10)
    assert not log.exists() and (tmp_path / "app.log.1").read_text() == "x" * 50
    assert L.LOG_MAX == 5 * 1024 * 1024

def test_desktop_js_reports_per_file_results():
    js = open(os.path.join(ROOT, "app", "static", "ui", "desktop.js"), encoding="utf-8").read()
    ui = open(os.path.join(ROOT, "app", "static", "ui", "ui.js"), encoding="utf-8").read()
    assert "window.gacSaveBlob" in js and "cancelled" in js and "skipped_big" in js and "gacDownload" not in js
    assert "gacSaveBlob" in ui and "Your browser is downloading" in ui
    assert "to Downloads" not in ui                          # no blanket "saved to Downloads" claim any more
