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

# round 6: .om (Oman) and .cm (Cameroon) are real country domains, so they get no one-click "fix" (skeptic R6-7)
TLD_FIX = {"con": "com", "corn": "com", "c0m": "com", "comm": "com", "co m": "com", "vom": "com", "xom": "com",
           "cpm": "com", "nte": "net", "ner": "net", "met": "net", "ogr": "org", "orq": "org", "0rg": "org", "edi": "edu", "eud": "edu"}
REAL_PROVIDERS = {"ymail.com", "rocketmail.com", "gmx.com", "gmx.net", "mail.com", "me.com", "mac.com", "live.com", "msn.com",
                  "yahoo.co.uk", "hotmail.co.uk", "proton.me", "protonmail.com", "zoho.com", "fastmail.com", "aim.com", "verizon.net", "cox.net"}
PROVIDERS = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "comcast.net", "sbcglobal.net", "att.net"]
TITLE_WORDS = {"president", "director", "manager", "ceo", "cfo", "coo", "cto", "vp", "owner", "founder", "engineer", "sales", "partner",
               "attorney", "consultant", "specialist", "coordinator", "executive", "officer", "chairman", "secretary", "treasurer",
               "representative", "associate", "supervisor", "agent", "broker", "realtor", "principal", "analyst", "administrator"}
COMPANY_WORDS = {"inc", "llc", "ltd", "corp", "corporation", "company", "co", "gmbh", "group", "services", "solutions", "bank",
                 "university", "college", "hospital", "association", "industries", "enterprises", "international", "llp"}

LOOKALIKE = {"rnbber": "rubber", "rubbcr": "rubber", "mian": "main", "akrn": "akron", "akton": "akron", "clevcland": "cleveland",
             "managcr": "manager", "dlrector": "director", "presldent": "president", "cornpany": "company", 
             "gloup": "group", "grnup": "group", "servlces": "services", "assoclates": "associates", "ohlo": "ohio", "strcet": "street",
             "avenuc": "avenue", "sulte": "suite", "unlversity": "university", "hospltal": "hospital", "insurancc": "insurance",
             # round 11 (reviewer r10): more common-word look-alikes (OCR letter swaps rn/m, l/i, c/e, 0/o, dropped letters)
             "akran": "akron", "akorn": "akron", "akrom": "akron", "arkon": "akron", "cantn": "canton", "cantom": "canton",
             "clevland": "cleveland", "clevelnd": "cleveland", "colurnbus": "columbus", "colmbus": "columbus", "ohi0": "ohio",
             "manger": "manager", "rnanager": "manager", "drector": "director", "presdent": "president",
             "presidnet": "president", "coordlnator": "coordinator", "specialst": "specialist", "assistnt": "assistant",
             "consultnt": "consultant", "ofice": "office", "offlce": "office", "rnarketing": "marketing", "markting": "marketing",
             "salse": "sales", "servces": "services", "solutlons": "solutions", "solutons": "solutions", "technolgy": "technology",
             "technologles": "technologies", "industrles": "industries", "internatlonal": "international", "natlonal": "national",
             "assoc1ates": "associates", "partnres": "partners", "pariners": "partners", "constructlon": "construction",
             "rnanufacturing": "manufacturing", "manufactring": "manufacturing", "engineerlng": "engineering", "dlstrict": "district",
             "chamher": "chamber", "charnber": "chamber", "cornmerce": "commerce", "comrnerce": "commerce", "cmmerce": "commerce",
             "rnain": "main", "maln": "main", "strect": "street", "steet": "street", "streeet": "street", "avenne": "avenue",
             "bouleverd": "boulevard", "parkwav": "parkway", "parkwy": "parkway", "plaza": None, "sute": "suite", "flor": "floor",
             "fl0or": "floor", "bldg": None, "rubher": "rubber", "rubbar": "rubber", "tlre": "tire", "tirc": "tire",
             "bakcry": "bakery", "bakeiy": "bakery", "robotlcs": "robotics", "roboties": "robotics", "analytlcs": "analytics",
             "hcalth": "health", "heaith": "health", "rnedical": "medical", "medlcal": "medical", "dental": None, "bnak": "bank",
             "credlt": "credit", "unlon": "union", "lnsurance": "insurance", "realtv": "realty", "propertles": "properties"}
