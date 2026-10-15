"""MC Trade import file: one sheet, the template's columns only, one row per person.
Everything else (audit columns, notes, rows left out) goes into a companion CSV and a READ ME text file.

Header row: if data/mctrade_template.xlsx exists (GAC's file from MC Trade Admin > Import Profiles > Download Template),
its first-row headers are copied EXACTLY and only recognised columns are filled. Otherwise the documented default set in
mctrade-dryrun/column_map.json is used (same mapping as the dry-run tool)."""
import os, re, json, html, unicodedata

ROOT = os.path.join(os.path.dirname(__file__), "..")
from . import paths
TEMPLATE_XLSX = os.environ.get("MCTRADE_TEMPLATE", paths.data("mctrade_template.xlsx"))
COLMAP = os.path.join(ROOT, "mctrade-dryrun", "column_map.json")
FALLBACK = ["ProfileID", "OrgName", "Address1", "Address2", "City", "State", "Zip", "WorkPhone", "Fax", "Email", "Website", "IndPrefix",
            "IndFirstName", "IndLastName", "IndTitle", "IndAddress1", "IndAddress2", "IndCity", "IndState", "IndZip", "IndWorkPhone",
            "IndCellPhone", "IndFax", "IndEmail", "MemberSince", "Category", "AffCode1"]
# card value -> template header (individual profile). Website goes in the (organisation) Website column.
IND = {"first_name": "IndFirstName", "last_name": "IndLastName", "title": "IndTitle", "address1": "IndAddress1", "address2": "IndAddress2",
       "city": "IndCity", "state": "IndState", "zip": "IndZip", "work_phone": "IndWorkPhone", "cell_phone": "IndCellPhone", "fax": "IndFax",
       "email": "IndEmail", "org_name": "OrgName", "affcode1": "AffCode1", "website": "Website"}
# Website is an ORGANISATION column in MC Trade (non-Ind prefix); a person's website goes to the companion CSV, not the individuals file.

def _hnorm(h): return re.sub(r"[\s_]+", "", str(h or "")).casefold()
KNOWN = {_hnorm(h): h for h in FALLBACK} | {"indwebsite": "IndWebsite", "webaddress": "Website"}

_HCACHE = {}
def headers():
    """-> (header row VERBATIM incl. blank spacer cells, source text). Use canonical() to map a template header to our names.
    Cached per file mtime/size (mctrade-r4 R4-3: the template was re-parsed on every export)."""
    if os.path.isfile(TEMPLATE_XLSX):
        import hashlib
        with open(TEMPLATE_XLSX, "rb") as fh: key = (TEMPLATE_XLSX, hashlib.sha1(fh.read()).hexdigest())   # cheap next to parsing
        if _HCACHE.get("key") != key: _HCACHE.update(key=key, val=_read_headers())
        return list(_HCACHE["val"][0]), _HCACHE["val"][1]
    return _read_headers()
def _read_headers():
    if os.path.isfile(TEMPLATE_XLSX):
        from openpyxl import load_workbook
        wb = load_workbook(TEMPLATE_XLSX, read_only=True); ws = wb.worksheets[0]
        for w in wb.worksheets:   # an instructions sheet may come first: use the sheet whose header row has IndEmail/AffCode1
            first = [_hnorm(x) for x in next(w.iter_rows(min_row=1, max_row=1, values_only=True), ()) or ()]
            if "indemail" in first or "affcode1" in first: ws = w; break
        row = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))
        while row and row[-1] in (None, ""): row.pop()          # trailing empty cells are not columns
        return ["" if h is None else str(h) for h in row], "GAC template file"
    try:
        with open(COLMAP) as fh: return [c["header"] for c in json.load(fh)["template_columns"]], "the scanner's default column names (not checked against MC Trade)"
    except Exception: return FALLBACK, "the scanner's default column names (not checked against MC Trade)"

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
EXT = re.compile(r"\s*,?\s*(?:x|ext\.?|extn\.?|extension|#)\s*[:.]?\s*(\d{1,6})\s*$", re.I)   # round 15: also "ext: 4271", ", x4271"
def looks_formula(v):
    """Text a spreadsheet would run as a formula (=, @, or +/- not followed by a plain number/phone).
    Round 7: a phone extension at the end ('+1 330-555-0185 x12', 'ext. 12', '#12') is not part of the check (skeptic R7-1)."""
    v = str(v or "")
    if re.match(r"^\s*\+[\d\s().-]*\d", v) and EXT.search(v): v = EXT.sub("", v)
    # '+1 -1' / '-2 +3': a sign after a space is arithmetic, not a phone ('+1 330-555-0181' has '-' only between digits)
    return bool(v) and (bool(FORMULA.match(v)) or bool(re.match(r"^\s*[+-]", v) and re.search(r"\d\s+[+\-*/]\s*\d|\d\s*[*/^]\s*\d", v)))
