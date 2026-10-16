"""v0.4 #1 tap-to-zoom: OCR keeps where each field sits; boxes are display-only (never change values or rules)."""
import io
from PIL import Image, ImageDraw, ImageFont
from app import boxes, pipeline, ui

import os
FONT = os.path.join(os.path.dirname(__file__), "..", "fonts", "OpenSans.ttf")


def _font(sz):
    try: return ImageFont.truetype(FONT, sz)
    except Exception: return ImageFont.load_default(sz)


def _card():
    im = Image.new("RGB", (1400, 800), "white"); d = ImageDraw.Draw(im)
    spots = {"name": (80, 120, "Petra Lindqvist", 64), "title": (80, 220, "Head of Procurement", 40), "company": (80, 40, "Fjordlight Optics", 44),
             "phones.0": (80, 470, "+1 555 014 7788", 38), "emails.0": (80, 560, "petra@fjordlight.example", 38), "website": (800, 660, "fjordlight.example", 36)}
    for k, (x, y, t, s) in spots.items(): d.text((x, y), t, fill="black", font=_font(s))
    b = io.BytesIO(); im.save(b, "JPEG", quality=92); return b.getvalue(), {k: (x / 1400, y / 800) for k, (x, y, _, _) in spots.items()}


def test_locate_matches_lines():
    lines = [dict(text="Petra Lindqvist", box=[.1, .1, .3, .05]), dict(text="T +1 (555) 014-7788", box=[.1, .6, .3, .04]),
             dict(text="12 Harbour Way", box=[.5, .7, .3, .04]), dict(text="Oslo 0150", box=[.5, .75, .2, .04])]
    f = {"first_name": "Petra", "last_name": "Lindqvist", "phones": [{"type": "work", "number": "+1 555 014 7788"}], "address": "12 Harbour Way, Oslo 0150", "company": "Nowhere Ltd"}
    b = boxes.locate(f, lines)
    assert b["name"] == [.1, .1, .3, .05] and b["phones.0"] == [.1, .6, .3, .04]
    assert b["address"] == [.5, .7, .3, .09]          # two lines joined
    assert "company" not in b                          # no confident match: no box (the UI shows the whole photo)
    assert boxes.locate(f, []) == {} and boxes.locate({}, lines) == {}


def test_scan_keeps_boxes_on_made_up_card():
    data, where = _card()
    f = pipeline.scan(data, use_vlm=False)["fields"]
    bx = f["boxes"]; hits = 0
    for k, (x, y) in where.items():
        if k in bx and abs(bx[k][0] - x) < 0.04 and abs(bx[k][1] - y) < 0.06: hits += 1
    assert hits >= 5, (bx, where)
    for b in bx.values(): assert all(0 <= v <= 1 for v in b)


def test_boxes_not_writable_from_the_form():
    f = {"first_name": "A", "boxes": {"name": [0, 0, 1, 1]}}
    ui._apply_fields(f, {"boxes": {"name": [.5, .5, .1, .1]}, "first_name": "A"})
    assert f["boxes"] == {"name": [0, 0, 1, 1]}
