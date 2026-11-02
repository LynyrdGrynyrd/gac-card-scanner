"""RapidOCR 3.x (PP-OCRv6 small) as the PP-OCR detector: bundled models only, never a download, the 1.2.x result shape."""
import os
import numpy as np
from PIL import Image
from app import ocr

CARD = os.path.join(os.path.dirname(__file__), "..", "cards", "card1_left.jpg")


def test_bundled_models_exist():
    import rapidocr
    md = os.path.join(os.path.dirname(rapidocr.__file__), "models")
    for f in ocr.RAPID_MODELS: assert os.path.isfile(os.path.join(md, f)), f"{f} is not in the rapidocr wheel any more: pick the new name"


def test_engine_never_downloads(monkeypatch):
    """The scanner promises that nothing leaves the computer: building the engine and reading a card must not touch the network."""
    import requests
    from rapidocr.utils import download_file
    def no_net(*a, **k): raise AssertionError(f"network access attempted: {a[:1]}")
    monkeypatch.setattr(download_file.DownloadFile, "run", classmethod(lambda cls, *a, **k: no_net(*a)))
    monkeypatch.setattr(requests.Session, "request", no_net)
    monkeypatch.setattr(requests, "get", no_net)
    monkeypatch.setattr(ocr, "_RAPID", None)   # build a fresh engine under the patches
    res, _ = ocr._rapid()(np.array(Image.open(CARD).convert("RGB")))
    assert res and all(len(r) == 3 and len(r[0]) == 4 and isinstance(r[1], str) for r in res)
    assert any("summitvalleybank" in r[1].lower().replace(" ", "") for r in res), [r[1] for r in res]


def test_hybrid_segments_still_read_the_card():
    segs = ocr.hybrid_segments(Image.open(CARD))
    txt = " ".join(s["text"] for s in segs).lower()
    assert "delgado" in txt and "summitvalleybank" in txt.replace(" ", "")
