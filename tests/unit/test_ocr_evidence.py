"""Regressions for the hybrid reader, checked at OCR output and pipeline entry points."""
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from app import email_evidence, ocr, pipeline, qr


@pytest.mark.parametrize(("first", "last", "expected"), [
    ("", "", ("Maria", "Delgado")), ("Maria", "", ("Maria", "Delgado")),
    ("Kara", "", ("Kara", "")), ("", "Smith", ("", "Smith"))])
def test_cropped_name_parts_stay_together(monkeypatch, first, last, expected):
    from app import parser
    full = parser.parse("Example Corp")
    crop = dict(full, first_name="Maria", last_name="Delgado")
    full.update(first_name=first, last_name=last)
    monkeypatch.setattr(parser, "parse", lambda text, lines=None: full if text == "full" else crop)
    monkeypatch.setattr(ocr, "run_ocr", lambda data, engine: {"engine": "ppocr+tesseract", "text": "full"})
    monkeypatch.setattr(ocr, "hybrid_ocr", lambda data, crop: {"text": "Maria Delgado"})
    monkeypatch.setattr(qr, "decode", lambda data: [])
    f = pipeline.scan(b"photo", use_vlm=False)["fields"]
    assert (f["first_name"], f["last_name"]) == expected


def test_batch_keeps_empty_pages_and_falls_back_on_mismatch(monkeypatch):
    pages = [Image.new("L", (22, 8)) for _ in range(3)]
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b"one\n\x0c\x0cthree\n"))
    assert ocr._read_batch(pages) == ["one", "", "three"]
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b"one\x0cthree"))
    monkeypatch.setattr(ocr.pytesseract, "image_to_string", lambda im, config: str(next(i for i, p in enumerate(pages) if p is im)))
    assert ocr._read_batch(pages) == ["0", "1", "2"]


def test_boundary_needs_two_readers_and_retains_original_box():
    reads = ["andrew.bernardarodriguez.co", "andrew bernard@rodriquez co"]
    box = [0.2, 0.45, 0.5, 0.12]
    f = {"emails": [], "confidence": {}}
    email_evidence.apply(f, [{"readings": reads, "box": box}], [{"readings": reads, "box": [0, 0, 1, 1]}], "")
    assert f["emails"] == ["andrew.bernard@rodriguez.co"]
    assert f["email_evidence"] == [{"box": box, "readings": reads}]
    assert f["confidence"]["emails"] < 0.6 and "emails" in f["needs_review"]
    unknown = {"emails": []}
    email_evidence.apply(unknown, [], [{"readings": ["andrew.bernardarodriguez.co"]}], "")
    assert not unknown["emails"]


def test_disputed_readings_never_replace_vcard(monkeypatch):
    monkeypatch.setattr(ocr, "run_ocr", lambda data, engine: {
        "engine": "test", "text": "Maria Delgado\nmaria@example.org",
        "lines": [{"text": "maria@example.org", "rel_h": 1, "top": 0.5, "col": 0,
                   "readings": ["maria@example.org", "maria@example.com"]}]})
    monkeypatch.setattr(qr, "decode", lambda data: ["BEGIN:VCARD\nFN:Maria Delgado\nEMAIL:qr@example.net\nEND:VCARD"])
    f = pipeline.scan(b"test", use_vlm=False)["fields"]
    assert f["emails"] == ["qr@example.net"] and "email_evidence" not in f


def test_complete_gate_counts_unknown_names(tmp_path, monkeypatch):
    from bench import eval_bench
    gt = tmp_path / "gt.json"
    gt.write_text("{}")
    assert eval_bench.main([str(gt), str(tmp_path), "--only", "missing.jpg", "--require-complete"]) != 0
