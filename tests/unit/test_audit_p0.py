"""Audit 2026-10 (docs/AUDIT-2026-10-15.md) P0 regression tests: data integrity, privacy clean-up, admin saves, backups,
DNS-rebinding and body-size guards."""
import io, os, sqlite3, threading, time, types, uuid
import pytest
from PIL import Image
from test_app import mk


def _approved(ui, store, batch):
    cid = mk(ui, store, first_name="Exp", last_name=uuid.uuid4().hex[:6].capitalize(), emails=[f"{uuid.uuid4().hex[:8]}@acme.com"])
    ui.set_meta(cid, batch=batch, batch_label=batch); store.update(cid, status="approved", reviewer="AA"); return cid


# ---------------------------------------------------------------- P0-1 set_meta writes only the given columns
def test_set_meta_never_writes_back_stale_columns(env, monkeypatch):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store); ui.set_meta(cid, crm_action="create_new")
    stale = dict(ui.meta(cid)) | {"crm_action": None, "batch": "stale"}
    monkeypatch.setattr(ui, "meta", lambda _cid: dict(stale))   # a writer holding an old copy of the row
    ui.set_meta(cid, ai_status="done")
    monkeypatch.undo()
    m = ui.meta(cid)
    assert m["ai_status"] == "done" and m["crm_action"] == "create_new" and m["batch"] == "b1"


def test_set_meta_creates_row_and_ignores_unknown_keys(env):
    ui, store = env["ui"], env["store"]
    cid = store.add("test", "raw", {"first_name": "Zed"}, "")
    ui.set_meta(cid, batch="x", not_a_column=1)
    assert ui.meta(cid)["batch"] == "x" and ui.meta(cid)["archived"] == 0


# ---------------------------------------------------------------- P0-4 / P0-6 database set-up
def test_wal_busy_timeout_and_indexes(env):
    from app import store
    c = store.db()
    assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"ix_hist_card", "ix_meta_batch", "ix_meta_sha", "ix_sessions_user"} <= names


def test_card_ids_never_reused_after_delete(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    cid = mk(ui, store)
    assert adm.post(f"/api/admin/cards/{cid}/delete", json={"confirm": cid}).status_code == 200
    assert mk(ui, store) > cid


def test_old_database_migrates_to_autoincrement(tmp_path, monkeypatch):
    from app import store
    p = str(tmp_path / "old.db"); c = sqlite3.connect(p)
    c.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY, created REAL, status TEXT DEFAULT 'pending', engine TEXT, raw_text TEXT, "
              "fields TEXT, image TEXT, reviewer TEXT, note TEXT, decided REAL)")
    c.execute("INSERT INTO cards(id, fields) VALUES(3, '{}')")
    c.execute("CREATE TABLE card_history(id INTEGER PRIMARY KEY, card_id INTEGER, ts REAL, reviewer TEXT, action TEXT, "
              "from_status TEXT, to_status TEXT, detail TEXT)")
    c.execute("INSERT INTO card_history(card_id, action) VALUES(9, 'deleted_on_request')")   # card 9 was deleted earlier
    c.commit(); c.close()
    monkeypatch.setattr(store, "DB", p)
    assert "AUTOINCREMENT" in store.db().execute("SELECT sql FROM sqlite_master WHERE name='cards'").fetchone()[0].upper()
    assert store.get(3)["fields"] == {}
    assert store.add("t", "", {}, "") == 10, "the counter starts above every id ever used, deleted ones included"


# ---------------------------------------------------------------- P0-3 the AI worker survives an error
def test_ai_worker_keeps_running_after_an_error(env, monkeypatch):
    ui = env["ui"]; calls = []; second = threading.Event(); park = threading.Event()
    def step():
        calls.append(1)
        if len(calls) == 1: raise sqlite3.OperationalError("database is locked")
        second.set(); park.wait()   # the loop came back for the next card: park this test thread
    monkeypatch.setattr(ui, "_ai_worker_step", step); monkeypatch.setattr(ui.time, "sleep", lambda s: None)
    threading.Thread(target=ui._ai_worker, daemon=True).start()
    assert second.wait(5) and len(calls) == 2


# ---------------------------------------------------------------- P0-2 / F01 / F02 exports
def _export(adm, batch, **extra):
    vs = adm.get(f"/api/export/check?status=approved_new&batch={batch}").json()["versions"]
    return adm.get("/api/export/csv", params={"status": "approved_new", "batch": batch, **{"seen_" + k: v for k, v in vs.items()}, **extra})


