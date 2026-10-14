"""Round-15 real-card accuracy rules: app/postfix.py clean-ups and the app/merge.py department / phone / name rules.
SYNTHETIC examples only (invented names, companies, numbers) - no real card data in tests."""
from app import postfix, merge
from app.merge import _dept_ok

# ---------------- postfix
def test_postal_code_not_phone():
    f = postfix.apply({"address": "1-2-3 Sample-cho, Tokyo 〒100-0001", "phones": [{"number": "100-0001", "valid": False}, {"number": "+81 3 5555 0100", "valid": True}]})
    assert [p["number"] for p in f["phones"]] == ["+81 3 5555 0100"]

def test_duplicate_phone_keeps_extension():
    f = postfix.apply({"phones": [{"number": "(317) 555-0100"}, {"number": "(317) 555-0100 ext 42"}]})
    assert [p["number"] for p in f["phones"]] == ["(317) 555-0100 ext 42"]

def test_exact_duplicate_phone_once():
    f = postfix.apply({"phones": [{"number": "317-555-0100"}, {"number": "317 555 0100"}]})
    assert len(f["phones"]) == 1

def test_title_echoing_name_and_company():
    f = postfix.apply({"first_name": "Pat", "last_name": "Example", "company": "Acme Widgets", "title": "Pat Example, Lead Engineer, Acme Widgets"})
    assert f["title"] == "Lead Engineer"

def test_title_left_alone():
    f = postfix.apply({"first_name": "Pat", "last_name": "Example", "company": "Acme", "title": "Lead Engineer, Coatings"})
    assert f["title"] == "Lead Engineer, Coatings"

def test_email_domain_snapped_to_website():
    f = postfix.apply({"website": "www.acmewidgets.com", "emails": ["pat@acmewidqets.com"]})
    assert f["emails"] == ["pat@acmewidgets.com"]

def test_email_domain_other_tld_untouched():
    f = postfix.apply({"website": "acmewidgets.com", "emails": ["pat@acmewidgets.org"]})
    assert f["emails"] == ["pat@acmewidgets.org"]

def test_website_leading_pipe_letter():
    f = postfix.apply({"website": "lacme.com", "emails": ["pat@acme.com"]})
    assert f["website"] == "acme.com"

def test_logo_company_from_email_domain():
    f = postfix.apply({"company": "ZORBEX", "emails": ["pat@zorbix.com"]})
    assert f["company"] == "Zorbix"

def test_address_drops_company_prefix():
    f = postfix.apply({"company": "Acme Widgets", "address": "Acme Widgets, 12 Sample St, Springfield, IN 46000"})
    assert f["address"] == "12 Sample St, Springfield, IN 46000"

def test_email_lookalike_to_name_pattern():
    f = postfix.apply({"first_name": "Dana", "last_name": "Mirel", "emails": ["dmirei@example.com", "clmirel@example.com"]})
    assert f["emails"] == ["dmirel@example.com", "dmirel@example.com"]

def test_email_lookalike_never_deletes_letters():
    # unrelated local parts (initials, doubled letters) stay as printed
    f = postfix.apply({"first_name": "Dana", "last_name": "Mirel", "emails": ["DDMirel@example.com", "dkmirel@example.com"]})
    assert f["emails"] == ["DDMirel@example.com", "dkmirel@example.com"]

def test_eszett_restored_from_email():
    f = postfix.apply({"first_name": "Uwe", "last_name": "StraBner", "emails": ["uwe.strassner@example.de"]})
    assert f["last_name"] == "Straßner"

def test_street_number_letter_o():
    f = postfix.apply({"address": "1O Sample Ave, Springfield"})
    assert f["address"] == "10 Sample Ave, Springfield"
    assert postfix.apply({"address": "Office 5, Oak Rd"})["address"] == "Office 5, Oak Rd"

# ---------------- merge: department guard
def test_dept_guard_rejects():
    assert not _dept_ok("CTO / Owner", "", "")                               # role word
    assert not _dept_ok("Engineered for curiosity", "", "")                   # tagline
    assert not _dept_ok("Widgets", "", "Acme Widgets")                         # part of company
    assert not _dept_ok("Coatings", "", "", "Senior Chemist - Coatings")       # r15: suffix of the model's title
    assert not _dept_ok("Pumps, Valves, and Seals Design", "", "")             # r15: "A, B, and C" capability line

def test_dept_guard_accepts():
    assert _dept_ok("Research and Development", "Chemist", "Acme")
    assert _dept_ok("Planning, Testing and Support Services", "Manager", "Acme")         # list without ", and" stays a department
    assert _dept_ok("Coatings", "", "", "Senior Chemist")
    assert _dept_ok("Coatings", "", "", "Coatings")                            # equal to title is handled elsewhere

def _rules(**kw):
    base = {"first_name": "Pat", "last_name": "Example", "title": "", "company": "Acme", "department": "", "emails": [], "phones": [], "website": "", "address": "", "confidence": {}}
    base.update(kw); return base

def test_merge_fills_supported_department():
    ocr = "Pat Example\nChemist\nResearch and Development\nAcme"
    f = merge.merge(_rules(title="Chemist"), {"first_name": "Pat", "last_name": "Example", "title": "Chemist", "department": "Research and Development", "company": "Acme"}, ocr)
    assert f["department"] == "Research and Development"

def test_merge_department_title_suffix_rejected():
    ocr = "Pat Example\nSenior Chemist - Coatings\nAcme"
    f = merge.merge(_rules(), {"first_name": "Pat", "last_name": "Example", "title": "Senior Chemist - Coatings", "department": "Coatings", "company": "Acme"}, ocr)
    assert f["department"] == ""

def test_merge_capability_line_rejected():
    ocr = "Pat Example\nOwner\nPumps, Valves, and Seals Design\nAcme"
    f = merge.merge(_rules(title="Owner"), {"first_name": "Pat", "last_name": "Example", "title": "Owner", "department": "Pumps, Valves, and Seals Design", "company": "Acme"}, ocr)
    assert f["department"] == ""

def test_merge_unsupported_department_rejected():
    f = merge.merge(_rules(title="Chemist"), {"first_name": "Pat", "last_name": "Example", "title": "Chemist", "department": "Quantum Logistics", "company": "Acme"}, "Pat Example\nChemist\nAcme")
    assert f["department"] == ""

def test_merge_international_phone_kept():
    ocr = "Pat Example\nAcme\nTel +49 30 5555 0100"
    f = merge.merge(_rules(), {"first_name": "Pat", "last_name": "Example", "phones": [{"number": "+49 30 5555 0100", "type": "work"}]}, ocr)
    assert any(p["number"].replace(" ", "").endswith("3055550100") for p in f["phones"])

def test_merge_non_latin_name_kept():
    ocr = "山田 太郎\nAcme\ntaro.yamada@example.jp"
    f = merge.merge(_rules(first_name="", last_name="", emails=["taro.yamada@example.jp"]), {"first_name": "太郎", "last_name": "山田"}, ocr)
    assert (f["first_name"], f["last_name"]) == ("太郎", "山田")

def test_merge_error_answer_ignored():
    r = _rules(department="Sales"); assert merge.merge(r, {"_error": "timeout"}, "")["department"] == "Sales"
