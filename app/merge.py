"""Merge rule-based fields with local VLM output. Rules stay authoritative for regex-verifiable fields
(emails/phones/website); the VLM wins on layout-semantic fields (name/title/company/address) when it is
supported by OCR evidence or fills a gap. Anything VLM-only is flagged for review (confidence 0.5)."""
import copy, re
from difflib import SequenceMatcher
from . import parser as P

def _n(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _nu(s):
    """Like _n but keeps letters from any script (CJK, Greek, ...) so Japanese/German names can match."""
    s = (s or "").casefold().replace("ß", "ss")
    return "".join(ch for ch in s if ch.isalnum())
def _tc(s):
    s = (s or "").strip()
    return " ".join(w.capitalize() if w.isupper() and len(w) > 3 else w for w in s.split()) if s.isupper() else s
def support(val, ocr):
    """fraction of value tokens found (fuzzily) in the OCR text; accepts letters from any script"""
    toks = [t for t in re.findall(r"[^\W_]{2,}", val or "", flags=re.UNICODE)]
    if not toks: return 0.0
    words = re.findall(r"[^\W_]{2,}", ocr or "", flags=re.UNICODE)
    words_l = [w.casefold() for w in words]; blob = _nu(ocr)
    hit = 0
    for t in toks:
        tl = t.casefold()
        if tl in words_l or _nu(t) in blob or any(SequenceMatcher(None, tl, w).ratio() >= 0.8 for w in words_l): hit += 1
    return hit / len(toks)

# a VLM "department" that is really a job role or a tagline (tuned on even cards; keep narrow)
_TAGLINE = re.compile(r"(?i)\b(engineered|curiosity|discovery|innovation!|serving |www\.|http|llc\b|inc\b|ltd\b)\b")
_LIST_TAG = re.compile(r",\s*(and|&)\s+\w", re.I)   # "A, B, and C" capability line, not a department (card-27 class)
def _dept_ok(vv, title, company, vtitle=""):
    if not vv or len(vv) < 3: return False
    # the model's own title already carries it ("Scientist - Formulations"): it is a title suffix, not a department
    if vtitle and _nu(vv) and _nu(vv) != _nu(vtitle) and _nu(vtitle).endswith(_nu(vv)): return False
    if _LIST_TAG.search(vv): return False
    if _nu(vv) in (_nu(title), _nu(company)): return False
    if _nu(vv) and (_nu(vv) in _nu(title) or _nu(vv) in _nu(company)): return False
    if _TAGLINE.search(vv): return False
    # starts with a role word/acronym ("CIO (Chief ...)", "Director of ...") -> that is a title, not a department
    if re.match(r"(?i)\s*(ceo|cfo|coo|cto|cio|cmo|vp|svp|evp|president|director|manager|chief|head|officer)\b", vv): return False
    # a bare title word with no department-ish marker is a role, not a department
    if P.TITLE.search(vv) and not re.search(r"(?i)\b(dept|department|division|section|program|lab|office|school|college|center|centre|institute|faculty|group|unit|team|science|technology|engineering|operations|planning|services|solutions|materials|procurement|acquisition|cooperation|transfer|innovation)\b", vv):
        return False
    return True

def merge(f, v, ocr_text):
    f = copy.deepcopy(f); conf = dict(f.get("confidence") or {}); src = {}   # audit 2026-10 (F10): pure; phone dicts/list were shared with the caller
    if not isinstance(v, dict) or v.get("_error"): return f
    g = lambda k: v.get(k) if isinstance(v.get(k), str) else ""
    # ---- name (Latin + non-Latin)
    vf, vl = g("first_name").strip(), g("last_name").strip()
    if vf or vl:
        # keep VLM casing for non-Latin; title-case Latin all-caps only
        if vf.isascii(): vf = _tc(vf)
        if vl.isascii(): vl = _tc(vl)
        locals_ = [re.sub(r"[^a-z]", "", e.split("@")[0].lower()) for e in f.get("emails", [])]
        # "GroBhauser": OCR/VLM read ß as B. If the B->ss spelling is in an email local part, restore ß.
        if re.search(r"[a-z]B[a-z]", vl) and any(re.sub(r"[^a-z]", "", vl.replace("B", "ss").lower()) in lp for lp in locals_):
            vl = vl.replace("B", "ß")
        def nscore(fn, ln):
            if not fn: return -1
            s = support(f"{fn} {ln}", ocr_text)
            if fn.isascii() and P._first_name(fn): s += 1
            # non-Latin: OCR support alone is enough (gender lexicons are Latin-only)
            if not fn.isascii() and support(fn, ocr_text) >= 0.8: s += 1
            s += 1 if any(len(x) >= 3 and x.lower() in lp for lp in locals_ for x in (fn, ln) if x.isascii()) else 0
            # email local contains a transliteration of a non-Latin name ("strassmann" vs "Straßmann")
            if any(_nu(ln) and _nu(ln)[:4] in lp for lp in locals_): s += 1
            return s
        rs, vs = nscore(f.get("first_name"), f.get("last_name")), nscore(vf, vl)
        if _nu(vf + vl) == _nu(f.get("first_name", "") + f.get("last_name", "")) and vf: conf["name"] = 0.95
        elif vs >= rs and vs > 0:
            f["first_name"], f["last_name"] = vf, (P.surname(vl) if vl and vl.isascii() else vl); src["name"] = "vlm"
            conf["name"] = 0.75 if vs >= 2 else 0.5
        else: conf["name"] = min(conf.get("name") or 0.6, 0.55)
    # ---- company / title / department / address
    for k, prefer_longer in (("company", True), ("title", True), ("department", False), ("address", True)):
        vv = (_tc(g(k)) if k != "address" and g(k).isascii() else g(k))
        rv = f.get(k) or ""
        if not vv: continue
        # prefer VLM Unicode over a Latin-garbled OCR company/title when scripts differ
        if k in ("company", "title", "department") and not vv.isascii() and rv.isascii() and support(vv, ocr_text) >= 0.5:
            f[k] = vv; src[k] = "vlm"; conf[k] = 0.7; continue
        # ß / digraph: VLM "GroBhauser"-style already handled in name; for company keep printed form
        if k == "title" and g("department") and _nu(rv) == _nu(vv + g("department")) and _dept_ok(g("department"), vv, f.get("company") or ""):
            f[k] = vv; src[k] = "vlm"; conf[k] = 0.8; continue
        sup = support(vv, ocr_text)
        if _nu(vv) == _nu(rv): conf[k] = 0.95; continue
        take = False
        if not rv:
            take = sup >= 0.5 or k == "company"
            if k == "department" and not _dept_ok(vv, f.get("title") or "", f.get("company") or "", g("title")): take = False
            elif k == "department" and not P.DEPT.search(vv) and sup < 0.8: take = False
            if k == "title" and (not P.TITLE.search(vv) or _nu(vv) in (_nu(f.get("company")), _nu(f.get("credentials")))): take = False
        elif k == "department" and _dept_ok(vv, f.get("title") or "", f.get("company") or "", g("title")) and (
                _nu(rv) in (_nu(f.get("title")), _nu(f.get("company"))) or (not P.DEPT.search(rv) and P.TITLE.search(rv))):
            take = True   # rules put the title/company in the department slot
        elif _nu(rv) in _nu(vv) and prefer_longer and sup >= 0.6: take = True
        elif (conf.get(k) or 0) < 0.6 and (sup >= 0.5 if k != "department" else (_dept_ok(vv, f.get("title") or "", f.get("company") or "", g("title")) and sup >= 0.8)): take = True
        elif k == "company" and (sup < 0.5 or not vv.isascii()) and (conf.get(k) or 0) < 0.8: take = True
        if take:
            f[k] = vv; src[k] = "vlm"; conf[k] = 0.8 if (k != "department" and sup >= 0.8) or (k == "department" and _dept_ok(vv, f.get("title") or "", f.get("company") or "", g("title"))) else (0.6 if sup >= 0.5 else 0.5)
        else: conf[k] = min(conf.get(k) or 0.7, 0.55) if (k != "department" and sup >= 0.6) else conf.get(k)
    # fill a blank department from the VLM when the guard passes (even if rules already had a value that was a title)
    vd = g("department")
    if vd and _dept_ok(vd, f.get("title") or "", f.get("company") or "", g("title")) and support(vd, ocr_text) >= 0.8:
        rv = f.get("department") or ""
        if not rv or _nu(rv) in (_nu(f.get("title")), _nu(f.get("company"))) or (P.TITLE.search(rv) and not P.DEPT.search(rv)):
            if _nu(rv) != _nu(vd):
                f["department"] = vd if not vd.isascii() else _tc(vd); src["department"] = "vlm"; conf["department"] = 0.75
    # ---- emails: fill gaps only
    ve = [e.lower() for e in (v.get("emails") or []) if isinstance(e, str) and P.EMAIL.fullmatch(e.strip())]
    if not f.get("emails") and ve:
        ok = [e for e in ve if support(e, ocr_text) >= 0.6]
        if ok: f["emails"] = ok; src["emails"] = "vlm"; conf["emails"] = 0.6
    od = re.sub(r"\D", "", ocr_text)
    have = {re.sub(r"\D", "", p["number"])[-7:] for p in f.get("phones", [])}
    TYPES = {"cell": "mobile", "cellular": "mobile", "mobile": "mobile", "fax": "fax", "home": "home", "work": "work", "office": "work", "phone": "work", "tel": "work"}
    for p in (v.get("phones") or []):
        if not isinstance(p, dict) or not p.get("number"): continue
        d = re.sub(r"\D", "", str(p["number"])); t = TYPES.get(str(p.get("type", "work")).lower(), "work")
        if len(d) < 5: continue
        if d[-7:] in have:
            for q in f.get("phones", []):
                if re.sub(r"\D", "", q["number"])[-7:] == d[-7:] and q.get("type") == "work" and t in ("mobile", "fax"):
                    q["type"] = t; src["phone_types"] = "vlm"
        elif d[-7:] in od:
            f["phones"].append({"type": t, "number": str(p["number"]), "valid": len(d) >= 10}); have.add(d[-7:]); src["phones"] = "vlm"
        else:
            # fix 3 (realcards): a valid international number the OCR missed. Keep it, flag for review.
            num = str(p["number"]).strip()
            ok = num.startswith("+") and len(d) >= 10
            if not ok:
                try:
                    import phonenumbers as _pn
                    ok = _pn.is_possible_number(_pn.parse(num if num.startswith("+") else "+" + d, None))
                except Exception: ok = False
            if ok:
                f["phones"].append({"type": t, "number": num, "valid": True}); have.add(d[-7:])
                src["phones"] = "vlm"; conf["phones"] = min(conf.get("phones") or 0.5, 0.5)
                nr = list(f.get("needs_review") or []); 
                if "phones" not in nr: f["needs_review"] = nr + ["phones"]
    no_mail = P.EMAIL.sub(" ", ocr_text)
    vw = re.sub(r"^(https?://)?(www\.)?", "", g("website").strip().lower())
    if not f.get("website") and re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(/\S*)?", vw) and _n(vw.split("/")[0]) in _n(no_mail) and not P.SOCIAL.search(vw) \
            and _n(ocr_text).count(_n(vw.split("/")[0])) > sum(e.lower().endswith("@" + vw.split("/")[0]) for e in f.get("emails", [])):
        f["website"] = g("website").lower(); src["website"] = "vlm"; conf["website"] = 0.6
    f["confidence"] = conf; f["vlm_fields"] = src
    vals = [x for x in conf.values() if x is not None]
    f["overall_confidence"] = round(min(sum(vals) / len(vals), min(vals) + 0.25), 2) if vals else 0.0
    nr = list(f.get("needs_review") or [])
    for k, x in conf.items():
        if x is not None and x < 0.6 and k not in nr: nr.append(k)
    f["needs_review"] = nr
    return f
