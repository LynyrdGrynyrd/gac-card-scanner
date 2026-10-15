"""Audit 2026-10 (docs/AUDIT-2026-10-15.md) P1 backend regression tests: undo sealing, job/throttle pruning, login
throttling, sessions, backups (status, tombstones), staged admin uploads, demo wipe, unique initials, reader limits,
PDF detection, vCard injection."""
import io, json, os, sqlite3, tarfile, threading, time, uuid
import pytest
from test_app import mk


# ---------------------------------------------------------------- undo: a request seals only its own snapshot
def test_seal_only_touches_this_threads_snapshots(env):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store); user = {"id": 1, "username": "adm"}
    other = []
    def other_request():   # another request's snapshot, taken but not yet written
        other.append(ui.snapshot([cid], user, "other request"))
    t = threading.Thread(target=other_request); t.start(); t.join()
    mine = ui.snapshot([cid], user, "mine"); ui._seal()
    snaps = {r["id"]: json.loads(r["snapshot"]) for r in ui.db().execute("SELECT id, snapshot FROM actions WHERE id IN (?,?)", (mine, other[0]))}
    assert "after" in snaps[mine][0] and "after" not in snaps[other[0]][0]


# ---------------------------------------------------------------- memory pruning (F05)
def test_prune_memory_drops_old_finished_jobs_only(env):
    ui = env["ui"]; now = time.time()
    with ui.JLOCK:
        ui.JOBS["old-done"] = {"id": "old-done", "state": "done", "batch": "", "finished": now - 3 * 3600}
        ui.JOBS["new-done"] = {"id": "new-done", "state": "done", "batch": "", "finished": now - 60}
        ui.JOBS["queued"] = {"id": "queued", "state": "queued", "batch": "", "created": now - 5 * 3600}
        ui.CANCELLED_BATCH[("ZZ", "b")] = now - 2 * 3600
    ui.prune_memory(now)
    assert "old-done" not in ui.JOBS and "new-done" in ui.JOBS and "queued" in ui.JOBS and ("ZZ", "b") not in ui.CANCELLED_BATCH
    with ui.JLOCK:
        for k in ("new-done", "queued"): ui.JOBS.pop(k, None)


# ---------------------------------------------------------------- login throttling
def test_wrong_passwords_from_elsewhere_dont_lock_out_the_owner(env, monkeypatch):
    from app import auth
    auth._fails.clear()
    auth._fails[("rev2", "10.0.0.66")] = [time.time()] * 5          # someone on another computer guessed 5 times
    from conftest import Client
    from app import main
    c = Client(main.app)
    assert c.post("/api/auth/login", json={"username": "rev2", "password": "nope-nope-nope"}).status_code == 401   # not 429
    for _ in range(4): c.post("/api/auth/login", json={"username": "rev2", "password": "nope-nope-nope"})
    assert c.post("/api/auth/login", json={"username": "rev2", "password": "nope-nope-nope"}).status_code == 429   # this address: locked
    auth._fails.clear()


def test_unknown_user_costs_a_password_check(env, monkeypatch):
    from app import auth
    seen = []
    real = auth.check_pw
    monkeypatch.setattr(auth, "check_pw", lambda pw, stored: seen.append(stored) or real(pw, stored))
    from conftest import Client
    from app import main
    Client(main.app).post("/api/auth/login", json={"username": "no-such-person", "password": "whatever-123"})
    assert seen == [auth._DUMMY_PW]; auth._fails.clear()


# ---------------------------------------------------------------- sessions
def test_session_touch_is_throttled_and_lifetime_is_capped(env, monkeypatch):
    from app import auth, main
    from conftest import Client
    c = Client(main.app); assert c.post("/api/auth/login", json={"username": "rev", "password": "temp-pass-1234"}).status_code == 200
    h = __import__("hashlib").sha256(c.cookies.get("gac_session").encode()).hexdigest()
    exp = lambda: auth.db().execute("SELECT expires FROM sessions WHERE token=?", (h,)).fetchone()[0]
    e1 = exp(); c.get("/api/cards?batch=x"); assert exp() == e1, "no write on every request"
    auth.db().execute("UPDATE sessions SET created=? WHERE token=?", (time.time() - (auth.SESSION_MAX_HOURS + 1) * 3600, h)).connection.commit()
    assert c.get("/api/cards?batch=x").status_code == 401


# ---------------------------------------------------------------- backups: status, retry, tombstones (F07)
def test_backup_status_reports_last_backup_and_error(tmp_path, monkeypatch):
    from app import backup
    monkeypatch.setenv("GAC_BACKUP_DIR", str(tmp_path))
    (tmp_path / "gac-backup-20260101-023000.tgz").write_bytes(b"x" * 10)
    backup.STATE.update(last_error="disk full", last_error_at=time.time())
    st = backup.status()
    assert st["count"] == 1 and st["last_size"] == 10 and st["last_error"] == "disk full"
    backup.STATE.update(last_error=None, last_error_at=None)


