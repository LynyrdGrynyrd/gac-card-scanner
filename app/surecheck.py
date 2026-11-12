"""v0.4.15 (real-card benchmark, Nov 2026): "sure but wrong" guard.

Runs last, on the final values. It never changes or drops a value; it only lowers a field's confidence to 0.5 (so the
review screen shows "Check") when the value is not backed up by what is printed on the card:

* department: a department line from the AI or the rules is sure only when it stands on its own line, is not part of
  the title line, does not start with a role word, and (on cards with no email or website, which are mostly old
  trade cards) carries a real department word ("Department", "Division of", "School of", ...).
* name: the card must print the last name outside the email/website, the name must look like a person's name, and
  the name line must not be a company ("J. H. Harvey & Co.") or several people ("Harry and June ...").
* address: no phone number, no directions ("between ...", "near ...", "rear of ...") and not two addresses run together.
* company: not a web address and not just the person's own name.
"""
import re, difflib
from . import parser as P

LOW = 0.5          # below the 0.6 "Check" line, same value the AI merge uses for unsupported fields
SURE = 0.6         # only fields at or above this are lowered (already-flagged fields are left alone)

def _n(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _lines(text): return [re.sub(r"\s+", " ", l).strip() for l in (text or "").splitlines() if l.strip()]
def _ratio(a, b): return difflib.SequenceMatcher(None, a, b).ratio()

_ROLE_START = re.compile(r"(?i)^\s*(ceo|cfo|coo|cto|cio|cmo|vp|svp|evp|mgr|asst|president|vice|director|manager|chief|head|officer|"
                         r"senior|sr\.?|junior|jr\.?|lead|principal|assistant|associate|executive|project|regional|account|sales)\b")
# words a real department/unit name carries; used only on cards with no email and no website
_DEPT_WORD = re.compile(r"(?i)\b(department|dept\.?|division|school|college|faculty|office of|institute|center|centre|program|"
                        r"laborator(?:y|ies)|bureau|district|section|unit)\b")

def _own_line(val, lines):
    """How well the value matches a whole printed line (or two lines joined, for wrapped text): 1.0 = its own line."""
    v = _n(val)
    if not v: return 0.0
    cands = lines + [a + " " + b for a, b in zip(lines, lines[1:])]
    return max((_ratio(v, _n(c)) for c in cands), default=0.0)

def _in_title_line(val, lines):
    """The value is printed (allowing a few misread letters) inside a longer line that also has a job title
    ("Regional Sales Manager, Northeast Ohio Territory")."""
    v = _n(val)
    if len(v) < 4: return False
    vw = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", val)}
    for l in lines:
        nl = _n(l)
        if len(nl) <= len(v) + 3: continue
        cover = sum(b.size for b in difflib.SequenceMatcher(None, nl, v, autojunk=False).get_matching_blocks()) / len(v)
        if cover < 0.85: continue
        rest = " ".join(w for w in re.findall(r"[A-Za-z]{2,}", l)
                        if not any(_ratio(w.lower(), x) >= 0.8 for x in vw))
        if P.TITLE.search(rest): return True
    return False

def department_ok(f, lines):
    d = (f.get("department") or "").strip()
    if not d: return True
    if _ROLE_START.match(d): return False
    head = d.split(",")[0]
    if "," in d and P.TITLE.search(head): return False                                   # "Senior Project Engineer, Civil ..."
    if _in_title_line(d, lines): return False
    if _own_line(d, lines) < 0.75 and not P.DEPT.search(d): return False
    if not f.get("emails") and not f.get("website") and not _DEPT_WORD.search(d): return False
    return True

_NOT_NAME = {"city", "the", "and", "of", "in", "at", "street", "st", "ave", "road", "co", "inc", "ont", "ontario", "box", "suite"}
_COMPANY_IN_LINE = re.compile(r"(?i)(&\s*co\b|\bco\.|\binc\b|\bllc\b|\bltd\b|\bcorp\b|\bcompany\b|\bbros\b)")
_SEVERAL = re.compile(r"(?i)\b(and|&)\s+[A-Z][a-z]*\.?\s")

def _strip_web(text):
    t = P.EMAIL.sub(" ", text or "")
    return P.URL.sub(" ", t)

def name_ok(f, text, lines):
    fn, ln = (f.get("first_name") or "").strip(), (f.get("last_name") or "").strip()
    if not fn and not ln: return True
    if not ln: return True   # single-word names are already handled by the rules' own confidence
    # printed somewhere other than inside an email address or website
    plain = _strip_web(text)
    if _n(ln) and _n(ln) not in _n(plain):
        words = [_n(w) for w in re.findall(r"[^\W_]{2,}", plain)]
        if not any(_ratio(_n(ln), w) >= 0.8 for w in words): return False
    # looks like a person's name
    for tok in (fn, ln):
        t = tok.strip(". ")
        if t.lower() in _NOT_NAME or t.upper() in P.STATES and len(t) == 2: return False
    if "." in ln.strip(".") or re.search(r"\d", fn + ln): return False                 # "S.Greene": two words run together
    if len(fn.strip(".")) == 2 and fn.strip(".").isupper(): return False                # "RU", "IN": not a first name
    # the line the name is printed on: a company ("J. H. Harvey & Co.") or several people ("Harry and June Smith")
    nln = _n(ln)
    for l in lines:
        if nln and nln in _n(l) and _n(fn) in _n(l) and len(_n(l)) <= len(_n(fn + ln)) + 40:
            if _COMPANY_IN_LINE.search(l): return False
            pre = l[: l.lower().find(ln.lower())] if ln.lower() in l.lower() else ""
            if _SEVERAL.search(pre + " "): return False
    return True

# a phone number inside the address: a modern 10-digit number or an old exchange name ("MAin 4-6789", "SENECA 0270")
_PHONEISH = re.compile(r"\(\d{3}\)\s*\d{3}[\s.-]\d{4}|\b\d{3}[.-]\d{3}[.-]\d{4}\b|\b[A-Z]{2}[A-Za-z]{0,8}\s?\d-\d{4}\b|\b[A-Z]{4,}\s+\d{4}$")
# directions printed next to the address ("between Jackson & Main", "(Cor. First Ave.)", "near the hotel")
_DIRECTIONS = re.compile(r"(?i)\b(between|bet\.|near|opp\.|opposite|rear of|next to|blocks? (?:north|south|east|west) of|take car|old no)\b|[\[\(][^\]\)]*\b(cor|corner|near|old)\b")
_TWO_ADDR = re.compile(r"(?i)\b(residence|res\.|office|mill|works|factory|plant|warehouse|branch)\s*(?:at|:)")

def address_ok(f):
    a = f.get("address") or ""
    if not a: return True
    if _PHONEISH.search(a): return False
    if _DIRECTIONS.search(a): return False
    if _TWO_ADDR.search(a): return False
    parts = [p.strip() for p in re.split(r",", a)]
    streets = [p for p in parts if re.match(r"^\d{1,6}[a-z]?\s+\S", p) and re.search(rf"(?i)\b({P.STREET_WORDS})\b\.?", p)]
    if len(streets) >= 2: return False
    if len(P.US_ZIP.findall(a)) >= 2: return False                                       # two "City, ST 12345" parts
    return True

def company_ok(f):
    c = (f.get("company") or "").strip()
    if not c: return True
    if re.fullmatch(r"(?i)[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}", c): return False          # "example.com" is the website
    # the person's own name in the company slot ("George Inwood" on a card with no company line)
    who = _n((f.get("first_name") or "") + (f.get("last_name") or ""))
    cn = _n(re.sub(r"(?i)'s\b", "", c))
    if who and len(who) >= 6 and (cn == who or (_n(f.get("last_name")) and cn.startswith(_n(f.get("first_name"))) and cn.endswith(_n(f.get("last_name"))) and len(cn) <= len(who) + 3)):
        return False
    return True

def apply(f, text):
    """Lower confidence (never values) for fields the card does not back up. Returns f (changed in place)."""
    conf = f.setdefault("confidence", {})
    lines = _lines(text)
    checks = {"department": department_ok(f, lines), "name": name_ok(f, text or "", lines),
              "address": address_ok(f), "company": company_ok(f)}
    nr = list(f.get("needs_review") or [])
    low = []
    for k, ok in checks.items():
        x = conf.get(k)
        if ok or x is None or x < SURE: continue
        conf[k] = LOW; low.append(k)
        if k not in nr: nr.append(k)
    if low:
        f["needs_review"] = nr
        vals = [x for x in conf.values() if isinstance(x, (int, float))]
        if vals: f["overall_confidence"] = round(min(sum(vals) / len(vals), min(vals) + 0.25), 2)
    return f

def apply_cached(fields, text):
    """Benchmark helper: re-run the guard on a saved scan result (copy; the saved one is not changed)."""
    import copy
    return apply(copy.deepcopy(fields), text)
