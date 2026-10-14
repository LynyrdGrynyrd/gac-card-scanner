"""MC Trade import file: one sheet, the template's columns only, one row per person.
Everything else (audit columns, notes, rows left out) goes into a companion CSV and a READ ME text file.

Header row: if data/mctrade_template.xlsx exists (GAC's file from MC Trade Admin > Import Profiles > Download Template),
its first-row headers are copied EXACTLY and only recognised columns are filled. Otherwise the documented default set in
mctrade-dryrun/column_map.json is used (same mapping as the dry-run tool)."""
import os, re, json, html, unicodedata

ROOT = os.path.join(os.path.dirname(__file__), "..")
TEMPLATE_XLSX = os.environ.get("MCTRADE_TEMPLATE", os.path.join(ROOT, "data", "mctrade_template.xlsx"))
COLMAP = os.path.join(ROOT, "mctrade-dryrun", "column_map.json")
FALLBACK = ["ProfileID", "OrgName", "Address1", "Address2", "City", "State", "Zip", "WorkPhone", "Fax", "Email", "Website", "IndPrefix",
            "IndFirstName", "IndLastName", "IndTitle", "IndAddress1", "IndAddress2", "IndCity", "IndState", "IndZip", "IndWorkPhone",
            "IndCellPhone", "IndFax", "IndEmail", "MemberSince", "Category", "AffCode1"]
# card value -> template header (individual profile). Website goes in the (organisation) Website column.
IND = {"first_name": "IndFirstName", "last_name": "IndLastName", "title": "IndTitle", "address1": "IndAddress1", "address2": "IndAddress2",
       "city": "IndCity", "state": "IndState", "zip": "IndZip", "work_phone": "IndWorkPhone", "cell_phone": "IndCellPhone", "fax": "IndFax",
       "email": "IndEmail", "org_name": "OrgName", "affcode1": "AffCode1"}
# Website is an ORGANISATION column in MC Trade (non-Ind prefix); a person's website goes to the companion CSV, not the individuals file.

def _hnorm(h): return re.sub(r"[\s_]+", "", str(h or "")).casefold()
KNOWN = {_hnorm(h): h for h in FALLBACK}

def headers():
    """-> (header row VERBATIM incl. blank spacer cells, source text). Use canonical() to map a template header to our names."""
    if os.path.isfile(TEMPLATE_XLSX):
        from openpyxl import load_workbook
        ws = load_workbook(TEMPLATE_XLSX, read_only=True).worksheets[0]
        row = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))
        while row and row[-1] in (None, ""): row.pop()          # trailing empty cells are not columns
        return ["" if h is None else str(h) for h in row], "GAC template file"
    try:
        with open(COLMAP) as fh: return [c["header"] for c in json.load(fh)["template_columns"]], "default column set (UNVERIFIED headers)"
    except Exception: return FALLBACK, "default column set (UNVERIFIED headers)"

def canonical(h):
    """Template header -> our column name, tolerant of case/spaces ('Profile ID', 'IndEmail ')."""
    return KNOWN.get(_hnorm(h), "")

TAG = re.compile(r"</?[A-Za-z!/?][^<>]*>")
def clean(s):
    """Plain single-line text. Entities are decoded FIRST (so '&lt;img&gt;' can't turn into a real tag), then tags are removed.
    A lone '<' or '>' between words ('5 < 6') is kept; one glued to text ('a<b') is dropped."""
    s = str(s or "")
    for _ in range(3):                      # double-encoded '&amp;lt;' too
        u = html.unescape(s)
        if u == s: break
        s = u
    s = TAG.sub("", s)
    s = re.sub(r"(?<=\S)[<>]|[<>](?=\S)", "", s)
    return " ".join(s.split())

FORMULA = re.compile(r"^\s*(?:[=@\t\r]|[+-](?![\d\s().-]*\d[\d\s().-]*$))")
def looks_formula(v):
    """Text a spreadsheet would run as a formula (=, @, or +/- not followed by a plain number/phone)."""
    v = str(v or "")
    return bool(v) and bool(FORMULA.match(v))