def test_admin_backup_status_endpoint(env):
    st = env["adm"].get("/api/admin/backup-status").json()
    assert {"dir", "count", "last_at", "last_error", "same_disk"} <= set(st)


def test_deleted_card_stays_deleted_after_restoring_an_older_backup(env):
    ui, store, adm = env["ui"], env["store"], env["adm"]
    cid = mk(ui, store, first_name="Restore", last_name="Me")
    created = store.get(cid)["created"]
    assert adm.post(f"/api/admin/cards/{cid}/delete", json={"confirm": cid}).status_code == 200
    assert ui._tombstones()[cid]["created"] == created
    # an older backup brings the card back (same number, same scan time)
    with store.db() as c:
        c.execute("INSERT INTO cards(id,created,status,engine,raw_text,fields,image) VALUES(?,?,?,?,?,?,?)",
                  (cid, created, "pending", "test", "raw", json.dumps({"first_name": "Restore", "last_name": "Me"}), ""))
    assert ui.apply_tombstones() == [cid] and store.get(cid) is None


def test_tombstone_never_hits_a_different_card(env):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store); ui._add_tombstone(cid, created=1.0)   # deleted card #cid was scanned at another time
    assert cid not in ui.apply_tombstones() and store.get(cid)


def test_restore_keeps_newer_tombstones(tmp_path):
    from app import backup
    data = tmp_path / "data"; data.mkdir(); (data / "uploads").mkdir()
    db = data / "cards.db"; c = sqlite3.connect(db); c.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY)"); c.commit(); c.close()
    bk = backup.make(dest=str(tmp_path / "bk"), data=str(data), db=str(db))
    (data / "deleted_cards.json").write_text(json.dumps({"7": {"deleted": 1, "created": 2}}))   # deleted AFTER the backup
    backup.restore(bk, data=str(data), db=str(db))
    assert "7" in json.load(open(data / "deleted_cards.json"))


# ---------------------------------------------------------------- staged admin uploads (F03)
def test_failed_contacts_write_keeps_the_old_file(env, monkeypatch):
    from app import crm_source, ui
    old = os.path.join(crm_source.DATA, "mctrade_contacts.csv"); open(old, "w").write("old file")
    real_open = os.open
    def failing_open(p, *a, **k):
        if str(p).endswith(".uploading"): raise OSError("disk full")
        return real_open(p, *a, **k)
    monkeypatch.setattr(os, "open", failing_open)
    monkeypatch.setattr(ui, "_check_contacts", lambda data, ext: ([{"x": 1}], 1, 0))
    v = env["adm"].get("/api/admin/mctrade-contacts").json().get("version", "")
    with pytest.raises(OSError):
        env["adm"].post(f"/api/admin/mctrade-contacts?expected_version={v}", files={"image": ("c.csv", b"a,b\n1,2\n", "text/csv")})
    monkeypatch.undo()
    assert open(old).read() == "old file"
    os.remove(old)


# ---------------------------------------------------------------- demo wipe (F09)
def test_reset_jobs_hides_old_results_and_blocks_late_cards(env, monkeypatch):
    ui = env["ui"]
    with ui.JLOCK:
        ui.JOBS["gen1-done"] = {"id": "gen1-done", "state": "done", "batch": "b", "file": "secret.jpg", "card": {"id": 1, "name": "Old Person"}}
        ui.JOBS["gen1-reading"] = {"id": "gen1-reading", "state": "reading", "batch": "b", "file": "x.jpg"}
    ui.AI_WAIT[999999] = (1, 1)
    ui.reset_jobs()
    assert "card" not in ui.JOBS["gen1-done"] and ui.JOBS["gen1-done"]["file"] == "" and not ui.AI_WAIT
    monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: {"engine": "t", "text": "", "fields": {"first_name": "Late"}})
    n = env["store"].db().execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    with pytest.raises(ui._Cancelled):   # a worker still reading a pre-wipe job can't create its card afterwards
        ui.ingest(b"x", None, ".jpg", jid="gen1-reading")
    assert env["store"].db().execute("SELECT COUNT(*) FROM cards").fetchone()[0] == n
    with ui.JLOCK:
        for k in ("gen1-done", "gen1-reading"): ui.JOBS.pop(k, None)


def test_demo_blocks_phone_pairing_and_shared_cancel(monkeypatch):
    from app import demo
    import types
    monkeypatch.setenv("GAC_DEMO", "1")
    req = lambda p: types.SimpleNamespace(url=types.SimpleNamespace(path=p), method="POST", headers={})
    assert demo.refuse(req("/api/phone/start")).status_code == 403
    assert demo.refuse(req("/api/jobs/cancel")).status_code == 403