def neutralize(v):
    """Formula-looking text stored as plain text: a leading ' is added so a later MC Trade 'Export to CSV' can't run it."""
    return "'" + v if looks_formula(v) else v
TEXT_KEYS = ("first_name", "last_name", "title", "company", "website", "address", "department", "credentials", "other_address", "note")
LIST_KEYS = ("emails", "social")          # phones are checked too (number text), see content_problems          # social: HTML check only ('@handle' is a normal value there)
INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad]")
def decoded(v, depth=6):
    """Fully decoded form used for checks: entities decoded until stable (same depth as clean() + margin), NFKC (fullwidth
    '＜' -> '<'), zero-width / bidi characters removed."""
    v = str(v or "")
    for _ in range(depth):
        u = html.unescape(v)
        if u == v: break
        v = u
    return INVISIBLE.sub("", unicodedata.normalize("NFKC", v))
def content_problems(f):
    """HTML (also entity-encoded, any depth, fullwidth) or formula text in any exported field: must be fixed before approval."""
    out = {}
    vals = [(k, f.get(k)) for k in TEXT_KEYS] + [(k, x) for k in LIST_KEYS for x in (f.get(k) or [])] \
           + [("phones", (p or {}).get("number")) for p in (f.get("phones") or [])]
    for k, v in vals:
        v = str(v or ""); dec = decoded(v); nm = k.replace("_", " ").rstrip("s") if k in LIST_KEYS + ("phones",) else k.replace("_", " ")
        if k in out or not v: continue
        if TAG.search(dec) or (dec != v and re.search(r"[<>]", dec)): out[k] = f"{nm} contains HTML code ({v[:30]})"
        elif k not in ("social", "note") and (looks_formula(v) or looks_formula(dec)): out[k] = f"{nm} looks like a spreadsheet formula ({v[:30]})"
        elif INVISIBLE.search(v) and k != "note": out[k] = f"{nm} contains invisible characters (zero-width / text-direction); retype it"
        elif k not in ("note", "address", "other_address") and re.search(r"[\r\n]", v): out[k] = f"{nm} contains a line break; put it on one line"   # audit 2026-10
    return out

def phone(n, style="gac"):
    """US numbers -> 330-555-0181 (GAC style) or +13305550181 (E.164); an extension is kept as ' x123'. Others: +<digits>."""
    n = str(n or "").strip()
    if looks_formula(n) and not re.fullmatch(r"\+?[\d\s().-]+(?:\s*(?:x|ext\.?|extension|#)\s*\d+)?", n, re.I): return clean(n)   # '=1+2+…' is never made into a number
    m = EXT.search(n); ext = m.group(1) if m else ""
    core = EXT.sub("", n); d = re.sub(r"\D", "", core)
    if len(d) == 11 and d[0] == "1": d = d[1:]
    if len(d) == 10 and not core.strip().startswith("+") or (len(d) == 10 and core.strip().startswith("+1")):
        out = f"+1{d}" if style == "e164" else f"{d[:3]}-{d[3:6]}-{d[6:]}"
    elif core.strip().startswith("+") and d:
        out = "+" + re.sub(r"\D", "", core)
        if style != "e164":   # round 17 (mctrade r16): the same '+44 20 7946 0958' form as the CSV, in the xlsx too
            try:
                import phonenumbers as _pn
                out = _pn.format_number(_pn.parse(out, None), _pn.PhoneNumberFormat.INTERNATIONAL)
            except Exception: pass
    else: out = clean(n); ext = ""
    return out + (f" x{ext}" if ext else "")

ADDR_TAIL = re.compile(r"[,\s]+([A-Za-z][A-Za-z .'-]*?)[,\s]+([A-Z]{2})\.?\s+(\d{5}(?:-\d{4})?)\s*$")
NOCOMMA = re.compile(r"^(.*\b(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way|Ct|Pkwy|Hwy|Pl|Cir|Ter|Sq)\.?"
                     r"(?:\s+(?:Suite|Ste\.?|Unit|#)\s*\S+)?)\s+([A-Za-z][A-Za-z .'-]*?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", re.I)
