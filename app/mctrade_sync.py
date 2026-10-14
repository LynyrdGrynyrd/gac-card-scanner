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

def _digits(s): return re.sub(r"\D", "", s or "")[-10:]
def _norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _nname(s): return " ".join(re.sub(r"[^a-z ]", "", (s or "").lower()).split())
def load_existing(path=SAMPLE):
    with open(path) as fh: return list(csv.DictReader(fh))

def match(fields, existing=None):
    existing = existing if existing is not None else load_existing()
    emails = {e.lower() for e in fields.get("emails", [])}
    phones = {_digits(p["number"]) for p in fields.get("phones", [])}
    name = _nname(fields.get("first_name","") + " " + fields.get("last_name",""))
    co = _norm(fields.get("company",""))
    res = []
    for r in existing:
        score, why = 0.0, []
        if r["email"] and r["email"].lower() in emails: score += 0.6; why.append("email exact")
        if _digits(r["phone"]) and _digits(r["phone"]) in phones: score += 0.25; why.append("phone exact")
        ns = _name_ratio(name, _nname(r["first_name"] + " " + r["last_name"])) if name else 0
        if ns > 0.85: score += 0.25*ns; why.append(f"name~{ns:.2f}")
        cs = _ratio(co, _norm(r["organization"])) if co else 0
        if cs > 0.7: score += 0.15*cs; why.append(f"org~{cs:.2f}")
        if score >= 0.3: res.append({"profile_id": r["profile_id"], "name": f"{r['first_name']} {r['last_name']}",
                                     "organization": r["organization"], "score": round(min(score,1),2), "why": why})
    return sorted(res, key=lambda x: -x["score"])

def to_mctrade_profile(f):
    """Maps to MC Trade import-template style columns ('Ind' prefix for individual profiles)."""
    ph = {p["type"]: p["number"] for p in f.get("phones", [])}
    return {"OrgInd": "Ind", "IndFirstName": f["first_name"], "IndLastName": f["last_name"], "IndTitle": f["title"],
            "OrgName": f["company"], "IndEmail": (f["emails"] or [""])[0], "IndPhone": ph.get("work",""),
            "IndCellPhone": ph.get("mobile",""), "IndFax": ph.get("fax",""), "WebAddress": f["website"],
            "Address": f["address"], "AffCode1": "CardScan-Pilot"}

def plan(card):
    m = match(card["fields"])
    top = m[0] if m else None
    if top and top["score"] >= 0.6:
        action = {"op": "UPDATE (would PATCH/PUT profile)", "method": "PUT", "path": f"<tenant>/api/v1/profiles/{top['profile_id']}  [UNVERIFIED]"}
    elif top:
        action = {"op": "REVIEW: possible duplicate, no auto-write", "method": None, "path": None}
    else:
        action = {"op": "CREATE (would POST new individual profile)", "method": "POST", "path": "<tenant>/api/v1/profiles  [UNVERIFIED]"}
    return {"dry_run": True, "card_id": card["id"], "status": card["status"], "eligible": card["status"] == "approved",
            "matches": m[:3], "action": action, "payload": to_mctrade_profile(card["fields"])}
