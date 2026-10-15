#!/usr/bin/env python3
"""MC Trade import DRY RUN for the GAC card scanner.  OFFLINE: makes no network calls, contacts nobody, calls no API.

Reads approved cards from the scanner's export (the 'MC Trade import (Excel)' .xlsx or the 'Spreadsheet (CSV)' file),
compares them with an MC Trade profile export (default: the SAMPLE/FAKE file in sample-data/), and writes:
  out/<run>/upload/A_New_organizations_<run>.xlsx   the IMPORT-READY files. One sheet each, template columns only, in
  out/<run>/upload/B_New_individuals_<run>.xlsx     template order, plain header row, text cells. MC Trade refuses
  out/<run>/upload/C_Updates_existing_<run>.xlsx    unknown columns and wants orgs/individuals and new/updates separate.
  out/<run>/READ-ME_not-for-upload.md               what to upload in which order, and the column provenance
  out/<run>/match_report.xlsx / .md / .html         every card: UPDATE / CREATE / NEEDS REVIEW, with reasons and diffs
No README tab and no audit columns go into an upload file (qa/mctrade-r1.md: a leading READ ME sheet and extra columns break the import).
Usage:
  python3 dryrun.py --export ~/Downloads/GAC-contacts-for-MC-Trade-new-approved-....xlsx
  python3 dryrun.py --export fixtures/FIXTURE_scanner_export_approved.xlsx            (demo)
  python3 dryrun.py --export X.xlsx --crm "/path/to/real MC Trade export.csv" --template "GAC Import Template.xlsx" --affcode CardScan-Pilot
Rules and column sources: DOCS-NOTES.md, COLUMNS.md, column_map.json."""
import argparse, csv, datetime, json, os, re, sys
from difflib import SequenceMatcher
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CRM = os.path.join(HERE, "sample-data", "SAMPLE-FAKE_mctrade_profiles_export.csv")
DEC_FILL = {"UPDATE": PatternFill("solid", fgColor="DDEBF7"), "CREATE": PatternFill("solid", fgColor="D9EAD3"),
            "NEEDS REVIEW": PatternFill("solid", fgColor="FCE4D6")}
NICK = [{"robert", "bob", "rob", "bobby"}, {"william", "bill", "will", "billy"}, {"james", "jim", "jimmy", "jamie"},
        {"anthony", "tony"}, {"michael", "mike"}, {"christopher", "chris"}, {"katherine", "kathryn", "katie", "kate", "kathy"},
        {"elizabeth", "liz", "beth", "betsy"}, {"daniel", "dan", "danny"}, {"thomas", "tom", "tommy"}, {"richard", "rick", "dick", "rich"},
        {"jennifer", "jen", "jenny"}, {"joseph", "joe", "joey"}, {"margaret", "maggie", "peggy", "meg"}, {"steven", "stephen", "steve"},
        {"samantha", "sam"}, {"samuel", "sam"}, {"patricia", "pat", "patty", "trish"}, {"deborah", "debbie", "deb"}]
ORG_SUFFIX = r"\b(llc|inc|incorporated|co|company|corp|corporation|ltd|group|the|pllc|pc|lp|llp)\b"

# ---------------------------------------------------------------- helpers
def low(s): return (s or "").strip().lower()
def digits(s): return re.sub(r"\D", "", s or "")[-10:]
def nname(s): return " ".join(re.sub(r"[^a-z ]", " ", low(s)).split())
def norg(s): return " ".join(re.sub(ORG_SUFFIX, " ", re.sub(r"[^a-z0-9& ]", " ", low(s)).replace("&", " and ")).split())
def ratio(a, b): return SequenceMatcher(None, a, b).ratio() if a and b else 0.0
def same_first(a, b):
    a, b = nname(a), nname(b)
    return a == b or any(a in g and b in g for g in NICK)
def truthy(v): return low(str(v)) in ("true", "1", "yes", "y", "t")
def split_address(a):
    """'200 S Main St, Suite 400, Akron, OH 44308' -> address1/address2/city/state/zip (ZIP stays text, ZIP+4 kept)."""
    a = re.sub(r"\s+", " ", (a or "").replace("\n", ", ")).strip(" ,")
    m = re.match(r"^(.*?),\s*([A-Za-z][A-Za-z .'-]+?),?\s+([A-Za-z]{2})\.?\s+(\d{5}(?:-\d{4})?)$", a)
    if not m: return {"address1": a, "address2": "", "city": "", "state": "", "zip": ""}
    street, a2 = m.group(1), ""
    sm = re.match(r"^(.*?),?\s*((?:suite|ste\.?|unit|apt\.?|floor|fl\.?|room|rm\.?|#)\s*[\w-]+)$", street, re.I)
    if sm: street, a2 = sm.group(1).strip(" ,"), sm.group(2)
    return {"address1": street, "address2": a2, "city": m.group(2).strip(), "state": m.group(3).upper(), "zip": m.group(4)}