LOOKALIKE = {k: v for k, v in LOOKALIKE.items() if v}
GLUE = ["coffee", "bank", "group", "law", "park", "street", "suite", "city", "robotics", "hardware", "health", "partners", "services",
        "solutions", "company", "realty", "insurance", "dental", "medical", "market", "events", "analytics"]
CAMEL_OK = {"iPhone", "eBay", "YouTube", "LinkedIn", "PayPal", "FedEx", "WordPress", "JavaScript", "McDonald", "PowerPoint", "HubSpot"}
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
    if s.startswith("www.") : return s[4:]
    if s.startswith("www") and "." in s[3:] and len(s) > 8: return s[3:]   # round 12: "wwwsummit…" (dot lost) compares like www.summit…
    return s
def _a(s):
    import unicodedata
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
def _digit_reading(w):
    """Round 15 (manager r14 L-r14-1): 'R1O' is R + a number '10', not 'RIO'. A run of digits and digit-look-alike letters
    (O o I l S) that touches a word END and holds a real digit is read as a number; a single digit between letters
    ('C0LUMBUS') is read as a letter."""
    m = re.search(r"[0-9OoIlS]*\d[0-9OoIlS]*$", w) or re.match(r"^[0-9OoIlS]*\d[0-9OoIlS]*", w)
    if m and len(m.group(0)) >= 2:
        run = m.group(0).translate(str.maketrans("OoIlS", "00115"))
        return w[:m.start()] + run + w[m.end():]
    return re.sub(r"(?<=[A-Za-z])0|0(?=[A-Za-z])", "O", re.sub(r"(?<=[A-Za-z])1|1(?=[A-Za-z])", "I", w))

