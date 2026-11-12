"""v0.4.15 (real-card benchmark): fields the card does not back up are not "sure".
On 441 benchmark cards the AI filled a department on cards that have none (all marked sure), invented a person on
company-only cards, and ran directions or a phone number into the address. Values never change; only the confidence
drops below the "Check" line. All examples are made up."""
import copy
import pytest
from app import surecheck as S, pipeline, ocr, qr


def _f(**kw):
    f = {"first_name": "Dana", "last_name": "Whitlock", "title": "Program Manager", "company": "Northfield Polymers Inc.",
         "department": "", "emails": ["dwhitlock@northfieldpolymers.example"], "website": "northfieldpolymers.example",
         "address": "120 Market St., Akron, OH 44308", "phones": [{"type": "work", "number": "(330) 555-0142", "valid": True}],
         "confidence": {"name": 0.95, "title": 0.8, "company": 0.95, "department": 0.8, "address": 0.85,
                        "emails": 0.95, "website": 0.95, "phones": 0.95},
         "needs_review": [], "vlm_fields": {}}
    f.update(kw); return f

TEXT = "Dana Whitlock\nProgram Manager\nPolymer Engineering\nNorthfield Polymers Inc.\n120 Market St., Akron, OH 44308\n" \
       "(330) 555-0142\ndwhitlock@northfieldpolymers.example\nnorthfieldpolymers.example"


def run(f, text=TEXT):
    return S.apply(copy.deepcopy(f), text)


# ---- department
def test_real_department_line_stays_sure():
    out = run(_f(department="Polymer Engineering", vlm_fields={"department": "vlm"}))
    assert out["confidence"]["department"] == 0.8 and "department" not in out["needs_review"]


def test_department_inside_the_title_line_is_check():
    text = "Dana Whitlock\nRegional Sales Manager, Northeast Ohio Territory\nNorthfield Polymers Inc.\ndwhitlock@northfieldpolymers.example"
    out = run(_f(department="Northeast Ohio Territory", vlm_fields={"department": "vlm"}), text)
    assert out["confidence"]["department"] == 0.5 and "department" in out["needs_review"]
    assert out["department"] == "Northeast Ohio Territory", "the value is kept"
    # a few misread letters in the OCR line do not hide it
    text2 = "Dana Whitlock\nSeniar Project Engineer,Civiland Structural Division\nNorthfield Polymers Inc.\ndwhitlock@northfieldpolymers.example"
    assert run(_f(department="Civil and Structural Division"), text2)["confidence"]["department"] == 0.5


def test_department_that_starts_with_a_role_is_check():
    for d in ("MGR, UNIFORM DEPT", "Seniot Project Engineer, Civil and Structural Division", "Director of Sales"):
        text = TEXT + "\n" + d
        assert run(_f(department=d), text)["confidence"]["department"] == 0.5, d


def test_trade_card_tagline_is_not_a_department():
    # an old trade card: no email, no website; the AI calls the trade line a department
    text = "J. Kestrel\nKESTREL & SONS\nFine Olive Oil and Groceries\n14 Water St., Marietta, O."
    f = _f(first_name="J.", last_name="Kestrel", company="Kestrel & Sons", emails=[], website="", phones=[],
           department="Fine Olive Oil and Groceries", address="14 Water St., Marietta, O.", vlm_fields={"department": "vlm"})
    assert run(f, text)["confidence"]["department"] == 0.5
    # a real department word keeps it sure even on such a card
    f2 = dict(f, department="Data Processing Division")
    assert run(f2, text.replace("Fine Olive Oil and Groceries", "Data Processing Division"))["confidence"]["department"] == 0.8


# ---- name
def test_printed_name_stays_sure():
    assert run(_f())["confidence"]["name"] == 0.95


def test_name_only_in_the_email_is_check():
    text = "WORDS FOR HIRE\nCopywriting and editing\ninfo@danawhitlockwrites.example"
    f = _f(emails=["info@danawhitlockwrites.example"], website="", company="Words For Hire")
    assert run(f, text)["confidence"]["name"] == 0.5


def test_name_that_is_not_a_person_is_check():
    for fn, ln, line in (("RU", "Nks", "RU NKS"), ("IN", "City", "IN THE CITY"), ("Roger", "S.greene", "ROGER S.GREENE, PRESIDENT")):
        f = _f(first_name=fn, last_name=ln); text = TEXT + "\n" + line
        out = run(f, text)
        assert out["confidence"]["name"] == 0.5 and "name" in out["needs_review"], (fn, ln)


