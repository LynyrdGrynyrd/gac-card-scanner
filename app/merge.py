"""Merge rule-based fields with local VLM output. Rules stay authoritative for regex-verifiable fields
(emails/phones/website); the VLM wins on layout-semantic fields (name/title/company/address) when it is
supported by OCR evidence or fills a gap. Anything VLM-only is flagged for review (confidence 0.5)."""
import re
from difflib import SequenceMatcher
from . import parser as P

def _n(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _tc(s):
    s = (s or "").strip()
    return " ".join(w.capitalize() if w.isupper() and len(w) > 3 else w for w in s.split()) if s.isupper() else s
def support(val, ocr):
    """fraction of value tokens found (fuzzily) in the OCR text"""
    toks = [t for t in re.findall(r"[A-Za-z0-9]{2,}", val or "")]
    if not toks: return 0.0
    words = re.findall(r"[A-Za-z0-9]{2,}", ocr)
    words_l = [w.lower() for w in words]; blob = _n(ocr)
    hit = 0
    for t in toks:
        tl = t.lower()
        if tl in words_l or tl in blob or any(SequenceMatcher(None, tl, w).ratio() >= 0.8 for w in words_l): hit += 1
    return hit / len(toks)
def merge(f, v, ocr_text):
    f = dict(f); conf = dict(f.get("confidence", {})); src = {}
    if not isinstance(v, dict) or v.get("_error"): return f
    g = lambda k: v.get(k) if isinstance(v.get(k), str) else ""
    # ---- name
    vf, vl = _tc(g("first_name")), _tc(g("last_name"))
    if vf or vl:
        locals_ = [re.sub(r"[^a-z]", "", e.split("@")[0].lower()) for e in f.get("emails", [])]
        def nscore(fn, ln):
            if not fn: return -1
            s = support(f"{fn} {ln}", ocr_text)
            s += 1 if P._first_name(fn) else 0
            s += 1 if any(len(x) >= 3 and x.lower() in lp for lp in locals_ for x in (fn, ln)) else 0
            return s
        rs, vs = nscore(f.get("first_name"), f.get("last_name")), nscore(vf, vl)
        if _n(vf + vl) == _n(f.get("first_name", "") + f.get("last_name", "")) and vf: conf["name"] = 0.95
        elif vs >= rs and vs > 0:
            f["first_name"], f["last_name"] = vf, vl.split()[-1] if vl else vl; src["name"] = "vlm"
            conf["name"] = 0.75 if vs >= 2 else 0.5
        else: conf["name"] = min(conf.get("name") or 0.6, 0.55)  # disagreement -> review
    # ---- company / title / department / address
    for k, prefer_longer in (("company", True), ("title", True), ("department", False), ("address", True)):
        vv = _tc(g(k)) if k != "address" else g(k)
        rv = f.get(k) or ""
        if not vv: continue
        sup = support(vv, ocr_text)
        if _n(vv) == _n(rv): conf[k] = 0.95; continue
        take = False
        if not rv:
            take = sup >= 0.5 or k == "company"
            if k == "department" and not P.DEPT.search(vv): take = False
            if k == "title" and (not P.TITLE.search(vv) or _n(vv) in (_n(f.get("company")), _n(f.get("credentials")))): take = False
        elif _n(rv) in _n(vv) and prefer_longer and sup >= 0.6: take = True          # VLM completes a truncated value
        elif (conf.get(k) or 0) < 0.6 and sup >= 0.5: take = True                   # rules unsure
        elif k == "company" and sup < 0.5 and (conf.get(k) or 0) < 0.8: take = True  # logo text OCR could not read
        if take:
            f[k] = vv; src[k] = "vlm"; conf[k] = 0.8 if sup >= 0.8 else (0.6 if sup >= 0.5 else 0.5)
        else: conf[k] = min(conf.get(k) or 0.7, 0.55) if sup >= 0.6 else conf.get(k)
    # ---- regex-verifiable fields: fill gaps only when OCR digits/letters support it
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
            pass  # rules keep the type (they see the printed label)
        elif d[-7:] in od:
            f["phones"].append({"type": t, "number": str(p["number"]), "valid": len(d) >= 10}); have.add(d[-7:]); src["phones"] = "vlm"
    no_mail = P.EMAIL.sub(" ", ocr_text)
    vw = re.sub(r"^(https?://)?(www\.)?", "", g("website").strip().lower())
    # VLM website must look like a domain and the whole domain must be printed outside an email address
    # (stops "chicago illinois" or a domain guessed from the email / company name)
    if not f.get("website") and re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(/\S*)?", vw) and _n(vw.split("/")[0]) in _n(no_mail) and not P.SOCIAL.search(vw) \
            and _n(ocr_text).count(_n(vw.split("/")[0])) > sum(e.lower().endswith("@" + vw.split("/")[0]) for e in f.get("emails", [])):
        f["website"] = g("website").lower(); src["website"] = "vlm"; conf["website"] = 0.6
    f["confidence"] = conf; f["vlm_fields"] = src
    vals = [x for x in conf.values() if x is not None]
    f["overall_confidence"] = round(min(sum(vals) / len(vals), min(vals) + 0.25), 2) if vals else 0.0
    f["needs_review"] = [k for k, x in conf.items() if x is not None and x < 0.6]
    return f