def test_export_id_is_this_exports_row(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    b = "p0-eid"; _approved(ui, store, b)
    r = _export(adm, b); assert r.status_code == 200, r.text
    row = ui.db().execute("SELECT id, filename FROM exports WHERE id=?", (int(r.headers["X-Export-Id"]),)).fetchone()
    assert row and row["filename"] in r.headers["content-disposition"]


def test_edit_during_build_refuses_and_marks_nothing(env, monkeypatch):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    b = "p0-drift"; cid = _approved(ui, store, b)
    real = ui.build_export
    def build_and_edit(*a, **k):
        res = real(*a, **k)
        c = store.get(cid); store.update(cid, fields=c["fields"] | {"title": "Edited meanwhile"})   # a reviewer saves now
        return res
    monkeypatch.setattr(ui, "build_export", build_and_edit)
    n_files = len(os.listdir(ui.EXP))
    r = _export(adm, b)
    assert r.status_code == 409 and r.json()["need"] == "stale_review"
    assert not ui.meta(cid).get("exported") and len(os.listdir(ui.EXP)) == n_files
    monkeypatch.setattr(ui, "build_export", real)
    r = _export(adm, b); assert r.status_code == 200 and ui.meta(cid).get("exported")


def test_card_approved_after_signoff_is_not_exported(env, monkeypatch):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    b = "p0-signoff"; _approved(ui, store, b); late = []
    real = ui._export_claim
    def claim_then_approve(*a, **k):   # a card is approved after the sign-off check passed, before the set is re-read
        r = real(*a, **k); late.append(_approved(ui, store, b)); return r
    monkeypatch.setattr(ui, "_export_claim", claim_then_approve)
    r = _export(adm, b)
    assert r.status_code == 409 and r.json()["need"] == "stale_review" and not ui.meta(late[0]).get("exported")


# ---------------------------------------------------------------- P0-5 / F08 permanent delete
def _photo(ui, suffix=""):
    name = uuid.uuid4().hex + suffix + ".jpg"
    Image.new("RGB", (800, 500), (200, 200, 200)).save(os.path.join(ui.UP, name), "JPEG"); return name


def test_delete_removes_both_sides_and_thumbnails_and_logs(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    front, back = _photo(ui), _photo(ui, "_back")
    cid = store.add("test", "raw", {"first_name": "Del"}, front); ui.set_meta(cid, batch="p0-del", back_image=back)
    for n in (front, back):
        for w in ui.THUMB_SIZES: assert adm.get(f"/img/{n}?w={w}").status_code == 200
    assert adm.post(f"/api/admin/cards/{cid}/delete", json={"confirm": cid}).status_code == 200
    left = [f for f in os.listdir(ui.THUMBS) + os.listdir(ui.UP) if front in f or back in f]
    assert left == []
    acts = [h["action"] for h in ui.history(cid)]
    assert "deleted_on_request" in acts
    from app import auth
    assert auth.db().execute("SELECT 1 FROM auth_log WHERE event LIKE ?", (f"deleted card #{cid} on request%",)).fetchone()
    ui.remove_photo(front); ui.remove_photo(back)   # repeating the clean-up is safe


def test_retention_removes_back_thumbnails_and_orphan_thumbnails(env):
    ui, store = env["ui"], env["store"]
    from app import auth
    front, back = _photo(ui), _photo(ui, "_back")
    cid = store.add("test", "raw", {"first_name": "Old"}, front); ui.set_meta(cid, batch="p0-ret", back_image=back)
    store.update(cid, status="approved", reviewer="AA")
    ui.db().execute("UPDATE cards SET created=? WHERE id=?", (time.time() - 400 * 86400, cid)).connection.commit()
    for n in (front, back): ui._thumb(os.path.join(ui.UP, n), 160)
    orphan = os.path.join(ui.THUMBS, "gone_" + uuid.uuid4().hex + ".jpg.160.webp"); open(orphan, "wb").write(b"x")
    auth.set_setting("retention_enabled", "1")
    ui.purge()
    assert not [f for f in os.listdir(ui.THUMBS) if front in f or back in f] and not os.path.exists(orphan)


# ---------------------------------------------------------------- P0-7 admin saves: validate first, then write
def test_edit_user_refusal_changes_nothing(env):
    adm = env["adm"]
    from conftest import Client
    from app import main
    me = adm.get("/api/auth/state").json()["user"]
    r = adm.post(f"/api/admin/users/{me['id']}", json={"password": "a-brand-new-pass-1", "active": False})
    assert r.status_code == 422
    c = Client(main.app); assert c.post("/api/auth/login", json={"username": "adm", "password": "admin-pass-123"}).status_code == 200
    assert adm.get("/api/auth/state").json()["user"], "the admin's own session is still alive"


def test_settings_bad_value_saves_nothing(env):
    adm = env["adm"]
    from app import auth
    before = auth.get_setting("image_retention_days")
    shown = adm.get("/api/admin/settings").json()
    r = adm.post("/api/admin/settings", json={"image_retention_days": "77", "phone_format": "nonsense",
                                               "_seen": {"image_retention_days": shown["image_retention_days"], "phone_format": shown["phone_format"]}})
    assert r.status_code == 422 and auth.get_setting("image_retention_days") == before


# ---------------------------------------------------------------- P0-8 / P0-9 backups
def test_backup_location_and_contents(tmp_path, monkeypatch):
    from app import backup
    monkeypatch.delenv("GAC_BACKUP_DIR", raising=False)
    monkeypatch.setenv("GAC_DATA_DIR", str(tmp_path / "GAC Card Scanner"))
    assert backup.backup_dir() == str(tmp_path / "GAC Card Scanner Backups")
    data = tmp_path / "data"; (data / "uploads").mkdir(parents=True); (data / "ai-helper").mkdir(); (data / "webview").mkdir()
    (data / "uploads" / "p.jpg").write_bytes(b"photo"); (data / "ai-helper" / "model.gguf").write_bytes(b"x" * 100)
    (data / "webview" / "Cookies").write_bytes(b"session"); (data / "app.log").write_text("log")
    db = data / "cards.db"; c = sqlite3.connect(db); c.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY)"); c.commit(); c.close()
    import tarfile
    names = tarfile.open(backup.make(dest=str(tmp_path / "bk"), data=str(data), db=str(db))).getnames()
    assert "data/uploads/p.jpg" in names
    assert not [n for n in names if "ai-helper" in n or "webview" in n or n.endswith("app.log")]


def test_tests_do_not_write_into_the_repo_data_folder(env):
    ui = env["ui"]; repo_data = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    assert not os.path.abspath(ui.UP).startswith(repo_data) and not os.path.abspath(ui.EXP).startswith(repo_data)


# ---------------------------------------------------------------- P0-11 DNS rebinding
def _req(host, ip="127.0.0.1"):
    return types.SimpleNamespace(headers={"host": host}, client=types.SimpleNamespace(host=ip))


@pytest.mark.parametrize("host,ok", [("localhost:8765", True), ("127.0.0.1:8765", True), ("[::1]:8765", True),
                                     ("192.168.1.20:8765", True), ("app.localhost", True),
                                     ("attacker.example:8765", False), ("127.0.0.1.nip.io", False), ("", False)])
def test_trusted_host(host, ok, monkeypatch):
    from app import auth
    monkeypatch.delenv("GAC_ALLOWED_HOSTS", raising=False)
    assert auth.trusted_host(_req(host)) is ok


def test_allowed_hosts_env(monkeypatch):
    from app import auth
    monkeypatch.setenv("GAC_ALLOWED_HOSTS", "scanner.office.example")
    assert auth.trusted_host(_req("scanner.office.example:443")) and not auth.trusted_host(_req("other.example"))
    assert not auth._loopback_trusted(_req("attacker.example", "127.0.0.1"))


def test_setup_refused_through_a_foreign_host_name(tmp_path, monkeypatch):
    from app import store, main
    from conftest import Client
    monkeypatch.setattr(store, "DB", str(tmp_path / "fresh.db"))
    c = Client(main.app)
    body = {"username": "evil", "display": "Evil", "password": "evil-pass-12345"}
    r = c.post("/api/auth/setup", json=body, headers={"Host": "attacker.example:8765", "Origin": "http://attacker.example:8765"})
    assert r.status_code == 403
    assert c.get("/api/auth/state", headers={"Host": "attacker.example"}).json()["setup_allowed"] is False


# ---------------------------------------------------------------- P0-12 body size counted, not declared
def test_chunked_upload_over_the_limit_is_refused(env, monkeypatch):
    from app import auth
    monkeypatch.setattr(auth, "MAX_BODY", 50_000)
    def chunks():
        for _ in range(40): yield b"x" * 4096
    r = env["rev"].post("/api/jobs", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 413


def test_body_limit_middleware_counts_bytes():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.bodylimit import BodyLimit
    a = FastAPI()
    @a.post("/echo")
    async def echo(request: Request): return {"n": len(await request.body())}
    a.add_middleware(BodyLimit, limit=1000)
    c = TestClient(a)
    assert c.post("/echo", content=b"x" * 900).json() == {"n": 900}
    assert c.post("/echo", content=(b"x" * 300 for _ in range(5))).status_code == 413
    assert c.post("/echo", content=b"x" * 2000).status_code == 413


# ---------------------------------------------------------------- C2 in-process decoding
def test_prepare_for_ocr_only_opens_plain_raster_formats():
    from app import formats
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"
    assert formats.prepare_for_ocr(eps) == eps
    big = io.BytesIO(); Image.new("1", (8000, 8000)).save(big, "PNG")   # 64 MP: above the decode cap
    assert formats.prepare_for_ocr(big.getvalue()) == big.getvalue(), "left alone for _check_image to refuse"