def test_name_line_that_is_a_company_or_two_people_is_check():
    f = _f(first_name="J.", last_name="Harlan", company="J. H. Harlan & Co.")
    assert run(f, "J. H. HARLAN & CO.\nDry Goods\n14 Water St., Marietta, O.")["confidence"]["name"] == 0.5
    f = _f(first_name="Harry", last_name="Delmore")
    assert run(f, "HARRY AND JUNE DELMORE, OWNERS\nLakeview Motor Court")["confidence"]["name"] == 0.5
    # a company line elsewhere on the card (not the name line) is fine
    f = _f(first_name="Timothy", last_name="Sandoval", company="Sandoval LLC")
    assert run(f, "Timothy Sandoval\nSandoval LLC\ntim@sandoval.example")["confidence"]["name"] == 0.95


# ---- address
def test_clean_addresses_stay_sure():
    for a in ("120 Market St., Akron, OH 44308", "233 S. Thomas Road, P.O. Box 441, Tallmadge, OH 44278",
              "1580 Tallmadge Blvd, Suite 713\nCleveland, OH 44179", "3-1-1, Ogawahigashi-cho, Kodaira-shi, Tokyo 187-8531, Japan"):
        assert run(_f(address=a))["confidence"]["address"] == 0.85, a


def test_address_with_extra_text_is_check():
    for a in ("225 Aurora, MAin 4-6789, Seattle, Wash.", "4th and Pike, Seattle, SENECA 0270",
              "307 Sixth Avenue So., Between Jackson & Main Sts., Seattle, Wash.",
              "89 Yesler Way, (Cor. First Ave.), Seattle, Wash.", "9 Abbott St., Vancouver, B.C. [near the hotel]",
              "120 Market St., Akron, OH 44308, 455 Main St., Kent, OH 44240",
              "P.O. Box 3858, Akron, Ohio 44314-3858, 485 Kenmore Boulevard, Akron, Ohio 44301",
              "Office: 31-35 Archer Str. Nicosia, Residence: 7 Acropolis Ave."):
        out = run(_f(address=a))
        assert out["confidence"]["address"] == 0.5 and out["address"] == a, a


# ---- company
def test_company_checks():
    assert run(_f(company="northfieldpolymers.example"))["confidence"]["company"] == 0.5
    assert run(_f(company="Dana Whitlock", emails=[], website=""))["confidence"]["company"] == 0.5
    assert run(_f(company="Dana Whitlock's", emails=[], website=""))["confidence"]["company"] == 0.5
    assert run(_f(company="Whitlock Tattoo Studio"))["confidence"]["company"] == 0.95
    assert run(_f())["confidence"]["company"] == 0.95


def test_only_lowers_never_raises_or_changes_values():
    f = _f(department="Northeast Ohio Territory", address="225 Aurora, MAin 4-6789, Seattle")
    f["confidence"]["department"] = 0.4; f["needs_review"] = ["department"]
    out = run(f, "Dana Whitlock\nRegional Sales Manager, Northeast Ohio Territory")
    assert out["confidence"]["department"] == 0.4
    for k in ("first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address"):
        assert out[k] == f[k], k
    assert out["overall_confidence"] <= 0.75


# ---- pipeline wiring
@pytest.fixture
def scan_with(monkeypatch):
    def go(text, vlm=None, env="1"):
        monkeypatch.setattr(ocr, "run_ocr", lambda data, engine=None: {"text": text, "engine": "tesseract", "lines": None})
        monkeypatch.setattr(qr, "decode", lambda data: [])
        monkeypatch.setenv("CONSISTENCY", "1"); monkeypatch.setenv("REALCARD_POSTFIX", "1"); monkeypatch.setenv("SURE_CHECK", env)
        return pipeline.scan(b"x", use_vlm=False, vlm_result=vlm)["fields"]
    return go


def test_pipeline_ai_department_from_the_title_line_is_check(scan_with):
    text = "Dana Whitlock\nRegional Sales Manager, Northeast Ohio Territory\nNorthfield Polymers Inc.\n" \
           "(330) 555-0142\ndwhitlock@northfieldpolymers.example\nnorthfieldpolymers.example"
    vlm = {"first_name": "Dana", "last_name": "Whitlock", "title": "Regional Sales Manager",
           "department": "Northeast Ohio Territory", "company": "Northfield Polymers Inc."}
    f = scan_with(text, vlm)
    assert f["department"] == "Northeast Ohio Territory"
    assert f["confidence"]["department"] < 0.6 and "department" in f["needs_review"]
    f0 = scan_with(text, vlm, env="0")
    assert f0["department"] == f["department"] and f0["confidence"]["department"] >= 0.7, "same value; sure with the guard off"


def test_pipeline_clean_card_unchanged(scan_with):
    f1 = scan_with(TEXT); f0 = scan_with(TEXT, env="0")
    assert f1["confidence"] == f0["confidence"] and f1["needs_review"] == f0["needs_review"]
