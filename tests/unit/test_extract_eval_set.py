"""bench/extract_eval_set.py: approved cards -> eval_bench ground truth + a per-field correction report, read-only."""
import itertools, json, os, sys, time, uuid
import pytest
from test_app import mk

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "bench"))
import extract_eval_set as X   # noqa: E402


_PEOPLE = itertools.product(["Marta", "Owen", "Priya", "Tomas", "Greta", "Henry", "Lucia", "Felix"],
                            ["Kowalski", "Brennan", "Okafor", "Lindqvist", "Moreau", "Halvorsen", "Castellano", "Nakamura"])


def _card(ui, store, batch, **f):
    first, last = next(_PEOPLE)   # a person no other test uses: approving a look-alike of another test's card is refused
    dom = f"{last.lower()}{first.lower()}.com"   # (409), and made-up letter strings read as "misread" to the plausibility checks
    f = {"first_name": first, "last_name": last, "emails": [f"{first.lower()}@{dom}"], "company": f"{last} Partners", "website": dom} | f
    cid = mk(ui, store, **f)
    img = f"t-{uuid.uuid4().hex}.jpg"; p = os.path.join(ui.UP, img); os.makedirs(ui.UP, exist_ok=True)
    with open(p, "wb") as fh: fh.write(b"\xff\xd8\xff" + os.urandom(64))
    os.utime(p, (time.time() - 5 * 86400,) * 2)   # an older photo: the copy must keep this date (retention clock)
    with store.db() as c: c.execute("UPDATE cards SET image=? WHERE id=?", (img, cid))
    ui.set_meta(cid, batch=batch, batch_label=batch, sha256=uuid.uuid4().hex)
    return cid


def _run(tmp_path, batch, *extra):
    from app import store, ui
    out = tmp_path / "out"
    rc = X.main(["--db", store.DB, "--uploads", ui.UP, "--out", str(out), "--batch", batch, *extra])
    return rc, out


