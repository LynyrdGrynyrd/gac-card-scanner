"""Typo / plausibility checks. SUGGESTIONS ONLY: never changes field values or confidence.
Returns a list of {code, field, text, suggestion} the reviewer can accept or ignore.
  email_tld        .con/.cm/.corn/.c0m ... -> .com (and .nte/.ogr/.edi)
  email_provider   gmial.com / yaho.com / hotmial.com -> gmail.com / yahoo.com / hotmail.com
  email_format     two @, spaces, missing TLD, leading/trailing dot
  email_web        email domain and website almost identical (edit distance <= 2) -> one is misread; suggests the one
                   that matches the company name when possible
  email_name       local part is edit-distance 1 from first.last / flast / first -> name or email letter misread
  area_state       US phone area code's state differs from address state
  phone_invalid    10-digit NANP number that libphonenumber says cannot exist (bad area code / exchange)
  name_sanity      digits/@/url in a name, a title/company word as the name, first == last, 1-letter last name
  title_sanity     title holds a phone/email/url
  company_sanity   company equals the person's name, or holds an email/phone"""
import re
from difflib import SequenceMatcher
try:
    from .consistency import address_state, phone_state, STATES, FREE
except ImportError:  # pragma: no cover
    from consistency import address_state, phone_state, STATES, FREE

TLD_FIX = {"con": "com", "cm": "com", "corn": "com", "c0m": "com", "om": "com", "comm": "com", "co m": "com", "vom": "com", "xom": "com",
           "cpm": "com", "nte": "net", "ner": "net", "met": "net", "ogr": "org", "orq": "org", "0rg": "org", "edi": "edu", "eud": "edu"}
PROVIDERS = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "comcast.net", "sbcglobal.net", "att.net"]
TITLE_WORDS = {"president", "director", "manager", "ceo", "cfo", "coo", "cto", "vp", "owner", "founder", "engineer", "sales", "partner",
               "attorney", "consultant", "specialist", "coordinator", "executive", "officer", "chairman", "secretary", "treasurer",
               "representative", "associate", "supervisor", "agent", "broker", "realtor", "principal", "analyst", "administrator"}
COMPANY_WORDS = {"inc", "llc", "ltd", "corp", "corporation", "company", "co", "gmbh", "group", "services", "solutions", "bank",
                 "university", "college", "hospital", "association", "industries", "enterprises", "international", "llp"}

def _lev(a, b):
    if a == b: return 0
    if abs(len(a) - len(b)) > 3: return 9
    return _osa(a, b)
def _osa(a, b):
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1): d[i][0] = i
    for j in range(len(b) + 1): d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + (a[i-1] != b[j-1]))
            if i > 1 and j > 1 and a[i-1] == b[j-2] and a[i-2] == b[j-1]: d[i][j] = min(d[i][j], d[i-2][j-2] + 1)
    return d[-1][-1]
def _dom(s):
    s = (s or "").lower().strip(); s = re.sub(r"^https?://", "", s).split("/")[0]
    return s[4:] if s.startswith("www.") else s
def _a(s):
    import unicodedata
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
def _sug(code, field, text, suggestion=None): return {"code": code, "field": field, "text": text, "suggestion": suggestion}