def norm_phone(p):
    """US numbers -> '(330) 555-0177', extension kept as ' ext. 990'. Anything else is left as typed.
    MC Trade's preferred phone format is not published (UNVERIFIED)."""
    p = (p or "").strip()
    if not p: return ""
    ext = ""
    m = re.search(r"\s*(?:ext\.?|extension|x)\s*(\d{1,6})\s*$", p, re.I)
    if m: ext, p = m.group(1), p[:m.start()]
    d = re.sub(r"\D", "", p)
    if len(d) == 11 and d[0] == "1": d = d[1:]
    if len(d) != 10: return (p + (f" ext. {ext}" if ext else "")).strip()
    if os.environ.get("DRYRUN_PHONE_STYLE") == "paren": return f"({d[:3]}) {d[3:6]}-{d[6:]}" + (f" ext. {ext}" if ext else "")
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" + (f" x{ext}" if ext else "")      # same style as the scanner (Admin > Phone format 'gac')
GUARD = re.compile(r"^'(?=[=+\-@])")       # the scanner's spreadsheet-formula guard prefixes ' ; in xlsx that ' becomes real data
def unguard(v):
    v = "" if v is None else str(v)
    return GUARD.sub("", v)
EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
def quality_issues(c):
    """Problems that must be fixed in the scanner before a row may go to MC Trade (QA round 1: qa/mctrade-r1.md)."""
    out = []
    if not c["first_name"].strip(): out.append("first name is blank (MC Trade matches people on First + Last name)")
    if not c["last_name"].strip(): out.append("last name is blank")
    for e in c["emails"]:
        if not EMAIL.match(e): out.append(f"email '{e}' is not a valid address")
    for t, ph in c["phones"].items():
        if ph and len(re.sub(r"\D", "", re.sub(r"(?i)(ext\.?|x)\s*\d+$", "", ph))) < 10: out.append(f"{t} phone '{ph}' has too few digits")
    for k in ("first_name", "last_name", "title", "company", "website", "address"):
        v = c.get(k) or ""
        if re.search(r"<[^>]+>", v): out.append(f"{k} contains HTML ({v[:40]})")
        if re.match(r"^[=+@]|^-[^\d]", v.strip()): out.append(f"{k} looks like a spreadsheet formula ({v[:40]})")
    return out