def fix_separators(a):
    """Round 10 (coordinator r3 4): OCR separators. "3800 Embassy Pkwy.Akron.OH 44308", "Akron;OH 44308", "OH44308".
    Round 11: also used to tell whether an address was misread (the text changes), see ui.address_validates."""
    a = re.sub(r"\b([A-Z]{2})(\d{5}(?:-\d{4})?)$", r"\1 \2", a)
    a = re.sub(r"(?<=[A-Za-z]{3})[.;|·•]\s*(?=[A-Z][a-z]{2,}|[A-Z]{2}\s+\d{5})", ", ", a)
    a = re.sub(r"(?<=[A-Za-z])\s*[;|]\s*", ", ", a)
    return re.sub(r"\s*,\s*,+\s*", ", ", a)

def split_address(a):
    a = clean(a); out = {"address1": "", "address2": "", "city": "", "state": "", "zip": ""}
    if not a: return out
    a = fix_separators(a)
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
def _phones(f): return {re.sub(r"\D", "", p.get("number") or "")[-10:] for p in f.get("phones") or []} - {""}
def _identity(a, b):
    """Same last name + same personal email + same phone + same company: one person even when the first names differ
    (nickname / variant: 'Zeb' and 'Zebulon' Quarrington, mctrade-r4 R4-1)."""
    la, lb = _nm(a.get("last_name")), _nm(b.get("last_name"))
    return (bool(la) and la == lb and bool(personal_emails(a) & personal_emails(b)) and bool(_phones(a) & _phones(b))
            and bool(_org(a.get("company"))) and _org(a.get("company")) == _org(b.get("company")))
def same_person(a, b):
    """Same name (Unicode-aware) AND something that ties them: a shared personal email or phone, or the same company when
    they don't both have (different) personal emails. A shared role mailbox (info@, sales@ ...) alone never makes two people one.
    Round 7: also the same last name + personal email + phone + company with a different first name (nickname)."""
    na, nb = _nm(f"{a.get('first_name','')} {a.get('last_name','')}"), _nm(f"{b.get('first_name','')} {b.get('last_name','')}")
    if na and nb and na != nb and _identity(a, b): return True
    if not na or na != nb: return False
    ea, eb = personal_emails(a), personal_emails(b)
    if ea & eb or _phones(a) & _phones(b): return True
    if ea and eb: return False          # two Ann Lees at one company with different personal emails: different people (R3-12)
    return bool(_org(a.get("company"))) and _org(a.get("company")) == _org(b.get("company"))
def identical(a, b):
    """Same name + same personal email + same phone + same company: one person, whatever a 'different people' click said.
    Round 21 (mctrade-admin r20 H1): the same full name AND the same personal email or phone is one person too, even when the
    company is spelled differently ('Coffee Co.' vs 'Coffee Company'): one row, never two."""
    na, nb = _nm(f"{a.get('first_name','')} {a.get('last_name','')}"), _nm(f"{b.get('first_name','')} {b.get('last_name','')}")
    if na and na == nb and " " in na and (personal_emails(a) & personal_emails(b) or _phones(a) & _phones(b)): return True
    return _identity(a, b)
def person_key(f):   # kept for callers/tests: name + org (never email alone)
    return f"{_nm(f.get('first_name','') + ' ' + f.get('last_name',''))}|{_org(f.get('company'))}"

def row(f, affcode, style):
    ph = {}
    for p in f.get("phones") or []:
        ph.setdefault({"mobile": "cell_phone", "cell": "cell_phone", "fax": "fax"}.get(p.get("type"), "work_phone"), phone(p.get("number"), style))
    v = {"first_name": clean(f.get("first_name")), "last_name": clean(f.get("last_name")), "title": clean(f.get("title")),
         "org_name": clean(f.get("company")), "email": ((f.get("emails") or [""])[0]).strip().lower(),
         "affcode1": affcode, "website": clean(f.get("website")), **ph, **split_address(f.get("address"))}
    out = {IND[k]: neutralize(x) if isinstance(x, str) else x for k, x in v.items() if k in IND}
    if out.get("Website"): out["IndWebsite"] = out["Website"]   # round 8 (part-timer r2): filled when the template has a website column
    return out

def _glued(s):
    """How many spacing slips a value has: '&' or a comma glued to a word, double spaces."""
    s = str(s or ""); return len(re.findall(r"\S&|&\S|,\S|  ", s))
