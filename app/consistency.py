"""Cross-field consistency checks (no extra hardware): fields that agree with each other raise confidence, fields
that disagree lower it and get a plain-language flag the reviewer sees. Never changes field values.
  - email domain  vs website domain     (same -> both more trustworthy; near-identical -> probably an OCR typo)
  - email domain  vs company name       (company words in the domain -> company more trustworthy)
  - email local part vs person's name   (jane.doe@ vs "Jane Doe")
  - phone area code vs address state    (330 = Ohio vs "Akron, OH 44308")"""
import re
from difflib import SequenceMatcher
FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "me.com", "live.com", "msn.com",
        "comcast.net", "att.net", "sbcglobal.net", "protonmail.com", "ymail.com", "mail.com", "zoho.com"}
GENERIC = {"info", "sales", "contact", "office", "admin", "hello", "mail", "team", "support", "service", "help", "inquiries",
           "enquiries", "frontdesk", "reception", "marketing", "hr", "jobs", "careers", "billing", "accounts", "orders"}
STOP = {"inc", "llc", "ltd", "co", "corp", "company", "the", "and", "of", "group", "services", "llp", "pc", "pllc", "associates", "partners"}
STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
          "DC": "Washington D.C.", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
          "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
          "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
          "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
          "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
          "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
NAME2ABBR = {v.lower(): k for k, v in STATES.items()}

def _dom(s):
    s = (s or "").lower().strip()
    s = re.sub(r"^https?://", "", s).split("/")[0]
    return s[4:] if s.startswith("www.") else s
def _core(d): return d.rsplit(".", 1)[0] if "." in d else d       # acme-widgets.com -> acme-widgets
def _alpha(s): return re.sub(r"[^a-z]", "", (s or "").lower())
def _sim(a, b): return SequenceMatcher(None, a, b).ratio() if a and b else 0.0

def address_state(addr):
    if not addr: return None
    m = re.search(r"\b([A-Z]{2})\.?\s*,?\s*\d{5}(?:-\d{4})?\b", addr) or re.search(r",\s*([A-Z]{2})\s*$", addr.strip())
    if m and m.group(1) in STATES: return m.group(1)
    for name, ab in NAME2ABBR.items():
        if re.search(r"\b" + re.escape(name) + r"\b", addr.lower()): return ab
    return None

def phone_state(number):
    try:
        import phonenumbers
        from phonenumbers import geocoder
        p = phonenumbers.parse(number, "US")
        if phonenumbers.region_code_for_number(p) != "US": return None
        d = geocoder.description_for_number(p, "en")
    except Exception: return None
    if not d: return None
    st = d.split(",")[-1].strip()
    return st if st in STATES else NAME2ABBR.get(st.lower())

def _adj(conf, k, delta, cap=0.97, floor=None):
    v = conf.get(k)
    if v is None: return
    if delta > 0 and v < 0.6: return     # agreement never un-flags a field the reader already found hard to read
    conf[k] = round(min(cap, v + delta), 2) if delta > 0 else round(max(floor if floor is not None else 0.0, min(v, v + delta)), 2)

