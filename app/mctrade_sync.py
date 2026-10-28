"""STUB MCTrade (MemberClicks MC Trade / Atlas API) sync. DRY-RUN ONLY: never performs network calls.
Real API (per public docs): OAuth2 client_credentials at https://www.weblinkauth.com/connect/token,
scope=PublicWebApi, acr_values=tenant:<SiteID>; Bearer token on tenant API host. Exact profile
create/update endpoint paths are UNVERIFIED (Developers Guide is gated / not fully public) -> placeholders below."""
import csv, os, re
try:   # RapidFuzz (MIT): faster, and token_sort handles swapped first/last name order
    from rapidfuzz import fuzz as _fz
    def _ratio(a, b): return _fz.ratio(a, b) / 100
    def _name_ratio(a, b): return _fz.token_sort_ratio(a, b) / 100
except ImportError:
    from difflib import SequenceMatcher
    def _ratio(a, b): return SequenceMatcher(None, a, b).ratio()
    def _name_ratio(a, b): return _ratio(" ".join(sorted(a.split())), " ".join(sorted(b.split())))
SAMPLE = os.path.join(os.path.dirname(__file__), "..", "data", "existing_contacts.csv")
DRY_RUN = True  # hard-coded; there is intentionally no live code path

from functools import lru_cache
def _digits(s): return re.sub(r"\D", "", s or "")[-10:]
@lru_cache(maxsize=65536)   # round 13 (reviewer r11): pure string helpers are cached; the queue list called them ~100k times
def fold(s):
    """Round 11 (mctrade-r7 F3): accents are folded before names are compared ('María Délgado' = 'Maria Delgado')."""
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch))
@lru_cache(maxsize=65536)
def _norm(s): return re.sub(r"[^a-z0-9]", "", fold(s).lower())
@lru_cache(maxsize=65536)
def _nname(s): return " ".join(re.sub(r"[^a-z ]", "", fold(s).lower()).split())
# v0.4.9 #3 (skeptic: 'Co' vs 'Co.', '+gac' emails slipped past): one normaliser for emails and company names
@lru_cache(maxsize=65536)
def norm_email(e):
    """'D.Lawson+gac@X.com ' -> 'd.lawson@x.com' (case, spaces and a '+tag' ignored)."""
    e = (e or "").strip().lower()
    if "@" not in e: return e
    loc, _, dom = e.rpartition("@")
    return re.split(r"[+\s]", loc, maxsplit=1)[0] + "@" + dom.strip()
CO_SUFFIX = {"co", "company", "inc", "incorporated", "llc", "lc", "ltd", "limited", "corp", "corporation", "plc", "lp", "llp",
             "pllc", "pc", "gmbh", "the"}
@lru_cache(maxsize=65536)
def norm_company(s):
    """'The Acme Co.' = 'Acme Company' = 'ACME, Inc' -> 'acme' (case, punctuation, '&'/'and' and legal suffixes ignored)."""
    w = re.sub(r"[^a-z0-9]+", " ", fold(s).lower().replace("&", " and ").replace("l.l.c", "llc")).split()
    w = [x for x in w if x != "and"]
    core = list(w)
    while core and core[-1] in CO_SUFFIX: core.pop()
    while core and core[0] == "the": core.pop(0)
    return "".join(core or w)
def load_existing(path=SAMPLE):
    with open(path, encoding="utf-8", newline="") as fh: return list(csv.DictReader(fh))

def match(fields, existing=None, near_names=False):
    existing = existing if existing is not None else load_existing()
    emails = {norm_email(e) for e in fields.get("emails", [])}
    phones = {_digits(p["number"]) for p in fields.get("phones", [])}
    name = _nname(fields.get("first_name","") + " " + fields.get("last_name",""))
    co = norm_company(fields.get("company",""))
    res = []
    for r in existing:
        score, why = 0.0, []
        if emails & {norm_email(x) for x in (r.get("emails") or [r.get("email")]) if x}: score += 0.6; why.append("email exact")
        if _digits(r["phone"]) and _digits(r["phone"]) in phones: score += 0.25; why.append("phone exact")
        ns = _name_ratio(name, _nname(r["first_name"] + " " + r["last_name"])) if name else 0
        if ns > 0.85: score += 0.25*ns; why.append(f"name~{ns:.2f}")
        cs = _ratio(co, norm_company(r["organization"])) if co else 0
        if cs > 0.7: score += 0.15*cs; why.append(f"org~{cs:.2f}")
        # round 9 (mctrade-r6 F1): an exact First+Last alone (0.25) is a match too
        if score >= 0.3 or ns >= 0.99 or (near_names and ns >= 0.9): res.append({"profile_id": r["profile_id"], "name": f"{r['first_name']} {r['last_name']}",
                                     "organization": r["organization"], "score": round(min(score,1),2), "why": why})
    return sorted(res, key=lambda x: -x["score"])

class Index:
    """Audit 2026-10 P1: the review list compared every card with EVERY contact (16-19 s for a 200-card batch against a
    10,000-row MC Trade export). A contact can only reach match()'s threshold through the same email, the same phone or a
    name similarity above 0.85 (company similarity alone tops out at 0.15), so those three lookups find every candidate;
    match() then scores just those, exactly as before. Built once per contacts file."""
    def __init__(self, rows):
        self.rows = rows; self.by_email = {}; self.by_phone = {}
        self.byid = {str(r["profile_id"]): r for r in rows}
        self.names = [_nname(r.get("first_name", "") + " " + r.get("last_name", "")) for r in rows]
        for i, r in enumerate(rows):
            for x in {norm_email(x) for x in (r.get("emails") or [r.get("email")]) if x}: self.by_email.setdefault(x, []).append(i)
            d = _digits(r.get("phone"))
            if d: self.by_phone.setdefault(d, []).append(i)
    def candidates(self, fields):
        hit = set()
        for e in fields.get("emails", []): hit.update(self.by_email.get(norm_email(e), ()))
        for p in fields.get("phones", []): hit.update(self.by_phone.get(_digits(p.get("number")), ()))
        name = _nname(fields.get("first_name", "") + " " + fields.get("last_name", ""))
        if name:
            try:
                from rapidfuzz import process, fuzz
                hit.update(i for _, _, i in process.extract(name, self.names, scorer=fuzz.token_sort_ratio, score_cutoff=85, limit=None))
            except ImportError:
                return self.rows   # no RapidFuzz: compare with everything, as before
        return [self.rows[i] for i in sorted(hit)]
    def match(self, fields, near_names=False):
        return match(fields, self.candidates(fields), near_names=near_names)

def to_mctrade_profile(f):
    """Maps to MC Trade import-template style columns ('Ind' prefix for individual profiles)."""
    ph = {p["type"]: p["number"] for p in f.get("phones", [])}
    return {"OrgInd": "Ind", "IndFirstName": f["first_name"], "IndLastName": f["last_name"], "IndTitle": f["title"],
            "OrgName": f["company"], "IndEmail": (f["emails"] or [""])[0], "IndPhone": ph.get("work",""),
            "IndCellPhone": ph.get("mobile",""), "IndFax": ph.get("fax",""), "WebAddress": f["website"],
            "Address": f["address"], "AffCode1": "CardScan-Pilot"}
