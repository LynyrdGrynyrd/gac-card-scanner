"""Audit 2026-10 P2: one transaction per save, the ui.py split keeps the public names, startup side effects only when
served, /api/scan uses the shared ingest."""
import json, threading
import pytest
from test_app import mk


def test_tx_rolls_back_everything_on_an_exception(env):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store)
    with pytest.raises(RuntimeError):
        with store.tx():
            store.update(cid, fields=store.get(cid)["fields"] | {"title": "Half-saved"})
            ui.set_meta(cid, crm_action="create_new"); ui.log(cid, "T", "edited", detail={"x": 1})
            raise RuntimeError("boom")
    assert store.get(cid)["fields"]["title"] == "CFO" and not ui.meta(cid).get("crm_action")
    assert not [h for h in ui.history(cid) if h["action"] == "edited"]


def test_tx_commits_once_at_the_end_and_other_threads_wait(env):
    ui, store = env["ui"], env["store"]
    cid = mk(ui, store); seen = []
    with store.tx():
        ui.set_meta(cid, crm_action="update_existing")     # inner `with db() as c:` must not commit yet
        t = threading.Thread(target=lambda: seen.append(store.connect().execute("SELECT crm_action FROM card_meta WHERE card_id=?", (cid,)).fetchone()[0]))
        t.start(); t.join()
        assert ui.meta(cid)["crm_action"] == "update_existing", "the same thread sees its own writes"
    assert seen == [None], "another connection doesn't see uncommitted writes"
    assert ui.meta(cid)["crm_action"] == "update_existing"


def test_failed_save_leaves_no_half_written_card(env, monkeypatch):
    ui, store, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, store)
    real_log = ui.log
    def failing_log(c_, rv, action, *a, **k):
        if action == "edited": raise RuntimeError("disk full while writing history")
        return real_log(c_, rv, action, *a, **k)
    monkeypatch.setattr(ui, "log", failing_log)
    f = store.get(cid)["fields"] | {"title": "Chief Financial Officer"}
    with pytest.raises(RuntimeError):
        rev.post(f"/api/cards/{cid}", json={"fields": f})
    monkeypatch.undo()
    assert store.get(cid)["fields"]["title"] == "CFO", "the card change was rolled back with the failed history row"


def test_split_modules_keep_ui_names(env):
    ui = env["ui"]
    for name in ("hard_delete", "purge", "apply_tombstones", "build_export", "do_export", "export_versions", "safe_cell",
                 "audit", "upload_template", "template_version", "contacts_version", "remove_photo", "drop_thumbs", "THUMBS"):
        assert hasattr(ui, name), name
    paths = [r.path for r in ui.router.routes]
    assert paths.index("/api/export/check") < paths.index("/api/export/{kind}")


def test_importing_main_has_no_side_effects(monkeypatch):
    import importlib, sys
    from app import ai_helper, demo
    called = []
    monkeypatch.setattr(ai_helper, "autostart", lambda: called.append("ai"))
    monkeypatch.setattr(demo, "start", lambda: called.append("demo"))
    monkeypatch.setenv("GAC_DEMO", "1")
    saved = sys.modules.pop("app.main")
    try:
        importlib.import_module("app.main")
        assert called == [], called
    finally:
        sys.modules["app.main"] = saved


def test_api_scan_cards_get_hash_and_history(env, monkeypatch):
    ui, store = env["ui"], env["store"]
    from app import main
    monkeypatch.setattr(ui, "scan_limited", lambda *a, **k: {"engine": "t", "text": "x", "fields": {"first_name": "Api", "last_name": "Scan", "emails": [], "phones": []}})
    cid = main._ingest(b"\xff\xd8\xffphoto-bytes", "auto")
    assert ui.meta(cid)["sha256"] and ui.meta(cid)["filename"] == "api-scan.jpg"
    assert any(h["action"] == "scanned" for h in ui.history(cid))