def test_demo_capacity_counts_queued_jobs(env, monkeypatch):
    from app import demo, store
    ui = env["ui"]
    monkeypatch.setenv("GAC_DEMO_MAX_CARDS", str(store.db().execute("SELECT COUNT(*) FROM cards").fetchone()[0] + 3))
    with ui.JLOCK:
        ui.JOBS["cap1"] = {"id": "cap1", "state": "queued"}; ui.JOBS["cap2"] = {"id": "cap2", "state": "reading"}
        ui.JOBS["cap3"] = {"id": "cap3", "kind": "pdf", "state": "splitting", "pages": 5, "page": 1}
    try: assert demo.capacity_left() == 3 - 2 - 4
    finally:
        with ui.JLOCK:
            for k in ("cap1", "cap2", "cap3"): ui.JOBS.pop(k, None)


# ---------------------------------------------------------------- unique initials (F11)
def test_two_people_never_share_initials(env):
    from app import auth
    a = auth.create_user("alex.b" + uuid.uuid4().hex[:4], "Xan Brown", "pass-word-123")
    b = auth.create_user("xavier.b" + uuid.uuid4().hex[:4], "Xavier Beam", "pass-word-123")
    ia, ib = (auth.db().execute("SELECT initials FROM users WHERE id=?", (i,)).fetchone()[0] for i in (a, b))
    assert ia != ib and ib.startswith("X")
    with pytest.raises(ValueError):
        auth.create_user("third" + uuid.uuid4().hex[:4], "Someone Else", "pass-word-123", initials=ia)


def test_existing_duplicate_initials_are_renumbered(tmp_path, monkeypatch):
    from app import auth, store
    monkeypatch.setattr(store, "DB", str(tmp_path / "dup.db"))
    c = store.connect()
    c.execute("""CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, display TEXT, initials TEXT,
      role TEXT DEFAULT 'reviewer', pw TEXT, active INTEGER DEFAULT 1, created REAL, must_change INTEGER DEFAULT 0)""")
    c.execute("INSERT INTO users(username,display,initials) VALUES('alex','Alex Brown','AB'),('amy','Amy Baker','AB')"); c.commit(); c.close()
    ini = [r[0] for r in auth.db().execute("SELECT initials FROM users ORDER BY id")]
    assert ini == ["AB", "AB2"]


# ---------------------------------------------------------------- reader limits are per call (C3)
def test_run_ocr_does_not_swap_module_limits(monkeypatch):
    from app import reader
    seen = []
    before = (reader.MEM_MB, reader.TIMEOUT)
    def fake_call(args, data, key=None, mem_mb=None, timeout=None):
        seen.append((mem_mb, timeout, reader.MEM_MB, reader.TIMEOUT)); return {}
    monkeypatch.setattr(reader, "_call", fake_call)
    reader.run_ocr(b"x")
    assert seen == [(reader.OCR_MEM_MB, reader.OCR_TIMEOUT, *before)], "OCR limits passed per call; module limits untouched"


def test_rss_of_own_process_is_measured():
    from app import reader
    assert reader._rss_mb(os.getpid()) > 10


# ---------------------------------------------------------------- PDF detection (C5)
def test_photo_with_pdf_marker_is_not_a_pdf():
    from app import formats
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (300, 200)).save(b, "JPEG")
    jpg = b.getvalue()[:20] + b"%PDF-1.4" + b.getvalue()[20:]
    assert not formats.is_pdf(jpg) and formats.is_pdf(b"\n\n%PDF-1.7\n...")


# ---------------------------------------------------------------- vCard injection
def test_vcard_values_cannot_break_out_of_their_line():
    from app import export
    f = {"first_name": "Ann", "last_name": "Lee", "company": "Acme", "title": "CFO", "emails": ["a@acme.com"], "website": "acme.com\r\nEND:VCARD",
         "address": "1 Main St\nAkron", "social": ["x\nBEGIN:VCARD"], "phones": [{"type": "work", "number": "330-555-0100\r\nEND:VCARD\r\nBEGIN:VCARD\r\nFN:Forged"}]}
    v = export.to_vcard([{"id": 1, "status": "approved", "fields": f}])
    lines = v.split("\r\n")
    assert lines.count("BEGIN:VCARD") == 1 and lines.count("END:VCARD") == 1 and "FN:Forged" not in lines and all("\n" not in x and "\r" not in x for x in lines)


def test_line_break_in_a_phone_blocks_approval():
    from app import mctrade_export as mx
    assert "phones" in mx.content_problems({"phones": [{"type": "work", "number": "330-555-0100\nEND:VCARD"}]})
    assert "address" not in mx.content_problems({"address": "1 Main St\nAkron, OH"})