SUSPICIOUS_WEB = ("phish", "login", "verify", "secure-", "account-", "password", "wallet", "free-", "bonus", "casino", "malware", "evil", "hack")
SUSPICIOUS_HOSTS = ("bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "000webhostapp.com", "ngrok.io", "ngrok-free.app", "blogspot.com")
def website_check(f):
    """Round 15 (mctrade r14 M2): the website must be a valid domain; warn when it matches neither the email domain nor the
    company, or has suspicious words/hosts. Review hints only, never a block."""
    out = []; w = (f.get("website") or "").strip()
    if not w: return out
    host = re.sub(r"^[a-z]+://", "", w.lower()).split("/")[0].split("?")[0].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    if not re.fullmatch(r"(?:xn--)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.(?:xn--)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.(?:[a-z]{2,24}|xn--[a-z0-9-]+)", host or ""):
        return [_sug("website_invalid", "website", f"Website “{w}” is not a valid web address: check it against the photo")]
    bad = [x for x in SUSPICIOUS_WEB if x in host] + [x for x in SUSPICIOUS_HOSTS if host == x or host.endswith("." + x)]
    if bad: out.append(_sug("website_suspicious", "website", f"Website “{w}” looks suspicious ({', '.join(bad)}): confirm it is really printed on the card before approving"))
    core = host.rsplit(".", 1)[0].split(".")[-1]
    from .consistency import FREE, reg, lost_dot
    # round 22 (datamanager r21): free-mail addresses say nothing about the website; subdomains (mail./shop.) are the same
    # site; a lost dot is a hard check of its own (no second line)
    doms = [e.split("@", 1)[1].lower() for e in f.get("emails") or [] if "@" in e]
    doms = [d for d in doms if d not in FREE]
    if any(reg(d) == reg(host) or lost_dot(d, host) for d in doms): doms = []
    comp = re.sub(r"[^a-z0-9]", "", (f.get("company") or "").lower())
    if doms and not any(d == host or d.endswith("." + host) or host.endswith("." + d) for d in doms):
        words = [x for x in re.findall(r"[a-z0-9]{3,}", (f.get("company") or "").lower()) if x not in ("inc", "llc", "the", "and", "company", "corp", "group")]
        if not (comp and (core in comp or any(x in core for x in words))):
            out.append(_sug("website_mismatch", "website", f"Website “{w}” matches neither the email domain ({', '.join(dict.fromkeys(doms))}) nor the company: check it against the photo"))
    return out

def _sug(code, field, text, suggestion=None): return {"code": code, "field": field, "text": text, "suggestion": suggestion}

_RARE2 = set("cd cf cg cj cp cv cw cx db dc dk dp dt dx fc fd fg fh fk fm fn fp fv fw fx gc gd gf gk gp gq gv gx hc hd hf hg hk hp hv hx hz jb jc jd jf jg jh jk jl jm jn jp jq jr js jt jv jw jx jz kc kd kf kg kp kq kv kx kz mk mq mx mz pq pv px pz qa qb qc qd qe qf qg qh qi qj qk ql qm qn qo qp qr qs qt qv qw qx qy qz vb vc vd vf vg vh vj vk vm vn vp vq vt vw vx vz wq wx wz xd xj xk xr xz zb zc zd zf zg zj zk zm zn zp zq zr zs zt zv zw zx".split())
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
        if d not in PROVIDERS and d not in REAL_PROVIDERS:   # ymail.com is Yahoo's real domain, not a misread gmail.com
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
                        out.append(_sug("email_name", "emails", f"Email “{e}” is one letter off the name “{f.get('first_name')} {f.get('last_name')}”: check the spelling of both")); break
    # round 12 (coordinator r4 N1 / reviewer r10): a garbled website, and .co vs .com between website and email
    rw = (f.get("website") or "").strip().lower(); rw_ = re.sub(r"^https?://", "", rw)
    if rw_ and (re.match(r"^www(?!\.)", rw_) or "." not in rw_):
        out.append(_sug("website_format", "website", f"Website “{f.get('website')}” looks misread (a dot is missing)", ("www." + rw_[3:]) if rw_.startswith("www") and "." in rw_[3:] else None))
    if web:
        for e in emails:
            d = e.lower().rsplit("@", 1)[-1]
            if "." not in d or d == web: continue
            wb, wt = web.rsplit(".", 1) if "." in web else (web, ""); db_, dt = d.rsplit(".", 1)
            if wb == db_ and {wt, dt} == {"co", "com"}:
                bad, good = ("website", f"{wb}.com") if wt == "co" else ("emails", e[: -len(dt)] + "com")
                out.append(_sug("tld_co", bad, f"Website “{web}” and email “{e}” differ only in .co / .com: one is probably misread", good if bad == "emails" else ("www." + good)))
                break
        if any(x["code"] == "tld_co" for x in out): out = [x for x in out if x["code"] != "email_web"]
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
        if re.search(r"[\d@/]|www|\.com", v, re.I): out.append(_sug("name_sanity", k, f"{k.replace('_', ' ').title()} “{v}” has a digit or a web address in it"))
        elif v and v.lower().strip(".,") in (TITLE_WORDS | COMPANY_WORDS if k == "first_name" else TITLE_WORDS - {"sales", "agent", "partner"}): out.append(_sug("name_sanity", "name", f"“{v}” looks like a title/company word, not a name"))
    if fn and fn == ln: out.append(_sug("name_sanity", "name", "First and last name are identical"))
    if f.get("first_name") and ln and len(ln) == 1: out.append(_sug("name_sanity", "name", f"Last name “{f.get('last_name')}” is a single letter"))
    t = f.get("title") or ""
    if re.search(r"@|www\.|\.com\b|\d{3}[-. )]\d{3}", t, re.I):
        out.append(_sug("title_sanity", "title", f"Title “{t}” looks like it contains other text (phone/email/address)"))
    # round 7 (part-timer r1): words glued by OCR, e.g. 'StSuite 210', 'Squarecoffee', 'CityRobotics'
    for k, label in (("company", "Company"), ("address", "Address"), ("title", "Title")):
        v = f.get(k) or ""
        g = re.search(r"\b(?:[A-Z][a-z]+|[a-z]{2,})[A-Z][a-z]+", v) or next((m for m in re.finditer(r"\b([A-Z][a-z]{3,})(" + "|".join(GLUE) + r")\b", v)), None)
        if g and not re.fullmatch(r"(?:Mc|Mac|De|La|Le|Van|Von|O)[A-Z][a-z]+", g.group(0)) and g.group(0) not in CAMEL_OK:
            out.append(_sug("glued_words", k, f"{label} “{g.group(0)}” looks like two words run together: check the spacing"))
    # round 7 (reviewer r7): OCR look-alike letters in common words ('Rnbber' -> 'Rubber', 'Mian St' -> 'Main St')
    for k, label in (("company", "Company"), ("title", "Title"), ("address", "Address")):
        v = f.get(k) or ""
        fixed, words = v, []   # round 11 (reviewer r10): every misread word is listed ("Mian St, Akrn" -> both), in one hint
        for w in re.findall(r"[A-Za-z]{3,}", v):
            fix = LOOKALIKE.get(w.lower())
            if fix:
                good = fix.capitalize() if w[0].isupper() else fix
                words.append(f"“{w}” is probably “{good}”"); fixed = re.sub(r"\b" + re.escape(w) + r"\b", good, fixed)
        if words: out.append(_sug("ocr_lookalike", k, f"{label}: " + "; ".join(words) + " (letters misread)", fixed))
    # round 11 (reviewer r10): a street address with a city but no state / zip
    ad = (f.get("address") or "").strip()
    if ad and re.match(r"^\d+\s", ad) and "," in ad and not re.search(r"\b[A-Z]{2}\b\.?\s*\d{5}(-\d{4})?\s*$|\b\d{5}(-\d{4})?\s*$", ad):
        out.append(_sug("addr_incomplete", "address", "Address has no state and/or zip code: check the photo"))
    # round 8 (part-timer r2): 'Akron. OH 44308' -> a misread comma before the state
    a_ = f.get("address") or ""
    mm = re.search(r"\b([A-Z][a-z]{2,})\. ([A-Z]{2})\b(?=\s*(?:\d{5}|$))", a_)
    if mm: out.append(_sug("addr_punct", "address", f"Address “{mm.group(0)}”: the “.” before the state is probably a misread “,”", a_.replace(mm.group(0), f"{mm.group(1)}, {mm.group(2)}")))
    c = f.get("company") or ""
    if c and (fn or ln) and _a(c) in (fn + ln, ln + fn) and len(_a(c)) > 3:
        out.append(_sug("company_sanity", "company", "Company is the same as the person's name"))
    elif re.search(r"@|\d{3}[-. )]\d{3}[-. ]\d{4}", c):
        out.append(_sug("company_sanity", "company", f"Company “{c}” contains an email or phone number"))
    # round 13 (manager r11 L-r11-1): a digit/letter mix-up inside a company word ("R1O Testworks": 1 / O)
    for w_ in re.findall(r"[A-Za-z0-9]+", c):
        if re.search(r"[A-Za-z]", w_) and re.search(r"\d", w_) and re.search(r"(?<=\d)[OoIlS]|[OoIlS](?=\d)|(?<=[A-Za-z])[015](?=[A-Za-z])|[01](?=[OoIl])|(?<=[OoIl])[01]", w_):
            fx = _digit_reading(w_)
            alt = re.sub(r"(?<=[A-Za-z])0|0(?=[A-Za-z])", "O", re.sub(r"(?<=[A-Za-z])1|1(?=[A-Za-z])", "I", w_))
            both = [x for x in dict.fromkeys([fx, alt]) if x != w_]
            out.append(_sug("company_digits", "company", f"Company word “{w_}” mixes digits and letters (0/O, 1/I/l, 5/S): check it against the photo"
                            + (f" (it may read “{both[0]}”" + (f" or “{both[1]}”" if len(both) > 1 else "") + ")" if both else ""), c.replace(w_, fx) if fx != w_ else None)); break
    # round 21 (newcomer/datamanager r20): gibberish company words ("Higneniscdaie CoffeeCa")
    for w_ in re.findall(r"[A-Za-z]+", c):
        rare = sum(1 for i in range(len(w_) - 1) if w_[i:i + 2].lower() in _RARE2)
        if re.search(r"[a-z]{3,}[A-Z][a-z]?$", w_) or (len(w_) >= 10 and rare >= 1) or rare >= 2 or re.search(r"[bcdfghjklmnpqrstvwxz]{5,}", w_.lower()):
            out.append(_sug("company_gibberish", "company", f"Company word “{w_}” doesn't look like a real word: check it against the photo")); break
    if not any(x["field"] == "website" and x["code"] == "email_web" for x in out): out += website_check(f)
    seen, uniq = set(), []   # round 11 (reviewer r10): each hint once
    web_ = [x for x in out if x["field"] == "website"]   # round 20 (coordinator r19): ONE website line, not 2-3 repeats
    if len(web_) > 1:
        keep_ = dict(next((x for x in web_ if x.get("suggestion")), web_[0]))
        keep_["codes"] = [x["code"] for x in web_]
        keep_["text"] = f"Website “{f.get('website')}” looks misread: check it against the photo"
        out = [x for x in out if x["field"] != "website"] + [keep_]
    for x in out:
        key = (x["field"], x["text"])
        if key not in seen: seen.add(key); uniq.append(x)
    return uniq

def apply(f):
    """Attach suggestions under f['suggestions']; does not touch values, confidence or needs_review."""
    f["suggestions"] = check(f); return f