# ---------------------------------------------------------------- read the scanner export
def read_export(path):
    """Return approved cards as dicts. Accepts the scanner's .xlsx (Individuals sheet) or .csv export."""
    rows = []
    if path.lower().endswith((".xlsx", ".xlsm")):
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb["Individuals"] if "Individuals" in wb.sheetnames else wb.worksheets[-1]
        it = ws.iter_rows(values_only=True); hdr = [str(h or "").strip() for h in next(it)]
        it = iter(list(it)); wb.close()   # read it all, then let go of the file (Windows keeps open files locked)
        new_layout = "IndWorkPhone" in hdr or "IndAddress1" in hdr       # scanner round 4+: template columns only
        old_layout = "IndPhone" in hdr or "Address" in hdr               # scanner round 1-3
        if not (new_layout or old_layout) or "IndLastName" not in hdr:
            raise SystemExit(f"{path}: not a scanner MC Trade export (expected IndLastName + IndWorkPhone/IndAddress1 columns, got {hdr[:8]}…). Nothing written.")
        extra = {}   # round 4+: audit columns live in the companion <name>-extra-columns.csv next to the xlsx
        base = os.path.splitext(path)[0]; base = base[:-len("-UPDATES")] if base.endswith("-UPDATES") else base
        ep = base + "-extra-columns.csv"      # the UPDATES companion shares the main file's extra-columns CSV
        if not os.path.isfile(ep) and "-MCTrade-" in base and "-MCTrade-new-" not in base and os.path.isfile(base.replace("-MCTrade-", "-MCTrade-new-") + "-extra-columns.csv"):
            ep = base.replace("-MCTrade-", "-MCTrade-new-") + "-extra-columns.csv"
        if new_layout and os.path.isfile(ep):
            with open(ep, newline="", encoding="utf-8-sig") as fh:
                for er in csv.DictReader(fh):
                    er = {k: unguard((v or "").strip()) for k, v in er.items()}
                    if er.get("InImportFile") in ("yes", "updates file"):   # keyed by name + email: the scan id belongs to THIS row
                        em = low((er.get("AllEmails") or "").split(";")[0])
                        extra[(low(er.get("FirstName")), low(er.get("LastName")), em)] = er
                        extra.setdefault((low(er.get("FirstName")), low(er.get("LastName"))), []).append(er)
        elif new_layout: print(f"NOTE: {ep} not found: reviewer/batch/website/extra phones are not available for this run.")
        for v in it:
            if not any(v): continue
            r = {h: unguard(x) for h, x in zip(hdr, v)}
            if new_layout:
                fl = (low(r.get("IndFirstName")), low(r.get("IndLastName")))
                ex = extra.get(fl + (low(r.get("IndEmail")),))
                if ex is None:   # no email match: only use a name match when it is unambiguous (never guess a card number)
                    cand = extra.get(fl) or []; ex = cand[0] if len(cand) == 1 else {}
                for k in ("ScanCardID", "AllPhones", "AllEmails", "ReviewedBy", "Batch", "MCTradeAction", "NeedsAttention"): r.setdefault(k, ex.get(k, ""))
                r["IndPhone"] = r.get("IndWorkPhone", ""); r["WebAddress"] = r.get("Website") or ex.get("Website", "")
                tail = " ".join(x for x in (r.get("IndState") or "", r.get("IndZip") or "") if x)
                r["Address"] = ", ".join(x for x in (r.get("IndAddress1"), r.get("IndAddress2"), r.get("IndCity"), tail) if x)
            phones = {}
            for part in (r.get("AllPhones") or "").split(";"):
                if ":" in part:
                    t, num = part.split(":", 1); phones.setdefault(t.strip(), num.strip())
            phones.setdefault("work", r.get("IndPhone", "")); phones.setdefault("mobile", r.get("IndCellPhone", "")); phones.setdefault("fax", r.get("IndFax", ""))
            emails = [e.strip() for e in (r.get("AllEmails") or "").split(";") if e.strip()] or [x for x in (r.get("IndEmail"), r.get("IndEmail2")) if x]
            rows.append({"card_id": r.get("ScanCardID", ""), "first_name": r.get("IndFirstName", ""), "last_name": r.get("IndLastName", ""),
                         "title": r.get("IndTitle", ""), "company": r.get("OrgName", ""), "emails": emails, "phones": phones,
                         "website": r.get("WebAddress", ""), "address": r.get("Address", ""), "reviewed_by": r.get("ReviewedBy", ""),
                         "batch": r.get("Batch", ""), "action": low(r.get("MCTradeAction")), "flag": r.get("NeedsAttention", ""),
                         "status": "approved"})   # the Excel export holds approved cards unless an admin exported 'all'
    else:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                r = {k: unguard(v) for k, v in r.items()}
                rows.append({"card_id": r.get("id", ""), "first_name": r.get("first_name", ""), "last_name": r.get("last_name", ""),
                             "title": r.get("title", ""), "company": r.get("company", ""),
                             "emails": [e.strip() for e in (r.get("all_emails") or ";".join([r.get("email", ""), r.get("email2", "")])).split(";") if e.strip()],
                             "phones": {"work": r.get("work_phone", ""), "mobile": r.get("mobile_phone", ""), "fax": r.get("fax", "")},
                             "website": r.get("website", ""), "address": r.get("address", ""), "reviewed_by": r.get("reviewed_by", ""),
                             "batch": r.get("batch", ""), "action": low(r.get("mc_trade_action")), "flag": r.get("needs_attention", ""),
                             "status": low(r.get("status")) or "approved"})
    return rows

# ---------------------------------------------------------------- read an MC Trade profile export (sample or real)
ALIASES = {  # canonical -> header names we accept (real Profile Selector / Query Tool exports: header text UNVERIFIED)
    "profile_id": ["ProfileId", "ProfileID", "Profile ID", "Profile Id", "profile_id"],
    "org_ind": ["OrgInd", "Org Indication", "Org Ind", "IsOrg"],
    "org_name": ["OrgName", "Organization Name", "OrganizationName"],
    "report_name": ["ReportName", "Report Name", "Profile Name"],
    "first_name": ["FirstName", "First Name", "first_name"], "last_name": ["LastName", "Last Name", "last_name"],
    "title": ["Title"], "email": ["Email", "Main Email", "Email Address", "email"],
    "work_phone": ["WorkPhone", "Work Phone", "phone"], "cell_phone": ["CellPhone", "Cell Phone"], "fax": ["Fax"],
    "address1": ["Address1", "Address 1"], "city": ["City"], "state": ["State"], "zip": ["Zip", "Zip Code"],
    "website": ["Website", "Web Address"], "inactive": ["Inactive"],
    "related_id": ["MainRelatedProfileId", "Related Org Id"],
    "related_name": ["MainRelatedProfileName", "Related Organization", "Related Org/Main Contact", "organization"],
    "sample": ["SAMPLE_FAKE"]}