def _merge_into(g, c, r, why):
    """Add card c's row r to group g (lead row = newest decision). Returns the text for WhyLeftOut."""
    g[1].append(c); lost = []
    for k, v in r.items():
        if not v: continue
        if not g[2].get(k): g[2][k] = v
        elif k == "IndTitle" and len(v) > len(g[2][k]) and _nm(g[2][k]) in _nm(v):   # 'Regional Head Groundskeeper' beats 'Head Groundskeeper'
            lost.append(f"{k}={g[2][k]}"); g[2][k] = v
        elif k == "OrgName" and g[2][k] != v and _org(g[2][k]) == _org(v) and _glued(g[2][k]) > _glued(v):
            g[2][k] = v   # round 12 (mctrade F4): same organization, the newer card has a typo ("Hughes& Partners"): keep the clean spelling
        elif g[2][k] != v and k not in ("AffCode1", "MemberSince"): lost.append(f"{k}={v}")
    return (f"{why} card #{g[0]['id']}: its extra details were added to that row (the newest decision wins)"
            + (f"; NOT imported (differs): {', '.join(lost)}" if lost else ""))

REVIEW, NEW, UPDATE, LEFT = "review", "new", "update", "left"
def classify(c, action, hard, crm_real, updates_on, look):
    """Round 8: the ONE per-card MC Trade decision used by the export, the in-app dry run and the export sign-off.
    -> (category, reason, profile_id). category: 'new' | 'update' | 'review' (in neither file: a person must decide) |
    'left' (in neither file: fix first). look(c) -> {"email": [pids with exactly this email], "strong": [pids matching by email,
    or exact name + phone/company], "name": [pids with the exact same name only], "sure": certain pid or None,
    "email_differs": bool}. Rules:
    - a card that matches an existing MC Trade profile is NEVER put in the new-profiles file silently: it is 'review',
      whatever the reviewer chose, unless it is a certain 'update existing' with the updates switch on;
    - an email shared by two MC Trade profiles is always 'review' (ambiguous);
    - without a real contacts export no Profile ID is ever assigned ('update existing' -> review, 'possible existing')."""
    if hard: return LEFT, "FIX FIRST: " + "; ".join(hard.values()), None
    lk = look(c) if crm_real else {}
    em, strong, name = lk.get("email") or [], lk.get("strong") or [], lk.get("name") or []
    if action == "update_existing":
        if not crm_real:
            return REVIEW, ("POSSIBLE EXISTING MEMBER: check in MC Trade. 'Update existing' was chosen, but no real MC Trade contacts "
                            "export is loaded (Admin > Settings), so no Profile ID is assigned and the card is in neither file"), None
        if not updates_on:
            return REVIEW, ("NEEDS REVIEW: 'update existing' was chosen, but updating existing MC Trade contacts is switched off "
                            "(Admin > Settings); in neither file"), None
        if len(em) > 1:
            return REVIEW, f"NEEDS REVIEW: {len(em)} MC Trade profiles share this email ({', '.join(map(str, em))}): ambiguous, merge them in MC Trade first", None
        pid = lk.get("sure")
        if not pid:
            return REVIEW, ("NEEDS REVIEW: 'update existing' but no certain MC Trade Profile ID (needs the same email, or the same "
                            "name + phone); confirm the profile in MC Trade"), None
        if lk.get("email_differs"):
            return REVIEW, f"NEEDS REVIEW: matches profile {pid}, but the email the update would write (the card's first email) differs from the MC Trade email; an update would overwrite it", None
        return UPDATE, f"update of MC Trade profile {pid}", str(pid)
    if crm_real and (em or strong or name):
        ids = list(dict.fromkeys([*em, *strong, *name]))
        why = ("same email" if em else "same name and phone/company" if strong else "same name")
        if len(em) > 1: return REVIEW, f"NEEDS REVIEW: {len(em)} MC Trade profiles share this email ({', '.join(map(str, em))}): ambiguous; in neither file", None
        chose = "Reviewer chose 'create new', but" if action == "create_new" else "Not marked 'update existing', but"
        return REVIEW, (f"NEEDS REVIEW: {chose} MC Trade profile {', '.join(map(str, ids[:3]))} matches ({why}). A new profile would be a "
                        "duplicate; in neither file: choose 'update existing' (if allowed) or confirm in MC Trade"), None
    return NEW, "", None