def check(f):
    """Returns (confidence_adjustments_applied: dict, flags: list[{code, fields, text}]). Mutates f['confidence']."""
    conf = f.setdefault("confidence", {}); flags = []; notes = {}
    emails = [e for e in (f.get("emails") or []) if "@" in e]
    edoms = [_dom(e.split("@", 1)[1]) for e in emails]
    biz = [d for d in edoms if d not in FREE]
    web = _dom(f.get("website"))
    # 1. email domain vs website
    if biz and web:
        best = max(biz, key=lambda d: _sim(_core(d), _core(web)))
        s = _sim(_core(best), _core(web))
        if best == web or best.endswith("." + web) or web.endswith("." + best):
            _adj(conf, "emails", +0.1); _adj(conf, "website", +0.1); notes["email_web"] = "match"
        elif s >= 0.75:
            _adj(conf, "emails", -1, floor=0.45); conf["emails"] = min(conf.get("emails") or 0.45, 0.45) if conf.get("emails") is not None else None
            _adj(conf, "website", -1, floor=0.45); conf["website"] = min(conf.get("website") or 0.45, 0.45) if conf.get("website") is not None else None
            flags.append({"code": "email_web_typo", "fields": ["emails", "website"], "text": f"Email domain “{best}” and website “{web}” are almost the same: one may be misread"})
            notes["email_web"] = "near"
        else: notes["email_web"] = "different"
    # 2. email domain vs company
    comp = [w for w in re.findall(r"[a-z0-9]+", (f.get("company") or "").lower()) if w not in STOP and len(w) >= 3]
    if biz and comp:
        cores = [_alpha(_core(d).split(".")[-1]) for d in biz]
        if any(w in c for w in comp for c in cores) or any(_sim("".join(comp), c) >= 0.7 for c in cores) or \
           any(len(c) >= 2 and c == "".join(w[0] for w in comp) for c in cores):
            _adj(conf, "company", +0.1); notes["email_company"] = "match"
    # 3. email local part vs name
    fn, ln = _alpha(f.get("first_name")), _alpha(f.get("last_name"))
    if emails and (fn or ln):
        hits = 0; personal = 0
        for e in emails:
            lp = e.split("@", 1)[0].lower(); la = _alpha(lp)
            if la in GENERIC or not la: continue
            personal += 1
            if (len(ln) >= 3 and ln in la) or (len(fn) >= 3 and fn in la) or (fn and ln and la in (fn[0] + ln, fn + ln[0], ln + fn[0])) \
               or max(_sim(la, fn + ln), _sim(la, fn[:1] + ln), _sim(la, ln)) >= 0.8:
                hits += 1
        if hits:
            _adj(conf, "name", +0.1); _adj(conf, "emails", +0.05); notes["email_name"] = "match"
        elif personal and re.search(r"[a-z]{2,}[._-][a-z]{2,}", emails[0].split("@")[0].lower()):
            # looks like firstname.lastname@ but matches neither name -> name or email is probably misread
            _adj(conf, "name", -1, floor=0.5); conf["name"] = min(conf["name"], 0.5) if conf.get("name") is not None else None
            flags.append({"code": "email_name", "fields": ["name", "emails"], "text": f"Email “{emails[0]}” doesn't match the name “{f.get('first_name','')} {f.get('last_name','')}”"})
            notes["email_name"] = "mismatch"
    # 4. area code vs address state
    st = address_state(f.get("address"))
    if st and f.get("phones"):
        work = [p for p in f["phones"] if p.get("type") in ("work", "fax", None, "")] or f["phones"]
        pst = [phone_state(p.get("number", "")) for p in work]; pst = [x for x in pst if x]
        if pst:
            if st in pst: _adj(conf, "phones", +0.05); _adj(conf, "address", +0.05); notes["area_state"] = "match"
            else:
                flags.append({"code": "area_state", "fields": ["phones", "address"], "text": f"Phone area code is in {STATES.get(pst[0], pst[0])} but the address is in {STATES[st]}"})
                _adj(conf, "phones", -0.1, floor=0.55); notes["area_state"] = "mismatch"
    return notes, flags

def apply(f):
    """Run the checks, store flags in f['consistency'], recompute overall confidence and needs_review."""
    notes, flags = check(f)
    f["consistency"] = flags; f["consistency_notes"] = notes
    conf = f.get("confidence") or {}; vals = [v for v in conf.values() if v is not None]
    if vals: f["overall_confidence"] = round(min(sum(vals) / len(vals), min(vals) + 0.25), 2)
    nr = [k for k, v in conf.items() if v is not None and v < 0.6]
    f["needs_review"] = sorted(set(nr) | {x for fl in flags for x in fl["fields"]} & set(conf))
    return f