def read_crm(path):
    if path.lower().endswith(".xlsx"):
        wb = load_workbook(path, read_only=True, data_only=True); ws = wb.worksheets[-1]
        try:
            it = ws.iter_rows(values_only=True); hdr = [str(h or "") for h in next(it)]
            raw = [{h: ("" if x is None else str(x)) for h, x in zip(hdr, v)} for v in it if any(v)]
        finally: wb.close()   # a read-only workbook keeps the file open (Windows: the scanner can't replace/remove it)
    else:
        with open(path, newline="", encoding="utf-8-sig") as fh: raw = list(csv.DictReader(fh)); hdr = list(raw[0].keys()) if raw else []
    pick = {k: next((h for h in hdr if h.strip().lower() in [a.lower() for a in al]), None) for k, al in ALIASES.items()}
    missing = [k for k in ("profile_id", "last_name", "email") if not pick[k]]
    if missing: sys.exit(f"CRM file {path}: could not find columns for {missing}. Add the real header names to ALIASES in dryrun.py.")
    people, orgs = [], []
    for r in raw:
        g = {k: (r.get(h, "") if h else "") for k, h in pick.items()}
        is_org = truthy(g["org_ind"]) if pick["org_ind"] else (not g["first_name"] and not g["last_name"])
        (orgs if is_org else people).append(g)
    is_sample = any(g["sample"] == "SAMPLE-FAKE" for g in people + orgs)
    return people, orgs, pick, is_sample

# ---------------------------------------------------------------- decide
def decide(c, people, orgs):
    em = {low(e) for e in c["emails"] if e}
    ph = {digits(p) for p in c["phones"].values() if digits(p)}
    first, last, co = c["first_name"], c["last_name"], norg(c["company"])
    generic = {low(o["email"]) for o in orgs if o["email"]}
    cands = []
    for p in people:
        why, s = [], 0.0
        pe = low(p["email"])
        if pe and pe in em and pe not in generic: s += 0.6; why.append("email exact")
        lastok = nname(p["last_name"]) == nname(last) and last
        if lastok and same_first(p["first_name"], first): s += 0.3; why.append("first+last name")
        elif lastok or ratio(nname(p["first_name"] + " " + p["last_name"]), nname(first + " " + last)) > 0.88:
            s += 0.15; why.append("similar name")
        orgsim = ratio(norg(p["related_name"]), co)
        if orgsim >= 0.85: s += 0.15; why.append("same organization")
        if ph & {digits(p["work_phone"]), digits(p["cell_phone"])} - {""}: s += 0.15; why.append("phone exact")
        if s >= 0.3 and (("email exact" in why) or "name" in " ".join(why)):
            cands.append({"p": p, "score": round(min(s, 1.0), 2), "why": why, "orgsim": orgsim})
    cands.sort(key=lambda x: -x["score"])
    # organization link
    best_org, best = None, 0.0
    for o in orgs:
        r_ = ratio(norg(o["org_name"] or o["report_name"]), co)
        if r_ > best: best, best_org = r_, o
    org = {"profile_id": best_org["profile_id"], "name": best_org["org_name"] or best_org["report_name"], "score": round(best, 2)} if best_org and best >= 0.9 else None
    reasons, dec, target = [], None, None
    email_hits = [x for x in cands if "email exact" in x["why"]]
    strong = [x for x in cands if "email exact" in x["why"] or ("first+last name" in x["why"] and ("same organization" in x["why"] or "phone exact" in x["why"]))]
    if c["flag"]:
        dec = "NEEDS REVIEW"; reasons.append(f"Scanner flagged this card: {c['flag']}")
    for q in quality_issues(c):
        dec = "NEEDS REVIEW"; reasons.append("FIX FIRST: " + q)
    if len(email_hits) > 1:
        dec = "NEEDS REVIEW"; reasons.append(f"{len(email_hits)} MC Trade profiles share this email ({', '.join(x['p']['profile_id'] for x in email_hits)}): a duplicate already exists in MC Trade; merge those first")
    elif len(strong) == 1 or (strong and strong[0]["score"] - (strong[1]["score"] if len(strong) > 1 else 0) >= 0.3):
        t = strong[0]; target = t["p"]
        if truthy(t["p"]["inactive"]):
            dec = "NEEDS REVIEW"; reasons.append(f"Matches profile {t['p']['profile_id']}, which is INACTIVE in MC Trade")
        elif "email exact" not in t["why"] and low(t["p"]["email"]) and em and low(t["p"]["email"]) not in em:
            dec = "NEEDS REVIEW"; reasons.append(f"Same name and organization as profile {t['p']['profile_id']}, but the card email differs from MC Trade ({t['p']['email']}); confirm before overwriting the email")
        elif c["action"] == "create new":
            dec = "NEEDS REVIEW"; reasons.append(f"Reviewer chose 'create new', but profile {t['p']['profile_id']} matches ({', '.join(t['why'])}). A second profile would be a duplicate")
        elif not dec:
            dec = "UPDATE"; reasons.append(f"Matches profile {t['p']['profile_id']} ({', '.join(t['why'])}, score {t['score']})")
    elif len(strong) > 1:
        dec = "NEEDS REVIEW"; reasons.append("Several profiles match strongly: " + "; ".join(f"{x['p']['profile_id']} ({', '.join(x['why'])})" for x in strong[:3]))
    elif cands:
        dec = "NEEDS REVIEW"
        reasons.append("Possible match by name only: " + "; ".join(f"{x['p']['profile_id']} {x['p']['first_name']} {x['p']['last_name']} at {x['p']['related_name'] or '?'} ({', '.join(x['why'])})" for x in cands[:3]))
        reasons.append("MC Trade's own import duplicate checker matches on First + Last name, so it would flag this row too")
    else:
        if c["action"] == "update existing":
            dec = "NEEDS REVIEW"; reasons.append("Reviewer chose 'update existing', but no matching profile was found in this MC Trade export (export out of date, or different name/email?)")
        elif not dec:
            dec = "CREATE"; reasons.append("No matching individual profile")
    if dec != "NEEDS REVIEW" and not c["emails"] and not any(c["phones"].values()):
        dec = "NEEDS REVIEW"; reasons.append("No email or phone")
    if dec != "UPDATE" and target is None and strong: target = strong[0]["p"]
    if dec == "CREATE" and c["company"] and not org: reasons.append(f"Organization '{c['company']}' not found: listed in upload file A_New_organizations (import that first)")
    if org and dec == "CREATE": reasons.append(f"Link to organization {org['profile_id']} {org['name']}")
    return dec, reasons, target, cands, org

