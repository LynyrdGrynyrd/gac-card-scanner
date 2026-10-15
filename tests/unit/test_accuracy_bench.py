"""Audit 2026-10 (Codex F12): the benchmark comparator is honest, reports skipped photos and can gate on a minimum."""
import importlib.util, json, os
import pytest

_P = os.path.join(os.path.dirname(__file__), "..", "..", "bench", "eval_bench.py")


@pytest.fixture(scope="module")
def eb():
    spec = importlib.util.spec_from_file_location("eval_bench_t", _P); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def test_unicode_names_do_not_collapse(eb):
    assert eb.n("山田") != eb.n("佐藤") and eb.n("山田") != ""
    assert eb.n("Straße") == eb.n("STRASSE") and eb.n("ＡＢＣ") == eb.n("abc")
    assert eb.n("www.Acme.com") == eb.n("acme.com")


def test_phone_comparison_full_digits(eb):
    assert eb.ph_eq("330-555-0101", "+1 (330) 555-0101")
    assert not eb.ph_eq("+44 20 7946 0958", "+49 20 7946 0958")      # same 9-digit tail, different country
    assert not eb.ph_eq("330-555-0101", "331-555-0101")
    assert eb.ph_eq("330-555-0101 x12", "+1 330 555 0101 ext. 12") and not eb.ph_eq("330-555-0101 x12", "330-555-0101")


def test_emails_exact_and_lists_one_to_one(eb):
    g = {"emails": ["Jo.Smith@acme.com"], "phones": [{"type": "work", "number": "330-555-0101"}, {"type": "mobile", "number": "330-555-0101"}]}
    f = {"emails": ["jo.smith@acme.com"], "phones": [{"type": "work", "number": "330-555-0101"}, {"type": "work", "number": "330-555-0102"}]}
    r = eb.compare(f, g)
    assert r["emails"] and not r["phones"], "one found number must not satisfy two expected ones"
    assert not eb.compare({"emails": ["josmith@acme.com"], "phones": []}, {"emails": ["jo.smith@acme.com"]})["emails"]


def test_missing_photos_reported_and_thresholds(eb, tmp_path, monkeypatch, capsys):
    from app import pipeline
    (tmp_path / "a.jpg").write_bytes(b"x")
    gt = {"a.jpg": {"first_name": "Jo", "last_name": "Smith", "emails": ["jo@acme.com"], "phones": []}, "gone.jpg": {"first_name": "X"}}
    p = tmp_path / "gt.json"; p.write_text(json.dumps(gt))
    monkeypatch.setattr(pipeline, "scan", lambda data, use_vlm=None, vlm_result=None: {"fields": {
        "first_name": "Jo", "last_name": "Smyth", "emails": ["jo@acme.com"], "phones": [], "confidence": {}}})
    assert eb.main([str(p), str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "SKIPPED 1 card(s): photo missing" in out and "gone.jpg" in out
    assert eb.main([str(p), str(tmp_path), "--min", "first_name=1", "--min", "last_name=1"]) == 1
    assert "BELOW THRESHOLD: last_name 0 < 1" in capsys.readouterr().out
    assert eb.main([str(p), str(tmp_path), "--min-overall", "95"]) == 1
    assert eb.main([str(p), str(tmp_path), "--min-overall", "80"]) == 0
    assert eb.main([str(p), str(tmp_path), "--only=gone.jpg"]) == 2