def test_extracts_edited_unchanged_and_bulk_cards(env, tmp_path, capsys):
    ui, store, rev = env["ui"], env["store"], env["rev"]
    b = "ev-" + uuid.uuid4().hex[:6]
    edited = _card(ui, store, b)
    f = store.get(edited)["fields"] | {"title": "Chief Financial Officer"}
    assert rev.post(f"/api/cards/{edited}", json={"fields": f, "status": "approved", "crm_action": "create_new"}).status_code == 200
    same = _card(ui, store, b)
    assert rev.post(f"/api/cards/{same}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    bulk = _card(ui, store, b)
    assert rev.post("/api/cards-bulk", json={"ids": [bulk], "status": "approved"}).status_code == 200
    pending = _card(ui, store, b)
    rc, out = _run(tmp_path, b)
    assert rc == 0
    gt = json.load(open(out / "gt.json"))
    by_id = {v["card_id"]: (k, v) for k, v in gt.items()}
    assert set(by_id) == {edited, same, bulk}, "pending cards are not ground truth"
    k, g = by_id[edited]
    assert g["title"] == "Chief Financial Officer" and g["corrected_fields"] == ["title"]
    assert set(g["cat"]) == {"pilot", "reviewed", "edited"}
    assert set(by_id[same][1]["cat"]) == {"pilot", "reviewed", "unchanged"} and by_id[same][1]["corrected_fields"] == []
    assert set(by_id[bulk][1]["cat"]) == {"pilot", "bulk", "unchanged"}
    assert g["phones"] and set(g["phones"][0]) == {"type", "number"}, "eval_bench's phone shape"
    src = os.path.join(ui.UP, store.get(edited)["image"])
    assert abs(os.path.getmtime(out / k) - os.path.getmtime(src)) < 2, "the copy keeps the photo's date"
    rep = json.load(open(out / "field_report.json"))
    assert rep["cards"] == 3 and rep["fields"]["title"]["fixed"] == 1 and rep["fields"]["title"]["cards"] == 3
    assert "Approved cards usable as test examples: 3" in capsys.readouterr().out
    assert pending not in by_id


def test_reviewed_only_dry_run_and_skips(env, tmp_path, capsys):
    ui, store, rev = env["ui"], env["store"], env["rev"]
    b = "ev-" + uuid.uuid4().hex[:6]
    bulk = _card(ui, store, b)
    rev.post("/api/cards-bulk", json={"ids": [bulk], "status": "approved"})
    gone = _card(ui, store, b)
    rev.post(f"/api/cards/{gone}", json={"status": "approved", "crm_action": "create_new"}); ui.set_meta(gone, image_deleted=time.time())
    back = _card(ui, store, b)
    rev.post(f"/api/cards/{back}", json={"status": "approved", "crm_action": "create_new"}); ui.set_meta(back, back_image="x-back.jpg")
    rc, out = _run(tmp_path, b, "--reviewed-only", "--dry-run")
    o = capsys.readouterr().out
    assert rc == 0 and not out.exists(), "a dry run copies nothing"
    assert "usable as test examples: 0" in o and "photo deleted" in o and "back photo" in o and "--reviewed-only" in o


def test_reextract_replaces_entry_and_keeps_others(env, tmp_path):
    ui, store, rev = env["ui"], env["store"], env["rev"]
    b = "ev-" + uuid.uuid4().hex[:6]
    cid = _card(ui, store, b, first_name="Hal", last_name="Iv", emails=["hal@iv.com"])
    rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"})
    out = tmp_path / "out"; out.mkdir()
    (out / "gt.json").write_text(json.dumps({"card999999_abc.jpg": {"first_name": "Keep"}, f"card{cid}_old.jpg": {"first_name": "Old"}}))
    (out / f"card{cid}_old.jpg").write_bytes(b"old")
    _run(tmp_path, b)
    gt = json.load(open(out / "gt.json"))
    assert "card999999_abc.jpg" in gt and f"card{cid}_old.jpg" not in gt and not (out / f"card{cid}_old.jpg").exists()
    assert [v["first_name"] for k, v in gt.items() if k.startswith(f"card{cid}_")] == ["Hal"]


def test_database_is_opened_read_only(env, tmp_path):
    from app import store
    con = X.sqlite3.connect(f"file:{os.path.abspath(store.DB)}?mode=ro", uri=True)
    with pytest.raises(X.sqlite3.OperationalError): con.execute("UPDATE cards SET note='x'")
    con.close()


def test_refuses_tracked_folder_in_repo(env, tmp_path):
    from app import store, ui
    with pytest.raises(SystemExit):
        X.main(["--db", store.DB, "--uploads", ui.UP, "--out", os.path.join(ROOT, "docs", "pilot-cards")])
    assert not X.inside_repo_unignored(os.path.join(ROOT, "bench", "corrections"))
    assert not X.inside_repo_unignored(str(tmp_path))
    assert X.inside_repo_unignored(os.path.join(ROOT, "docs"))


def test_default_out_is_the_apps_corrections_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("CORRECTIONS_DIR", raising=False)
    assert X.default_out(str(tmp_path)) == os.path.join(str(tmp_path), "corrections")
    assert X.default_out(os.path.join(X.ROOT, "data")) == os.path.join(X.ROOT, "bench", "corrections")


def test_output_scores_with_eval_bench(env, tmp_path, monkeypatch):
    """The written gt.json is accepted by bench/eval_bench.py's comparer (same record shape)."""
    import eval_bench
    ui, store, rev = env["ui"], env["store"], env["rev"]
    b = "ev-" + uuid.uuid4().hex[:6]
    cid = _card(ui, store, b, first_name="Ivy", last_name="Jo", emails=["ivy@jo.com"])
    rev.post(f"/api/cards/{cid}", json={"status": "approved", "crm_action": "create_new"})
    _, out = _run(tmp_path, b)
    g = next(iter(json.load(open(out / "gt.json")).values()))
    r = eval_bench.compare(store.get(cid)["fields"], g)
    assert all(r.values()), r
