"""Audit 2026-10: consistency/plausibility describe the FINAL values (after the AI merge and post-fixes); VLM_CROP on by default."""
import copy
import pytest
from app import pipeline, ocr, parser, qr


def _base():
    return {"first_name": "Jane", "last_name": "Doe", "credentials": "", "title": "Sales Manager", "company": "Acme Widgets Inc", "department": "",
            "emails": ["john.smith@acmewidgets.com"], "phones": [], "website": "acmewidgets.com", "address": "", "other_address": "", "social": [],
            "confidence": {"name": 0.9, "title": 0.75, "company": 0.6, "department": None, "emails": 0.95, "phones": None, "website": 0.85, "address": None},
            "overall_confidence": 0.8, "needs_review": []}


@pytest.fixture
def fake(monkeypatch):
    text = "John Smith\nSales Manager\nAcme Widgets Inc\njohn.smith@acmewidgets.com\nacmewidgets.com"
    monkeypatch.setattr(ocr, "run_ocr", lambda data, engine=None: {"text": text, "engine": "tesseract", "lines": None})
    monkeypatch.setattr(qr, "decode", lambda data: [])
    monkeypatch.setattr(parser, "parse", lambda t, meta=None: copy.deepcopy(_base()))
    monkeypatch.setenv("CONSISTENCY", "1"); monkeypatch.setenv("REALCARD_POSTFIX", "1")


def test_flags_recomputed_after_vlm_merge(fake):
    f = pipeline.scan(b"x", use_vlm=False, vlm_result={"first_name": "John", "last_name": "Smith"})["fields"]
    assert (f["first_name"], f["last_name"]) == ("John", "Smith")
    assert not any(fl["code"] == "email_name" for fl in f["consistency"]), "stale 'email doesn't match the name' flag"
    assert "name" not in f["needs_review"] and f["confidence"]["name"] >= 0.6
    assert not any(s.get("field") == "name" for s in f.get("suggestions") or [])


def test_rules_only_adjustments_do_not_stack(fake):
    f = pipeline.scan(b"x", use_vlm=False)["fields"]
    assert f["confidence"]["company"] == 0.7      # email domain matches the company once (+0.1), not twice
    assert any(fl["code"] == "email_name" for fl in f["consistency"]) and "name" in f["needs_review"]


def test_vlm_crop_default_on(monkeypatch):
    from app import vlm
    seen = []
    def prep(data, side, crop): seen.append(crop); raise RuntimeError("stop")
    monkeypatch.setattr(vlm, "_prep", prep)
    monkeypatch.delenv("VLM_CROP", raising=False)
    with pytest.raises(RuntimeError): vlm.extract(b"x")
    monkeypatch.setenv("VLM_CROP", "0")
    with pytest.raises(RuntimeError): vlm.extract(b"x")
    assert seen == [True, False]
