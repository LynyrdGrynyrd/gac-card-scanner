"""Audit 2026-10 (Codex F10): merge.merge() is pure; it never edits the caller's fields (shared phone list/dicts)."""
import copy
from app import merge


def _fields():
    return {"first_name": "Mary", "last_name": "Jones", "title": "Sales Manager", "company": "Acme Widgets Inc", "department": "",
            "emails": ["mjones@acmewidgets.com"], "website": "acmewidgets.com", "address": "", "social": [],
            "phones": [{"type": "work", "number": "330-555-0101", "valid": True}],
            "confidence": {"name": 0.9, "phones": 0.9, "emails": 0.95}, "needs_review": []}


OCR = "Mary Jones\nSales Manager\nAcme Widgets Inc\nC 330-555-0101\nF 330-555-0102\nmjones@acmewidgets.com\nacmewidgets.com"


def test_merge_does_not_mutate_input():
    f = _fields(); before = copy.deepcopy(f)
    v = {"first_name": "Mary", "last_name": "Jones", "phones": [{"type": "mobile", "number": "330-555-0101"}, {"type": "fax", "number": "330-555-0102"}]}
    g = merge.merge(f, v, OCR)
    assert f == before, "the input fields were edited in place"
    assert g["phones"] is not f["phones"]


def test_phone_type_correction_is_a_visible_difference():
    f = _fields()
    g = merge.merge(f, {"phones": [{"type": "mobile", "number": "(330) 555-0101"}]}, OCR)
    assert f["phones"][0]["type"] == "work" and g["phones"][0]["type"] == "mobile"
    assert g.get("vlm_fields", {}).get("phone_types") == "vlm"
    assert f["phones"] != g["phones"]   # ui's diff (old vs merged) can now see the AI's phone suggestion


def test_vlm_added_phone_not_appended_to_input():
    f = _fields()
    g = merge.merge(f, {"phones": [{"type": "fax", "number": "330-555-0102"}]}, OCR)
    assert len(f["phones"]) == 1 and len(g["phones"]) == 2