def card_values(c):
    a = split_address(c["address"])
    return {"first_name": c["first_name"].strip(), "last_name": c["last_name"].strip(), "title": c["title"].strip(),
            "email": (c["emails"] or [""])[0], "work_phone": norm_phone(c["phones"].get("work", "")),
            "cell_phone": norm_phone(c["phones"].get("mobile", "")), "fax": norm_phone(c["phones"].get("fax", "")),
            "org_name": c["company"].strip(), **a}
CMP = {"title": "title", "email": "email", "work_phone": "work_phone", "cell_phone": "cell_phone", "fax": "fax", "state": "state",
       "address1": "address1", "city": "city", "zip": "zip"}
ADDR = ("address1", "address2", "city", "state", "zip")
def diffs(v, p):
    out = {}
    for k, pk in CMP.items():
        new, old = (v.get(k) or "").strip(), (p.get(pk) or "").strip()
        if not new: continue
        same = digits(new) == digits(old) if "phone" in k or k == "fax" else low(new) == low(old)
        if not same: out[k] = (old, new)
    return out

# ---------------------------------------------------------------- write
def template_header(cmap, template):
    """The ONE column set every upload file uses. MC Trade refuses columns that are not in its template (H1), so
    with --template we copy GAC's real header row verbatim; without it we use column_map.json (partly UNVERIFIED)."""
    if template:
        wb = load_workbook(template, read_only=True); ws = wb.worksheets[0]
        try: hdr = [("" if h is None else str(h)).strip() for h in next(ws.iter_rows(max_row=1, values_only=True))]
        finally: wb.close()
        while hdr and not hdr[-1]: hdr.pop()
        return hdr, ws.title
    return [c["header"] for c in cmap["template_columns"]], "Sheet1"

