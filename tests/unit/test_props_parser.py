"""Property-based tests (Hypothesis) for the rule parser, app/parser.parse (what app/pipeline.scan calls on the OCR text).
Fixed properties for ANY text: never raises, same shape every time, deterministic, never invents an email or a phone number;
and on generated well-formed cards the planted email and phone are found. Fast and reproducible on CI: derandomize=True,
no example database (nothing written into the repo), deadline=None (slow CI machines)."""
import re, string
import pytest
pytest.importorskip("hypothesis", reason="pip install -r requirements-dev.txt")
from hypothesis import example, given, settings, strategies as st   # noqa: E402
from app import parser as P

FAST = settings(max_examples=150, deadline=None, derandomize=True, database=None)
KEYS = {"first_name": str, "last_name": str, "credentials": str, "title": str, "company": str, "department": str, "emails": list,
        "phones": list, "website": str, "address": str, "other_address": str, "social": list, "confidence": dict,
        "overall_confidence": float, "needs_review": list}

def _ref(text):
    """The text the parser actually reads: its own per-line normalization (NFKC, OCR spacing fixes like 'a @ b . com'),
    lower case, whitespace and line breaks dropped (a wrapped email is joined across two lines on purpose)."""
    return re.sub(r"\s+", "", "".join(P._norm_line(l) for l in text.splitlines()).lower())

def check_invariants(text, meta=None):
    f = P.parse(text, meta)
    assert set(f) == set(KEYS), set(f) ^ set(KEYS)
    for k, t in KEYS.items(): assert isinstance(f[k], t), (k, f[k])
    assert all(isinstance(e, str) and "@" in e for e in f["emails"]) and all(isinstance(s, str) for s in f["social"])
    for p in f["phones"]:
        assert set(p) == {"type", "number", "valid"} and p["type"] in ("work", "mobile", "fax", "home") and isinstance(p["valid"], bool)
        assert len(re.sub(r"\D", "", p["number"])) >= 5
    assert all(v is None or isinstance(v, (int, float)) and 0 <= v <= 1 for v in f["confidence"].values()), f["confidence"]
    assert 0 <= f["overall_confidence"] <= 1 and all(isinstance(k, str) for k in f["needs_review"])
    # emails come from the text. The '@'-repair heuristics ('mvillaabenson.com' -> 'mvilla@benson.com') build one from two
    # pieces that are both in the text, so the property is on the local part and the domain, not the whole string.
    ref = _ref(text)
    for e in f["emails"]:
        loc, dom = e.rsplit("@", 1)
        assert loc in ref and dom in ref, (e, ref)
    # phone numbers are kept as written (the +1 / GAC formatting happens later, at export), so each one is a piece of a line
    norm = [P._norm_line(l) for l in text.splitlines()]
    for p in f["phones"]: assert any(p["number"] in l for l in norm), (p, norm)
    return f

# ---- any text at all (incl. control characters, other scripts, emoji)
@FAST
@given(st.text(max_size=400))
@example("")
@example("\n\n\n")
@example("@\n@@\n.@.\n+\n()")
@example("John Smith\nİstanbul@İİ.com\n３３０-555-0101")   # 'İ' lower-cases to two characters; full-width digits
def test_any_text_never_raises(text): check_invariants(text)

@FAST
@given(st.text(max_size=300))
def test_deterministic(text): assert P.parse(text) == P.parse(text)

# ---- card-like lines
FIRST = ["John", "Mary", "Ana", "José", "Chen", "Priya", "Olu", "Renée", "Mohammed", "Kim", "Sarah", "Lee"]
LAST = ["Smith", "O'Neil", "van der Meer", "García", "Nguyen", "Okafor", "Schmidt", "Lee", "McDonald", "Kowalski"]
TITLES = ["CEO", "Sales Manager", "Vice President, Operations", "Director of Marketing", "Owner", "Senior Engineer", "Realtor®"]
CO = ["Acme", "Summit", "Rubber City", "Blue Heron", "Northcoast", "Keystone", "Polymer"]
SUFFIX = ["Inc", "LLC", "Group", "Solutions", "Industries", "Bank", "GmbH", ""]
PH_US = ["{a}-{b}-{c}", "({a}) {b}-{c}", "{a}.{b}.{c}", "+1 {a} {b} {c}", "{a}/{b}-{c}"]
PH_LABEL = ["", "Tel: ", "T ", "Phone ", "Cell: ", "M: ", "Office ", "Fax: ", "P. "]
safe = st.sampled_from
word = st.text(string.ascii_lowercase, min_size=2, max_size=10)

@st.composite
def us_phone(draw):
    a = draw(st.sampled_from(["330", "216", "614", "212", "415", "800"])); b = f"{draw(st.integers(200, 999))}"; c = f"{draw(st.integers(0, 9999)):04d}"
    return draw(safe(PH_US)).format(a=a, b=b, c=c)
