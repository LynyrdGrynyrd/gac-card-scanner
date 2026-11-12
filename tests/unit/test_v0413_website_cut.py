"""v0.4.13 (real-card A/B of the RapidOCR switch): a website that lost its first word ('Harwick College.example.edu' read
as 'college.example.edu'-style) went out marked sure (0.95), because the email domain ends with it and that counted as
agreement. Now it is flagged "Check". Values never change."""
import copy
import pytest
from app import consistency as C, merge as M, parser, pipeline, ocr, qr


def _f(web, email="info@northfield.edu", conf=0.85):
    return {"first_name": "Ada", "last_name": "Redmond", "emails": [email], "website": web, "company": "Northfield College",
            "confidence": {"name": 0.9, "emails": 0.95, "website": conf, "company": 0.8}}


def test_website_missing_its_first_word_is_not_sure():
    for web in ("field.edu", "http://field.edu/programs", "www.field.edu"):
        f = _f(web); notes, flags = C.check(f)
        assert f["confidence"]["website"] <= 0.45 and notes["email_web"] == "cut", web
        assert [x["fields"] for x in flags if x["code"] == "website_cut"] == [["website"]]
        assert f["confidence"]["emails"] == 0.95, "the email gets no boost from a cut website"


def test_matching_websites_still_raise_confidence():
    for web in ("northfield.edu", "www.northfield.edu/x", "shop.northfield.edu"):
        f = _f(web); notes, _ = C.check(f)
        assert notes["email_web"] == "match" and f["confidence"]["website"] > 0.85, web
    f = _f("northfield.edu", email="ada@mail.northfield.edu"); C.check(f); assert f["confidence"]["website"] > 0.85


def test_email_lost_dot_keeps_old_behaviour():
    # the email is the misread one (blocked by its own lost-dot check); the website is right
    for e in ("b@firestoneparkhardwexample.com", "b@acmecomexample.com"):
        f = _f("example.com", email=e); notes, flags = C.check(f)
        assert notes["email_web"] == "match" and not [x for x in flags if x["code"] == "website_cut"], e


def test_short_or_unrelated_is_not_a_cut():
    for web, e in (("other.com", "a@northfield.edu"), ("x.edu", "a@northfield.edu"), ("northfield.edu", "a@northfield.edu")):
        f = _f(web, email=e); C.check(f); assert C.check(f)[0].get("email_web") != "cut", (web, e)
    f = _f("field.edu", email="a@gmail.com"); C.check(f); assert f["confidence"]["website"] == 0.85, "free mail says nothing"


def test_parser_sees_a_word_before_the_address():
    t = "Ada Redmond\nRegistrar\nhttp: //North Field.edu/programs\n(330) 555-0142"
    f = parser.parse(t)
    assert f["website"].startswith("field.edu") and f["confidence"]["website"] < 0.6
    for line in ("http://northfield.edu/programs", "www.northfield.edu", "Web: northfield.edu", "Visit www. northfield.edu"):
        f = parser.parse("Ada Redmond\nRegistrar\n" + line)
        assert f["website"] and f["confidence"]["website"] >= 0.8, line


def test_merge_ai_reads_a_longer_address():
    f = _f("field.edu/programs", email="ada@other.example.com", conf=0.95)
    out = M.merge(copy.deepcopy(f), {"website": "northfield.edu/programs"}, "")
    assert out["website"] == "field.edu/programs" and out["confidence"]["website"] == 0.5 and "website" in out["needs_review"]
    for vw in ("field.edu/programs", "www.field.edu", "acme.com"):
        out = M.merge(copy.deepcopy(f), {"website": vw}, "")
        assert out["confidence"]["website"] == 0.95, vw


@pytest.fixture
def scan_with(monkeypatch):
    def run(text, vlm=None):
        monkeypatch.setattr(ocr, "run_ocr", lambda data, engine=None: {"text": text, "engine": "tesseract", "lines": None})
        monkeypatch.setattr(qr, "decode", lambda data: [])
        monkeypatch.setenv("CONSISTENCY", "1"); monkeypatch.setenv("REALCARD_POSTFIX", "1")
        return pipeline.scan(b"x", use_vlm=False, vlm_result=vlm)["fields"]
    return run


def test_pipeline_cut_website_is_not_sure(scan_with):
    text = "Ada Redmond\nRegistrar\nNorthfield College\nTel. (330) 555-0142\naredmond@northfield.edu\nhttp: //North Field.edu/Programs"
    for vlm in (None, {"first_name": "Ada", "last_name": "Redmond", "website": "northfield.edu/programs"}):
        f = scan_with(text, vlm)
        assert f["website"].startswith("field.edu"), f["website"]
        assert f["confidence"]["website"] < 0.6 and "website" in f["needs_review"], vlm
    f = scan_with(text.replace("North Field", "Northfield"))
    assert "northfield.edu" in f["website"] and f["confidence"]["website"] >= 0.9