def write_upload(path, header, sheet_title, side, rows, template):
    """Single sheet, template columns only, template order, plain header row (no notes, colours or README tab),
    every value a text cell (keeps ZIP leading zeros; no formula prefix is needed or added)."""
    h2k = {}
    for k, h in side.items():
        if h: h2k.setdefault(h.strip().lower(), k)
    if template:
        wb = load_workbook(template); ws = wb.worksheets[0]
        if ws.max_row > 1: ws.delete_rows(2, ws.max_row)
    else:
        wb = Workbook(); ws = wb.active; ws.title = sheet_title; ws.append(header)
    for r in rows:
        ws.append([str(r.get(h2k.get(h.lower()), "") or "") if h.lower() in h2k else None for h in header])
        for cell in ws[ws.max_row]:
            if cell.value is not None: cell.data_type = "s"; cell.number_format = "@"
    wb.save(path)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", required=True, nargs="+", help="scanner export(s): .xlsx (MC Trade import) or .csv")
    ap.add_argument("--crm", default=DEFAULT_CRM, help="MC Trade profile export (.csv/.xlsx). Default: the SAMPLE/FAKE file")
    ap.add_argument("--affcode", default="CardScan-Pilot", help="Affiliation Code for every imported row (must already exist in MC Trade)")
    ap.add_argument("--map", default=os.path.join(HERE, "column_map.json"))
    ap.add_argument("--template", help="GAC's real Import Profiles template (.xlsx from Admin > Import Profiles > Download Template Here). "
                    "Its header row is copied exactly; without it the default column set in column_map.json is used (partly UNVERIFIED)")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--run", default=datetime.datetime.now().strftime("%Y-%m-%d_%H%M"))
    a = ap.parse_args(argv)
    cmap = json.load(open(a.map))
    exports = list(a.export)
    for f in a.export:   # the scanner writes 'update existing' rows to a separate <name>-UPDATES.xlsx: read it too (mctrade-r3 R3-7a)
        b0 = os.path.splitext(f)[0]   # the app names it without '-new-' (GAC-MCTrade-new-X.xlsx -> GAC-MCTrade-X-UPDATES.xlsx)
        for u in (b0 + "-UPDATES.xlsx", b0.replace("-MCTrade-new-", "-MCTrade-") + "-UPDATES.xlsx"):
            if f.lower().endswith(".xlsx") and not f.endswith("-UPDATES.xlsx") and os.path.isfile(u) and u not in exports:
                exports.append(u); print("Also reading the updates companion:", u); break
    a.export = exports
    cards = [c for f in a.export for c in read_export(f)]
    skipped = [c for c in cards if c["status"] != "approved"]; cards = [c for c in cards if c["status"] == "approved"]
    people, orgs, pick, is_sample = read_crm(a.crm)
    res = []
    for c in cards:
        dec, reasons, target, cands, org = decide(c, people, orgs)
        res.append({"c": c, "dec": dec, "reasons": reasons, "target": target, "cands": cands, "org": org, "v": card_values(c)})
    # within-file duplicates (same email twice in the scanner export)
    seen = {}
    for r in res:
        for e in r["c"]["emails"]:
            if low(e) in seen and seen[low(e)] is not r and not any("in this export" in x for x in r["reasons"]):
                r["dec"] = "NEEDS REVIEW"; r["reasons"].insert(0, f"Same email as card #{seen[low(e)]['c']['card_id']} in this export (MC Trade does not de-duplicate inside one file; that copy goes ahead, merge this one in the scanner)")
            seen.setdefault(low(e), r)
    seen_n = {}
    for r in res:
        key = (low(r["c"]["first_name"]), low(r["c"]["last_name"]), norg(r["c"]["company"]))
        if not key[1]: continue
        if key in seen_n and not any("in this export" in x for x in r["reasons"]):
            r["dec"] = "NEEDS REVIEW"; r["reasons"].insert(0, f"Same name and company as card #{seen_n[key]['c']['card_id']} in this export (MC Trade does not de-duplicate inside one file)")
        seen_n.setdefault(key, r)
    run_dir = os.path.join(a.out, a.run); up = os.path.join(run_dir, "upload"); os.makedirs(up, exist_ok=True)
    I, O = cmap["individual"], cmap["organization"]
    new_ind, upd, new_org, org_names = [], [], [], set()
    for r in res:
        v = dict(r["v"]); v["affcode1"] = a.affcode
        if r["dec"] == "CREATE":
            if r["org"]: v["org_name"] = r["org"]["name"]          # use MC Trade's exact spelling so the relationship links
            new_ind.append(v)
            if r["c"]["company"] and not r["org"] and norg(r["c"]["company"]) not in org_names:
                org_names.add(norg(r["c"]["company"])); dom = (r["c"]["emails"] or ["@"])[0].split("@")[-1]
                new_org.append({"org_name": r["c"]["company"], "email": "", "work_phone": "",   # a person's direct line is not the organisation's number (R3-7c)
                                "website": r["c"]["website"], **split_address(r["c"]["address"]), "affcode1": a.affcode})   # website never guessed from the email domain (a department subdomain is not the org site)
        elif r["dec"] == "UPDATE":
            p = r["target"]; d = diffs(v, p); r["diffs"] = d
            row = {"profile_id": p["profile_id"], "last_name": p["last_name"] or v["last_name"], "affcode1": a.affcode,
                   "member_since": "1/1/1900"}     # H2: use 1/1/1900 on updates so the existing MemberSince is not overwritten
            for k, (old, new) in d.items(): row[k] = new        # only changed fields: blank cells never overwrite in MC Trade
            if any(k in d for k in ADDR):                       # an address is one unit: send all its parts together
                for k in ADDR:
                    if v.get(k): row[k] = v[k]
            upd.append(row)
    for r in res: r.setdefault("diffs", diffs(r["v"], r["target"]) if r["target"] else {})
    header, sheet_title = template_header(cmap, a.template)
    hl = {h.lower() for h in header}
    dropped = sorted({f"{k} -> {h}" for side in (I, O) for k, h in side.items() if h and h.lower() not in hl})
    unfilled = [h for h in header if h.lower() not in {x.lower() for side in (I, O) for x in side.values() if x}]
    plan = [("A", "New_organizations", O, new_org, "Import FIRST: Organizations, new profiles (so new people can be related to them)."),
            ("B", "New_individuals", I, new_ind, "Then: Individuals, new profiles; relationship Employer-Employee to OrgName."),
            ("C", "Updates_existing", I, upd, "Separately: Individuals, updates to existing profiles (ProfileID + LastName; only changed fields filled).")]
    sample_banner = "SAMPLE/FAKE MC Trade data was used: this is a REHEARSAL. Do not import these files." if is_sample else "Compared against: " + os.path.basename(a.crm)
    written = []
    if upd and I.get("profile_id", "").lower() not in hl:
        print(f"WARNING: the column set has no '{I.get('profile_id')}' header, so updates cannot be matched. Fix 'individual.profile_id' in column_map.json.")
        lines_warn = ["WARNING: no Profile ID column in the column set: file C cannot be imported until column_map.json names it."]
    else: lines_warn = []
    for letter, name, side, rows, note in plan:
        if not rows: continue
        fn = os.path.join(up, f"{letter}_{name}_{a.run}.xlsx"); write_upload(fn, header, sheet_title, side, rows, a.template)
        written.append((os.path.relpath(fn, run_dir), len(rows), note))
    lines = [f"GAC card scanner: MC Trade import files (DRY RUN {a.run})", sample_banner, "",
             f"{len(cards)} approved card(s) from {', '.join(os.path.basename(x) for x in a.export)}; {len(skipped)} non-approved row(s) ignored.",
             f"UPDATE {sum(r['dec']=='UPDATE' for r in res)} · CREATE {sum(r['dec']=='CREATE' for r in res)} · NEEDS REVIEW {sum(r['dec']=='NEEDS REVIEW' for r in res)} (NEEDS REVIEW rows are in NO upload file)", "",
             "UPLOAD ONLY the files in upload/. Each has one sheet and only template columns, because MC Trade refuses columns that are not in its template",
             "and the scanner's own Excel (READ ME FIRST tab + audit columns) is NOT importable as-is (qa/mctrade-r1.md, B1).",
             ("Column set: copied from the template you supplied: " + os.path.basename(a.template)) if a.template else
             "Column set: the DEFAULT in column_map.json. Only IndEmail, Email, MemberSince, Category and AffCode1 are documented header text; the rest are inferred. Re-run with --template <GAC template.xlsx> before a real import.",
             "Order: A (new organizations) first, then B (new individuals), then C (updates) as a separate import. Imports cannot be undone; test 2 rows first.",
             "Every AffCode value must already exist in MC Trade (Admin > Manage Codes) or the file is not valid. Blank cells never erase data on update.",
             "In the duplicate checker, choose Overwrite only for file C; for file B keep Create new unless the match is clearly the same person."] + lines_warn
    with open(os.path.join(run_dir, "READ-ME_not-for-upload.md"), "w") as fh:
        fh.write("# " + lines[0] + "\n\n> " + sample_banner + "\n\n" + "\n".join(f"- {l}" for l in lines[3:] if l) + "\n\n## Upload files\n\n")
        fh.write("".join(f"- `{f}`: {n} row(s). {note}\n" for f, n, note in written) or "- (none: nothing to create or update)\n")
        fh.write(f"\n## Column set ({len(header)} columns, in this order)\n\n`" + "`, `".join(header) + "`\n\n")
        if not a.template:
            fh.write("| Header | Status | Source |\n|---|---|---|\n" + "".join(f"| {c['header']} | {c['status']} | {c['source']} |\n" for c in cmap["template_columns"]))
        fh.write("\nColumns in the set that this run leaves blank: " + (", ".join(unfilled) or "none") + "\n")
        fh.write("\nMapped fields NOT written because the column set has no such header (data stays in match_report): " + (", ".join(dropped) or "none") + "\n")
    # match report
    mr = Workbook(); s = mr.active; s.title = "Summary (not for upload)"
    for l in lines: s.append([l])
    for f, n, note in written: s.append([f"{f}: {n} row(s). {note}"])
    s.column_dimensions["A"].width = 120; s["A1"].font = Font(bold=True, size=14)
    d = mr.create_sheet("Cards"); hdr = ["Decision", "ScanCardID", "Name", "Company (card)", "Email (card)", "Reviewer choice", "Reasons",
                                          "MC Trade profile", "MC Trade name / org", "Fields that would change (old -> new)", "Org link", "Other candidates"]
    d.append(hdr)
    for i, h in enumerate(hdr, 1): d.cell(1, i).font = Font(bold=True, color="FFFFFF"); d.cell(1, i).fill = PatternFill("solid", fgColor="388A9C")
    order = {"NEEDS REVIEW": 0, "UPDATE": 1, "CREATE": 2}
    for r in sorted(res, key=lambda r: (order[r["dec"]], str(r["c"]["card_id"]))):
        c, t = r["c"], r["target"]
        d.append([r["dec"], c["card_id"], f"{c['first_name']} {c['last_name']}".strip(), c["company"], "; ".join(c["emails"]), c["action"] or "(none)",
                  "\n".join(r["reasons"]), t["profile_id"] if t else "", f"{t['first_name']} {t['last_name']} / {t['related_name']}" if t else "",
                  "\n".join(f"{k}: {o or '(blank)'} -> {n}" for k, (o, n) in r["diffs"].items()), f"{r['org']['profile_id']} {r['org']['name']}" if r["org"] else "(not found)",
                  "; ".join(f"{x['p']['profile_id']} {x['p']['first_name']} {x['p']['last_name']} ({x['score']})" for x in r["cands"][1:4])])
        d.cell(d.max_row, 1).fill = DEC_FILL[r["dec"]]
        for cell in d[d.max_row]: cell.alignment = Alignment(wrap_text=True, vertical="top")
    for col, w in zip("ABCDEFGHIJKL", [14, 10, 20, 28, 30, 15, 60, 12, 30, 40, 28, 30]): d.column_dimensions[col].width = w
    d.freeze_panes = "C2"; mr.save(os.path.join(run_dir, "match_report.xlsx"))
    with open(os.path.join(run_dir, "match_report.md"), "w") as fh:
        fh.write(f"# MC Trade dry-run match report ({a.run})\n\n> {sample_banner}\n\n")
        fh.write(f"Input: {', '.join(a.export)}  \nMC Trade export: {a.crm} ({len(people)} individuals, {len(orgs)} organizations)  \n")
        fh.write(f"Columns detected in the MC Trade export: {json.dumps({k: v for k, v in pick.items() if v})}\n\n")
        fh.write("| Decision | Count |\n|---|---|\n" + "".join(f"| {k} | {sum(r['dec']==k for r in res)} |\n" for k in order) + "\n")
        fh.write("Upload files (one sheet, template columns only): " + ", ".join(f"`{f}` ({n})" for f, n, _ in written) + ". Read `READ-ME_not-for-upload.md` first.\n\n")
        fh.write("| Decision | Card | Name | Company | Reasons | MC Trade profile | Changes |\n|---|---|---|---|---|---|---|\n")
        for r in sorted(res, key=lambda r: (order[r["dec"]], str(r["c"]["card_id"]))):
            c, t = r["c"], r["target"]
            fh.write(f"| {r['dec']} | #{c['card_id']} | {c['first_name']} {c['last_name']} | {c['company']} | {'<br>'.join(r['reasons'])} | "
                     f"{t['profile_id'] if t else ''} | {'<br>'.join(f'{k}: {o or chr(8212)} → {n}' for k, (o, n) in r['diffs'].items())} |\n")
    # small self-contained HTML version of the report (for a browser / the demo video)
    import html as _h
    col = {"UPDATE": "#ddebf7", "CREATE": "#d9ead3", "NEEDS REVIEW": "#fce4d6"}
    trs = "".join(f"<tr style='background:{col[r['dec']]}'><td><b>{r['dec']}</b></td><td>#{_h.escape(str(r['c']['card_id']))}</td>"
                  f"<td>{_h.escape(r['c']['first_name'] + ' ' + r['c']['last_name'])}</td><td>{_h.escape(r['c']['company'])}</td>"
                  f"<td>{'<br>'.join(_h.escape(x) for x in r['reasons'])}</td><td>{_h.escape(r['target']['profile_id']) if r['target'] else ''}</td>"
                  f"<td>{'<br>'.join(_h.escape(f'{k}: {o or chr(8212)} -> {n}') for k, (o, n) in r['diffs'].items())}</td></tr>"
                  for r in sorted(res, key=lambda r: (order[r['dec']], str(r['c']['card_id']))))
    cnt = " · ".join(f"<b>{k}</b> {sum(r['dec']==k for r in res)}" for k in order)
    with open(os.path.join(run_dir, "match_report.html"), "w") as fh:
        fh.write(f"""<!doctype html><meta charset=utf-8><title>MC Trade dry run {a.run}</title>
<style>body{{font-family:Lato,Arial,sans-serif;margin:24px;color:#222}}h1{{color:#388a9c;margin:0 0 4px}}.ban{{background:#ef6728;color:#fff;padding:6px 10px;display:inline-block;border-radius:4px;font-weight:bold}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin-top:12px}}td,th{{border:1px solid #ccc;padding:6px;vertical-align:top;text-align:left}}th{{background:#388a9c;color:#fff}}</style>
<h1>MC Trade dry run: match report</h1><div class=ban>{_h.escape(sample_banner)}</div>
<p>{len(cards)} approved card(s) · {cnt} · import files: new orgs {len(new_org)}, new individuals {len(new_ind)}, updates {len(upd)}. Offline: no API was called.</p>
<table><tr><th>Decision</th><th>Card</th><th>Name</th><th>Company</th><th>Why</th><th>MC Trade profile</th><th>Would change</th></tr>{trs}</table>""")
    print(f"{len(cards)} approved cards -> UPDATE {len(upd)}, CREATE {len(new_ind)} (+{len(new_org)} new orgs), NEEDS REVIEW {sum(r['dec']=='NEEDS REVIEW' for r in res)}")
    print("Wrote", run_dir)
    return run_dir

if __name__ == "__main__":
    main()
