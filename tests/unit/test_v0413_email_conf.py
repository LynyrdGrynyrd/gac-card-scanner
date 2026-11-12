"""v0.4.13 (real-card A/B of the RapidOCR switch): an email misread by one letter ('d' read as 'c' before the @) went out
marked sure (0.97). The name check counted the near match as agreement, and the merge ignored the AI's different read."""
import copy
import pytest
from app import consistency as C, merge as M, pipeline, ocr, parser, qr


def _f(email, first="Ada", last="Redmond", conf=0.97):
    return {"first_name": first, "last_name": last, "emails": [email], "website": "harwick-college.example.edu", "company": "Harwick College",
            "confidence": {"name": 0.9, "emails": conf, "website": 0.9, "company": 0.8}}


def test_one_letter_off_the_name_lowers_the_email():
    f = _f("arecmond@harwick-college.example.edu")
    notes, flags = C.check(f)
    assert f["confidence"]["emails"] <= 0.45 and notes["email_name"] == "near"
    assert [x["fields"] for x in flags if x["code"] == "email_name_typo"] == [["emails"]]
    assert f["confidence"]["name"] == 0.9, "a near match is not agreement: no name boost"


def test_exact_name_patterns_still_raise_confidence():
    for e in ("aredmond@", "ada.redmond@", "redmonda@", "redmond@", "adar@"):
        f = _f(e + "harwick-college.example.edu", conf=0.9); C.check(f)
        assert f["confidence"]["emails"] > 0.9 and f["confidence"]["name"] > 0.9, e


def test_not_a_misread():
    # a middle initial (an inserted letter), a different person, a generic box and a name with digits (the name is the misread part)
    for f in (_f("amredmond@x.example.edu"), _f("jlarsen@x.example.edu"), _f("info@x.example.edu"),
              _f("arecmond@x.example.edu", first="Ad4", last="Redmond")):
        C.check(f)
        assert f["confidence"]["emails"] >= 0.9, f["emails"]
        assert C.check(f)[0].get("email_name") != "near"


def test_swapped_neighbours_count_as_a_misread():
    f = _f("aerdmond@harwick-college.example.edu"); C.check(f)
    assert f["confidence"]["emails"] <= 0.45


def test_merge_ai_reads_the_email_differently():
    f = _f("arecmond@harwick-college.example.edu")
    out = M.merge(f, {"first_name": "Ada", "last_name": "Redmond", "emails": ["aredmond@harwick-college.example.edu"]}, "Ada Redmond")
    assert out["emails"] == ["arecmond@harwick-college.example.edu"], "the rules' value is kept; only its confidence drops"
    assert out["confidence"]["emails"] == 0.5 and "emails" in out["needs_review"]


def test_merge_ai_agrees_or_reads_another_address():
    for ve in (["arecmond@harwick-college.example.edu"], ["admissions@harwick-college.example.edu"], ["arecmond@other.example.com"]):
        out = M.merge(_f("arecmond@harwick-college.example.edu", first="Bo", last="Lind"), {"emails": ve}, "")
        assert out["confidence"]["emails"] == 0.97, ve
    f = _f("asmith@harwick-college.example.edu", first="Bo", last="Lind"); f["emails"].append("bsmith@harwick-college.example.edu")
    out = M.merge(f, {"emails": ["asmith@harwick-college.example.edu", "bsmith@harwick-college.example.edu"]}, "")
    assert out["confidence"]["emails"] == 0.97, "two similar addresses on one card, both read the same by the AI"


@pytest.fixture
def scan_with(monkeypatch):
    def run(email, vlm=None):
        base = {"first_name": "Ada", "last_name": "Redmond", "credentials": "", "title": "Registrar", "company": "Harwick College", "department": "",
                "emails": [email], "phones": [], "website": "harwick-college.example.edu", "address": "", "other_address": "", "social": [],
                "confidence": {"name": 0.95, "title": 0.75, "company": 0.7, "department": None, "emails": 0.97, "phones": None, "website": 0.9, "address": None},
                "overall_confidence": 0.85, "needs_review": []}
        text = f"Ada Redmond\nRegistrar\nHarwick College\n{email}\nharwick-college.example.edu"
        monkeypatch.setattr(ocr, "run_ocr", lambda data, engine=None: {"text": text, "engine": "tesseract", "lines": None})
        monkeypatch.setattr(qr, "decode", lambda data: [])
        monkeypatch.setattr(parser, "parse", lambda t, meta=None: copy.deepcopy(base))
        monkeypatch.setenv("CONSISTENCY", "1"); monkeypatch.setenv("REALCARD_POSTFIX", "1")
        return pipeline.scan(b"x", use_vlm=False, vlm_result=vlm)["fields"]
    return run


def test_pipeline_misread_email_is_not_sure(scan_with):
    for vlm in (None, {"first_name": "Ada", "last_name": "Redmond", "emails": ["aredmond@harwick-college.example.edu"]}):
        f = scan_with("arecmond@harwick-college.example.edu", vlm)
        assert f["confidence"]["emails"] < 0.6 and "emails" in f["needs_review"], vlm
        assert any(x["code"] == "email_name_typo" for x in f["consistency"])


def test_pipeline_post_fixed_email_is_trusted_again(scan_with):
    # 'cl' for 'd' is a known look-alike: the post-fix restores 'aredmond', and the first pass's lowered confidence is undone
    f = scan_with("areclmond@harwick-college.example.edu")
    assert f["emails"] == ["aredmond@harwick-college.example.edu"] and f["confidence"]["emails"] >= 0.9
    assert not any(x["code"] == "email_name_typo" for x in f["consistency"])