intl_phone = st.sampled_from(["+44 20 7946 0958", "+49 30 1234567", "+33 1 42 68 53 00", "+81 3-1234-5678", "+61 2 9374 4000", "+52 55 1234 5678"])
phone = st.one_of(us_phone(), intl_phone)

@st.composite
def email(draw, first="", last=""):
    loc = draw(st.sampled_from([first.lower(), (first[:1] + last).lower(), f"{first}.{last}".lower(), "info", "sales"]))
    loc = re.sub(r"[^a-z.]", "", loc).strip(".") or "info"
    return f"{loc}@{draw(word)}{draw(st.sampled_from(['', '-co', 'group']))}.{draw(st.sampled_from(['com', 'org', 'net', 'co.uk', 'io', 'de']))}"

@st.composite
def address(draw):
    street = f"{draw(st.integers(1, 99999))} {draw(st.sampled_from(['Main', 'S. High', 'Market', 'Oak Hill', 'Cedar']))} {draw(st.sampled_from(['St', 'Street', 'Ave', 'Rd', 'Blvd', 'Dr', 'Suite 200']))}"
    city = draw(st.sampled_from([f"Akron, OH {draw(st.integers(10000, 99999))}", "Cleveland, Ohio 44113", "London EC1A 1BB", "10115 Berlin", "Toronto, ON"]))
    return draw(st.sampled_from([[street, city], [f"{street}, {city}"], [street]]))
url = st.builds(lambda pre, w, tld: f"{pre}{w}.{tld}", st.sampled_from(["", "www.", "https://", "http://www."]), word, st.sampled_from(["com", "org", "net", "biz", "tech"]))
# OCR junk without digits or '@' (a junk number could legitimately be read as a phone, or swallow the planted one as a duplicate)
junk = st.one_of(st.text("~|_-=*.,:;'\"!?()[]{}<>•·©®" + string.ascii_letters + " ", min_size=1, max_size=20),
                 st.sampled_from(["SCAN ME", "Your trusted partner", "|||", "~~", "Member FDIC", "—", "业务经理", "Geschäftsführer"]))

@st.composite
def card(draw):
    first, last = draw(safe(FIRST)), draw(safe(LAST))
    em, ph = draw(email(first, last)), draw(phone)
    e_line, p_line = draw(safe(["", "E: ", "Email: ", "e-mail "])) + em, draw(safe(PH_LABEL)) + ph
    # footer rows often put both on one line ('E: x@y.com | T: 330-555-0101'): the phone used to be dropped there
    contact = [e_line, p_line] if draw(st.booleans()) else [draw(safe(["{} | {}", "{}  {}", "{} • {}"])).format(*draw(st.permutations([e_line, p_line])))]
    lines = [f"{first} {last}" + draw(safe(["", ", MBA", ", CPA"])), draw(safe(TITLES)),
             f"{draw(safe(CO))} {draw(safe(SUFFIX))}".strip(), *contact, *draw(address())]
    if draw(st.booleans()): lines.append(draw(url))
    lines += draw(st.lists(junk, max_size=3))
    order = draw(st.permutations(range(len(lines))))   # cards put things anywhere; the name block usually first
    if draw(st.booleans()): lines = [lines[i] for i in order]
    case = draw(safe([str, str.upper]))
    text = "\n".join(case(l) if not ("@" in l) else l for l in lines)
    return text, em, ph

@FAST
@given(card())
@example(("John Smith\nCEO\nAcme Inc\njsmith@acme.com\nTel: 330-555-0101\n1 Main St\nAkron, OH 44308", "jsmith@acme.com", "330-555-0101"))
@example(("Mary Jones\nOwner\nE: mary@jones.com | T: 330-555-0102", "mary@jones.com", "330-555-0102"))   # regression: phone on the email line
def test_card_invariants_and_planted_fields_found(c):
    text, em, ph = c
    f = check_invariants(text)
    assert em.lower() in f["emails"], (em, f["emails"], text)
    want = re.sub(r"\D", "", ph)
    assert any(re.sub(r"\D", "", p["number"]) == want for p in f["phones"]), (ph, f["phones"], text)
    assert f["confidence"]["emails"] and f["confidence"]["phones"]

@FAST
@given(card(), st.data())
def test_layout_meta_never_breaks_it(c, data):
    """The OCR also passes per-line layout (top of the card, relative height); any values must be safe."""
    text = c[0]
    meta = [{"text": l, "top": data.draw(st.floats(0, 1)), "rel_h": data.draw(st.floats(0.1, 5))} for l in text.splitlines() if data.draw(st.booleans())]
    check_invariants(text, meta)
    check_invariants(data.draw(st.text(max_size=200)), meta)