def build(cards, affcode, style, hard_errors, kept=lambda a, b: False, crm_profile=lambda c: None, action=lambda c: "",
          crm_exact=lambda c: None, crm_real=True, crm_hint=lambda c: None, crm_look=None, updates_on=True, confirmed=lambda f: ()):
    """-> dict(headers, source, rows[(card,row)], updates[(card,row)], left[(card,reason)], merged{card_id: [ids]}, unknown_cols,
    conflicts[str], review[card ids], possible[card ids], decisions{card_id: (category, reason)}).
    Round 8: every card is first put in ONE category by classify() (shared with the dry run and the sign-off); then people
    who appear twice are merged into one row (the merged card is 'left', with the row it went into).
    crm_look(c) -> see classify(); the older crm_profile / crm_exact callbacks are turned into one when it is not given."""
    hdr, source = headers(); out, merged, conflicts, review, possible, dec = [], {}, [], [], [], {}
    if crm_look is None:
        def crm_look(c):
            ex = crm_exact(c); ex = ex if isinstance(ex, list) else ([ex] if ex else [])
            return {"email": ex, "strong": ex, "name": [], "sure": crm_profile(c), "email_differs": False}
    cards = sorted(cards, key=lambda c: -(c.get("decided") or c.get("created") or 0))
    def unconf(c, r):   # round 23 (mctrade-admin r22 H1): a value only 'confirmed as correct' on THIS card never rides into another card's row
        cf = set(confirmed(c["fields"]) or ())
        if not cf: return r
        return row({k: (("" if isinstance(v, str) else []) if k in cf else v) for k, v in c["fields"].items()}, affcode, style)
    groups, ugroups = [], {}
    pending_new = []
    for c in cards:
        r = row(c["fields"], affcode, style)
        cat, why, pid = classify(c, action(c), hard_errors(c["fields"]), crm_real, updates_on, crm_look)
        if cat != NEW and cat != UPDATE:
            if not crm_real and action(c) == "update_existing":
                h = crm_hint(c); why += f" (sample-data hint: {h})" if h else ""; possible.append(c["id"])
            elif cat == REVIEW: review.append(c["id"])
            out.append((c, why)); dec[c["id"]] = (cat, why); continue
        if cat == UPDATE:
            r["ProfileID"] = pid; r["MemberSince"] = ""; dec[c["id"]] = (UPDATE, why)
            if pid in ugroups:
                merged.setdefault(ugroups[pid][0]["id"], []).append(c["id"]); t = _merge_into(ugroups[pid], c, unconf(c, r), f"same MC Trade profile {pid} as")
                out.append((c, t)); dec[c["id"]] = (LEFT, t)
            else: ugroups[pid] = [c, [c], r]
            continue
        pending_new.append((c, r))
    upd_cards = [(pid, x) for pid, g in ugroups.items() for x in g[1]]
    for c, r in pending_new:
        # a person can't be both new and updated (R3-3)
        hit = next((pid for pid, x in upd_cards if same_person(c["fields"], x["fields"])), None)
        if hit:
            t = (f"NEEDS REVIEW: marked 'create new', but this person matches MC Trade profile {hit}"
                 " (also being updated in this export). Not in either file: choose one")
            out.append((c, t)); review.append(c["id"]); dec[c["id"]] = (REVIEW, t); continue
        g = None
        for gg in groups:
            if all(same_person(c["fields"], x["fields"]) and (not kept(c["id"], x["id"]) or identical(c["fields"], x["fields"])) for x in gg[1]):
                g = gg; break
        if not g: groups.append([c, [c], r]); dec[c["id"]] = (NEW, ""); continue
        ka = [x["id"] for x in g[1] if kept(c["id"], x["id"])]
        if ka:
            conflicts.append(f"Cards #{c['id']} and #{', #'.join(map(str, ka))}: a reviewer said 'different people', but name, personal email, "
                             f"phone and company are identical. Exported ONCE (row of card #{g[0]['id']}); check before importing.")
            review.append(c["id"])
        merged.setdefault(g[0]["id"], []).append(c["id"])
        t = (("CONFLICT (check): marked 'different people' but identical email+phone+company; " if ka else "")
             + _merge_into(g, c, unconf(c, r), "same person as"))
        out.append((c, t)); dec[c["id"]] = (REVIEW if ka else LEFT, t)
    rows = [(g[0], g[2]) for g in groups]; upd = [(g[0], g[2]) for g in ugroups.values()]
    names = {canonical(h) for h in hdr if h}
    unknown = [h for h in hdr if h and not canonical(h)]
    unused = sorted({v for v in IND.values()} - names)
    return {"headers": hdr, "source": source, "rows": rows, "updates": upd, "left": out, "merged": merged, "unknown_cols": unknown,
            "unfilled": unused, "conflicts": conflicts, "review": review, "possible": possible, "decisions": dec}

def counts(decisions):
    """Category counts of build()['decisions'] (cards, not rows)."""
    out = {NEW: 0, UPDATE: 0, REVIEW: 0, LEFT: 0}
    for cat, _ in decisions.values(): out[cat] += 1
    return out

def cells(hdr, r):
    """Row values in template order; blank spacer columns stay blank so nothing shifts."""
    return [r.get(canonical(h), "") if h else "" for h in hdr]
