"""Audit 2026-10 recognition-accuracy probes (docs/AUDIT-2026-10-15.md, P1 'Parser bugs'): each was high-confidence and unflagged."""
from app import parser as P, merge


def _p(*lines): return P.parse("\n".join(lines))


def test_title_after_comma_ceo():
    f = _p("John Smith, CEO", "Acme Widgets Inc", "jsmith@acmewidgets.com", "330-555-0101")
    assert (f["first_name"], f["last_name"]) == ("John", "Smith")
    assert f["title"] == "CEO" and not f["credentials"]


def test_title_after_comma_keeps_real_credentials():
    f = _p("Jane Doe, CPA, MBA", "Partner", "Doe Accounting LLC", "jdoe@doeaccounting.com")
    assert (f["first_name"], f["last_name"], f["title"]) == ("Jane", "Doe", "Partner") and f["credentials"] == "CPA, MBA"


def test_slash_separated_phone_labels():
    f = _p("Mary Jones", "Sales Manager", "Acme Widgets Inc", "P 330-555-0101 / F 330-555-0102", "mjones@acmewidgets.com")
    assert [(p["type"], p["number"]) for p in f["phones"]] == [("work", "330-555-0101"), ("fax", "330-555-0102")]


def test_slash_labels_mobile_then_office():
    f = _p("Mary Jones", "Sales Manager", "Acme Widgets Inc", "Cell: 330-555-0103 / Office: 330-555-0101", "mjones@acmewidgets.com")
    assert [(p["type"], p["number"]) for p in f["phones"]] == [("mobile", "330-555-0103"), ("work", "330-555-0101")]


def test_floor_line_stays_in_address():
    f = _p("Mary Jones", "Sales Manager", "Acme Widgets Inc", "50 S Main St", "3rd Floor", "Akron, OH 44308", "mjones@acmewidgets.com")
    assert f["address"] == "50 S Main St, 3rd Floor, Akron, OH 44308"


def test_trailing_label_letter_stripped_from_street():
    f = _p("Mary Jones", "Sales Manager", "Acme Widgets Inc", "50 S Main St T", "Akron, OH 44308", "mjones@acmewidgets.com")
    assert f["address"] == "50 S Main St, Akron, OH 44308"


def test_comma_reversed_name():
    f = _p("Smith, John", "Director of Sales", "Acme Widgets Inc", "330-555-0101")
    assert (f["first_name"], f["last_name"]) == ("John", "Smith")


def test_lowercase_particle_names_kept():
    f = _p("Maria de la Cruz", "Manager", "Acme Widgets Inc", "330-555-0101")
    assert (f["first_name"], f["last_name"]) == ("Maria", "de la Cruz")
    f = _p("Pieter van der Meer", "Director", "Acme Widgets Inc", "pvandermeer@acmewidgets.com")
    assert (f["first_name"], f["last_name"]) == ("Pieter", "van der Meer")


def test_vlm_compound_surname_not_cut():
    f = {"first_name": "", "last_name": "", "emails": [], "phones": [], "confidence": {}}
    g = merge.merge(f, {"first_name": "Pieter", "last_name": "van der Meer"}, "Pieter van der Meer\nDirector")
    assert (g["first_name"], g["last_name"]) == ("Pieter", "van der Meer")


def test_email_rejects_appended_label_word():
    f = _p("Tom Hill", "Owner", "Hill Construction", "tom@hillco.com.tel 330-555-0101")
    assert f["emails"] == ["tom@hillco.com"]
    assert _p("Tom Hill", "tom@hillco.co.uk")["emails"] == ["tom@hillco.co.uk"]
    assert _p("Tom Hill", "tom@mail.hillco.com")["emails"] == ["tom@mail.hillco.com"]


def test_website_new_gtlds():
    f = _p("Ray Builds", "Owner", "raybuilds.tech", "330-555-0101")
    assert f["website"] == "raybuilds.tech" and f["company"] != "raybuilds.tech" and f["emails"] == []
    assert _p("Ann Law", "Attorney", "www.annlaw.legal")["website"] == "www.annlaw.legal"
    assert _p("Ann Law", "Attorney", "annlaw.legal")["website"] == "annlaw.legal"


def test_website_not_from_plain_words():
    f = _p("Mary Jones", "Sales Manager", "Acme Widgets Inc", "mjones@acmewidgets.com", "Dr. No.Kidding")
    assert f["website"] == ""


def test_two_people_on_one_card_flagged():
    f = _p("John & Jane Smith", "Owners", "Smith Bakery", "330-555-0101")
    assert "name" in f["needs_review"] and (f["confidence"].get("name") or 0) <= 0.5
    assert f["last_name"] != "Bakery"
