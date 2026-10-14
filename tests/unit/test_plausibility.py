import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app import plausibility as P
def codes(f): return {s["code"] for s in P.check(f)}
BASE = {"first_name": "Jane", "last_name": "Doe", "title": "Sales Manager", "company": "Acme Widgets Inc",
        "emails": ["jane.doe@acmewidgets.com"], "website": "www.acmewidgets.com",
        "phones": [{"type": "work", "number": "(330) 555-0100"}], "address": "100 Main St, Akron, OH 44308"}
def test_clean_card_no_suggestions(): assert P.check(dict(BASE)) == []
def test_tld():
    s = P.check({**BASE, "emails": ["jane.doe@acmewidgets.con"]})
    assert any(x["code"] == "email_tld" and x["suggestion"] == "jane.doe@acmewidgets.com" for x in s)
def test_provider(): assert "email_provider" in codes({**BASE, "emails": ["jdoe@gmial.com"]})
def test_format(): assert "email_format" in codes({**BASE, "emails": ["jane doe@acme.com"]})
def test_email_web_picks_company_side():
    s = [x for x in P.check({**BASE, "website": "www.acmewidqets.com"}) if x["code"] == "email_web"]
    assert s and s[0]["field"] == "website" and s[0]["suggestion"] == "acmewidgets.com"
def test_email_name(): assert "email_name" in codes({**BASE, "last_name": "Dot"})
def test_area_state(): assert "area_state" in codes({**BASE, "phones": [{"type": "work", "number": "(312) 555-0199"}]})
def test_area_state_cell_ignored(): assert "area_state" not in codes({**BASE, "phones": [{"type": "mobile", "number": "(312) 555-0199"}]})
def test_invalid_phone(): assert "phone_invalid" in codes({**BASE, "phones": [{"type": "work", "number": "(116) 555-0100"}]})
def test_name_title_word(): assert "name_sanity" in codes({**BASE, "first_name": "President"})
def test_name_digits(): assert "name_sanity" in codes({**BASE, "last_name": "D0e1"})
def test_title_holds_phone(): assert "title_sanity" in codes({**BASE, "title": "Manager 330-555-0100"})
def test_company_is_name(): assert "company_sanity" in codes({**BASE, "company": "Jane Doe"})
def test_suggest_only_never_mutates():
    f = {**BASE, "emails": ["jane.doe@acmewidgets.con"], "confidence": {"emails": 0.9}}; before = repr(f)
    P.check(f); assert repr(f) == before
    P.apply(f); assert f["emails"] == ["jane.doe@acmewidgets.con"] and f["confidence"] == {"emails": 0.9}
def test_intl_no_false_flags():
    assert P.check({"first_name": "Antonio", "last_name": "Mosca", "title": "Pittore", "phones": [{"type": "work", "number": "32402"}],
                    "address": "Via Savenella, 40, Bologna", "emails": [], "website": ""}) == []