def check(f):
    out = []; emails = [e.strip() for e in (f.get("emails") or []) if e]
    fn, ln = _a(f.get("first_name")), _a(f.get("last_name")); web = _dom(f.get("website"))
    comp = [w for w in re.findall(r"[a-z0-9]+", (f.get("company") or "").lower()) if len(w) >= 3 and w not in COMPANY_WORDS]
    for e in emails:
        el = e.lower()
        if el.count("@") != 1 or " " in el or el.startswith(".") or el.endswith(".") or ".." in el:
            out.append(_sug("email_format", "emails", f"Email “{e}” is not a valid address")); continue
        lp, d = el.split("@")
        if "." not in d:
            out.append(_sug("email_format", "emails", f"Email “{e}” has no domain ending (.com, .org …)")); continue
        base, tld = d.rsplit(".", 1)
        if tld in TLD_FIX:
            fix = f"{lp}@{base}.{TLD_FIX[tld]}"; out.append(_sug("email_tld", "emails", f"“.{tld}” is probably “.{TLD_FIX[tld]}”", fix)); d = f"{base}.{TLD_FIX[tld]}"
        if d not in PROVIDERS:
            near = [p for p in PROVIDERS if _lev(d, p) <= (2 if len(p) > 9 else 1)]
            if near: out.append(_sug("email_provider", "emails", f"“{d}” looks like a misread “{near[0]}”", f"{lp}@{near[0]}"))
        # email vs website
        if web and d not in FREE and d != web and not d.endswith("." + web) and not web.endswith("." + d):
            dist = _lev(d, web)
            if 1 <= dist <= 2 and len(web) >= 6:
                cd, cw = _a(d.rsplit(".", 1)[0]), _a(web.rsplit(".", 1)[0])
                best = None
                if comp:
                    sd = max(SequenceMatcher(None, "".join(comp), cd).ratio(), 0); sw = SequenceMatcher(None, "".join(comp), cw).ratio()
                    if abs(sd - sw) > 0.05: best = ("website", d) if sd > sw else ("emails", f"{lp}@{web}")
                if best:
                    out.append(_sug("email_web", best[0], f"Email domain “{d}” and website “{web}” differ by {dist} letter(s); the company name suggests {best[1]}", best[1]))
                else:
                    out.append(_sug("email_web", "emails", f"Email domain “{d}” and website “{web}” differ by {dist} letter(s): one is probably misread"))
        # local part vs name
        la = _a(lp)
        if fn and ln and len(la) >= 4:
            pats = {fn + ln, fn[0] + ln, fn, ln, ln + fn[0], fn + ln[0]}
            full = {fn + ln, fn[0] + ln, ln + fn[0], ln + fn}
            if la not in pats:
                for p in full:
                    if len(p) >= 5 and len(la) == len(p) and _lev(la, p) == 1:   # substitution/transposition only (middle initials are insertions)
                        out.append(_sug("email_name", "name", f"Email “{e}” is one letter off the name “{f.get('first_name')} {f.get('last_name')}”: check the spelling of both")); break
    # phones
    st = address_state(f.get("address"))
    for p in f.get("phones") or []:
        num = p.get("number", ""); dg = re.sub(r"\D", "", num)
        if len(dg) == 11 and dg[0] == "1": dg = dg[1:]
        if len(dg) != 10 or dg[0] == "0" and "+1" not in num or not (st or "+1" in num or re.search(r"\(\d{3}\)|\d{3}[-. ]\d{3}[-. ]\d{4}", num)): continue
        try:
            import phonenumbers
            pn = phonenumbers.parse("+1" + dg)
            if not phonenumbers.is_valid_number(pn):
                out.append(_sug("phone_invalid", "phones", f"“{num}” is not a possible US/Canada number (bad area code or exchange): a digit may be misread")); continue
        except Exception: continue
        ps = phone_state("+1" + dg)
        if st and ps and ps != st and p.get("type") in ("work", "fax", "", None):
            out.append(_sug("area_state", "phones", f"Area code of “{num}” is in {STATES.get(ps, ps)} but the address is in {STATES.get(st, st)}: check the digits (or it may be a cell)"))
    # name
    for k in ("first_name", "last_name"):
        v = f.get(k) or ""
        if re.search(r"[\d@/]|www|\.com", v, re.I): out.append(_sug("name_sanity", "name", f"{k.replace('_', ' ').title()} “{v}” contains digits or web text"))
        elif v and v.lower().strip(".,") in TITLE_WORDS | COMPANY_WORDS: out.append(_sug("name_sanity", "name", f"“{v}” looks like a title/company word, not a name"))
    if fn and fn == ln: out.append(_sug("name_sanity", "name", "First and last name are identical"))
    if f.get("first_name") and ln and len(ln) == 1: out.append(_sug("name_sanity", "name", f"Last name “{f.get('last_name')}” is a single letter"))
    t = f.get("title") or ""
    if re.search(r"@|www\.|\.com\b|\d{3}[-. )]\d{3}", t, re.I):
        out.append(_sug("title_sanity", "title", f"Title “{t}” looks like it contains other text (phone/email/address)"))
    c = f.get("company") or ""
    if c and (fn or ln) and _a(c) in (fn + ln, ln + fn) and len(_a(c)) > 3:
        out.append(_sug("company_sanity", "company", "Company is the same as the person's name"))
    elif re.search(r"@|\d{3}[-. )]\d{3}[-. ]\d{4}", c):
        out.append(_sug("company_sanity", "company", f"Company “{c}” contains an email or phone number"))
    return out

def apply(f):
    """Attach suggestions under f['suggestions']; does not touch values, confidence or needs_review."""
    f["suggestions"] = check(f); return f
