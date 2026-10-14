"""Real-card post-processing (realcards prototype). Pure clean-ups of the merged fields; runs after OCR(+VLM) merge.
Each rule only fires on a narrow, verifiable pattern. Env REALCARD_POSTFIX=0 disables."""
import re

def _n(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _d(s): return re.sub(r"\D", "", s or "")
def _ed(a, b):
    if abs(len(a) - len(b)) > 2: return 9
    p = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        q = [i]
        for j, cb in enumerate(b, 1): q.append(min(p[j] + 1, q[j - 1] + 1, p[j - 1] + (ca != cb)))
        p = q
    return p[-1]
def _dom(s):
    s = re.sub(r"^(https?://)?(www\.)?", "", (s or "").strip().lower()); return s.split("/")[0]

def apply(f: dict) -> dict:
    phones = f.get("phones") or []
    addr_d = _d(f.get("address")) + " " + _d(f.get("other_address"))
    # 1. a postal code read as a phone (Japanese "〒187-8531")
    phones = [p for p in phones if not (len(_d(p.get("number"))) <= 8 and not p.get("valid", True) and _d(p.get("number")) in addr_d)]
    # 2. the same number twice, once with an extension: keep the one with the extension
    out = []
    for p in phones:
        d = _d(re.split(r"(?i)\b(ext|x)\b", p.get("number", ""))[0])
        if any(q is not p and _d(re.split(r"(?i)\b(ext|x)\b", q.get("number", ""))[0]) == d and len(_d(q["number"])) > len(_d(p["number"])) for q in phones): continue
        if any(_d(q.get("number")) == _d(p.get("number")) for q in out): continue
        out.append(p)
    f["phones"] = out
    # 3. title that repeats the name or ends with the company
    t = f.get("title") or ""; fn, ln = f.get("first_name") or "", f.get("last_name") or ""
    if t and fn and ln and fn.isascii() and ln.isascii():
        m = re.match(r"^\s*" + re.escape(fn) + r"\b.*?\b" + re.escape(ln) + r"\b[^,|]*[,|]\s*", t, re.I)
        if m and t[m.end():].strip(): t = t[m.end():].strip()
    co = f.get("company") or ""
    if co and "," in t and _n(t.rsplit(",", 1)[1]) == _n(co): t = t.rsplit(",", 1)[0].strip()
    if t != (f.get("title") or ""): f["title"] = t
    # 4. email domain one or two letters off the printed website domain; or a leading "|" misread into the website
    wd = _dom(f.get("website"))
    if wd and "." in wd:
        em = []
        for e in f.get("emails") or []:
            loc, _, dom = e.partition("@")
            if dom and wd[1:] == dom.lower() and wd[0] in "il1|":
                f["website"] = re.sub(re.escape(wd), dom.lower(), f["website"], flags=re.I); wd = dom.lower()
            elif dom and dom.lower() != wd and 0 < _ed(dom.lower(), wd) <= 2 and dom.rsplit(".", 1)[-1] == wd.rsplit(".", 1)[-1]:
                e = loc + "@" + wd
            em.append(e)
        f["emails"] = em
    # 5. company garbled from a stylised logo while the email domain spells it
    doms = {e.split("@")[-1].lower().split(".")[0] for e in f.get("emails") or [] if "@" in e}
    if co and " " not in co.strip():
        for dm in doms:
            if len(dm) >= 5 and 0 < _ed(_n(co), dm) <= 2:
                f["company"] = dm.capitalize() if co.islower() or co.isupper() or co[0].islower() else co; break
    # 6. address that starts with the company name
    a = f.get("address") or ""; co = f.get("company") or ""
    if co and a and "," in a and _n(a.split(",", 1)[0]) == _n(co): f["address"] = a.split(",", 1)[1].strip()
    # 7. look-alike letters in an email local part: only single known OCR confusions (i/l, cl/d, rn/m, 0/o, 1/l, vv/w),
    #    and only when the swap turns the local into an exact name pattern (jdoe, john.doe, johndoe, doej). Never deletes letters.
    fn, ln = f.get("first_name") or "", f.get("last_name") or ""
    if fn and ln and fn.isascii() and ln.isascii():
        F, L = re.sub(r"[^a-z]", "", fn.lower()), re.sub(r"[^a-z]", "", ln.lower())
        pats = {F[:1] + L, F + L, L + F[:1], F + "." + L, F[:1] + "." + L, F + "_" + L, L}
        PAIRS = [("i", "l"), ("l", "i"), ("cl", "d"), ("d", "cl"), ("rn", "m"), ("m", "rn"), ("0", "o"), ("1", "l"), ("vv", "w")]
        em = []
        for e in f.get("emails") or []:
            loc, _, dom = e.partition("@")
            if dom and loc.lower() not in pats:
                lo = loc.lower(); hit = None
                for a_, b_ in PAIRS:
                    for i in [m.start() for m in re.finditer(re.escape(a_), lo)]:
                        c = lo[:i] + b_ + lo[i + len(a_):]
                        if c in pats: hit = c; break
                    if hit: break
                if hit: e = hit + "@" + dom
            em.append(e)
        f["emails"] = em
        # ß restore from email ("GroBhauser" + "grosshauser@")
        if "B" in ln and any("ss" in x.split("@")[0].lower() for x in f["emails"]):
            trial = re.sub(r"(?<=[a-z])B(?=[a-z])", "ß", ln)
            if trial != ln and any(re.sub(r"[^a-z]", "", trial.replace("ß", "ss").lower()) in x.split("@")[0].lower() for x in f["emails"]):
                f["last_name"] = trial
    # 8. look-alike: letter O for digit 0 inside a street number ("1O E. Firestone")
    a = f.get("address") or ""
    if a:
        a2 = re.sub(r"(?<=\d)O(?=\s|[A-Za-z]|\.|$)", "0", a)
        a2 = re.sub(r"(^|[\s,])O(?=\d)", r"\g<1>0", a2)
        if a2 != a: f["address"] = a2
    return f