def neutralize(v):
    """Formula-looking text stored as plain text: a leading ' is added so a later MC Trade 'Export to CSV' can't run it."""
    return "'" + v if looks_formula(v) else v
TEXT_KEYS = ("first_name", "last_name", "title", "company", "website", "address", "department", "credentials")
def content_problems(f):
    """HTML (also entity-encoded) or formula text in a field: must be fixed before approval/import."""
    out = {}
    for k in TEXT_KEYS:
        v = str(f.get(k) or "")
        dec = html.unescape(html.unescape(v))
        if TAG.search(dec): out[k] = f"{k.replace('_', ' ')} contains HTML code ({v[:30]})"
        elif looks_formula(v): out[k] = f"{k.replace('_', ' ')} looks like a spreadsheet formula ({v[:30]})"
    return out

EXT = re.compile(r"\s*(?:x|ext\.?|extension)\s*(\d{1,6})\s*$", re.I)
def phone(n, style="gac"):
    """US numbers -> 330-555-0181 (GAC style) or +13305550181 (E.164); an extension is kept as ' x123'. Others: +<digits>."""
    n = str(n or "").strip(); m = EXT.search(n); ext = m.group(1) if m else ""
    core = EXT.sub("", n); d = re.sub(r"\D", "", core)
    if len(d) == 11 and d[0] == "1": d = d[1:]
    if len(d) == 10 and not core.strip().startswith("+") or (len(d) == 10 and core.strip().startswith("+1")):
        out = f"+1{d}" if style == "e164" else f"{d[:3]}-{d[3:6]}-{d[6:]}"
    elif core.strip().startswith("+") and d: out = "+" + re.sub(r"\D", "", core)
    else: out = clean(n); ext = ""
    return out + (f" x{ext}" if ext else "")

ADDR_TAIL = re.compile(r"[,\s]+([A-Za-z][A-Za-z .'-]*?)[,\s]+([A-Z]{2})\.?\s+(\d{5}(?:-\d{4})?)\s*$")
NOCOMMA = re.compile(r"^(.*\b(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way|Ct|Pkwy|Hwy|Pl|Cir|Ter|Sq)\.?"
                     r"(?:\s+(?:Suite|Ste\.?|Unit|#)\s*\S+)?)\s+([A-Za-z][A-Za-z .'-]*?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", re.I)
def split_address(a):
    a = clean(a); out = {"address1": "", "address2": "", "city": "", "state": "", "zip": ""}
    if not a: return out
    nc = NOCOMMA.match(a) if a.count(",") == 0 else None
    if nc:   # "11000 Euclid Ave Cleveland OH 44106": split after the street suffix
        a = f"{nc.group(1)}, {nc.group(2)}, {nc.group(3)} {nc.group(4)}"
    m = ADDR_TAIL.search(a)
    if not m: out["address1"] = a; return out
    out.update(city=m.group(1).strip(), state=m.group(2), zip=m.group(3))
    parts = [p.strip() for p in a[:m.start()].split(",") if p.strip()]
    if parts:
        # "200 S Main St Suite 400" -> street + suite
        s2 = re.search(r"\s+((?:suite|ste\.?|unit|apt\.?|#|floor|fl\.?)\s*\S+)$", parts[0], re.I)
        if s2 and len(parts) == 1: parts = [parts[0][:s2.start()], s2.group(1)]
        out["address1"] = parts[0]; out["address2"] = ", ".join(parts[1:])
    return out

ROLE = {"info", "sales", "office", "admin", "contact", "hello", "support", "team", "mail", "enquiries", "inquiries", "general",
        "reception", "frontdesk", "service", "billing", "accounts", "marketing", "hr", "jobs", "careers", "events", "noreply", "no-reply"}
def _nm(s):
    """Unicode-aware name key: accents folded (José = Jose), non-Latin letters kept (two Chinese names stay different)."""
    s = unicodedata.normalize("NFKD", str(s or "")).casefold()
    return " ".join("".join(ch for ch in s if ch.isalnum() or ch.isspace()).split())
def _org(s): return _nm(s).replace(" ", "")
def personal_emails(f):
    return {e.strip().lower() for e in f.get("emails") or [] if "@" in e and e.split("@")[0].strip().lower() not in ROLE}
def same_person(a, b):
    """Same name (Unicode-aware) AND something that ties them: a shared personal email, phone or the same company.
    A shared role mailbox (info@, sales@ ...) alone never makes two people one."""
    na, nb = _nm(f"{a.get('first_name','')} {a.get('last_name','')}"), _nm(f"{b.get('first_name','')} {b.get('last_name','')}")
    if not na or na != nb: return False
    if personal_emails(a) & personal_emails(b): return True
    pa = {re.sub(r"\D", "", p.get("number") or "")[-10:] for p in a.get("phones") or []} - {""}
    pb = {re.sub(r"\D", "", p.get("number") or "")[-10:] for p in b.get("phones") or []} - {""}
    if pa & pb: return True
    return bool(_org(a.get("company"))) and _org(a.get("company")) == _org(b.get("company"))
def person_key(f):   # kept for callers/tests: name + org (never email alone)
    return f"{_nm(f.get('first_name','') + ' ' + f.get('last_name',''))}|{_org(f.get('company'))}"

def row(f, affcode, style):
    ph = {}
    for p in f.get("phones") or []:
        ph.setdefault({"mobile": "cell_phone", "cell": "cell_phone", "fax": "fax"}.get(p.get("type"), "work_phone"), phone(p.get("number"), style))
    v = {"first_name": clean(f.get("first_name")), "last_name": clean(f.get("last_name")), "title": clean(f.get("title")),
         "org_name": clean(f.get("company")), "email": ((f.get("emails") or [""])[0]).strip(),
         "affcode1": affcode, **ph, **split_address(f.get("address"))}
    return {IND[k]: neutralize(x) if isinstance(x, str) else x for k, x in v.items() if k in IND}

def build(cards, affcode, style, hard_errors, kept=lambda a, b: False, crm_profile=lambda c: None, action=lambda c: ""):
    """-> dict(headers, source, rows[(card,row)], updates[(card,row)], left[(card,reason)], merged{card_id: [ids]}, unknown_cols)
    kept(a_id, b_id): the reviewer said these two are different people. action(card) = 'update_existing'|'create_new'|''.
    crm_profile(card) -> MC Trade ProfileID for an 'update existing' card, or None."""
    hdr, source = headers(); rows, upd, out, merged = [], [], [], {}
    groups = []   # [lead card, [cards], row]
    for c in cards:
        hard = hard_errors(c["fields"])
        if hard: out.append((c, "FIX FIRST: " + "; ".join(hard.values()))); continue
        if action(c) == "update_existing":
            pid = crm_profile(c)
            if not pid: out.append((c, "update existing: no MC Trade Profile ID found; use the dry-run C (updates) file")); continue
            r = row(c["fields"], affcode, style); r["ProfileID"] = str(pid); r["MemberSince"] = "1/1/1900"
            upd.append((c, r)); continue
        r = row(c["fields"], affcode, style)
        g = next((g for g in groups if all(same_person(c["fields"], x["fields"]) and not kept(c["id"], x["id"]) for x in g[1])), None)
        if not g: groups.append([c, [c], r]); continue
        g[1].append(c); lost = []
        for k, v in r.items():
            if not v: continue
            if not g[2].get(k): g[2][k] = v
            elif g[2][k] != v and k != "AffCode1": lost.append(f"{k}={v}")
        merged.setdefault(g[0]["id"], []).append(c["id"])
        out.append((c, f"same person as card #{g[0]['id']}: its extra details were added to that row" + (f"; NOT imported (differs): {', '.join(lost)}" if lost else "")))
    rows = [(g[0], g[2]) for g in groups]
    names = {canonical(h) for h in hdr if h}
    unknown = [h for h in hdr if h and not canonical(h)]
    unused = sorted({v for v in IND.values()} - names)
    return {"headers": hdr, "source": source, "rows": rows, "updates": upd, "left": out, "merged": merged, "unknown_cols": unknown, "unfilled": unused}

def cells(hdr, r):
    """Row values in template order; blank spacer columns stay blank so nothing shifts."""
    return [r.get(canonical(h), "") if h else "" for h in hdr]
