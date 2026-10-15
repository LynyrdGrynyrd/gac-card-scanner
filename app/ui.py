"""Data-team web UI (/ui) + JSON API. Only ADDS routes (and takes over the legacy page URLs, which now redirect to /ui
so every path goes through the same checks). /api/scan contract untouched.
UI state (batches, hashes, archive, audit history, duplicate decisions, undo snapshots, exports, field sources)
lives in extra tables in the same SQLite DB so store.py stays unchanged."""
import asyncio, copy, io, os, re, json, time, uuid, hashlib, datetime, threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Body, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import Response, JSONResponse
from . import store, mctrade_sync, auth, crm_source

router = APIRouter()

# ---- round 13 (skeptic r11 R11-1/2/3): ONE strict card-id rule for every endpoint -----------------------------------
# Accepted: a JSON int (not a bool) or a string of digits only, 1 .. 2**31. Everything else (true, 266.0, null, "abc",
# " 266", "1e3", 2**70) is refused with 422, never coerced and never a 500.
from typing import Annotated
from pydantic import BeforeValidator
MAX_CARD_ID = 2 ** 31
class BadId(Exception):
    def __init__(self, what, value): self.what, self.value = what, value
def strict_id(x, what="card id"):
    if type(x) is int: n = x
    elif type(x) is str and x.isascii() and x.isdigit() and len(x) <= 10: n = int(x)
    else: raise BadId(what, x)
    if not 1 <= n <= MAX_CARD_ID: raise BadId(what, x)
    return n
def _path_id(x):
    try: return strict_id(x)
    except BadId: raise ValueError("must be a whole card number from 1 to 2147483648")
CardId = Annotated[int, BeforeValidator(_path_id)]   # used for every {cid} path parameter
def bad_id_response(e):
    return JSONResponse({"error": f"{e.what} must be a whole card number (1 to {MAX_CARD_ID}); got {json.dumps(e.value)[:40] if not isinstance(e.value, (bytes,)) else 'bytes'}.", "need": "bad_id"}, 422)
STATIC = os.path.join(os.path.dirname(__file__), "static")
from . import paths
DATA = paths.DATA
UP = os.path.join(DATA, "uploads"); EXP = os.path.join(DATA, "exports")

INBOX = os.path.join(DATA, "inbox")   # accepted-but-not-yet-read uploads; survives a crash/restart and is re-queued at start
DONE = os.path.join(DATA, "jobs_done")   # small result records so an open browser can still look a job up after a restart (24 h)
for _d in (UP, EXP, INBOX, DONE): os.makedirs(_d, exist_ok=True)

# ---------------------------------------------------------------- extra tables
META_COLS = ["card_id", "batch", "batch_label", "filename", "sha256", "archived", "dup_resolution", "crm_action", "exported",
             "field_sources", "image_deleted", "ai_status", "ai_detail", "override", "reexport", "back_image", "kept_apart", "ai_rejected"]
def _init_ui(c):
    c.execute("""CREATE TABLE IF NOT EXISTS card_meta(card_id INTEGER PRIMARY KEY, batch TEXT, batch_label TEXT,
      filename TEXT, sha256 TEXT, archived INTEGER DEFAULT 0, dup_resolution TEXT, crm_action TEXT, exported REAL)""")
    have = {r[1] for r in c.execute("PRAGMA table_info(card_meta)")}
    for col, typ in (("field_sources", "TEXT"), ("image_deleted", "REAL"), ("ai_status", "TEXT"), ("ai_detail", "TEXT"), ("override", "TEXT"), ("reexport", "REAL"), ("back_image", "TEXT"), ("kept_apart", "TEXT"), ("ai_rejected", "TEXT")):
        if col not in have:
            try: c.execute(f"ALTER TABLE card_meta ADD COLUMN {col} {typ}")
            except Exception as e:   # another thread added it first
                if "duplicate column" not in str(e): raise
    c.execute("""CREATE TABLE IF NOT EXISTS card_history(id INTEGER PRIMARY KEY, card_id INTEGER, ts REAL, reviewer TEXT,
      action TEXT, from_status TEXT, to_status TEXT, detail TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, ts REAL, user_id INTEGER, username TEXT, label TEXT,
      snapshot TEXT, undone REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS exports(id INTEGER PRIMARY KEY, ts REAL, username TEXT, initials TEXT, kind TEXT,
      filter TEXT, count INTEGER, filename TEXT, card_ids TEXT, stored TEXT)""")
    if "batch_label" not in {r[1] for r in c.execute("PRAGMA table_info(exports)")}:
        try: c.execute("ALTER TABLE exports ADD COLUMN batch_label TEXT")
        except Exception as e:
            if "duplicate column" not in str(e): raise
    for name, ix in (("ix_hist_card", "card_history(card_id, id)"), ("ix_hist_action", "card_history(action, reviewer)"),
                     ("ix_meta_batch", "card_meta(batch)"), ("ix_meta_sha", "card_meta(sha256)"),
                     ("ix_actions_user", "actions(user_id, undone)"), ("ix_exports_file", "exports(filename)")):
        c.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {ix}")
def db():
    """Audit 2026-10 P0-4: schema set-up runs once per database file, not on every connection."""
    c = store.db(); store.once("ui", _init_ui)
    return c

def meta(cid):
    r = db().execute("SELECT * FROM card_meta WHERE card_id=?", (cid,)).fetchone()
    return dict(r) if r else {k: None for k in META_COLS} | {"card_id": cid, "archived": 0}

def set_meta(cid, **kw):
    """Audit 2026-10 P0-1: write ONLY the given columns. The old read-whole-row / INSERT OR REPLACE put back stale values
    of every other column, so a background writer (AI check, export marking, retention) could undo a reviewer's change."""
    cols = [k for k in kw if k in META_COLS and k != "card_id"]
    with db() as c:
        c.execute("INSERT INTO card_meta(card_id) VALUES(?) ON CONFLICT(card_id) DO NOTHING", (cid,))
        if cols: c.execute(f"UPDATE card_meta SET {','.join(k + '=?' for k in cols)} WHERE card_id=?", (*(kw[k] for k in cols), cid))

def log(cid, reviewer, action, frm=None, to=None, detail=None):
    with db() as c:
        c.execute("INSERT INTO card_history(card_id,ts,reviewer,action,from_status,to_status,detail) VALUES(?,?,?,?,?,?,?)",
                  (cid, time.time(), reviewer, action, frm, to, json.dumps(detail) if detail is not None else None))

def history(cid):
    out = [dict(r) | {"detail": json.loads(r["detail"]) if r["detail"] else None}
           for r in db().execute("SELECT * FROM card_history WHERE card_id=? ORDER BY id", (cid,))]
    for h in out: h["text"] = _audit_text(h["action"], h["from_status"], h["to_status"], h["detail"])
    return out

def all_metas():
    return {r["card_id"]: dict(r) for r in db().execute("SELECT * FROM card_meta")}

def sources(cid):
    try: return json.loads(meta(cid).get("field_sources") or "{}")
    except Exception: return {}

# ---------------------------------------------------------------- undo (snapshot before every change)
def snapshot(ids, user, label):
    snap = []
    for i in ids:
        r = db().execute("SELECT * FROM cards WHERE id=?", (i,)).fetchone()
        m = db().execute("SELECT * FROM card_meta WHERE card_id=?", (i,)).fetchone()
        if r: snap.append({"card": dict(r), "meta": dict(m) if m else None,
                           "hist_max": db().execute("SELECT COALESCE(MAX(id),0) FROM card_history WHERE card_id=?", (i,)).fetchone()[0]})
    with db() as c:
        aid = c.execute("INSERT INTO actions(ts,user_id,username,label,snapshot) VALUES(?,?,?,?,?)",
                        (time.time(), user["id"], user["username"], label, json.dumps(snap))).lastrowid
    _unsealed().append(aid); return aid

# audit 2026-10 P1: per THREAD (= per request), so one request's _seal() never seals another request's snapshot before
# that request has written (Undo then saw before == after and "undid" nothing while reporting success)
_SEAL_TLS = threading.local()
def _unsealed():
    if not hasattr(_SEAL_TLS, "ids"): _SEAL_TLS.ids = []
    return _SEAL_TLS.ids
def _row_state(i):
    r = db().execute("SELECT * FROM cards WHERE id=?", (i,)).fetchone()
    m = db().execute("SELECT * FROM card_meta WHERE card_id=?", (i,)).fetchone()
    return (dict(r) if r else None), (dict(m) if m else None)
def _seal():
    """Round 9 (skeptic R9-1): once the action has been written, store each card's state AFTER it, so Undo can tell
    which values the action changed and which were changed later by someone else."""
    pend = _unsealed()
    while pend:
        aid = pend.pop()
        r = db().execute("SELECT snapshot FROM actions WHERE id=?", (aid,)).fetchone()
        if not r: continue
        snap = json.loads(r[0])
        for s_ in snap:
            cd, md = _row_state(s_["card"]["id"]); s_["after"] = {"card": cd, "meta": md}
        with db() as c: c.execute("UPDATE actions SET snapshot=? WHERE id=?", (json.dumps(snap), aid))

def _s(n, w):   # round 21: '1 card' / '3 cards' instead of 'card(s)'
    return w if n == 1 else w + 's'
def _who(request): return request.state.user["initials"]

# ---------------------------------------------------------------- validation & attention (single source of truth)
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}$")
def _digits(s): return re.sub(r"\D", "", s or "")
def phone_ok(n): return 10 <= len(_digits(n)) <= 15

def _nm(f): return re.sub(r"\s+", " ", f"{(f or {}).get('first_name','')} {(f or {}).get('last_name','')}".strip().lower())
def validate(f):
    err = {}
    if not (f.get("first_name") or "").strip():
        err["name"] = "First name is required." if f.get("last_name") else "Name is required."
    bad = [e for e in f.get("emails", []) if email_syntax(e)]
    if bad: err["emails"] = "Not a valid email: " + ", ".join(bad)
    badp = [p["number"] for p in f.get("phones", []) if not phone_ok(p.get("number"))]
    if badp: err["phones"] = "Phone number looks incomplete: " + ", ".join(badp)
    if not f.get("emails") and not f.get("phones"): err.setdefault("emails", "Add at least an email or a phone number.")
    return err

# Round 7: RFC-style rules (mctrade-r4 R4-4). Local part: the RFC 5322 'atext' characters (so ann&co@ and ann#1@ pass) and
# letters, no leading = + - @ . ' (formula / junk), no '..'. Domain: letter/digit/hyphen labels (no '_', no '..', no leading or
# trailing '-'), and a top-level domain of 2+ letters (or xn--). These are HARD errors: 'Approve anyway' can't bypass them.
_LOCAL_OK = re.compile(r"^[\w!#$%&'*+/=?^`{|}~.-]+$")
_LABEL = re.compile(r"^(?!-)[^\W_](?:[^\W_]|-){0,62}(?<!-)$")
def email_syntax(e):
    """None if e is a usable email address, else a short reason."""
    e = (e or "").strip()
    if e.count("@") != 1: return "needs exactly one @"
    lp, dom = e.rsplit("@", 1)
    if not lp or len(lp) > 64 or not _LOCAL_OK.match(lp): return "the part before @ has characters an address can't have"
    if lp[0] in "=+-@.'" or lp[-1] == "." or ".." in lp: return "the part before @ starts or ends badly or has '..'"
    if not dom or len(dom) > 253 or dom.endswith(".") or ".." in dom: return "the domain is incomplete"
    labels = dom.split(".")
    if len(labels) < 2: return "the domain has no ending (.com, .org …)"
    if not all(_LABEL.match(l) for l in labels): return "the domain has characters a web address can't have (e.g. _)"
    tld = labels[-1]
    if not (tld.isalpha() and len(tld) >= 2) and not tld.lower().startswith("xn--"): return "the domain ending (.com, .org …) is not valid"
    return None
ZW = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff\u202a-\u202e\u00ad]")
def clean_note(n):
    """Round 10 (skeptic R9-3): invisible characters are removed from the note, and a note that a spreadsheet could run as
    a formula (= + - @ at the start, also after spaces or a tab) gets a leading apostrophe, like the CSV export does."""
    n = ZW.sub("", n or "")
    if re.match(r"^[\s]*[=+\-@\t]", n) and not re.match(r"^\s*-\s", n): n = "'" + n.lstrip()
    return n

REASON_MAX = 300
def clean_reason(r):
    """Round 22 (skeptic r21 L1): an 'approve anyway' reason: invisible characters removed, at least 3 real letters/digits,
    at most 300 characters, no formula start or HTML. Returns (clean text, problem or None)."""
    if not isinstance(r, str): return "", "The reason must be text."
    r = re.sub(r"\s+", " ", ZW.sub("", r).replace("\u00a0", " ")).strip()
    if len(re.findall(r"\w", r)) < 3: return r, "Write a short reason (at least 3 letters)."
    if len(r) > REASON_MAX: return r, f"The reason is too long (at most {REASON_MAX} characters)."
    if re.match(r"^[=+\-@]", r) or re.search(r"<\s*[a-z/!]|&#|javascript:", r, re.I): return r, "The reason can't contain formulas or HTML code."
    return r, None

TEXT_FIELDS = ("first_name", "last_name", "credentials", "title", "company", "department", "website", "address", "other_address")
def fields_shape_problem(fields):
    """Fuzz 2026-10: 'fields' must be what the review page sends (text values; emails/social lists of text; phones a list of
    {type, number}). fields: [...], phones: true or phones: [null] crashed the save/validate code with a 500."""
    if fields is None: return None
    if not isinstance(fields, dict): return "fields must be an object of card values."
    for k in TEXT_FIELDS:
        if fields.get(k) is not None and not isinstance(fields[k], str): return f"{LABEL.get(k, k.replace('_', ' ').capitalize())} must be text."
    for k in ("emails", "social"):
        v = fields.get(k)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)): return f"{LABEL.get(k, k)} must be a list of text values."
    v = fields.get("phones")
    if v is not None and not (isinstance(v, list) and all(isinstance(p, dict) and all(isinstance(p.get(x, ""), str) for x in ("type", "number")) for p in v)):
        return "Phone numbers must be a list of {type, number} with text values."
    return None

def payload_problems(fields):
    """Shared server-side check for every endpoint that writes card values (save, approve, merge, AI accept, validate):
    only the values being sent are checked. HTML, formula text, invisible characters, impossible emails/phones."""
    if not isinstance(fields, dict) or not fields: return {}
    f = {k: v for k, v in fields.items() if k in ("first_name", "last_name", "title", "company", "website", "address", "department",
                                                   "credentials", "other_address", "emails", "phones", "social")}
    out = {}
    from . import mctrade_export as _mx
    if isinstance(fields.get("note"), str) and fields["note"]: f["note"] = fields["note"]   # skeptic R8-3: the note is checked too
    for k, msg in _mx.content_problems(f).items(): out[k] = msg[0].upper() + msg[1:]
    bad = [e for e in (f.get("emails") or []) if isinstance(e, str) and e.strip() and email_syntax(e) and re.search(r"[<>=]|@.*@", e)]
    if bad: out.setdefault("emails", "Not an email address: " + ", ".join(bad))
    return out

def hard_errors(f):
    """Problems that 'Approve anyway' can NOT override: a blank first name, and values that are certainly not an email / phone number."""
    err = {}
    if not (f.get("first_name") or "").strip():
        err["name"] = "First name is required." if f.get("last_name") else "Name is required (at least a first name)."
    bad = [f"{e} ({email_syntax(e)})" for e in f.get("emails", []) if email_syntax(e)]
    if bad: err["emails"] = "Not a valid email address: " + ", ".join(bad) + ". Fix or delete it."
    _hasl = lambda n: bool(re.search(r"[A-Za-z]", _mx_ext_strip(n)))   # round 24 (mctrade-admin r23 L1): '33o-555-0100' has a letter, not a missing area code
    letp = [p["number"] for p in f.get("phones", []) if _hasl(p.get("number"))]
    if letp: err["phones"] = "Phone " + ", ".join(f"“{x}”" for x in letp) + " has a letter in it. Check the photo and fix it."
    badp = [p["number"] for p in f.get("phones", []) if not _hasl(p.get("number")) and len(_digits(p.get("number"))) < 7]
    if letp: pass
    elif badp: err["phones"] = "Not a phone number (too few digits): " + ", ".join(badp) + ". Fix or delete it."
    else:   # round 23 (mctrade-admin r22 M3): '555-0100' (7 digits, no area code) can't go to MC Trade
        shortp = [p["number"] for p in f.get("phones", []) if not _hasl(p.get("number")) and phone_no_area(p.get("number"))]
        if shortp: err["phones"] = "Phone " + ", ".join(f"“{x}”" for x in shortp) + " has no area code. Add it from the card, or delete it."
    from . import mctrade_export as _mx
    for k, msg in _mx.content_problems(f).items(): err.setdefault(k, msg[0].upper() + msg[1:] + ". Fix it: it can't go into MC Trade.")
    for k, msg in garbled_errors(f).items(): err.setdefault(k, msg)
    return err

_MIXNUM = re.compile(r"\b\d+[oOlI]+(?:\d+[A-Za-z]*|\b|(?=[A-Z]))")   # round 21: '38ooEmbassy Pkwy' too
_GARB_SYM = re.compile(r"[@#%|¦~€!$^*_=<>{}\\\[\]]")
_GARB_MIX = re.compile(r"(?<=[A-Za-z])[01]{1,2}(?=[A-Za-z])|\b[01](?=[a-z]{2})")   # 0/O and 1/l swaps inside or starting a word: 'J0hn', 'Gr0up', 'Mar1a', '0livia'; 'Test3', 'Person0', 'Manager1792' are not swaps
_GARB_LOOK = re.compile(r"\b(?:[A-Z][a-z]*[Il][a-z]*\|)|[a-z]\|[a-z]")
def name_garbled(v, allow_digits=False):
    """Round 21 (reviewer r20 HIGH): 'M@r#ia%%', 'Vlce Pres|dent ¦¦ ~~ Comm€rc!al', 'J0hn'. None if clean, else the bad bit."""
    v = str(v or "")
    if not v.strip(): return None
    m = _GARB_SYM.search(v)
    if m: return m.group(0)
    if not allow_digits:
        m = _GARB_MIX.search(v)
        if m: return m.group(0)
    return None
def garbled_errors(f):
    """Round 20 (coordinator r19): misreads that reached the export with only a soft hint now BLOCK approval until fixed:
    a house number with a letter in it ('118o S Main St'), a garbled website ('wwwsummit…', 'wvw.c0m.xq'), and an email
    domain that is 1-2 letters off the website ('pembertn.com' vs 'pemberton.com')."""
    err = {}
    for k, lab in (("first_name", "First name"), ("last_name", "Last name"), ("title", "Job title"),
                   ("company", "Company"), ("department", "Department")):   # round 22 (reviewer r21 HIGH): company/department too
        v_ = f.get(k)
        if k in ("company", "department"): v_ = re.sub(r"!+\s*$", "", str(v_ or ""))   # 'Yahoo!' is a real name
        if k in ("company", "department"): v_ = re.sub(r"(?<=[A-Za-z])\*(?=[A-Za-z])", "", v_)   # round 23 (mctrade-admin r22 M1): 'E*Trade' is a real name
        bad = name_garbled(v_, allow_digits=(k == "title"))
        if not bad and k in ("first_name", "last_name"):   # round 23 (part-timer r22 HIGH): 'Morg4n': a digit in a name is always a misread
            m_ = re.search(r"\d", str(v_ or "")); bad = m_.group(0) if m_ else None
        if not bad and k == "title":   # round 22 (newcomer r21): 'Acc0unt Manager' (a 0/1 inside a word); '1st', 'Level 3' are fine
            m_ = re.search(r"(?<=[A-Za-z])[01]{1,2}(?=[A-Za-z])", str(v_ or "")); bad = m_.group(0) if m_ else None
        if bad: err["name" if k == "first_name" else k] = f"{lab} “{f.get(k)}” has “{bad}” in it: a misread. Check the photo and fix it."
    for p_ in f.get("phones") or []:
        n_ = str((p_ or {}).get("number") or "")
        if re.search(r"(?<![A-Za-z])[oOlI](?=\d)|(?<=\d)[oOlI](?![A-Za-z])|\d[oOlIsS]+\d|\([\doOlI]*[oOlI][\doOlI]*\)|\d{3}\)?[ .-]?\d{2,3}[oOlI]", n_):
            err["phones"] = f"Phone “{n_}” has a letter inside the number (0/o, 1/l). Check the photo and fix it."; break
    for k in ("address", "other_address"):
        v = str(f.get(k) or "")
        m = _MIXNUM.search(v) or re.search(r"\b[A-Za-z]+0[A-Za-z]*\b|\bl\d+\b", v)   # round 21 (mctrade-admin r20): S0uth, l18
        if m: err[k] = f"“{m.group(0)}” has letters mixed with digits. Check the photo."
        elif re.match(r"^\s*[a-z]\s+(?:[NSEW]\.?\s+)?[A-Z]", v):   # round 22: 'g W Exchange St' (house number read as a letter)
            err[k] = f"Address “{v[:100]}” starts with “{v.strip()[0]}” where the house number should be. Check the photo and fix it."
        else:
            m = re.search(r"[|¦~€!$^*_=<>{}\\\[\]]", v)   # round 22: garbled symbols in the address
            if m: err[k] = f"Address “{v[:100]}” has “{m.group(0)}” in it: a misread. Check the photo and fix it."
    if "company" not in err and f.get("company"):   # round 22 (newcomer r21): a gibberish company ('Higneniscdaie CoffeeCa') blocks
        try:
            if company_gibberish(f.get("company")):   # round 23 (r22 reviewer/newcomer/datamanager): 'CoffeeCo.' is run-together, not gibberish
                err["company"] = f"Company “{f.get('company')}” looks misread. Check the photo."
        except Exception: pass
    w = str(f.get("website") or "").strip()
    ems = [e for e in f.get("emails") or [] if "@" in str(e)]
    for e in ems:   # round 22 (datamanager r21 M2): a lost dot is caught with no website too ('…hardwexample.com', '…comcom.com')
        ed = str(e).lower().rsplit("@", 1)[-1].strip(); sld = ed.rsplit(".", 1)[0].split(".")[-1]
        m_ = re.search(r"^(.{4,}?)(example|com|net|org)$", sld)
        if m_ and (m_.group(2) == "example" or re.search(r"(com|net|org)$", m_.group(1))):
            err["emails"] = f"Email domain “{ed}” looks like a dot is missing. Check the photo and fix it."; break
    if w and "website" not in err:   # round 24 (datamanager r23 M1): the website gets the same lost-dot check as emails
        wd = re.sub(r"^[a-z]+://", "", w.lower()).split("/")[0]; wd = wd[4:] if wd.startswith("www.") else wd
        sldw = wd.rsplit(".", 1)[0].split(".")[-1]
        m_ = re.search(r"^(.{4,}?)(example|com|net|org)$", sldw)
        if "." in wd and m_ and (m_.group(2) == "example" or re.search(r"(com|net|org)$", m_.group(1))):
            err["website"] = f"Website “{w}” looks like a dot is missing. Check the photo and fix it."
    if "website" in err: pass
    elif w and (re.match(r"^(https?://)?(www(?![.\d])|wvw\.|vvww?\.)", w, re.I) or ".." in w or not plausible_site(w, ems)):
        err["website"] = f"Website “{w}” looks misread. Check the photo and fix it, or clear it."
    elif w:
        d = re.sub(r"^[a-z]+://", "", w.lower()).split("/")[0]; d = d[4:] if d.startswith("www.") else d
        for e in ems:
            ed = str(e).lower().rsplit("@", 1)[-1].strip()
            if ed == d or ed.endswith("." + d) or d.endswith("." + ed): continue
            # round 21 (datamanager r20 HIGH): a dot lost in the domain ('firestoneparkhardwexample.com' vs 'example.com')
            if len(d) >= 6 and (ed.endswith(d) or ed.replace(".", "") == d.replace(".", "")):
                err["emails"] = (f"Email domain “{ed}” looks like the website “{d}” with a dot missing: a misread. Fix it (e.g. “…{ed[:-len(d)] if ed.endswith(d) else ''}.{d}”)."); break
            a_, b_ = ed.rsplit(".", 1)[0], d.rsplit(".", 1)[0]
            if a_.replace("-", "") == b_.replace("-", ""): continue   # acmegroup.com vs acme-group.com
            dd = _lev(a_, b_) if a_ and b_ else 9   # 'same' vs 'acme' is two companies; 'pembertn' vs 'pemberton' is a misread
            if dd == 1 and min(len(a_), len(b_)) >= 5 or dd == 2 and min(len(a_), len(b_)) >= 8:
                err.setdefault("emails", f"Email domain “{ed}” and website “{d}” differ by a letter or two: one is misread. Fix the wrong one."); break
    ok = valid_confirmations(f)   # round 23: only confirmations that pass today's rules (re-checked everywhere, also at export)
    for k in list(err):   # round 21 (mctrade-admin r20): a reviewer said 'This is correct' for exactly this value
        fk = "first_name" if k == "name" else k
        if fk in ok and json.dumps(f.get(fk), sort_keys=True) == ok[fk]: err.pop(k)
    return err

def _mx_ext_strip(n):
    from . import mctrade_export as _mx
    return _mx.EXT.sub("", str(n or ""))
def phone_no_area(n):
    """Round 23: a US-style number with 7-9 digits (extension removed): the area code is missing. '+' numbers are left alone."""
    n = str(n or "").strip()
    if n.startswith("+"): return False
    from . import mctrade_export as _mx
    d = _digits(_mx.EXT.sub("", n))
    return 7 <= len(d) <= 9

_CO_TAIL = {"Co", "Inc", "Ltd", "Corp", "Llc", "Lp", "Pc", "Pa", "Plc"}
def company_gibberish(c):
    """Round 23: a company word that can't be a word ('Higneniscdaie', 'CoffeeCa'). 'CoffeeCo.' (two words run together,
    ending in a usual company abbreviation) is only a spacing hint, never a block."""
    from . import plausibility as _pl
    for w_ in re.findall(r"[A-Za-z]+", str(c or "")):
        rare = sum(1 for i in range(len(w_) - 1) if w_[i:i + 2].lower() in _pl._RARE2)
        if (len(w_) >= 10 and rare >= 1) or rare >= 2 or re.search(r"[bcdfghjklmnpqrstvwxz]{5,}", w_.lower()): return w_
        if w_ in _pl.CAMEL_OK or w_ in ("QuickBooks", "LinkedIn", "HubSpot", "PayPal", "DoorDash", "SoundCloud", "GitHub", "DropBox", "MailChimp"): continue   # round 24 (mctrade-admin r23 M1)
        m_ = re.search(r"[a-z]{3,}([A-Z][a-z]?)$", w_)
        if m_ and m_.group(1).capitalize() not in _CO_TAIL: return w_
    return None

CONFIRM_FIELDS = ("first_name", "last_name", "title", "company", "department", "address", "other_address", "website", "emails")
def valid_confirmations(f):
    """Round 23 (mctrade-admin r22 H1, datamanager r22 H1): the 'This is correct' confirmations that still count, re-checked
    against today's rules every time (save, approve, export): one field each, a known person, a reason, admin-only fields
    confirmed by an admin, the exact saved value, and never a phone, a formula or HTML. Older confirmations (before r23:
    no author/reason recorded) no longer count, so those values block again until fixed or confirmed again."""
    ok = f.get("confirmed_ok") if isinstance(f.get("confirmed_ok"), dict) else {}
    cm = f.get("confirmed_meta") if isinstance(f.get("confirmed_meta"), dict) else {}
    out = {}
    from . import mctrade_export as _mx
    cp = _mx.content_problems({k: v for k, v in f.items() if k in CONFIRM_FIELDS})
    for fk, val in ok.items():
        m = cm.get(fk) if isinstance(cm.get(fk), dict) else None
        k = "name" if fk == "first_name" else fk
        if fk not in CONFIRM_FIELDS or not m or not m.get("user") or not m.get("reason") or m.get("value") != val: continue
        if json.dumps(f.get(fk), sort_keys=True) != val or fk in cp or k in cp: continue
        if k in ADMIN_OVERRIDE and m.get("role") != "admin": continue
        vs = f.get(fk) if isinstance(f.get(fk), str) else json.dumps(f.get(fk))
        if re.search(r"(^|[\s\"])[=+@]|^\s*-|<[a-z/!]", vs or "", re.I): continue
        out[fk] = val
    return out

# round 22: phones are never overridable (a letter in a phone number is never right)
OVERRIDABLE = ("name", "last_name", "title", "company", "department", "address", "other_address", "website", "emails")
ADMIN_OVERRIDE = ("emails", "website", "address", "other_address")
def overridable(f):
    """Fields whose hard check can be confirmed with 'This is correct': only garbled-looking values, never formula/HTML."""
    from . import mctrade_export as _mx
    g = garbled_errors({**f, "confirmed_ok": {}}); cp = _mx.content_problems(f)
    out = []
    for k in g:
        fk = "first_name" if k == "name" else k
        if k in OVERRIDABLE and k not in cp and fk not in cp:
            v = f.get(fk); vs = json.dumps(v) if not isinstance(v, str) else v
            if not re.search(r"(^|[\s\"])[=+@]|^\s*-|<[a-z/!]", vs, re.I): out.append(k)
    return out
def _lev(a, b):
    if abs(len(a) - len(b)) > 2: return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1): cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

def address_validates(a):
    """Round 10 (part-timer r3): an address that splits cleanly into street, city, a real state and a zip is readable,
    whatever score the OCR gave it."""
    from . import mctrade_export as _mx, parser as _pz
    if not (a or "").strip(): return False
    # round 11 (part-timer r4): "Akron. OH" / "Pkwy.Akron" is still a misread (it exports fine, but the card should say so)
    if _mx.fix_separators(_mx.clean(a)) != _mx.clean(a): return False
    p = _mx.split_address(a)
    return bool(p["city"] and p["state"] in _pz.STATES and re.fullmatch(r"\d{5}(-\d{4})?", p["zip"] or "")
                and re.match(r"^(\d+\w?\s|p\.?\s*o\.?\s*box)", p["address1"] or "", re.I))

def calibrated_conf(f):
    c = dict(f.get("confidence") or {})
    if c.get("address") is not None and 0.45 <= c["address"] < 0.8 and address_validates(f.get("address")): c["address"] = 0.8
    return c

def low_fields(f, src=None):
    """Fields the reviewer should double-check: low confidence, or listed in the parser's needs_review.
    A field a person already edited or explicitly confirmed (e.g. 'Keep current' on an AI suggestion) is not listed."""
    done = {k for k, v in (src or {}).items() if str(v).startswith(("edited", "confirmed"))}
    if "first_name" in done or "last_name" in done: done.add("name")
    ok_addr = ((f.get("confidence") or {}).get("address") or 1) >= 0.45 and address_validates(f.get("address"))   # a very poor read (< 45 %) is still listed
    out = [k for k in (f.get("needs_review") or []) if isinstance(k, str) and k not in done and not (k == "address" and ok_addr)]
    for n, v in calibrated_conf(f).items():
        if v is None or v >= 0.6 or n in done: continue
        val = f.get(n) if n != "name" else (f.get("first_name") or f.get("last_name"))
        if (val or n in ("name", "company", "emails")) and n not in out: out.append(n)
    return out

def _low_after_ai(f, src, m):
    """Yellow 'Please check' flags. When the AI double-check read the card and found nothing to change, the flags on the
    fields it reads are dropped (newcomer F5: yellow next to 'no changes needed' was a mixed signal)."""
    low = low_fields(f, src)
    try: det = json.loads(m.get("ai_detail") or "{}")
    except Exception: det = {}
    if m.get("ai_status") == "checked" and not det.get("diff") and det.get("finished"):
        try:   # reviewer r8: a rule-based hint (Rnbber, Mian ...) keeps its field flagged whatever the AI said
            from . import plausibility as _pl
            hinted = {x.get("field") for x in _pl.check(json.loads(json.dumps(f)))}
        except Exception: hinted = set()
        if "name" in hinted: hinted |= {"first_name", "last_name"}
        low = [k for k in low if k in hinted or k not in ("name", "first_name", "last_name", "title", "company", "emails", "phones", "website", "address")]
    return low

def _as_row(c):
    f = c["fields"]
    return {"profile_id": f"card:{c['id']}", "first_name": f.get("first_name", ""), "last_name": f.get("last_name", ""),
            "organization": f.get("company", ""), "email": (f.get("emails") or [""])[0],
            "phone": (f.get("phones") or [{"number": ""}])[0]["number"],
            "phones": [p_.get("number") or "" for p_ in f.get("phones") or []], "emails": list(f.get("emails") or []),
            "website": f.get("website") or "", "address": f.get("address") or ""}

# round 14 (speed, /api/cards 2.5-5.6 s at ~330 cards): (1) a blocking index so each card is only compared with cards that
# share a phone, an email, a name start, a company word, a website, an address or the photo; (2) the look-alike list of
# every card is cached until any card, status or look-alike-relevant meta field changes (one fingerprint per request).
_DK = ("batch", "sha256", "archived", "kept_apart", "dup_resolution", "crm_action")
_DC = {"refs": {}, "ctx": None}; _DCL = threading.Lock()

def _bkeys(f, m):
    k = set(); al = lambda x: re.sub(r"[^a-z0-9@]", "", (x or "").lower())
    for p_ in f.get("phones") or []:
        from . import mctrade_export as _mx
        for d_ in (_digits(p_.get("number") or ""), _digits(_mx.EXT.sub("", p_.get("number") or ""))):
            if len(d_) >= 7: k.add("p:" + d_[-7:])
    for e in f.get("emails") or []:
        if al(e): k.add("e:" + al(e)); k.add("u:" + al(e).split("@")[0][:6])
    for nm, t in ((f.get("last_name"), "l:"), (f.get("first_name"), "f:")):
        if al(nm)[:2]: k.add(t + al(nm)[:2])
    for w in re.findall(r"[a-z0-9]{3,}", (f.get("company") or "").lower())[:2]: k.add("c:" + w)
    if al(f.get("website"))[:6]: k.add("w:" + re.sub(r"^(https?)?(www)?", "", al(f.get("website")))[:10])
    if al(f.get("address"))[:8]: k.add("a:" + al(f.get("address"))[:12])
    if m.get("sha256"): k.add("h:" + m["sha256"])
    return k
def _dctx(others, metas):
    """One look-alike context per data fingerprint. Each request gets a context whose index and result cache belong to
    exactly the data it passed in (requests run in parallel threads: one request never reads or fills another's)."""
    now = time.time()
    with _DCL:   # the SAME list/dict objects within 3 s = one request; they are held here, so their ids can't be reused
        hit = _DC["refs"].get(id(others))
        if hit and hit[0] is others and hit[1] is metas and hit[2] == len(others) and now - hit[3] < 3: return hit[4]
        ctx = _DC["ctx"]
    sig = hashlib.sha1(json.dumps([[o["id"], o["status"], o["fields"], [(metas.get(o["id"]) or {}).get(k_) for k_ in _DK]] for o in others],
                                  sort_keys=True, default=str).encode()).hexdigest()
    if not ctx or ctx["sig"] != sig:
        idx = {}
        for o in others:
            for k_ in _bkeys(o["fields"], metas.get(o["id"]) or {}): idx.setdefault(k_, []).append(o)
        ctx = {"sig": sig, "idx": idx, "res": {}}
    with _DCL:
        _DC["refs"] = {k_: v for k_, v in _DC["refs"].items() if now - v[3] < 3}
        _DC["refs"][id(others)] = (others, metas, len(others), now, ctx); _DC["ctx"] = ctx
    return ctx
def _cands(c, others, metas, ctx):
    seen = {}
    for k_ in _bkeys(c["fields"], metas.get(c["id"]) or {}):
        for o in ctx["idx"].get(k_, ()): seen[o["id"]] = o
    return [o for o in others if o["id"] in seen]   # same order as before
_CRM_IX = {"rows": None, "ix": None}; _CRM_IXL = threading.Lock()

def _crm_index(rows):
    """One mctrade_sync.Index per contacts list object (the list is cached by crm_source until the file changes)."""
    with _CRM_IXL:
        if _CRM_IX["rows"] is not rows: _CRM_IX.update(rows=rows, ix=mctrade_sync.Index(rows))
        return _CRM_IX["ix"]
def dupes(c, others, metas):
    f = c["fields"]; m = metas.get(c["id"]) or {}
    _crm_rows, _crm_sample = crm_source.rows_for_hints()
    crm = [d | {"sample": _crm_sample} for d in _crm_index(_crm_rows).match(f) if d["score"] >= 0.3]
    ctx = _dctx(others, metas)
    # the card's OWN meta is part of the key: approval_check() changes it in place (kept_apart) before asking again
    ck = (c["id"], c["status"], json.dumps(f, sort_keys=True, default=str), json.dumps([m.get(k_) for k_ in _DK], default=str))
    if ck in ctx["res"]:
        r = copy.deepcopy(ctx["res"][ck]); r.update(crm=crm, meta=m, updates_enabled=auth.get_setting("mctrade_updates_enabled") == "1"); return r
    r = _dupes(c, _cands(c, others, metas, ctx), metas, crm)
    ctx["res"][ck] = copy.deepcopy({k_: v for k_, v in r.items() if k_ not in ("crm", "meta")}); return r
def _dupes(c, others, metas, crm):
    f = c["fields"]; m = metas.get(c["id"]) or {}
    rej = c["status"] == "rejected"   # round 14 (reviewer r12): a rejected card keeps its look-alike hints, incl. rejected ones
    _gone = lambda o: (metas.get(o["id"]) or {}).get("archived") or str((metas.get(o["id"]) or {}).get("dup_resolution") or "").startswith("merged_into")
    # round 15 (reviewer r14): a pending card still shows rejected look-alikes as hints (never blocking). Before, bulk-rejecting
    # one twin dropped "May be the same person as #N" from the other card.
    rows = [_as_row(o) for o in others if o["id"] != c["id"] and not _gone(o)
            and not (metas.get(o["id"]) or {}).get("archived")]
    # round 7 (coordinator r1 #3): a very similar name + the same company counts too (the email/phone may be misread or missing)
    q = [d | {"card_id": int(d["profile_id"].split(":")[1])} for d in mctrade_sync.match(f, rows, near_names=True)
         if d["score"] >= 0.5 or (d["score"] >= 0.39 and any(w.startswith("name~") and float(w[5:]) >= 0.9 for w in d["why"])
                                  and any(w.startswith("org~") and float(w[4:]) >= 0.85 for w in d["why"]))
         or _name_plus(d, f, rows)]
    # round 10 (newcomer r9): ONE look-alike source. Approved cards in other batches with the same email/phone (what the
    # approve warning and the READ-ME use) are always in this list too.
    for x in _cross_batch(c, f, others, metas):
        hit = next((d for d in q if d["card_id"] == x["card_id"]), None)
        if hit: hit["why"] = hit["why"] + [w for w in x["why"] if w not in hit["why"] and w != "same photo"]
        elif {"same email", "same phone"} & set(x["why"]):
            o = next(o for o in others if o["id"] == x["card_id"]); of = o["fields"]
            q.append({"card_id": x["card_id"], "profile_id": f"card:{x['card_id']}", "name": f"{of.get('first_name','')} {of.get('last_name','')}".strip(),
                      "organization": of.get("company", ""), "score": 0.5, "why": list(x["why"])})
    h = m.get("sha256")
    if h:
        same = [o["id"] for o in others if o["id"] != c["id"] and (metas.get(o["id"]) or {}).get("sha256") == h
                and not (metas.get(o["id"]) or {}).get("archived") and not _gone(o)]
        for sid in same:
            hit = next((d for d in q if d["card_id"] == sid), None)
            if hit and "same photo" not in hit["why"]: hit["why"] = ["same photo"] + hit["why"]   # 'already scanned' and review name the same card
            if not hit:
                q.insert(0, {"card_id": sid, "profile_id": f"card:{sid}", "name": "", "organization": "", "score": 1.0, "why": ["same photo"]})
    q.sort(key=lambda d: ("same photo" not in d["why"], -d["score"], d["card_id"]))   # one order everywhere (newcomer r7 F4)
    res = m.get("dup_resolution")
    # round 14: a rejected card keeps its look-alikes as hints (never blocking, see below) so it does not read "Looks good"
    for x in q:
        o = next((o for o in others if o["id"] == x["card_id"]), None)
        x["strong"] = is_true_duplicate(x, m, metas.get(x["card_id"]) or {})
        x["kept_apart"] = (not x["strong"]) and (x["card_id"] in _kept(m) or c["id"] in _kept(metas.get(x["card_id"]) or {})
                                                 or (res == "keep_both" and not _kept(m)))   # legacy all-matches choice
        if o: x["other_status"] = o["status"]
        om = metas.get(x["card_id"]) or {}
        x["same_batch"] = bool(m.get("batch")) and m.get("batch") == om.get("batch")
        other_rej = (o or {}).get("status") == "rejected"
        x["blocking"] = (x["strong"] or x["same_batch"]) and not rej and not other_rej   # a rejected twin only warns
    open_q = [x for x in q if not x["kept_apart"]]
    return {"crm": crm, "queue": q, "open": open_q, "unresolved_queue": any(x["blocking"] for x in open_q), "lookalikes_elsewhere": [x["card_id"] for x in open_q if not x["blocking"]], "resolution": res, "crm_action": m.get("crm_action"), "meta": m,
            "updates_enabled": auth.get_setting("mctrade_updates_enabled") == "1"}

def _name_plus(d, f, rows):
    """Round 10 (coordinator r3 1): with no company, a very similar name (>= 0.9) plus the same phone, or plus a similar
    email (>= 0.8, e.g. jsmith@ vs j.smith@ or a misread letter), is enough to flag a look-alike."""
    ns = next((float(w[5:]) for w in d["why"] if w.startswith("name~")), 0.0)
    if ns < 0.9: return False
    if re.search(r"\d", f"{f.get('first_name','')}{f.get('last_name','')}{d.get('name','')}"): return False   # numbered test names ("Test1 Person1"), not people
    if "phone exact" in d["why"]: return True
    r = next((r for r in rows if r["profile_id"] == d["profile_id"]), None)
    # round 11 (coordinator r4 #1, the Farid pair): a truncated or partly misread phone still ties them when the last 7
    # digits agree ("555-0165" vs "(330) 555-0165")
    op = _digits((r or {}).get("phone") or "")
    if len(op) >= 7 and any(len(_digits(p_.get("number") or "")) >= 7 and _digits(p_.get("number") or "")[-7:] == op[-7:] for p_ in f.get("phones") or []):
        return True
    import difflib
    sim = lambda x, y: difflib.SequenceMatcher(None, x, y).ratio()
    r = r or {}
    # round 12 (coordinator r4 #1): the name plus ANY other field that agrees: any phone (last 7 digits), any email,
    # the website or the street address, each allowing for a misread character or a lost dot/space
    ops = {_digits(x)[-7:] for x in r.get("phones") or [r.get("phone") or ""] if len(_digits(x)) >= 7}
    if ops & {_digits(p_.get("number") or "")[-7:] for p_ in f.get("phones") or [] if len(_digits(p_.get("number") or "")) >= 7}: return True
    key = lambda x: re.sub(r"[^a-z0-9@]", "", (x or "").lower())
    oes = [key(e) for e in (r.get("emails") or [r.get("email") or ""]) if e]
    if any(sim(key(e), oe) >= 0.8 for e in f.get("emails") or [] if e for oe in oes): return True
    site = lambda x: re.sub(r"^(https?)?(www)?", "", key(x))
    if f.get("website") and r.get("website") and len(site(f["website"])) >= 6 and sim(site(f["website"]), site(r["website"])) >= 0.85: return True
    street = lambda x: key((x or "").split(",")[0])[:24]
    if f.get("address") and r.get("address") and len(street(f["address"])) >= 8 and sim(street(f["address"]), street(r["address"])) >= 0.85: return True
    return False

def _kept(m):
    try: return set(json.loads(m.get("kept_apart") or "[]"))
    except Exception: return set()

def is_true_duplicate(x, m, om):
    """Same photo, or same batch with the same email/phone: almost certainly the same card scanned twice.
    These can't be cleared with 'keep both'; merge or reject one of them."""
    same_batch = bool(m.get("batch")) and m.get("batch") == om.get("batch")
    if "same photo" in x.get("why", []): return same_batch   # a deliberate "Scan it anyway" in another batch can be kept apart
    return same_batch and m.get("batch") == om.get("batch") and any(w in ("email exact", "phone exact") for w in x.get("why", []))

WHY = {"email exact": "same email", "phone exact": "same phone", "same photo": "same photo uploaded"}
def _why(ws):   # round 16 (reviewer r15 #4): each reason once ('same email, same phone', never twice)
    return ", ".join(dict.fromkeys(WHY.get(w, "similar name" if w.startswith("name") else "similar company" if w.startswith("org") else w) for w in ws or []))
LABEL = {"name": "Name", "title": "Job title", "company": "Company", "emails": "Email", "phones": "Phone", "website": "Website",
         "address": "Address", "department": "Department", "other_address": "Other address",
         "first_name": "First name", "last_name": "Last name", "credentials": "Credentials", "social": "Social profiles", "note": "Note"}

def _ids10(ids, n=10):
    """Round 17 (reviewer/newcomer r16): every look-alike id list shows the first 10, then '…and N more'."""
    ids = list(ids); t = ", ".join(f"#{i}" for i in ids[:n])
    return t + (f" …and {len(ids) - n} more" if len(ids) > n else "")

def attention(c, d, cards=None, names=None):
    f = c["fields"]; r = []
    v = validate(f)
    for k, msg in v.items(): r.append({"code": "invalid", "field": k, "text": msg})
    # round 21 (datamanager/part-timer r20): hard problems are in To check as soon as the card opens, not only at Approve
    try: hard = {k: m_ for k, m_ in hard_errors(f).items() if k not in v and not (k == "name" and "name" in v)}
    except Exception: hard = {}
    for k, msg in hard.items(): r.append({"code": "hard", "field": "first_name" if k == "name" else k, "text": "Blocks approval: " + msg})
    hard_f = {"first_name" if k == "name" else k for k in hard} | set(v)
    try: _src = json.loads((d.get("meta") or {}).get("field_sources") or "{}")
    except Exception: _src = {}
    # round 22: ONE line for 'hard to read' and 'missing' (they used to be several lines)
    lows_ = [k for k in low_fields(f, _src) if k not in v and k not in hard_f]
    # round 13 (reviewer r11): decided cards keep their checks and hints (a rejected card no longer turns "Looks good")
    if True:   # re-checked live, so a fix by the reviewer clears it
        from . import consistency
        import copy as _cp
        for fl in consistency.check(_cp.deepcopy(f))[1]: r.append({"code": "consistency", "field": fl["fields"][0], "text": fl["text"]})
    if True:
        try:
            from . import plausibility
            for sg in plausibility.check(json.loads(json.dumps(f))):
                if sg.get("field") in hard_f: continue   # round 21: never 'Suggestion' AND 'blocks' for one value
                if sg.get("field") in valid_confirmations(f): continue   # round 24 (coordinator r23): a confirmed value gets no second note
                if sg.get("field") in {x_.get("field") for x_ in r if x_.get("code") == "hint"}: continue   # round 24 (newcomer r23 'CoffeeCo' twice): one note per field
                r.append({"code": "hint", "field": sg.get("field"), "text": "Suggestion: " + (sg.get("text") or ""), "suggestion": sg.get("suggestion")})
        except Exception: pass
    if True:   # round 7 (coordinator r1 #4): 'Looks good' needs company, email and website
        miss = [LABEL[k] for k in ("company", "emails", "website") if not (f.get(k) if k != "emails" else [e for e in f.get("emails") or [] if e])]
        if not [p_ for p_ in f.get("phones") or [] if (p_.get("number") or "").strip()]: miss.append(LABEL.get("phones", "Phone"))   # round 14 (coordinator r6 #5)
        parts_ = ([f"Hard to read: {', '.join(LABEL.get(k, k) for k in lows_)}"] if lows_ else []) + (["Missing: " + ", ".join(miss)] if miss else [])
        if parts_:
            r.append({"code": "low" if lows_ else "missing", "field": lows_[0] if lows_ else ("company" if "Company" in miss else "emails" if "Email" in miss else "website"),
                      "fields": lows_, "text": " · ".join(parts_) + ". Check the photo."})   # round 23: shorter
        t_ = str(f.get("title") or "").strip()   # round 22: a job title that stops mid-phrase ('Director of', 'Sales &')
        if t_ and "title" not in hard_f and re.search(r"(?:[&,/+-]|\b(?:of|and|for|the|to|in|at|&amp))$", t_, re.I):
            r.append({"code": "hint", "field": "title", "text": f"Suggestion: Job title “{t_}” looks cut off. Check the photo."})
    if d["unresolved_queue"]: r.append({"code": "dup_queue", "text": "May be the same person as card " + _ids10(x['card_id'] for x in d["open"] if x["blocking"])})
    # round 11 (reviewer r10 blocker 2): 'Looks good' never shows while a card has ANY open look-alike or MC Trade match
    # round 17 (reviewer r16 NO-GO #1): a same-batch look-alike that no longer blocks (it, or this card, was rejected) gets
    # its OWN line. Before, it shared one 5-id list with the other-batch look-alikes and was cut off when a person had been
    # scanned in many earlier batches, so after a bulk reject the in-batch twin vanished from the queue and "Why...".
    decided = (d.get("resolution") == "keep_both")   # round 21: 'Different person' silences every duplicate line
    nb = [] if decided else [x for x in d["open"] if not x["blocking"]]
    sb_ = [x for x in nb if x.get("same_batch")]
    if sb_:
        rj = all(x.get("other_status") == "rejected" for x in sb_)
        r.append({"code": "dup_other", "text": "May be the same person as card " + _ids10(x["card_id"] for x in sb_) + (" (rejected, this batch)" if rj else " (this batch)")
                  + (": a hint only, it doesn't block" if c["status"] != "rejected" else "")})
    ob_ = [x for x in nb if not x.get("same_batch")]
    if not d["unresolved_queue"] and ob_ and d["queue"] and c["status"] == "pending":   # round 21: short; the Seen-before box has the details
        r.append({"code": "dup_other", "text": f"Seen before: similar to {plural(len(ob_), 'other card')}"}); ob_ = []
    if not d["unresolved_queue"] and ob_:
        op = ob_; rej_all = all(x.get("other_status") == "rejected" for x in op)
        tag = ", ".join(t for t in ("rejected" if rej_all else "", "another batch") if t)
        if c["status"] != "pending" and len(op) > 3:   # round 22 (part-timer r21): a decided card shows a count, not 28 card numbers
            r.append({"code": "dup_other", "text": f"Looks like {plural(len(op), 'other card')} ({tag})"})
        else: r.append({"code": "dup_other", "text": ("May be the same person as card " if rej_all else "Looks like card ") + _ids10(x["card_id"] for x in op)
                  + f" ({tag})" + (": a hint only, it doesn't block" if rej_all and c["status"] != "rejected" else "" if c["status"] != "pending" else ": check before approving")})
    if d["crm"] and not d["crm_action"]: r.append({"code": "dup_crm", "text": f"May already be in MC Trade: {d['crm'][0]['name']}"})
    elif d["crm"] and "email exact" not in (d["crm"][0].get("why") or []) and c["status"] == "pending":
        r.append({"code": "dup_crm", "text": f"Similar to MC Trade contact {d['crm'][0]['name']} (you chose: {'update that contact' if d['crm_action'] == 'update_existing' else 'add as new'})"})
    elif d["crm"] and "email exact" in (d["crm"][0].get("why") or []):   # newcomer r8 N6: still an MC Trade email match after 'add as new'
        if crm_source.real() is None:   # round 9 (newcomer r9 N1): say what the export really does with SAMPLE data
            r.append({"code": "dup_crm", "field": "emails", "text": f"Same email as SAMPLE test contact {d['crm'][0]['name']}. Only SAMPLE contacts are loaded, so the export does NOT hold it back: it goes in the new-profiles file. With GAC's real MC Trade contacts loaded it would be NEEDS REVIEW."})
        else:
            r.append({"code": "dup_crm", "field": "emails", "text": f"Same email as MC Trade contact {d['crm'][0]['name']}: the export lists it under NEEDS REVIEW"})
    m = d.get("meta") or {}
    if m.get("ai_rejected"):   # reviewer r8: 'Keep current' over an AI suggestion is not 'Looks good'
        # round 16 (coordinator r15 #3): a field the person has since set to the AI's value themselves is no longer "kept"
        _n = lambda v: re.sub(r"\s+", " ", json.dumps(v, sort_keys=True) if not isinstance(v, str) else v).strip().lower()
        try: rj = [LABEL.get(k, k) for k, v in json.loads(m["ai_rejected"] or "{}").items() if _n(f.get(k)) != _n(v)]
        except Exception: rj = []
        if rj: r.append({"code": "ai_overridden", "field": None, "text": "AI suggested a different " + ", ".join(rj) + " (you kept the current value): check against the photo"})
    if c["status"] == "approved" and m.get("override"):
        r.append({"code": "override", "text": "Approved anyway: " + (_ov(m).get("reason") or "")})
    if m.get("reexport"): r.append({"code": "reexport", "text": "Changed after export: export it again"})
    # round 15 (reviewer r14): each reason once (duplicate reasons used to repeat themselves)
    seen_t, uniq = set(), []
    for x in r:
        t = x.get("text") or ""
        if t in seen_t: continue
        seen_t.add(t); uniq.append(x)
    r = uniq
    # round 15 (mctrade r14 M1): same first+last as another approved card or an MC Trade contact (review hint)
    nm = _nm(f)
    if nm and " " in nm and c["status"] in ("pending", "approved"):
        _la = {x["card_id"] for x in d.get("queue") or []}
        pool = (names or {}).get(nm) if names is not None else [x for x in (cards or []) if _nm(x.get("fields")) == nm]
        twins = [x for x in (pool or []) if x["id"] != c["id"] and x["id"] not in _la and x["status"] != "rejected"]
        if twins: r.append({"code": "same_name", "field": "name", "text": "Same first and last name as card " + ", ".join("#" + str(x["id"]) for x in twins[:5]) + ": MC Trade may merge them. Check they are different people."})
        rows = crm_source.real()
        if rows:
            if not hasattr(attention, "_crm_names") or attention._crm_key != id(rows):
                attention._crm_names = {}; attention._crm_key = id(rows)
                for rr in rows:
                    n = re.sub(r"\s+", " ", f"{rr.get('first_name','')} {rr.get('last_name','')}".strip().lower())
                    if n: attention._crm_names.setdefault(n, []).append(rr)
            hits = attention._crm_names.get(nm) or []
            if hits and not d.get("crm_action"):
                r.append({"code": "same_name", "field": "name", "text": f"Same first and last name as MC Trade contact {hits[0].get('first_name')} {hits[0].get('last_name')} (profile {hits[0].get('profile_id')}): confirm they are different people before exporting as new"})
    return r

def _ov(m):
    try: return json.loads(m.get("override") or "{}")
    except Exception: return {}

def _active(include_archived=False):
    metas = all_metas(); cards = store.all_(None)
    if not include_archived: cards = [c for c in cards if not (metas.get(c["id"]) or {}).get("archived")]
    return cards, metas

def _shown_conf(f, a, src=None):
    """Confidence shown in lists (part-timer r1: 90 % next to a blank name). Capped below 'high' while a required field is
    blank or a check/hint is open, so a high number never sits next to a problem."""
    v = f.get("overall_confidence")
    if v is None: return v
    # Round 9 (coordinator N2): the old cap returned a flat 0.55 for almost every card (nearly all have a hint or a
    # low field), so the list showed 55 % whatever the photo. Now the card's own read score is kept, held below the
    # "looks good" band (0.6) and lowered a little per open problem, so two cards with different reads show different numbers.
    probs = [x for x in a if x["code"] in ("invalid", "hint", "consistency", "low", "missing")]
    if not (f.get("first_name") or "").strip(): probs = probs + [{"code": "missing"}]
    if probs:
        # round 12 (coordinator r4 #7): min(v, 0.59) put every well-read card with one flag at exactly 56 %. The read score is
        # now SCALED into the band below "looks good" (so a clear card still shows higher than a blurred one), then lowered per problem
        return round(max(0.05, 0.6 * min(v, 0.99) - 0.03 * min(len(probs), 5)), 2)
    # round 20 (datamanager r19): the chip is about the CURRENT data. A card a person has edited or confirmed, with no
    # open problem left, is no longer "Unclear" because of the original photo read.
    if v < 0.6 and any(str(x).startswith(("edited", "confirmed")) for x in (src or {}).values()): return 0.8
    return v
def enrich(c, cards, metas, full=False, names=None):
    d = dupes(c, cards, metas); m = metas.get(c["id"]) or meta(c["id"]); a = attention(c, d, cards, names)
    f = c["fields"]
    try: src = json.loads(m.get("field_sources") or "{}")
    except Exception: src = {}
    out = {"id": c["id"], "status": c["status"], "image": c["image"], "created": c["created"],
           "name": f"{f.get('first_name','')} {f.get('last_name','')}".strip(), "company": f.get("company", ""),
           "email": (f.get("emails") or [""])[0], "conf": _shown_conf(f, a, src), "reviewer": c.get("reviewer"),
           "attention": a, "needs_attention": bool(a), "version": card_version(c), "dup": bool(d["queue"] or d["crm"]), "lookalikes_elsewhere": d["lookalikes_elsewhere"],
           "batch": m.get("batch"), "batch_label": m.get("batch_label"), "filename": m.get("filename"),
           "archived": bool(m.get("archived")), "exported": m.get("exported"), "qr": "qr" in src.values(),
           "image_deleted": m.get("image_deleted"), "ai_status": m.get("ai_status"),
           "ai_detail": calm_ai_detail(json.loads(m["ai_detail"])) if m.get("ai_detail") else None,
           "override": _ov(m) or None, "reexport": m.get("reexport"), "back_image": m.get("back_image"),
           "ai_progress": ai_progress(c["id"]) if m.get("ai_status") in ("queued", "checking") else None}
    try: out["blocked"] = c["status"] == "pending" and bool(hard_errors(f))   # round 23 (datamanager r22 M3): the chip never says OK on a blocked card
    except Exception: out["blocked"] = False
    if full:
        d = {k: v for k, v in d.items() if k != "meta"}
        # round 11 (part-timer r4): the review page warns BEFORE Approve when this person was already approved+exported elsewhere
        xb = [x for x in _cross_batch(c, f, cards, metas) if x["exported"] and {"same email", "same phone", "same photo"} & set(x["why"])]
        with db() as conn:
            nexp = {x["card_id"]: conn.execute("SELECT COUNT(*) FROM card_history WHERE card_id=? AND action='exported'", (x["card_id"],)).fetchone()[0] for x in xb}
        _kx = _kept(m)   # round 21: after 'Different person' (or for kept-apart cards) the 'already exported' warning is silent
        out["exported_elsewhere"] = [] if (m.get("dup_resolution") == "keep_both" or c["status"] != "pending") else [x | {"times": nexp.get(x["card_id"], 1)} for x in xb if x["card_id"] not in _kx]
        out["dup_decided"] = m.get("dup_resolution") == "keep_both"
        try:   # round 22: hard blocks + which of them 'This is correct' may confirm, so the card shows them (and the button) on open
            hard_ = hard_errors(f)   # the page hides admin-only ones (ADMIN_OVERRIDE) for reviewers; the server checks the role anyway
            out |= {"hard": hard_, "overridable": [k for k in overridable(f) if k in hard_], "admin_override": list(ADMIN_OVERRIDE)}
            _cm = f.get("confirmed_meta") if isinstance(f.get("confirmed_meta"), dict) else {}   # round 23: confirmed values are marked on Review
            out["confirmed"] = {k: {"by": _cm[k].get("by"), "reason": _cm[k].get("reason")} for k in valid_confirmations(f)}
        except Exception: pass
        out |= {"version": card_version(c), "card": c | {"fields": f | {"confidence": calibrated_conf(f)}}, "dupes": d, "history": history(c["id"]), "errors": validate(f), "low": _low_after_ai(f, src, m), "sources": src}
        for x in d["queue"]:
            o = store.get(x["card_id"])
            if o: x |= {"name": f"{o['fields'].get('first_name','')} {o['fields'].get('last_name','')}".strip(),
                        "organization": o["fields"].get("company", ""), "status": o["status"], "why_text": _why(x["why"])}
        for x in d["crm"]: x["why_text"] = _why(x["why"])
    return out

# ---------------------------------------------------------------- async scan jobs
SCAN_WORKERS = max(1, int(os.environ.get("SCAN_WORKERS", "1")))
POOL = ThreadPoolExecutor(max_workers=SCAN_WORKERS)
# Caps how many photos are read (OCR) at the same time across ALL entry points (the /ui job pool, /api/scan, back-of-card),
# so a burst of uploads queues instead of multiplying RAM use.
SCAN_SEM = threading.BoundedSemaphore(SCAN_WORKERS)
OCR_CHILD = os.environ.get("OCR_CHILD", "1") == "1"   # round 21 (skeptic r20 M1): OCR runs in the capped reader child
def scan_limited(*a, **k):
    from . import pipeline, reader
    with SCAN_SEM:
        if OCR_CHILD and not k.get("use_vlm") and isinstance(a[0], (bytes, bytearray)):
            try: return reader.run_ocr(bytes(a[0]), a[1] if len(a) > 1 else k.get("engine"), key=k.pop("key", None))
            except reader.ReaderError: raise
        k.pop("key", None)
        return pipeline.scan(*a, **k)

def _calm_read_error(ex):
    """Round 22: never show exception class names (e.g. 'ReaderError') to the user."""
    from . import reader
    print("read error:", type(ex).__name__, str(ex)[:200], flush=True)
    if isinstance(ex, reader.ReaderError) and str(ex) and str(ex) != reader.CALM: return str(ex)
    return "Couldn't read this page. Try again, or use a photo or a smaller PDF."

MEM_MIN_MB = int(os.environ.get("MEM_MIN_MB", "1000"))   # round 21 (skeptic r20): pause new reads below ~1 GB free
def mem_free_mb():
    try:
        with open("/proc/meminfo") as fh:
            for ln in fh:
                if ln.startswith("MemAvailable:"): return int(ln.split()[1]) // 1024
    except Exception: pass
    return 10 ** 6
MEM_LONG_S = 900
def wait_for_memory(jid=None, max_s=None):
    """Hold a read while the computer is short of memory ('Waiting for memory…'), so the server and AI stay safe.
    Round 22 (skeptic r21 L4): never reads anyway after 15 min; it keeps waiting with a calm message. With max_s (tests)
    it gives up (False) instead of reading."""
    t0 = time.time()
    while mem_free_mb() < MEM_MIN_MB:
        if max_s is not None and time.time() - t0 >= max_s: return False
        if jid:
            with JLOCK:
                j = JOBS.get(jid) or {}
                if j.get("state") == "cancelled": return False
                j["waiting_memory"] = True
                if time.time() - t0 > MEM_LONG_S:
                    j["waiting_memory_msg"] = "Still waiting for free memory. Nothing is lost: this starts by itself, or Cancel it."
        time.sleep(2)
    if jid:
        with JLOCK: j = JOBS.get(jid) or {}; j.pop("waiting_memory", None); j.pop("waiting_memory_msg", None)
    return True
JOBS, JLOCK = {}, threading.Lock()
DEAD_JOBS: set = set()   # audit 2026-10 F09: jobs from before a demo wipe; a worker still reading one never creates its card
def reset_jobs():
    """Public demo wipe: every job (queued, reading, finished) belongs to the old generation. Running readers are stopped,
    queued work is cancelled, finished results lose their card data, and the AI queue is emptied."""
    from . import reader
    with JLOCK:
        for jid, j in JOBS.items():
            DEAD_JOBS.add(jid); reader.stop(jid)
            JOBS[jid] = {"id": jid, "state": "cancelled", "batch": "", "file": "", "created": j.get("created"), "finished": time.time()}
        CANCELLED_BATCH.clear()
    AI_WAIT.clear()
    try:
        while True: AI_Q.get_nowait()
    except _queue.Empty: pass
    with _BATCH_LOCK: BATCH_OWNER.clear()
CANCELLED_BATCH = {}   # (who, batch) -> time Cancel was pressed: an upload that lands just after it is not scanned (round 21)
MAX_BYTES = 25 * 1024 * 1024

# Only plain raster formats are decoded (no EPS/PDF/etc. plugins, which can shell out to external tools), and images above
# MAX_PIXELS are refused before decoding (decompression bombs: a small file that expands to gigabytes of pixels).
FORMATS = ["JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "MPO"]
MAX_PIXELS = 60_000_000      # ~60 MP: above any phone camera
def _check_image(data):
    import warnings
    from PIL import Image, ImageStat
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(data), formats=FORMATS)
            if im.size[0] * im.size[1] > MAX_PIXELS: raise Image.DecompressionBombError("too many pixels")
            im.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "This picture is far too large (too many pixels). Use a normal phone photo."
    except Exception:
        return "This file isn't a photo the scanner can open (use JPG, PNG, HEIC or PDF)."
    w, h = im.size
    if w < 200 or h < 100: return f"Photo is too small ({w}×{h} pixels). Take the picture closer to the card."
    g = im.convert("L"); g.thumbnail((400, 400))
    if ImageStat.Stat(g).stddev[0] < 6: return "Photo looks blank (one solid colour). Please retake it."
    return None

QR_KEYS = ("first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address", "social")
class _Cancelled(Exception): pass
def ingest(data, engine, ext, jid=None, meta_kw=None):
    """Image -> card using the shared pipeline (QR/vCard decode + OCR + parser). Returns (card_id, field_sources)."""
    from . import qr
    name = uuid.uuid4().hex + ext
    with open(os.path.join(UP, name), "wb") as fh: fh.write(data)
    r = scan_limited(data, None if engine in (None, "", "auto", "standard", "tesseract") else engine, use_vlm=False, **({"key": jid} if jid else {}))
    f = r["fields"]; src = {}
    qrv = None
    if (f.get("sources") or {}).get("qr"):
        for t in qr.decode(data):
            qrv = qr.parse_vcard(t)
            if qrv: break
    for k in QR_KEYS:
        if f.get(k): src[k] = "qr" if qrv and qrv.get(k) and qrv.get(k) == f.get(k) else "ocr"
    # round 22 (newcomer r21 HIGH): Cancel is atomic. The card is created (with its batch) under JLOCK only if the job was
    # not cancelled meanwhile; Cancel takes the same lock and can no longer stop a job that already has a card.
    with JLOCK:
        if jid and (jid in DEAD_JOBS or (JOBS.get(jid) or {}).get("state") == "cancelled"):
            try: os.remove(os.path.join(UP, name))
            except OSError: pass
            raise _Cancelled()
        cid = store.add(r["engine"], r["text"], f, name)
        if meta_kw: set_meta(cid, **meta_kw)
        if jid and jid in JOBS: JOBS[jid]["card_id"] = cid
    return cid, src

def _run(jid, data, engine, ext, batch, label, fname, sha, who, skip_ai=False):  # noqa: PLR0913
    wait_for_memory(jid)
    with JLOCK:
        if (JOBS.get(jid) or {}).get("state") != "queued": return   # round 19: cancelled while waiting in line
        JOBS[jid]["state"] = "reading"; JOBS[jid]["started"] = time.time()
    final = None
    try:
        if data is None:   # queued jobs keep only a file on disk, not the photo bytes in memory
            with open(os.path.join(INBOX, jid + ".bin"), "rb") as fh: data = fh.read()
        open(os.path.join(INBOX, jid + ".reading"), "w").close()   # round 20 poison guard: a crash now -> not re-queued
        cid, src = ingest(data, engine, ext, jid=jid, meta_kw={"batch": batch, "batch_label": label, "filename": fname, "sha256": sha}); data = None
        set_meta(cid, field_sources=json.dumps(src))
        log(cid, who, "scanned", None, "pending", {"file": fname, "batch": label, "qr": "qr" in src.values()})
        bp = os.path.join(INBOX, jid + ".back")
        if os.path.isfile(bp):   # phone mode: front + back sent together
            with open(bp, "rb") as fh: bdata = fh.read()
            if not _check_image(bdata):
                r = attach_back(cid, bdata, ".jpg", who, confirm_other_person=False)
                if isinstance(r, tuple): log(cid, who, "back_skipped", detail={"why": r[0].get("error", "")[:200]})
        if skip_ai: set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"note": f"AI check skipped at scan by {who} (Skip AI)"}))
        else: maybe_ai_check(cid)
        cards, metas = _active()
        e = enrich(store.get(cid), cards, metas)
        final = {"state": "done", "card": e, "finished": time.time()}
    except Exception as ex:
        with JLOCK: stopped = (JOBS.get(jid) or {}).get("state") == "cancelled" or isinstance(ex, _Cancelled)
        final = {"state": "cancelled", "finished": time.time()} if stopped else {"state": "error", "error": _calm_read_error(ex), "finished": time.time()}
    finally:
        # the final state is published only after the done record is written and the inbox files (.reading included) are
        # gone, so nobody polling the job sees "done" while the reader still owns its files (flaky on Windows CI)
        with JLOCK: j = dict(JOBS.get(jid) or {}) | (final or {})
        try:
            with open(os.path.join(DONE, jid + ".json"), "w") as fh:
                json.dump({k: j.get(k) for k in ("id", "state", "file", "batch", "error", "created", "started", "finished")} | {"card_id": (j.get("card") or {}).get("id")}, fh)
        except Exception: pass
        _inbox_clear(jid)
        if final:
            with JLOCK: JOBS[jid] |= final

@router.post("/api/jobs")
async def create_job(request: Request, image: UploadFile = File(...), engine: str = Form("auto"), batch: str = Form(""),
                     batch_label: str = Form(""), allow_duplicate: str = Form(""), skip_ai: str = Form("")):
    t0 = time.time(); data = await image.read(); fname = image.filename or "photo"
    batch = batch_for(batch, batch_label, _who(request))
    if _cancelled_since(_who(request), batch, t0):   # round 21: landed just after Cancel -> not scanned
        return JSONResponse({"error": "Not scanned: the upload was cancelled.", "cancelled": True}, 409)
    return await enqueue_upload(data, fname, engine=engine, batch=batch, batch_label=batch_label, allow_duplicate=allow_duplicate, who=_who(request), t0=t0,
                                skip_ai=skip_ai.strip().lower() in ("1", "true", "yes", "on"))

def _cancelled_since(who, batch, t0=None):
    """Round 23 (part-timer r22 HIGH): an upload is not scanned when Cancel was pressed for its batch while it was on its
    way (after the request started: e.g. a multi-card photo still being cut up), or up to 8 s before it arrived."""
    ct = CANCELLED_BATCH.get((who, batch or ""))
    if not ct: return False
    return time.time() - ct < 8 or (t0 is not None and ct >= t0 - 0.5)

BATCH_OWNER = {}; _BATCH_LOCK = threading.Lock()

def batch_for(batch, label, who=""):
    """Round 13 (part-timer r5 HIGH): two people who started a batch in the same second got the SAME batch id, so one
    batch showed the other's cards (export dialog, queue filter). A batch id belongs to the first person (and name) that
    used it; anyone else, or another name, gets a derived id of their own. The page also adds a random suffix."""
    if not batch: return batch
    lb = clean_batch_label(label).lower()
    def owner(b_):
        if b_ in BATCH_OWNER: return BATCH_OWNER[b_]
        r = db().execute("""SELECT m.batch_label, (SELECT h.reviewer FROM card_history h WHERE h.card_id=m.card_id AND h.action='scanned' LIMIT 1)
                            FROM card_meta m WHERE m.batch=? ORDER BY m.card_id LIMIT 1""", (b_,)).fetchone()
        return None if r is None else (str(r[1] or ""), " ".join(str(r[0] or "").split()).lower())
    with _BATCH_LOCK:
        cand = batch
        for n in range(50):
            o = owner(cand)
            if o is None: BATCH_OWNER[cand] = (who, lb); return cand
            if not lb: return cand                                   # no name given (API/legacy): keep
            if who and o[0]: 
                if o[0] == who: return cand                          # your own batch (whatever name you typed)
            elif not o[1] or o[1] == lb: return cand                 # owner unknown: same name = same batch
            cand = batch + "-" + hashlib.sha1(f"{who}|{lb}|{n}".encode()).hexdigest()[:6]
        return batch + "-" + uuid.uuid4().hex[:8]

def clean_batch_label(s):
    """Round 8 (newcomer r8 N2): the batch name is kept as typed; only control characters and markup brackets are removed,
    spaces collapsed and the length capped at 120. Nothing is appended (no time, no initials)."""
    s = re.sub(r"[\x00-\x1f\x7f<>]", "", str(s or ""))
    return " ".join(s.split())[:120]

def unique_batch_label(label, batch, extra_taken=()):
    """Round 9 (R8-7): a phone batch's name must not match another batch's name. If the label is already used by a
    different batch (or another live phone pairing), " (2)", " (3)" … is added, the same way desktop batches are."""
    label = clean_batch_label(label)
    rows = db().execute("SELECT DISTINCT batch_label FROM card_meta WHERE COALESCE(batch,'')<>? AND batch_label IS NOT NULL", (batch or "",)).fetchall()
    taken = {(r[0] or "").strip().lower() for r in rows} | {str(x).strip().lower() for x in extra_taken if x}
    if label.lower() not in taken: return label
    k = 2
    while f"{label} ({k})".lower() in taken: k += 1
    return f"{label} ({k})"

MAX_PARTS = 400   # round 18: most cards one upload (PDF pages x cards per page) may create
async def enqueue_upload(data, fname, engine="auto", batch="", batch_label="", allow_duplicate="", who="?", back=None, _part=False, t0=None, skip_ai=False):
    """Shared by the desktop upload (/api/jobs) and phone mode (app/phone.py). back = optional back-of-card photo bytes,
    attached to the new card after it is read (same rules as "Add back of card").
    Round 18: a HEIC/HEIF photo is converted to JPEG first; a PDF becomes one card per page; a page or flatbed scan
    holding several cards becomes one card per card (app/formats.py). Several cards answer {"job": first, "jobs": [...]}."""
    if len(data) > MAX_BYTES: return JSONResponse({"error": "File is larger than 25 MB."}, 422)
    if not data: return JSONResponse({"error": "File is empty."}, 422)
    batch_label = clean_batch_label(batch_label)
    from starlette.concurrency import run_in_threadpool
    if not _part:
        from . import formats, reader
        if formats.is_pdf(data):
            # round 20 (skeptic H1): pages are COUNTED here (in the reader child, no rendering); one background job
            # then renders them one at a time and adds a card job per card as it goes (progress + Cancel work)
            try: n = await run_in_threadpool(reader.run_count, data)
            except reader.ReaderError as e: return JSONResponse({"error": str(e)}, 422)
            return await run_in_threadpool(_enqueue_pdf, data, fname, n, engine, batch, batch_label, allow_duplicate, who, bool(back), t0, skip_ai)
        try: parts = await run_in_threadpool(reader.run_photo, data, fname)
        except reader.ReaderError as e: return JSONResponse({"error": str(e)}, 422)
        if parts is not None and len(parts) > MAX_PARTS:
            return JSONResponse({"error": f"This file holds {len(parts)} cards; the limit is {MAX_PARTS} per upload. Split it into smaller files."}, 422)
        if parts is not None and len(parts) == 1: data, fname = parts[0]
        elif parts:
            jobs = []
            for pdata, label in parts:
                jobs.append(_part_result(label, await run_in_threadpool(_enqueue_one, pdata, label, engine, batch, batch_label, allow_duplicate, who, None, t0, skip_ai)))
            ok = [j for j in jobs if j.get("job")]
            if not ok: return JSONResponse({"error": f"None of the {len(parts)} cards in this file could be added: " + jobs[0]["error"], "jobs": jobs}, 409 if all(j["status"] == 409 for j in jobs) else 422)
            return {"job": ok[0]["job"], "jobs": jobs, "state": "queued", "ahead": ok[0]["ahead"], "batch": batch, "source": os.path.basename(fname or ""),
                    "back_skipped": bool(back)}
    return await run_in_threadpool(_enqueue_one, data, fname, engine, batch, batch_label, allow_duplicate, who, back, t0, skip_ai)

def _part_result(label, r):
    if isinstance(r, Response):
        try: body = json.loads(r.body)
        except Exception: body = {}
        return {"file": label, "status": r.status_code, "error": body.get("error") or "Not added.", "duplicate_of": body.get("duplicate_of")}
    return {"file": label, "job": r["job"], "ahead": r.get("ahead", 0)}

def _enqueue_one(data, fname, engine, batch, batch_label, allow_duplicate, who, back, t0=None, skip_ai=False):
    """One card photo -> one queued job (sync; the checks of round 7-19 unchanged)."""
    from . import formats
    data = formats.prepare_for_ocr(data)   # round 20: photos above 16 MP are downscaled before they are stored/queued
    problem = _check_image(data)
    if problem: return JSONResponse({"error": problem}, 422)
    sha = hashlib.sha256(data).hexdigest()
    if allow_duplicate.strip().lower() in ("", "0", "false", "no"):
        # the OLDEST active, non-rejected card with this photo: the same one the review screen lists as "same photo"
        # round 7 (coordinator r1 #1): refused only inside the SAME batch; another person's / batch's copy only warns (review box)
        r = db().execute("SELECT m.card_id, c.created, m.batch_label FROM card_meta m JOIN cards c ON c.id=m.card_id WHERE m.sha256=? AND m.archived=0 "
                         "AND COALESCE(m.batch,'')=? ORDER BY (c.status='rejected'), c.id ASC", (sha, batch or "")).fetchone()
        if r:
            h = db().execute("SELECT reviewer FROM card_history WHERE card_id=? ORDER BY id LIMIT 1", (r[0],)).fetchone()
            who = (h[0] if h and h[0] not in (None, "system") else None) or "someone"
            when = datetime.datetime.fromtimestamp(r[1]).strftime("%b %d, %I:%M %p").replace(" 0", " ") if r[1] else "earlier"
            return JSONResponse({"error": f"This exact photo is already in this batch: scanned by {who} on {when} (card #{r[0]}" + (f", batch {r[2]}" if r[2] else "") + ").",
                                 "duplicate_of": r[0], "by": who, "when": r[1]}, 409)
        with JLOCK:
            for j in JOBS.values():
                if j.get("sha") == sha and j["state"] in ("queued", "reading") and (j.get("batch") or "") == (batch or "") and j.get("who") == who:   # reviewer-r8: same person's same batch only
                    return JSONResponse({"error": "This exact photo is already in this upload.", "duplicate_of": None}, 409)
    jid = uuid.uuid4().hex[:12]; ext = os.path.splitext(fname)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"): ext = ".jpg"
    with JLOCK:
        if t0 is not None and _cancelled_since(who, batch, t0):   # round 23: Cancel was pressed while this upload was on its way
            return JSONResponse({"error": "Not scanned: the upload was cancelled.", "cancelled": True}, 409)
        ahead = sum(1 for j in JOBS.values() if j["state"] in ("queued", "reading") and j.get("kind") != "pdf")
        JOBS[jid] = {"id": jid, "state": "queued", "file": fname, "batch": batch, "sha": sha, "created": time.time(), "ahead": ahead, "who": who}
    args = dict(engine=engine, ext=ext, batch=batch or None, label=batch_label or None, fname=fname, sha=sha, who=who)
    if skip_ai: args["skip_ai"] = True   # round 23 (coordinator r22 #7): 'Skip AI' for this scan
    with open(os.path.join(INBOX, jid + ".bin"), "wb") as fh: fh.write(data)
    if back:
        with open(os.path.join(INBOX, jid + ".back"), "wb") as fh: fh.write(back)
    with open(os.path.join(INBOX, jid + ".json"), "w") as fh: json.dump(args, fh)
    POOL.submit(_run, jid, None, **args)
    return {"job": jid, "state": "queued", "ahead": ahead, "batch": batch}

SPLIT_POOL = ThreadPoolExecutor(max_workers=1)   # round 20: PDFs are rendered here, one page at a time, never in a request
CALM_POISON = "This file stopped the scanner while it was being read, so it was set aside. Save it as JPG or a smaller PDF and try again."
def _enqueue_pdf(data, fname, n, engine, batch, batch_label, allow_duplicate, who, had_back, t0=None, skip_ai=False):
    if t0 is not None and _cancelled_since(who, batch, t0):
        return JSONResponse({"error": "Not scanned: the upload was cancelled.", "cancelled": True}, 409)
    from . import demo
    if demo.enabled():   # audit 2026-10 P1 (F09): a PDF in the public demo reads only as many pages as the cap still allows
        n = min(n, demo.capacity_left())
        if n <= 0: return JSONResponse({"error": f"Public demo is full ({demo.max_cards()} cards)."}, 429)
    jid = uuid.uuid4().hex[:12]
    args = dict(kind="pdf", engine=engine, batch=batch or "", label=batch_label or "", fname=fname, pages=n, allow_duplicate=allow_duplicate, who=who, skip_ai=bool(skip_ai))
    with open(os.path.join(INBOX, jid + ".pdf"), "wb") as fh: fh.write(data)
    with open(os.path.join(INBOX, jid + ".json"), "w") as fh: json.dump(args, fh)
    with JLOCK: JOBS[jid] = {"id": jid, "kind": "pdf", "state": "queued", "file": fname, "batch": batch or "", "created": time.time(),
                             "who": who, "pages": n, "page": 0, "children": []}
    SPLIT_POOL.submit(_split_pdf, jid)
    return {"job": jid, "pdf": True, "pages": n, "state": "queued", "ahead": 0, "batch": batch, "source": os.path.basename(fname or ""), "back_skipped": had_back}

def _inbox_clear(jid, exts=(".bin", ".json", ".back", ".pdf", ".reading")):
    for x in exts:
        try: os.remove(os.path.join(INBOX, jid + x))
        except FileNotFoundError: pass

def _done_record(jid, j):
    try:
        with open(os.path.join(DONE, jid + ".json"), "w") as fh:
            json.dump({k: j.get(k) for k in ("id", "kind", "state", "file", "batch", "error", "created", "started", "finished", "pages", "page", "children")}
                      | {"card_id": (j.get("card") or {}).get("id")}, fh)
    except Exception: pass

def _split_pdf(jid):
    """Round 20: render one page at a time in the reader child (memory-limited), add each page's cards as jobs at once."""
    from . import reader
    with JLOCK:
        j = JOBS.get(jid)
        if not j or j.get("state") != "queued": return
        j["state"] = "splitting"; j["started"] = time.time()
    try:
        with open(os.path.join(INBOX, jid + ".json")) as fh: a = json.load(fh)
        with open(os.path.join(INBOX, jid + ".pdf"), "rb") as fh: data = fh.read()
        open(os.path.join(INBOX, jid + ".reading"), "w").close()     # poison guard: present only while a page is read
        n = a["pages"]; made = 0; err = None
        for i in range(n):
            with JLOCK:
                if JOBS[jid].get("state") == "cancelled": break
                JOBS[jid]["page"] = i + 1
            try: parts = reader.run_page(data, i, n, a["fname"], key=jid)
            except reader.ReaderError as e:
                with JLOCK:
                    if JOBS[jid].get("state") == "cancelled": break
                    JOBS[jid]["children"].append({"file": f"{os.path.splitext(os.path.basename(a['fname']))[0]}.pdf (page {i + 1} of {n})", "status": 422, "error": str(e)})
                continue
            for pdata, label in parts:
                if made >= MAX_PARTS:
                    err = f"This file holds more than {MAX_PARTS} cards; the first {MAX_PARTS} were added. Split it to add the rest."; break
                with JLOCK:
                    if JOBS[jid].get("state") == "cancelled": break
                r = _part_result(label, _enqueue_one(pdata, label, a["engine"], a["batch"], a["label"], a["allow_duplicate"], a["who"], None, JOBS[jid].get("created"), bool(a.get("skip_ai"))))
                made += 1
                with JLOCK: JOBS[jid]["children"].append(r)
            del parts
            if err: break
        del data
        with JLOCK:
            j = JOBS[jid]
            if j.get("state") != "cancelled":
                ok = [c for c in j["children"] if c.get("job")]
                if ok or not j["children"]: j |= {"state": "split", "note": err}
                else: j |= {"state": "error", "error": f"None of the {len(j['children'])} cards in this file could be added: " + j["children"][0]["error"]}
            j["finished"] = time.time(); jj = dict(j)
        _done_record(jid, jj)
    except Exception as ex:
        with JLOCK: JOBS[jid] |= {"state": "error", "error": "This PDF couldn't be read. Save it again and retry.", "finished": time.time()}; jj = dict(JOBS[jid])
        _done_record(jid, jj); print("pdf split error:", type(ex).__name__, ex)
    finally:
        _inbox_clear(jid)
        reader.CANCELLED.discard(jid)

@router.post("/api/jobs/cancel")
async def cancel_jobs(request: Request):
    """Round 19: Cancel on the Scan screen. Cards still waiting in line are dropped; cards already read (or being read) stay.
    Only your own jobs are cancelled (an admin may cancel anyone's)."""
    try: body = await request.json()
    except Exception: body = {}
    ids = [str(x) for x in (body.get("ids") or []) if isinstance(x, str)][:2000]
    user = request.state.user; me = _who(request); n = 0
    bt = str(body.get("batch") or "")
    with JLOCK:
        if body.get("all_waiting") is True and bt:   # round 21 (part-timer r20): Cancel stops EVERY waiting card of the batch
            CANCELLED_BATCH[(me, bt)] = time.time()
            ids = list(dict.fromkeys(ids + [k for k, j in JOBS.items() if j.get("batch") == bt and j.get("who") == me and j.get("state") in ("queued", "reading")]))
        for jid in ids:
            j = JOBS.get(jid)
            # round 22: a card being READ is cancelled too (atomic with card creation, see ingest), unless its card exists
            if not j or j.get("state") not in (("queued", "splitting") if j.get("kind") == "pdf" else ("queued", "reading")) or j.get("card_id"): continue
            if j.get("who") != me and user.get("role") != "admin": continue   # round 20 (skeptic M1): recovered jobs keep their owner
            was = j["state"]; j |= {"state": "cancelled", "finished": None}; n += 1
            if was in ("splitting", "reading"):
                from . import reader; reader.stop(jid)                       # stops the page / OCR being run now
    for jid in ids:
        with JLOCK: st = (JOBS.get(jid) or {}).get("state")
        if st != "cancelled": continue
        with JLOCK: jj = dict(JOBS.get(jid) or {})
        if os.path.exists(os.path.join(INBOX, jid + ".reading")) and jj.get("kind") != "pdf": continue   # the reader thread finishes up
        if jj.get("kind") == "pdf":
            if not os.path.exists(os.path.join(INBOX, jid + ".reading")): _inbox_clear(jid)   # else the splitter cleans up
            continue
        try:
            with open(os.path.join(DONE, jid + ".json"), "w") as fh: json.dump({"id": jid, "state": "cancelled", "card_id": None}, fh)
        except Exception: pass
        _inbox_clear(jid)
    # round 23 (skeptic/part-timer r22): ONE final, truthful count: wait until no job of this upload is still being read
    # (a cancelled read stops; one that already made its card finishes), then count the cards THIS upload made
    sess = [str(x) for x in (body.get("session") or []) if isinstance(x, str)][:2000] or ids
    def _sess_jobs():
        with JLOCK:
            out_ = []
            for jid in sess:
                j = JOBS.get(jid)
                if not j: continue
                out_.append(dict(j))
                if j.get("kind") == "pdf": out_ += [dict(JOBS.get(c_["job"]) or {}) for c_ in j.get("children") or [] if c_.get("job")]
            return out_
    for _ in range(60):
        if not any(j.get("state") in ("reading", "splitting") or (j.get("state") == "cancelled" and os.path.exists(os.path.join(INBOX, str(j.get("id")) + ".reading"))) for j in _sess_jobs()): break
        await asyncio.sleep(0.25)
    kept_ids = set()
    for jid in sess:   # jobs of an earlier server run are in the done records
        try:
            with open(os.path.join(DONE, jid + ".json")) as fh: d_ = json.load(fh)
            if d_.get("card_id"): kept_ids.add(int(d_["card_id"]))
        except Exception: pass
    for j in _sess_jobs():
        cid_ = j.get("card_id") or (j.get("card") or {}).get("id")
        if cid_: kept_ids.add(int(cid_))
    kept_ids = {i for i in kept_ids if store.get(i)}
    if n:   # round 20 (reviewer r19): Cancel leaves an audit row
        log(None, me, "upload_cancelled", detail={"not_scanned": n, "kept": len(kept_ids), "batch": clean_batch_label(body.get("batch_label") or "") or str(body.get("batch") or "")[:80]})
    return {"cancelled": n, "kept": len(kept_ids), "kept_ids": sorted(kept_ids)}

@router.get("/api/jobs")
def list_jobs(request: Request, ids: str = "", batch: str = ""):
    want = set(filter(None, ids.split(",")))
    u_ = getattr(request.state, "user", None) or {}; me_ = u_.get("initials"); adm_ = u_.get("role") == "admin"
    with JLOCK:   # round 21 (skeptic r20 L4): listing by batch shows only your own jobs (an admin sees all)
        js = [dict(j) for j in JOBS.values() if (j["id"] in want) or (batch and j["batch"] == batch and (adm_ or j.get("who") == me_))]
        missing = want - set(JOBS)
    for jid in missing:   # finished before a restart: answer from the result record
        if not re.fullmatch(r"[0-9a-f]{12}", jid): continue
        try:
            with open(os.path.join(DONE, jid + ".json")) as fh: r = json.load(fh)
        except (FileNotFoundError, ValueError): continue
        if r.get("card_id") and store.get(r["card_id"]):
            cards_, metas = _active(); r["card"] = enrich(store.get(r["card_id"]), cards_, metas)
        elif r.get("state") == "done": r = r | {"state": "error", "error": "This card was removed."}
        js.append(r)
    with JLOCK: done = [j["finished"] - j["started"] for j in JOBS.values() if j.get("finished") and j.get("started")]
    avg = sum(done[-10:]) / len(done[-10:]) if done else None
    for j in js: j.pop("sha", None)
    # round 14 (newcomer r12): cards from OTHER people waiting to be read ahead of these (the reading line is shared)
    mine = [j.get("created") or 0 for j in js if j.get("state") in ("queued", "reading")]
    with JLOCK: ahead = sum(1 for j in JOBS.values() if j["id"] not in want and j.get("state") in ("queued", "reading") and j.get("kind") != "pdf"
                            and mine and (j.get("created") or 0) < max(mine))
    return {"jobs": js, "avg_seconds": avg, "queue_ahead": ahead}

# ---------------------------------------------------------------- AI double-check (optional local vision model)
# Fast path is OCR+rules+QR. If a card looks uncertain and the local vision server (llama.cpp, VLM_URL, default
# 127.0.0.1:8090) is running, a second pass runs in the background on its own single worker and merges results
# (app/merge.py rules). It only changes cards that are still pending and not edited by a person; otherwise it is skipped.
import queue as _queue, itertools as _it
AI_Q: "_queue.PriorityQueue" = _queue.PriorityQueue()   # (priority, seq, cid, why): 0 = asked for by a person, 1 = background
AI_SEQ = _it.count(); AI_WAIT: dict = {}                  # cid -> (priority, seq) while waiting

BACK_BUSY = threading.Event()   # round 15 (reviewer r14): back-of-card OCR pauses the AI queue so it is not stuck ~5 min behind
AI_TIMES: list = []                                       # recent run times (s), for the progress estimate
AI_RUNNING: dict = {}
AI_TURN: dict = {}       # batch -> checks queued so far (round-robin priority)
AI_RETRIES: dict = {}    # cid -> automatic retries after connection refused
AI_MAX_WAIT = int(os.environ.get("AI_MAX_WAIT", "1800"))   # background checks waiting longer than this are skipped
def _ai_worker():
    """Audit 2026-10 P0-3: one failing card (e.g. 'database is locked') must not end the thread and stop every later check."""
    while True:
        try: _ai_worker_step()
        except Exception as e:
            print("AI worker error (continuing):", repr(e), flush=True); time.sleep(1)
def _ai_worker_step():
    prio, seq, cid, why = AI_Q.get()
    while BACK_BUSY.is_set(): time.sleep(0.25)   # yield to a person's back-of-card OCR
    if AI_WAIT.get(cid) != (prio, seq): return      # superseded (e.g. re-queued as manual)
    AI_WAIT.pop(cid, None)
    try:
        c = store.get(cid); m = meta(cid); det = json.loads(m.get("ai_detail") or "{}")
    except Exception: c, m, det = None, {}, {}
    why_skip = None
    if not c or c["status"] != "pending": why_skip = "the card was already decided"
    manual = bool(det.get("manual"))
    if not why_skip and not manual and m.get("exported"): why_skip = "the card was already exported"
    elif not why_skip and not manual and time.time() - (det.get("queued_at") or time.time()) > AI_MAX_WAIT: why_skip = "the AI was busy for too long"
    if why_skip:
        if c: set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"why": why, "note": why_skip}))
        return
    t0 = time.time(); AI_RUNNING.update(cid=cid, since=t0)
    try: _ai_run(cid, why)
    finally: AI_TIMES.append(time.time() - t0); del AI_TIMES[:-10]; AI_RUNNING.clear()
# started by start_workers() from the served app's lifespan, never on import (mctrade-r3 incident)
def ai_progress(cid):
    """Where a card is in the AI line and how long a check usually takes."""
    w = AI_WAIT.get(cid); typical = round(sum(AI_TIMES) / len(AI_TIMES)) if AI_TIMES else None
    ahead = sum(1 for v in list(AI_WAIT.values()) if w and v < w) if w else 0
    run_for = round(time.time() - AI_RUNNING["since"]) if AI_RUNNING.get("since") else 0
    busy = run_for > max(2 * (typical or 45), 120)   # the model is slow right now (e.g. shared with other jobs)
    t = typical or 60   # round 14: same default as the header (measured ~1 card/min on the pilot box)
    if w: eta = ahead * t + (max(5, t - run_for) if AI_RUNNING.get("since") else 0) + t          # waiting: line ahead + the running one + itself
    elif AI_RUNNING.get("cid") == cid: eta = max(5, t - run_for)
    else: eta = None
    return {"ahead": ahead, "position": (ahead + 1) if w else (0 if AI_RUNNING.get("cid") == cid else None), "typical_seconds": typical,
            "eta_seconds": round(eta) if eta is not None else None, "busy": busy, "current_running_seconds": run_for}
def ai_queue():
    """Whole AI line for the header indicator: how many cards wait, and when the last one should be done."""
    typical = round(sum(AI_TIMES) / len(AI_TIMES)) if AI_TIMES else None; t = typical or 45
    run_for = round(time.time() - AI_RUNNING["since"]) if AI_RUNNING.get("since") else 0
    # round 14 (coordinator r6 #4): count only cards that will really be checked (still pending, not archived; decided or
    # merged ones are skipped in a second), and with no timing history use the measured ~1 card/min, not a guess per card
    def _live(i):
        c_ = store.get(i); return bool(c_ and c_["status"] == "pending" and not meta(i).get("archived"))
    waiting = sum(1 for i in list(AI_WAIT) if _live(i)); running = 1 if AI_RUNNING.get("since") else 0
    if typical is None: t = 60
    eta = waiting * t + (max(5, t - run_for) if running else 0)
    return {"waiting": waiting, "running": running, "typical_seconds": typical, "eta_seconds": round(eta) if (waiting or running) else 0}
KEY_FIELDS = ("name", "company", "title", "emails", "phones")
def ai_reason(f):
    k = f.get("confidence") or {}
    if (f.get("sources") or {}).get("qr"): return None             # QR data is already exact
    low = [x for x in KEY_FIELDS if k.get(x) is not None and k[x] < 0.75] + [x for x in (f.get("needs_review") or []) if x in KEY_FIELDS]
    if not (f.get("first_name") or f.get("last_name")): low.append("name")
    if not f.get("company"): low.append("company")
    ov = f.get("overall_confidence")
    # round 21 (datamanager r20): faster AI line. A field that proves itself (a valid email on the website's domain, a full
    # 10-digit phone, an address that splits into street/city/state/zip) doesn't need the slow AI look
    def _proven(x):
        try:
            if x == "emails":
                d_ = re.sub(r"^[a-z]+://", "", str(f.get("website") or "").lower()).split("/")[0].removeprefix("www.")
                return bool(d_) and bool(f.get("emails")) and all(not email_syntax(e) and (e.lower().rsplit("@", 1)[1] == d_ or e.lower().endswith("." + d_)) for e in f["emails"])
            if x == "phones": return bool(f.get("phones")) and all(len(_digits(p.get("number"))) in (10, 11) for p in f["phones"]) and "phones" not in hard_errors(f)
            if x == "address": return address_validates(f.get("address")) and "address" not in garbled_errors(f)
        except Exception: return False
        return False
    low = [x for x in low if not _proven(x)]
    if low or (ov is not None and ov < 0.8): return sorted(set(low)) or ["overall"]
    return None

AI_OFF = "AI check is off right now. Scanning still works."
_RAW = re.compile(r"URLError|Errno|refused|Traceback|Exception|Error:|urlopen|HTTPConnection|socket", re.I)
def calm_ai_detail(d):
    """Round 20 (a): older cards may still hold a raw error ('URLError Errno 111 ...'); show the calm line instead."""
    if isinstance(d, dict) and isinstance(d.get("error"), str) and _RAW.search(d["error"]):
        d = dict(d, error=AI_OFF, offline=True)
    return d

def ai_available():
    try:
        from . import vlm
        return vlm.available(timeout=1.0)
    except Exception: return False

def maybe_ai_check(cid, force=False):
    if auth.get_setting("ai_check_enabled") != "1" and not force: return "off"
    c = store.get(cid)
    if not c or c["status"] != "pending" or not c.get("image"): return "skip"
    why = ai_reason(c["fields"]) if not force else ["requested"]
    if not why: return "not needed"
    if not ai_available(): set_meta(cid, ai_status="unavailable"); return "unavailable"
    if meta(cid).get("ai_status") == "checking": return "queued"
    # round 7 (reviewer r7): automatic checks must not starve behind manual ones. Priority = the card's turn in ITS batch
    # (round-robin across people, round 13); a manual request jumps 3 turns ahead, not ahead of everything.
    # round 13 (coordinator r5 N1): the turn is counted per PERSON (whoever scanned the card), so one tester's big stack
    # can't push everyone else's cards back; inside one person's line the oldest card goes first (queue order).
    if cid in AI_WAIT:   # round 14 (skeptic r12): asking again never moves a waiting card back or uses up another turn
        old = AI_WAIT[cid]; d_ = json.loads(meta(cid).get("ai_detail") or "{}")
        if force and not d_.get("manual"):   # a manual request on an automatic check: same 3 turns ahead, once
            AI_WAIT[cid] = (max(0, old[0] - 3), old[1]); AI_Q.put((AI_WAIT[cid][0], old[1], cid, ["requested"]))
            set_meta(cid, ai_detail=json.dumps(d_ | {"manual": True}))
        return "already"
    r_ = db().execute("SELECT reviewer FROM card_history WHERE card_id=? AND action='scanned' ORDER BY id LIMIT 1", (cid,)).fetchone()
    b = "u:" + (r_[0] if r_ and r_[0] else (meta(cid).get("batch") or "")); AI_TURN[b] = max(AI_TURN.get(b, 0), min((v[0] for v in list(AI_WAIT.values())), default=0)) + 1   # a late starter joins at the current turn
    prio = max(0, AI_TURN[b] - (3 if force else 0)); key = (prio, next(AI_SEQ))
    if cid in AI_WAIT and AI_WAIT[cid][0] <= key[0] and not force: return "queued"
    AI_WAIT[cid] = key
    set_meta(cid, ai_status="queued", ai_detail=json.dumps({"why": why, "queued_at": time.time(), "manual": bool(force)}))
    AI_Q.put((prio, key[1], cid, why)); return "queued"

def _ai_run(cid, why):
    """Runs the vision model and stores the differences as SUGGESTIONS only. The card itself is never changed here:
    the reviewer accepts or keeps each value in the review screen (so typed, unsaved edits can never be overwritten)."""
    from . import vlm, merge
    try:
        started = time.time(); set_meta(cid, ai_status="checking", ai_detail=json.dumps({"why": why, "started": started}))
        c = store.get(cid); p = os.path.join(UP, os.path.basename(c.get("image") or ""))
        if not os.path.isfile(p): set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"why": why, "note": "photo missing"})); return
        try:
            from . import plausibility as _pl
            hints = "; ".join(x.get("text", "") for x in _pl.check(c["fields"]))[:600]
        except Exception: hints = ""
        lowf = ", ".join(low_fields(c["fields"], sources(cid)))
        if lowf: hints = (hints + "; " if hints else "") + "hard to read: " + lowf
        keys = vlm.keys_for(why, c["fields"]) if os.getenv("VLM_SUBSET", "1") == "1" else None
        v = vlm.extract(open(p, "rb").read(), c["raw_text"] or "", keys=keys, hints=hints)
        c = store.get(cid); f = c["fields"]; g = merge.merge(f, v, c["raw_text"] or "")
        for k in ("address", "other_address"):   # a line break in the AI's address is a separator, never glue ('State RdCuyahoga')
            if isinstance(g.get(k), str): g[k] = re.sub(r"\s*[\r\n]+\s*", ", ", g[k]).strip(" ,")
        from . import consistency as _cons, plausibility as _plaus
        _cons.apply(g); _plaus.apply(g)   # audit 2026-10: flags describe the merged values (merge() is pure: f is untouched)
        src = sources(cid)
        edited = {k for k, x in src.items() if str(x).startswith("edited")}
        if "first_name" in edited or "last_name" in edited: edited.add("name")
        try: rej = json.loads(meta(cid).get("ai_rejected") or "{}")
        except Exception: rej = {}
        # round 7 (reviewer r7): a value the person already declined ("Keep current") is not offered again
        changed = {k: {"from": f.get(k), "to": g.get(k), "edited_by_person": k in edited}
                   for k in QR_KEYS + ("credentials", "other_address") if k in g and g.get(k) != f.get(k)
                   and json.dumps(rej.get(k), sort_keys=True) != json.dumps(g.get(k), sort_keys=True)
                   and not (k in garbled_errors(dict(f, **{k: g.get(k)})) and k not in garbled_errors(f))}   # round 20: never offer a garbled value over a clean one
        secs = round(time.time() - started, 1)
        if meta(cid).get("ai_status") != "checking":   # cancelled meanwhile (the card was approved/rejected during the check)
            log(cid, "AI", "ai_checked", detail={"changed": {}, "suggested": [], "seconds": secs, "cancelled": True}); return
        set_meta(cid, ai_status="suggested" if changed else "checked", ai_detail=json.dumps(
            {"why": why, "diff": changed, "changed": [], "applied": False, "seconds": secs, "finished": time.time()}))
        log(cid, "AI", "ai_checked", detail={"changed": {}, "suggested": list(changed), "seconds": secs})
    except Exception as e:
        slow = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
        refused = "refused" in str(e).lower() or "urlerror" in type(e).__name__.lower() or "connection" in str(e).lower()
        print(f"AI check error on card {cid}: {type(e).__name__}: {str(e)[:200]}", flush=True)   # technical detail: console only
        # round 20 (a): never show 'URLError Errno 111' on a card
        msg = ("The AI was too busy to answer. Nothing changed. Try again later." if slow
               else AI_OFF if refused else "The AI check hit a problem. Nothing changed. Scanning still works.")
        n = AI_RETRIES.get(cid, 0)
        if refused and n < 3:   # round 7: the AI server restarting -> retry by itself, and say so
            AI_RETRIES[cid] = n + 1; wait = 60 * (n + 1)
            set_meta(cid, ai_status="failed", ai_detail=json.dumps({"why": why, "error": AI_OFF, "offline": True, "retrying": True}))
            def _again(cid=cid, why=why, n=n):
                c_ = store.get(cid)
                if c_ and c_["status"] == "pending" and meta(cid).get("ai_status") == "failed":
                    key = (0, next(AI_SEQ)); AI_WAIT[cid] = key
                    set_meta(cid, ai_status="queued", ai_detail=json.dumps({"why": why, "queued_at": time.time(), "manual": True, "retry": n + 1}))
                    AI_Q.put((0, key[1], cid, why))
            t_ = threading.Timer(wait, _again); t_.daemon = True; t_.start()
        else:
            set_meta(cid, ai_status="busy" if slow else "failed", ai_detail=json.dumps({"why": why, "error": msg, "offline": refused}))
        return
    AI_RETRIES.pop(cid, None)

AI_MANUAL = {}   # user id -> recent manual-check times (round 13 rate limit)
AI_MANUAL_MAX, AI_MANUAL_WINDOW = 6, 600
@router.post("/api/cards/{cid}/ai-check")
def ai_check_now(cid: CardId, request: Request):
    # round 13 (skeptic r11 R11-3): only cards the person can see in the queue (exists, not archived), and a per-user limit
    if not store.get(cid): return JSONResponse({"error": "Card not found."}, 404)
    if auth.get_setting("ai_check_enabled") != "1":
        return JSONResponse({"error": "The AI double-check is switched off (Admin → Settings → AI double-check).", "need": "ai_off"}, 409)
    if meta(cid).get("archived"): return JSONResponse({"error": f"Card #{cid} is archived: it can't be AI-checked.", "need": "archived"}, 409)
    u = (getattr(request.state, "user", None) or {}).get("id"); now = time.time()
    t_ = [x for x in AI_MANUAL.get(u, []) if now - x < AI_MANUAL_WINDOW]
    again = cid in AI_WAIT or meta(cid).get("ai_status") == "checking"   # round 14: asking again for a card already in line is never limited
    if len(t_) >= AI_MANUAL_MAX and not again:
        return JSONResponse({"error": f"You asked for {AI_MANUAL_MAX} AI checks in the last {AI_MANUAL_WINDOW // 60} minutes. Wait a few minutes; the AI checks cards one at a time.", "need": "rate_limited"}, 429)
    r = maybe_ai_check(cid, force=True)
    if r not in ("unavailable", "skip", "already") and not again: t_.append(now)
    if r == "already": r = "queued"
    AI_MANUAL[u] = t_
    if r == "unavailable": return JSONResponse({"error": "The AI double-check isn't running on this computer (vision server not started)."}, 503)
    if r == "skip": return JSONResponse({"error": "Only pending cards with a photo can be AI-checked."}, 409)
    return {"status": r} | ai_progress(cid)

@router.post("/api/cards/{cid}/ai-decide")
def ai_decide(cid: CardId, request: Request, body: dict = Body(...)):
    with WRITE_LOCK, store.tx():
        try: return _ai_decide(cid, request, body)
        finally: _seal()
def _ai_decide(cid, request, body):
    """body: {choices: {field: "accept"|"reject"}, version}. 'accept' puts the AI value in, 'reject' keeps/restores the earlier value.
    Goes through the normal edit path (snapshot, undo, history, re-export flag). Round 7: needs the card version; an empty or
    unknown choice list changes nothing (skeptic R7-6: all([]) used to mark a queued check as 'checked')."""
    c = store.get(cid); m = meta(cid)
    if not c: raise HTTPException(404, "Card not found")
    if m.get("archived"): return _archived_409(cid)
    ch_ = {k: v for k, v in (body.get("choices") or {}).items() if v in ("accept", "reject")} if isinstance(body.get("choices"), dict) else {}
    if not ch_: return JSONResponse({"error": "No AI suggestion was chosen: nothing changed.", "need": "choices"}, 400)
    vp = _version_problem(c, body.get("version"), cid)
    if vp is not None: return vp
    try: det = json.loads(m.get("ai_detail") or "{}")
    except Exception: det = {}
    diff = det.get("diff") or {}; fields = {}; made = {}; stale = []
    for k, choice in (body.get("choices") or {}).items():
        if k not in diff or choice not in ("accept", "reject"): continue
        # a suggestion expires once decided, once the card is decided, or once the value it was made for has changed (R6-6)
        if choice == "reject" and k in (det.get("decided") or {}):   # skeptic R8-6: already decided -> stale, like a repeated accept
            stale.append(k); continue
        if choice == "accept" and (c["status"] != "pending" or k in (det.get("decided") or {}) or c["fields"].get(k) != diff[k]["from"]) \
                and not (body.get("record_only") and k not in (det.get("decided") or {}) and c["status"] == "pending"):
            stale.append(k); continue
        if choice == "accept" and body.get("record_only") and c["fields"].get(k) != diff[k]["from"] and c["fields"].get(k) != diff[k]["to"]:
            stale.append(k); continue   # record_only can't skip the value-changed expiry
        want = diff[k]["to"] if choice == "accept" else diff[k]["from"]
        if choice == "accept" and c["fields"].get(k) != want: fields[k] = want
        det.setdefault("decided", {})[k] = choice; made[k] = choice
    if not made and not stale:   # skeptic R8-6: choices only for fields the AI made no suggestion for
        return JSONResponse({"error": "The AI made no suggestion for that field: nothing changed.", "need": "stale_suggestion", "fields": list(ch_)}, 409)
    if fields and payload_problems(fields):
        return JSONResponse({"error": "The AI value can't be used: " + "; ".join(payload_problems(fields).values()), "need": "fix"}, 422)
    if fields and not body.get("record_only"):   # record_only: the browser put the value in the form; the person saves it
        r = _update(cid, request, {"fields": fields, "note": c.get("note")}, internal=True)
        if isinstance(r, JSONResponse): return r
    src = sources(cid); rv = request.state.user["initials"]
    try: rej = json.loads(m.get("ai_rejected") or "{}")
    except Exception: rej = {}
    for k, ch in made.items():
        if ch == "reject" and not str(src.get(k, "")).startswith("edited"): src[k] = "confirmed:" + rv
        if ch == "reject": rej[k] = diff[k]["to"]
    set_meta(cid, ai_rejected=json.dumps(rej))
    set_meta(cid, field_sources=json.dumps(src))
    det["resolved"] = bool(diff) and all(k in det.get("decided", {}) for k in diff)
    set_meta(cid, ai_detail=json.dumps(det), ai_status=("checked" if det["resolved"] else meta(cid).get("ai_status")))
    _ai_settle(cid)
    if made: log(cid, rv, "ai_suggestion", detail=made)
    if stale and not made:
        return JSONResponse({"error": "This AI suggestion is out of date. Nothing changed. Check with AI again if needed.",
                             "need": "stale_suggestion", "fields": stale}, 409)
    return card(cid) | ({"stale": stale} if stale else {})

def _ai_settle(cid, saved=False):
    """Round 9 (coordinator N5): a card no longer stays at ai_status 'suggested' once nothing is left to decide.
    A suggestion is open while it is undecided AND the field still holds the value it was made for. A person's Save
    (after 'Keep current' or editing) records every still-open suggestion as kept, and a decided card has none open."""
    m = meta(cid)
    if m.get("ai_status") != "suggested": return
    c = store.get(cid)
    if not c: return
    try: det = json.loads(m.get("ai_detail") or "{}")
    except Exception: return
    diff = det.get("diff") or {}; dec = det.setdefault("decided", {})
    still = [k for k in diff if k not in dec and c["fields"].get(k) == diff[k]["from"]]
    if still and (saved or c["status"] != "pending"):
        for k in still: dec[k] = "kept"
        still = []
    for k in diff:
        if k not in dec and c["fields"].get(k) != diff[k]["from"]:
            dec[k] = "accepted" if c["fields"].get(k) == diff[k]["to"] else "changed"
    if not still:
        det["resolved"] = True
        set_meta(cid, ai_status="checked", ai_detail=json.dumps(det))

@router.post("/api/validate")
def validate_api(request: Request, body: dict = Body(...)):
    """Same checks as approval, for every field approval checks (skeptic R7-7: other_address, department, credentials, social)."""
    f = {"first_name": "", "last_name": "", "title": "", "company": "", "website": "", "address": "", "department": "",
         "credentials": "", "other_address": "", "note": "", "emails": [], "phones": [], "social": []}
    bad = fields_shape_problem(body.get("fields"))
    if bad: return JSONResponse({"error": bad, "need": "fix"}, 422)
    _apply_fields(f, body.get("fields") or {})
    if isinstance(body.get("note"), str): f["note"] = body["note"]
    try:   # round 21: values a reviewer confirmed as correct ('This is correct') stay confirmed while unchanged
        c_ = store.get(int(body.get("card_id"))) if str(body.get("card_id") or "").isdigit() else None
        if c_:
            for k_ in ("confirmed_ok", "confirmed_meta"):
                if isinstance(c_["fields"].get(k_), dict): f[k_] = c_["fields"][k_]
    except Exception: pass
    hard = hard_errors(f)
    adm = (getattr(request.state, "user", None) or {}).get("role") == "admin"
    over = [k for k in overridable(f) if k in hard and (adm or k not in ADMIN_OVERRIDE)]
    return {"errors": validate(f), "hard": hard, "overridable": over}

@router.post("/api/cards/{cid}/confirm-correct")
def confirm_correct(cid: CardId, request: Request, body: dict = Body(...)):
    """Round 21 (mctrade-admin r20): a hard 'looks misread' check can be wrong (www2., smithlaw/smithlaws). The reviewer
    says 'This is correct' for one field: that exact saved value is accepted from then on, and the audit says who did it."""
    # Round 22 (skeptic r21 M1/M2, mctrade-admin r21 M1/M2): body {field, value, version}; archived cards and stale versions
    # are refused; the exact value the reviewer saw must still be the saved one; admin-only for email/website/address.
    with WRITE_LOCK, store.tx():
        c = store.get(cid)
        if not c: return JSONResponse({"error": "Card not found."}, 404)
        if meta(cid).get("archived"): return _archived_409(cid)
        k = str(body.get("field") or ""); fk = "first_name" if k == "name" else k
        if k not in OVERRIDABLE: return JSONResponse({"error": "This check can't be overridden."}, 400)
        u = request.state.user
        if k in ADMIN_OVERRIDE and u.get("role") != "admin":
            return JSONResponse({"error": "Only an admin can confirm this field. Ask an admin, or fix the value."}, 403)
        vp = _version_problem(c, body.get("version"), cid)
        if vp: return vp
        f = c["fields"]
        if "value" not in body or json.dumps(body.get("value"), sort_keys=True) != json.dumps(f.get(fk), sort_keys=True):
            return JSONResponse({"error": "The saved value is different from the one you checked. Reload the card and check again.", "need": "stale"}, 409)
        g = garbled_errors({**f, "confirmed_ok": {}})
        if k not in g: return JSONResponse({"error": "Nothing to confirm: save the card first, then confirm the saved value."}, 409)
        if k not in overridable(f): return JSONResponse({"error": "This value can't be confirmed (it looks like a formula or code). Fix it."}, 400)
        ok = dict(f.get("confirmed_ok") or {}); val = json.dumps(f.get(fk), sort_keys=True)
        cm = dict(f.get("confirmed_meta") or {})
        if ok.get(fk) == val and fk in valid_confirmations(f): return {"ok": True, "field": fk, "already": True, "version": card_version(c)}   # replay: no duplicate audit rows
        why_, bad_ = clean_reason(body.get("reason") or "")   # round 23 (datamanager r22 H1): a reason is always required
        if bad_: return JSONResponse({"error": bad_ if body.get("reason") else "Say why it is correct (e.g. “printed like this on the card”).", "need": "reason"}, 422)
        ok[fk] = val
        cb = dict(f.get("confirmed_by") or {}); cb[fk] = u["initials"]
        cm[fk] = {"user": u["username"], "by": u["initials"], "role": u.get("role"), "reason": why_, "value": val, "ts": time.time()}
        store.update(cid, fields=f | {"confirmed_ok": ok, "confirmed_by": cb, "confirmed_meta": cm}, status=c["status"], reviewer=c.get("reviewer"), note=c.get("note"))
        rv = _who(request); log(cid, rv, "hard_check_override", detail={"field": fk, "value": f.get(fk), "check": g[k], "reason": why_, "user": u["username"]})
        # round 24 (datamanager/mctrade-admin r23 L2): one audit row per confirm (the card-history row above)
        return {"ok": True, "field": fk, "version": card_version(store.get(cid))}

def confirmed_lines(f):
    """Round 23: '#621 Email confirmed by QA: x (reason)' lines for the READ-ME / extra columns: only confirmations that
    still pass today's rules (valid_confirmations), with the value in plain words."""
    ok = valid_confirmations(f); cm = f.get("confirmed_meta") if isinstance(f.get("confirmed_meta"), dict) else {}
    return [f"{LABEL.get(k, k)} confirmed by {cm[k].get('by')}: {_fmtv(f.get(k))} ({cm[k].get('reason')})" for k in sorted(ok)]

@router.post("/api/admin/ai/skip-waiting")
def ai_skip_waiting(request: Request):
    """Round 22: busy event: an admin skips every AI check that is still WAITING (a running one finishes). Cards stay
    pending and can still be checked one by one with 'Ask the AI'."""
    n = 0
    for cid in list(AI_WAIT):
        AI_WAIT.pop(cid, None); n += 1
        set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"note": "AI check skipped by an admin (busy event)"}))
    auth.alog(request.state.user["username"], f"skipped {n} waiting AI {'check' if n == 1 else 'checks'} (busy event)")
    return {"ok": True, "skipped": n}

@router.get("/api/ai/status")
def ai_status():
    return {"enabled": auth.get_setting("ai_check_enabled") == "1", "available": ai_available(), "queue": ai_queue()}

# ---------------------------------------------------------------- cards
def _name_index(cards):
    """Round 15 (speed): one first+last index for the whole list, so attention() is O(1) per card instead of O(n)."""
    by = {}
    for c in cards:
        n = _nm(c.get("fields"))
        if n and " " in n: by.setdefault(n, []).append(c)
    return by

@router.get("/api/cards")
def cards(request: Request, status: str | None = None, batch: str | None = None, archived: bool = False):
    if status not in (None, "", "pending", "approved", "rejected"):
        return JSONResponse({"error": "status must be pending, approved, rejected, or empty (all).", "need": "bad_status"}, 422)
    cs, metas = _active(include_archived=archived)
    # round 15 (manager r14: ~6 s under load): filter BEFORE the expensive enrich, so a one-batch queue only enriches its own cards
    def _b(c): return (metas.get(c["id"]) or {}).get("batch")
    sel = [c for c in cs if (not status or c["status"] == status) and (not batch or (not _b(c) if batch == "__none__" else _b(c) == batch))]
    if archived: sel = [c for c in sel if (metas.get(c["id"]) or {}).get("archived")]   # round 16 (skeptic r15 M1): BEFORE paging
    names = _name_index(cs)
    # round 15 (skeptic): optional pagination. Default page size 200 when listing ALL batches (the one-batch path is small).
    # The queue always asks with ?batch=, so it never paginates. ?limit=&offset= is for the rare "All batches" and scripts.
    try:   # round 16 (skeptic r15 L2): limit=abc is a 422, not a silent default; X-Limit reports the limit really used
        lim = int(request.query_params.get("limit") or (0 if batch else 200))
        off = int(request.query_params.get("offset") or 0)
        if lim < 0 or off < 0: raise ValueError
    except Exception:
        return JSONResponse({"error": "limit and offset must be whole numbers (limit=0 means all cards).", "need": "bad_limit"}, 422)
    total = len(sel)
    if lim > 0: lim = min(lim, 500); sel = sel[off: off + lim]
    out = [enrich(c, cs, metas, names=names) for c in sel]
    if lim > 0:
        r = JSONResponse(out); r.headers["X-Total"] = str(total); r.headers["X-Offset"] = str(off); r.headers["X-Limit"] = str(lim); return r
    return out

def _my_batches(ini):
    return {r[0] for r in db().execute("""SELECT DISTINCT m.batch FROM card_history h JOIN card_meta m ON m.card_id=h.card_id
       WHERE h.action='scanned' AND h.reviewer=? AND m.batch IS NOT NULL""", (ini,))}

@router.get("/api/counts")
def counts(request: Request, batch: str = ""):
    """Round 15 (part-timer r14): cheap counts for the nav badge (SQL only, no look-alike work). 'mine' = pending cards in the
    batches the signed-in person scanned; 'everyone' = all pending; 'batch' = counts of one batch."""
    mine = _my_batches(request.state.user["initials"])
    rows = db().execute("""SELECT m.batch b, c.status s, COUNT(*) n FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id
       WHERE COALESCE(m.archived,0)=0 GROUP BY m.batch, c.status""").fetchall()
    out = {"mine_pending": 0, "everyone_pending": 0, "batch": {"pending": 0, "approved": 0, "rejected": 0, "all": 0}}
    for r in rows:
        if r["s"] == "pending":
            out["everyone_pending"] += r["n"]
            if r["b"] in mine: out["mine_pending"] += r["n"]
        if batch and ((r["b"] or "__none__") == batch):
            out["batch"][r["s"]] = out["batch"].get(r["s"], 0) + r["n"]; out["batch"]["all"] += r["n"]
    return out

@router.get("/api/batches")
def batches(request: Request):
    """Batches, newest first. Round 7: per batch also 'ready' (approved and not yet exported, or changed after export: what
    'Approved, not yet exported' would export), 'approved', and 'mine' (the signed-in person scanned cards in it)."""
    rows = db().execute("""SELECT m.batch, m.batch_label, COUNT(*) n, SUM(c.status='pending') pending, SUM(c.status='approved') approved,
       SUM(c.status='approved' AND (m.exported IS NULL OR m.reexport IS NOT NULL)) ready, MIN(c.created) started
       FROM card_meta m JOIN cards c ON c.id=m.card_id WHERE m.archived=0 AND m.batch IS NOT NULL GROUP BY m.batch ORDER BY started DESC""")
    out = [dict(r) for r in rows]
    ini = request.state.user["initials"]
    mine = _my_batches(ini)
    # round 15 (part-timer r14): 'own' = YOU scanned the batch's first card. The default batch (queue, export) is your newest
    # OWN batch, never one of someone else's that you only added a card to.
    own = {r[0] for r in db().execute("""SELECT m.batch FROM card_meta m JOIN card_history h ON h.card_id=m.card_id AND h.action='scanned'
       WHERE m.batch IS NOT NULL AND h.id=(SELECT MIN(h2.id) FROM card_history h2 JOIN card_meta m2 ON m2.card_id=h2.card_id
       WHERE m2.batch=m.batch AND h2.action='scanned') AND h.reviewer=?""", (ini,))}
    for r in out: r["mine"] = r["batch"] in mine; r["own"] = r["batch"] in own
    # round 24 (reviewer r23): the owner's name, for the "this batch belongs to …" warning
    try:
        names = {u_["initials"]: (u_["display"] or u_["initials"]) for u_ in auth.db().execute("SELECT initials, display FROM users")}
        for b_, ini_ in db().execute("""SELECT m.batch, h.reviewer FROM card_meta m JOIN card_history h ON h.card_id=m.card_id AND h.action='scanned'
               WHERE h.id=(SELECT MIN(h2.id) FROM card_history h2 JOIN card_meta m2 ON m2.card_id=h2.card_id WHERE m2.batch=m.batch AND h2.action='scanned') GROUP BY m.batch"""):
            for r in out:
                if r["batch"] == b_: r["owner"] = names.get(ini_, ini_)
    except Exception: pass
    nob = db().execute("SELECT COUNT(*) FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id WHERE m.batch IS NULL AND COALESCE(m.archived,0)=0").fetchone()[0]
    if nob: out.append({"batch": "__none__", "batch_label": "Earlier cards (no batch)", "n": nob})
    return out

def card_version(c):
    """Short fingerprint of what the reviewer sees (fields, status, note). Saves send it back; a mismatch means the form is stale."""
    return hashlib.sha1(json.dumps([c.get("fields"), c.get("status"), c.get("note") or ""], sort_keys=True, default=str).encode()).hexdigest()[:12]
@router.get("/api/cards/{cid}")
def card(cid: CardId):
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    cs, metas = _active(include_archived=True)
    return enrich(c, cs, metas, full=True)

def _apply_fields(f, body_fields):
    changed = {}
    for k, v in body_fields.items():
        if k in ("confidence", "overall_confidence", "ocr_conf", "fallback_reason", "edited", "sources"): continue
        if k in ("emails", "social"):
            v = [str(x).strip() for x in (v or []) if str(x).strip()]
        elif k == "phones":
            v = [{"type": str(p.get("type", "work")), "number": str(p.get("number", "")).strip(), "valid": phone_ok(str(p.get("number", "")))} for p in (v or []) if str(p.get("number", "")).strip()]
            old = [{"type": p.get("type"), "number": p.get("number"), "valid": phone_ok(p.get("number"))} for p in f.get("phones", [])]
            if old == v: continue
        elif k in f and isinstance(f[k], str) or k in ("first_name", "last_name", "title", "company", "website", "address"):
            v = str(v or "").strip()
        else: continue
        if f.get(k) != v: changed[k] = {"from": f.get(k), "to": v}; f[k] = v
    if changed: f["edited"] = True
    return changed

# Round 7 (skeptic R7-2/R7-3): REAL optimistic locking. Every writer of a card (save, merge, bulk, AI accept/reject, the AI
# worker) holds WRITE_LOCK while it compares the version and writes, so "check version, then write" is one atomic step: of
# two saves sent with the same version exactly one wins and the other gets 409 'stale'. A missing / empty / 0 version is
# refused (409 'version'), so old tabs and scripts can't overwrite blindly.
WRITE_LOCK = threading.RLock()
def _version_problem(c, v, cid):
    if v in (None, "", 0, "0", False) or not isinstance(v, str):
        return JSONResponse({"error": "Nothing was saved: the page is out of date. Reload the card and save again.",
                             "need": "version", "version": card_version(c)}, 409)
    if v != card_version(c):
        return JSONResponse({"error": f"Card #{cid} changed since you opened it. Nothing was saved. Reload, check and save again.",
                             "need": "stale", "version": card_version(c)}, 409)
    return None

def _archived_409(cid):
    """Round 14 (skeptic r12): an archived card is read-only everywhere (save, approve, reject, merge, back side, AI, bulk)."""
    return JSONResponse({"error": f"Card #{cid} is archived, so it can't be changed. Un-archive its batch first (Admin) if it needs work.", "need": "archived"}, 409)

@router.post("/api/cards/{cid}")
def update(cid: CardId, request: Request, body: dict = Body(...)):
    """body: card_id, version (required), fields?, status?, note?, override_reason?, confirm_redecide?, dup_resolution?,
       merge_into?, crm_action?, confirm_cross_batch?. The reviewer is always the signed-in user."""
    with WRITE_LOCK, store.tx():
        try: return _update(cid, request, body, internal=False)
        finally: _seal()

def _update(cid, request, body, internal=False):
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    if not internal and meta(cid).get("archived"): return _archived_409(cid)
    if not internal and "override_reason" in body and body.get("override_reason") not in (None, ""):
        why_, bad_ = clean_reason(body.get("override_reason"))
        # hard problems are reported first (approval_check); a bad reason is refused only where a reason is needed
        body = dict(body, override_reason="" if bad_ else why_, _reason_bad=bad_)
    body = {k: v for k, v in body.items() if k != "_via_ai"} if isinstance(body, dict) else body   # client can't hide an edit (skeptic R6-2)
    if isinstance(body, dict) and isinstance(body.get("note"), str): body["note"] = clean_note(body["note"])   # skeptic R9-3
    if isinstance(body, dict):
        for k_ in ("confirm_cross_batch", "confirm_redecide"):   # round 11 (skeptic R10-2)
            if k_ in body: body[k_] = body[k_] is True
    if not isinstance(body, dict): return JSONResponse({"error": "Send a JSON object."}, 422)
    shape = fields_shape_problem(body.get("fields"))
    if shape: return JSONResponse({"error": shape, "need": "fix"}, 422)
    # round 13 (skeptic r11 R11-1): ids in the body follow the same strict rule as the path
    if body.get("card_id") not in (None, ""): body["card_id"] = strict_id(body["card_id"], "card_id")
    if "merge_into" in body:
        mi = strict_id(body["merge_into"], "merge_into")
        if mi == cid:
            return JSONResponse({"error": f"Card #{cid} can't be merged into itself. Open the OTHER card (the duplicate) and merge it into #{cid}.", "need": "merge_self"}, 422)
        if not store.get(mi): return JSONResponse({"error": f"Card #{mi} to merge into was not found.", "need": "merge_missing"}, 422)
        if meta(mi).get("archived"): return JSONResponse({"error": f"Card #{mi} is archived: it can't receive a merge.", "need": "merge_archived"}, 422)
        body["merge_into"] = mi
    if isinstance(body.get("keep_apart"), list): body["keep_apart"] = [strict_id(x, "keep_apart id") for x in body["keep_apart"]]
    user = request.state.user; rv = user["initials"]
    # round 6 (newcomer F1): the page says which card and which version it is showing; refuse a save meant for another card
    # or made from an out-of-date form (another tab, an AI suggestion applied, a teammate's edit)
    if body.get("card_id") not in (None, "") and str(body.get("card_id")) != str(cid):
        return JSONResponse({"error": f"This save was meant for card #{body.get('card_id')}, not #{cid}. Nothing was saved; reload the card.", "need": "wrong_card"}, 409)
    if not internal:
        vp = _version_problem(c, body.get("version"), cid)
        if vp is not None: return vp
    ka = body.get("keep_apart")   # skeptic R9-5: keep_apart:true used to crash (500)
    if ka not in (None, False, "", "all") and not (isinstance(ka, list) and all(str(x).isdigit() for x in ka)):
        return JSONResponse({"error": "keep_apart must be \"all\" or a list of card numbers.", "need": "fix"}, 422)
    f = c["fields"]
    if body.get("crm_action") == "update_existing" and auth.get_setting("mctrade_updates_enabled") != "1":
        return JSONResponse({"error": "'Update existing MC Trade contact' is switched off (Admin → Settings). Choose 'add as new contact', or ask an admin.",
                             "need": "updates_off"}, 409)
    # round 7: ONE shared check for every value a person can write (save, approve, merge, AI accept): markup / formula /
    # invisible characters are refused at SAVE too, not only at approval (reviewer r7: 'Save stores invalid values')
    bad = payload_problems({**(body.get("fields") or {}), **({"note": body["note"]} if isinstance(body.get("note"), str) and body["note"] else {})})
    if bad and body.get("status") == "approved":   # list everything that blocks approval together (not one problem per try)
        try: bad = {**hard_errors({**f, **(body.get("fields") or {})}), **bad}
        except Exception: pass
    if bad: return JSONResponse({"error": "Some values can't be saved: " + "; ".join(bad.values()), "need": "fix", "errors": bad, "hard": list(bad)}, 422)
    st = body.get("status"); st = st if st in ("pending", "approved", "rejected") else None
    # dry-run the checks before taking a snapshot so refused requests don't create undo entries
    import copy
    f2 = copy.deepcopy(f); changes = _apply_fields(f2, body.get("fields") or {})
    # round 13 (reviewer r11, R10 regression): a save that BLANKS the first name is refused (a card read without one can still be saved)
    if "first_name" in (body.get("fields") or {}) and not (f2.get("first_name") or "").strip() and (f.get("first_name") or "").strip():
        # round 16 (reviewer r15 #7): list EVERY problem on the form, not only the blank first name
        all_e = {"name": "First name is required."} | {k: v for k, v in (validate(f2) | hard_errors(f2)).items() if k != "name"}
        return JSONResponse({"error": "First name is required: it can't be cleared. Type the first name from the card." + (" Also: " + "; ".join(v for k, v in all_e.items() if k != "name") if len(all_e) > 1 else ""), "need": "fix",
                             "errors": all_e, "hard": ["name"] + [k for k in hard_errors(f2) if k != "name"]}, 422)
    # round 15 (part-timer): never let a blank typed value silently wipe a filled field (a save fired while the form was still empty after a reload)
    bf = body.get("fields") or {}; wiped = []
    for k in ("last_name", "title", "company", "website", "address", "department", "credentials", "other_address"):
        if k in bf and not str(bf.get(k) or "").strip() and str(f.get(k) or "").strip(): wiped.append(k)
    for k in ("emails", "phones", "social"):
        if k in bf and not (bf.get(k) or []) and (f.get(k) or []): wiped.append(k)
    # round 15: only refuse a MASS wipe (empty form after reload). Clearing one field on purpose is fine.
    # r15int: "whole form" = the page's collect() shape (it always sends all of these keys). A partial API edit that names
    # six fields and clears two on purpose (e2e_r10) is not a form wipe and is allowed.
    _form = all(k in bf for k in ("first_name", "last_name", "title", "company", "website", "address", "emails", "phones", "social"))
    if len(wiped) >= 2 and _form and body.get("_allow_blank") is not True:   # a whole form sent (the page), not a deliberate partial API edit
        return JSONResponse({"error": "This save would clear " + ", ".join(LABEL.get(k, k) for k in wiped) + " (the form was probably still empty when Save was clicked). Nothing was saved: wait for the card to finish loading, then try again.",
                             "need": "blank_wipe", "fields": wiped}, 409)
    if (st and st != c["status"] or body.get("merge_into")):
        if c["status"] != "pending" and not body.get("confirm_redecide"):
            return JSONResponse({"error": f"This card was already {c['status']} by {c.get('reviewer') or 'someone'}. Change it?",
                                 "need": "confirm_redecide", "previous": {"status": c["status"], "reviewer": c.get("reviewer")}}, 409)
    if st == "approved" and not body.get("merge_into"):   # EVERY approval (new or re-sent on an approved card) is checked
        refused = approval_check(c, f2, body, changes)
        if refused is not None: return refused
    if body.get("keep_apart") or body.get("dup_resolution") == "keep_both":
        cs_, metas_ = _active()
        strong = [x["card_id"] for x in dupes(c | {"fields": f2}, cs_, metas_)["queue"] if x["strong"] and x["card_id"] in _req_ids(c, f2, cs_, metas_, body)]
        if strong:
            return JSONResponse({"error": f"Card #{strong[0]} is the same photo, or the same email/phone in the same batch: that's a duplicate scan, "
                                          "not a different person. Merge or reject one of them.", "need": "true_duplicate", "other": strong[0]}, 409)
    if body.get("merge_into") and str(body["merge_into"]).strip() == str(cid):   # round 11 (part-timer r4 CRITICAL)
        return JSONResponse({"error": f"Card #{cid} can't be merged into itself. Open the OTHER card (the duplicate) and merge it into #{cid}.", "need": "merge_self"}, 422)
    merge_tgt = store.get(int(body["merge_into"])) if body.get("merge_into") else None
    if body.get("merge_into") and not merge_tgt: return JSONResponse({"error": "Card to merge into was not found.", "need": "merge_missing"}, 422)
    label = ({"approved": "Approve", "rejected": "Reject", "pending": "Move to pending"}.get(st, "Edit") + f" card #{cid}")
    if merge_tgt: label = f"Merge card #{cid} into #{merge_tgt['id']}"
    elif body.get("crm_action") and not st: label = f"MC Trade choice on card #{cid}"
    elif body.get("dup_resolution") and not st: label = f"Keep-both choice on card #{cid}"
    # round 14 (skeptic r12): a save that changes nothing makes no undo entry
    _noop = (not changes and (st is None or st == c["status"]) and not merge_tgt and body.get("note", c.get("note")) == c.get("note")
             and not any(body.get(k_) for k_ in ("crm_action", "dup_resolution", "keep_apart", "override_reason")))
    if not _noop: snapshot([cid] + ([merge_tgt["id"]] if merge_tgt else []), user, label)

    f = f2; note = body.get("note", c.get("note"))
    if changes:
        src = sources(cid)
        for k in changes: src[k] = "edited:" + rv
        set_meta(cid, field_sources=json.dumps(src))
    if body.get("crm_action") in ("update_existing", "create_new"):
        set_meta(cid, crm_action=body["crm_action"])   # (update_existing is refused earlier unless an admin switched it on)
        log(cid, rv, "mc_trade_choice", detail=body["crm_action"])   # manager-r8 L-r8-5: this call sat inside the comment
    if body.get("keep_apart") or body.get("dup_resolution") == "keep_both":
        cs_, metas_ = _active(); ids = _keep_ids(c, f2, cs_, metas_, body)
        set_meta(cid, kept_apart=json.dumps(sorted(_kept(meta(cid)) | set(ids))), dup_resolution="keep_both")
        log(cid, rv, "duplicate_kept_both", detail={"cards": ids})
    if merge_tgt:
        tf = merge_tgt["fields"]; filled = {}; replaced = {}
        for k in ("first_name", "last_name", "title", "company", "website", "address", "department"):
            pk = merge_pick(tf, f, k)
            if pk == "src":
                if tf.get(k): replaced[k] = tf[k]
                filled[k] = f[k]; tf[k] = f[k]
        for k in ("emails", "social"):
            add = [x for x in f.get(k, []) if x not in tf.get(k, [])]
            if add and k == "emails":   # round 9 (part-timer r3): a misread email is REPLACED by the valid look-alike, not kept beside it
                keep_, rep_ = email_replacements(tf, add, f)
                # round 11 (coordinator r4 N1): a near-copy of an email the target keeps is a misread, not a second address
                add = [a_ for a_ in add if any(a_ == n_ for _, n_ in rep_) or not email_is_misread_copy(a_, keep_, tf, f)]
                add = [a_ for a_ in add if any(a_ == n_ for _, n_ in rep_) or not email_fails_check(a_, tf, f)]   # round 12 (coordinator r4 #3)
                if rep_:
                    replaced["emails"] = [o_ for o_, _ in rep_]
                    sc_ = (f.get("confidence") or {}).get("emails")
                    if sc_ is not None: tf["confidence"] = dict(tf.get("confidence") or {}, emails=sc_)
                tf["emails"] = keep_
            if add: tf[k] = tf.get(k, []) + add; filled[k] = add
        title_note = ""
        if f.get("title") and tf.get("title") and merge_pick(tf, f, "title") == "tgt" and f["title"].lower() not in tf["title"].lower():
            title_note = f"Also titled: {f['title']}"   # round 10: the other title is kept in the note, not lost
        nums = {_digits(p["number"]) for p in tf.get("phones", [])}
        # round 9 (coordinator r3 N1): a truncated copy of a number already there ("555-0165" vs "(330) 555-0165") is not added
        addp = [p for p in f.get("phones", []) if _digits(p["number"]) not in nums and not any(n_.endswith(_digits(p["number"])) for n_ in nums if _digits(p["number"]))
                and not payload_problems({"phones": [p]}) and _phone_ok(p)]   # round 10 (coordinator r3 6): a truncated number is never added
        if addp:
            # round 14 (coordinator r6 #3): the full number REPLACES a truncated copy on the kept card ("555-0165" -> "(330) 555-0165")
            full = [_digits(p["number"]) for p in addp]
            keep_p = [q for q in tf.get("phones", []) if not (len(_digits(q["number"])) >= 7 and any(d_ != _digits(q["number"]) and d_.endswith(_digits(q["number"])) for d_ in full))]
            tf["phones"] = keep_p + addp; filled["phones"] = addp
        dn = (body.get("note") if body.get("note") is not None else c.get("note") or "").strip()
        if title_note and title_note not in dn: dn = (dn + " | " + title_note).strip(" |")
        if dn and dn not in (merge_tgt.get("note") or ""):
            tn = ((merge_tgt.get("note") or "") + f" | From #{cid}: {dn}").strip(" |")
            with db() as conn: conn.execute("UPDATE cards SET note=? WHERE id=?", (tn, merge_tgt["id"]))
            filled["note"] = dn
        for k_ in ("confirmed_ok", "confirmed_meta", "confirmed_by"):   # round 23: a merged-in value is never 'confirmed'
            if isinstance(tf.get(k_), dict): tf[k_] = {x: y for x, y in tf[k_].items() if x not in filled and x not in replaced}
        store.update(merge_tgt["id"], fields=tf); log(merge_tgt["id"], rv, "merged_from", detail={"card": cid, "added": filled} | ({"replaced": replaced} if replaced else {}))
        sb, tb = meta(cid).get("back_image"), meta(merge_tgt["id"]).get("back_image")
        if sb and not tb:   # carry the back photo over with the back's details
            set_meta(merge_tgt["id"], back_image=sb); set_meta(cid, back_image=None); log(merge_tgt["id"], rv, "back_added", detail={"filled": [], "from_card": cid})
        if merge_tgt["status"] == "approved": _recheck_approved(merge_tgt["id"], tf, rv, f"details merged from #{cid}")
        if filled and meta(merge_tgt["id"]).get("exported"):   # target already went out: it must be exported again
            set_meta(merge_tgt["id"], reexport=time.time()); log(merge_tgt["id"], rv, "reexport_needed", detail={"why": f"details merged from #{cid}"})
        st = "rejected"; note = f"Duplicate of #{merge_tgt['id']} (details merged)"; set_meta(cid, dup_resolution=f"merged_into:{merge_tgt['id']}")
    if st == "approved" and not merge_tgt and STALE_DUP.search(note or ""):   # re-approved after a merge: the note is no longer true
        note = STALE_DUP.sub("", note).strip(" |"); set_meta(cid, dup_resolution=None)
    store.update(cid, fields=f, status=st, reviewer=rv if st else c.get("reviewer"), note=note)
    if st in ("approved", "rejected") and meta(cid).get("ai_status") in ("queued", "checking"):   # part-timer r2: cancel cleanly, running or not
        AI_WAIT.pop(cid, None); set_meta(cid, ai_status="skipped", ai_detail=json.dumps({"note": "the card was decided before the AI check finished (check cancelled)"}))
    if st == "approved":   # every approval past a cross-batch look-alike leaves a confirm row (also via 'none are the same person')
        cs_x, metas_x = _active(); xb = [x for x in _cross_batch(c | {"fields": f}, f, cs_x, metas_x) if {"same email", "same phone"} & set(x["why"])]
        ka_ = {int(x) for x in body["keep_apart"] if str(x).isdigit()} if isinstance(body.get("keep_apart"), list) else set()
        xb_ = [x["card_id"] for x in xb] if body.get("confirm_cross_batch") else [x["card_id"] for x in xb if x["card_id"] in ka_ | _kept(meta(cid) or {})]
        if xb_:
            log(cid, rv, "cross_batch_confirmed", detail={"note": "approved although an approved look-alike exists in another batch",
                                                          "cards": xb_, "via": "confirm" if body.get("confirm_cross_batch") else "none are the same person"})
    if st == "approved":
        try: save_correction(cid, f)
        except Exception as e: print("correction capture failed:", e)
        errs_now = validate(f); why = (body.get("override_reason") or "").strip()
        if not why and not changes and c["status"] == "approved" and meta(cid).get("override") and errs_now: pass   # re-sent, nothing changed: keep the reason
        else: set_meta(cid, override=json.dumps({"reason": why, "problems": list(errs_now.values()), "by": rv}) if errs_now and why else None)
    elif st: set_meta(cid, override=None)
    note_changed = "note" in body and (note or "") != (c.get("note") or "")
    if (changes or note_changed) and st in (None, "approved") and c["status"] == "approved" and meta(cid).get("exported"):   # skeptic R7-5, R8-3 (note too)
        set_meta(cid, reexport=time.time()); log(cid, rv, "reexport_needed", detail={"why": "edited after export"})
    moved = _recheck_approved(cid, f, rv, "edited after approval") if changes and not st and c["status"] == "approved" else False
    if not st and (note or "") != (c.get("note") or ""):
        with db() as conn: conn.execute("UPDATE cards SET note=? WHERE id=?", (note, cid))
    if (note or "") != (c.get("note") or "") and not merge_tgt and "note" in body:
        changes = dict(changes); changes["note"] = {"from": c.get("note") or "", "to": note or ""}
    if changes: log(cid, rv, "edited", detail=changes)   # every edit has a history row (AI accepts too: from -> to)
    if st and st != c["status"]:
        log(cid, rv, "decision", c["status"], st, {"override": body.get("override_reason")} if body.get("override_reason") else None)
    if not internal: _ai_settle(cid, saved=True)
    out = card(cid)   # (audit 2026-10 P2: a never-firing "stale after save" check was removed; the check under WRITE_LOCK above is the real one)
    if not st and changes: out["save_problems"] = validate(f) | hard_errors(f)   # saved, but tell the person what still blocks approval
    if moved: out["notice"] = "This approved card now has problems, so it was moved back to pending: " + "; ".join(validate(f).values())
    return out

STALE_DUP = re.compile(r"\s*\|?\s*Duplicate of #\d+ \(details merged\)")
def approval_check(c, f2, body, changes=None):
    """The one validator for approving a card. Returns a JSONResponse refusing it, or None."""
    cid = c["id"]
    hard = hard_errors(f2)
    if hard:   # list every problem at once; the hard ones can't be overridden
        all_e = validate(f2) | hard
        return JSONResponse({"error": "Some values can't be approved even with a reason: " + "; ".join(all_e.values()), "need": "fix",
                             "errors": all_e, "hard": list(hard)}, 422)
    errs = validate(f2)
    kept_override = c["status"] == "approved" and meta(cid).get("override") and not changes
    if errs and body.get("_reason_bad"):
        return JSONResponse({"error": body["_reason_bad"], "need": "reason", "errors": {"override_reason": body["_reason_bad"]}}, 422)
    if errs and not (body.get("override_reason") or "").strip() and not kept_override:
        return JSONResponse({"error": "Please fix: " + "; ".join(errs.values()), "need": "fix_or_override", "errors": errs}, 422)
    cs, metas = _active()
    if body.get("dup_resolution") == "keep_both" or body.get("keep_apart"):
        metas.setdefault(cid, {})["kept_apart"] = json.dumps(sorted(_kept(metas.get(cid) or {}) | set(_keep_ids(c, f2, cs, metas, body))))
    if body.get("crm_action"): metas.setdefault(cid, {})["crm_action"] = body["crm_action"]
    d = dupes(c | {"fields": f2, "status": "approved"}, cs, metas)
    appr = [x for x in d["open"] if x["card_id"] != cid and x["blocking"] and (store.get(x["card_id"]) or {}).get("status") == "approved"]
    if appr:
        x = appr[0]
        how = "Merge this card into it, or reject this card." if x.get("strong") else "Use the choices in the orange box: merge into that card, or mark them as different people."
        return JSONResponse({"error": f"Card #{x['card_id']} for what looks like the same person is already approved. {how}",
                             "need": "resolve_duplicate", "other": x["card_id"], "strong": bool(x.get("strong"))}, 409)
    # round 7: approved cards in OTHER batches with the same email or the same phone (any format; skeptic R7-4) need an explicit
    # confirm. A same-photo match alone only warns (it is shown in the box; newcomer r7 F2). Kept-apart pairs were already decided.
    kept_ = _kept(metas.get(cid) or {})
    ka_ = {int(x) for x in body["keep_apart"] if str(x).isdigit()} if isinstance(body.get("keep_apart"), list) else set()
    other = [] if (metas.get(cid) or {}).get("dup_resolution") == "keep_both" else [x for x in _cross_batch(c, f2, cs, metas) if {"same email", "same phone"} & set(x["why"]) and x["card_id"] not in kept_ | ka_]
    if other and not body.get("confirm_cross_batch"):   # skeptic R8-1: keep_apart only covers the cards it names
        x = other[0]; ex_ = any(o["exported"] for o in other)
        lst = ", ".join(f"#{o['card_id']} ({', '.join(o['why'])}{', exported' if o['exported'] else ''})" for o in other)
        return JSONResponse({"error": f"Approved cards in another batch look like the same person: {lst}"
                             + ". Approving this one too may send the same person to MC Trade twice.", "need": "confirm_cross_batch",
                             "other": x["card_id"], "others": [o["card_id"] for o in other], "exported": bool(ex_)}, 409)
    if d["crm"] and not d["crm_action"]:
        return JSONResponse({"error": f"{d['crm'][0]['name']} may already be in MC Trade.", "need": "crm_choice", "match": d["crm"][0] | {"why_text": _why(d["crm"][0]["why"])}}, 409)
    return None

def _field_flagged(fl, k):
    """True when the field fails validation or has a rule-based hint (plausibility)."""
    from . import plausibility as _pl
    key = "name" if k in ("first_name", "last_name") else k
    try: hs = {x.get("field") for x in _pl.check(json.loads(json.dumps(fl)))}
    except Exception: hs = set()
    return key in hs or k in hs or key in validate(fl)
def _phone_ok(p):
    from . import mctrade_export as _mx
    d = _digits(_mx.EXT.sub("", p.get("number") or ""))
    return len(d) >= 10 or (str(p.get("number") or "").strip().startswith("+") and len(d) >= 8)

def email_replacements(tf, add, sf=None):
    """(emails kept on the target, [(misread target email, valid look-alike that replaces it)]). Same rule for the merge and its preview.
    Round 11 (part-timer r4): the target's email counts as misread when it fails a check, OR it was read with low confidence
    (< 60 %) while the other card's was read well, OR the card's website domain matches the look-alike but not it."""
    from difflib import SequenceMatcher as _SM
    keep_, rep = [], []
    ct = ((tf.get("confidence") or {}).get("emails"))
    cs = ((sf or {}).get("confidence") or {}).get("emails") if sf else None
    site = re.sub(r"^(https?://)?(www\.)?", "", (tf.get("website") or (sf or {}).get("website") or "").lower()).split("/")[0]
    dom = lambda e: e.lower().rsplit("@", 1)[-1]
    for t_ in tf.get("emails", []) or []:
        twin = next((a_ for a_ in add if _SM(None, t_.lower(), a_.lower()).ratio() >= 0.8), None)
        if not twin or _field_flagged(dict(tf, emails=[twin]), "emails"): keep_.append(t_); continue
        bad = (_field_flagged(dict(tf, emails=[t_]), "emails")
               or (ct is not None and ct < 0.6 and (cs is None or cs >= 0.8))
               or (site and dom(twin) == site and dom(t_) != site))
        if bad:
            rep.append((t_, twin)); continue
        keep_.append(t_)
    return keep_, rep

def email_fails_check(a_, tf, sf):
    """Round 12 (coordinator r4 #3): the other card's email fails validation or plausibility (checked against the merged
    card's website, name and company), so a merge never adds it."""
    ctx = dict(tf, emails=[a_], website=tf.get("website") or (sf or {}).get("website") or "")
    return _field_flagged(ctx, "emails")

def email_is_misread_copy(a_, keep_, tf, sf):
    """Round 11 (coordinator r4 N1): the other card's email is a near-copy of one the target keeps AND it is the worse read
    (fails a check, or a lower read score). Then it is not added as a second address."""
    from difflib import SequenceMatcher as _SM2
    if not any(_SM2(None, a_.lower(), t_.lower()).ratio() >= 0.8 for t_ in keep_): return False
    if _field_flagged(dict(tf, emails=[a_]), "emails"): return True
    cs = ((sf or {}).get("confidence") or {}).get("emails"); ct = (tf.get("confidence") or {}).get("emails")
    return cs is not None and ct is not None and cs < ct

def _garbled_addr(v):
    """An OCR-garbled street address: a letter o/O/l/I glued to digits ("380oEmbassy", "12l0 Main") or a number run into the word."""
    v = str(v or "")
    return bool(re.search(r"\d[oOlI](?=[A-Za-z\d])|\d[oOlI]\b|\d{2,}[A-Za-z]{4,}", v))

def merge_pick(tf, sf, k):
    """Which value a merge keeps for field k: 'src' (this card's), 'tgt' (the target's) or None (nothing to take).
    Round 8 (part-timer r2): the target's value wins unless it is empty, or it is flagged (validation / hint) and the other
    card's value is not ('Akron, OH' beats 'Akron. OH')."""
    a, b = tf.get(k), sf.get(k)
    if not b or a == b: return None
    if k == "website" and (re.match(r"^(https?://)?www(?!\.)", str(b), re.I) or not plausible_site(b, list(tf.get("emails") or []) + list(sf.get("emails") or []))):
        return None   # round 11 (coordinator r4 N1): a garbled website ("wwwsummit…") is never carried over
    t2 = dict(tf); t2[k] = b
    tf = dict(tf, confirmed_ok={}); t2["confirmed_ok"] = {}   # round 23 (mctrade-admin r22 H1): a confirmation never rides a merge
    # round 20 (coordinator r19): a garbled value never replaces a clean one ('118o' over '1180')
    if k in garbled_errors(t2) and k not in garbled_errors(tf) and a: return "tgt"
    if k in garbled_errors(t2) and not a: return None
    # round 12 (coordinator r4 #3): the other card's value is taken only when it passes validation and plausibility
    if k != "title" and _field_flagged(t2, k): return "tgt" if a else None
    if not a: return "src"
    if _field_flagged(tf, k) and not _field_flagged(t2, k): return "src"
    if k == "address" and _garbled_addr(a) and not _garbled_addr(b): return "src"   # round 14 (coordinator r6 #3): "380oEmbassy" loses to "3800 Embassy"
    # round 10 (coordinator r3 2): for the title, the fuller one wins ("VP" < "VP, Sales & Marketing"); when they say
    # different things, the target keeps its title and the other one goes into the note (see the merge code)
    if k == "title" and not _field_flagged(t2, k):
        na, nb = re.sub(r"\W+", " ", a.lower()).split(), re.sub(r"\W+", " ", b.lower()).split()
        # round 15 (coordinator r14 #5): the longer title wins only when it is a clean, verified read (QR/edited) or the
        # target's own title was hard to read; otherwise the target's (cleaner) title is kept and the other goes to the note
        if len(b) > len(a) and set(na) <= set(nb) and (len(na) == 1 and len(a) <= 4 or ((tf.get("confidence") or {}).get("title") or 1) < 0.6 or ((sf.get("confidence") or {}).get("title") or 0) >= 0.9): return "src"
    return "tgt"

@router.post("/api/cards/{cid}/merge-preview")
def merge_preview(cid: CardId, body: dict = Body(...)):
    """Read-only: what merging this card's (typed) fields into card `into` would keep, per field (same rule as the merge)."""
    t = store.get(strict_id(body.get("into") if isinstance(body, dict) else None, "into"))   # round 13: strict id
    if not t: return JSONResponse({"error": "Card to merge into was not found."}, 404)
    shape = fields_shape_problem(body.get("fields"))
    if shape: return JSONResponse({"error": shape, "need": "fix"}, 422)
    f = body.get("fields") or (store.get(cid) or {}).get("fields") or {}
    out = []
    for k in ("first_name", "last_name", "title", "company", "website", "address", "department"):
        pk = merge_pick(t["fields"], f, k)
        _sq = lambda v: re.sub(r"\s+|(?<=\w),(?=\s)", "", str(v or "").lower())
        _ws = lambda v: " ".join(str(v or "").replace(" ,", ",").split()).lower()
        if pk and t["fields"].get(k) and _ws(t["fields"].get(k)) == _ws(f.get(k)): continue   # round 13: only extra spaces / capitals differ
        if pk and t["fields"].get(k) and _sq(t["fields"].get(k)) == _sq(f.get(k)):   # round 14 (coordinator r6): words joined/split: shown, not hidden
            out.append({"field": k, "target": t["fields"].get(k) or "", "this": f.get(k) or "", "keep": "tgt", "why": "spacing", "to_note": False}); continue
        if pk: out.append({"field": k, "target": t["fields"].get(k) or "", "this": f.get(k) or "", "keep": pk,
                           # round 13 (coordinator r5 N3): the real reason the other value wins
                           "why": "fails_check" if pk == "src" and t["fields"].get(k) and _field_flagged(t["fields"], k) else ("fuller" if pk == "src" and t["fields"].get(k) else ""),
                           "to_note": k == "title" and pk == "tgt" and (f.get(k) or "").lower() not in (t["fields"].get(k) or "").lower()})
    add = [x for x in f.get("emails") or [] if x not in (t["fields"].get("emails") or [])]
    keep_, rep = email_replacements(t["fields"], add, f)   # round 11 (part-timer r4): the preview says REPLACE for a misread email
    drop = [a_ for a_ in add if not any(a_ == n_ for _, n_ in rep) and (email_is_misread_copy(a_, keep_, t["fields"], f) or email_fails_check(a_, t["fields"], f))]
    why_ = {a_.lower(): ("misread" if email_is_misread_copy(a_, keep_, t["fields"], f) and (t["fields"].get("emails") or []) else "fails_check") for a_ in drop}   # round 13 (coordinator r5 N2)
    return {"rows": out, "email_replace": [{"old": o_, "new": n_} for o_, n_ in rep], "email_drop": drop, "email_drop_why": why_}

def _cross_batch(c, f, cs, metas):
    """Approved, non-archived cards in OTHER batches sharing this card's photo, an email (case/space-insensitive) or a phone
    (digits, extension ignored). Ordered: same photo first, then by card number (the order everywhere in the UI)."""
    from . import mctrade_export as _mx
    m = metas.get(c["id"]) or {}; b = m.get("batch")
    def ph(fl): return {d[-10:] for d in (_digits(_mx.EXT.sub("", p.get("number") or "")) for p in fl.get("phones") or []) if len(d) >= 10}
    def em(fl): return {e.strip().lower() for e in fl.get("emails") or [] if (e or "").strip()}
    e0, p0, out = em(f), ph(f), []
    for o in cs:
        if o["id"] == c["id"] or o["status"] != "approved": continue
        om = metas.get(o["id"]) or {}
        if om.get("archived") or (b and om.get("batch") == b): continue
        why = []
        if m.get("sha256") and om.get("sha256") == m.get("sha256"): why.append("same photo")
        if e0 & em(o["fields"]): why.append("same email")
        if p0 & ph(o["fields"]): why.append("same phone")
        if why: out.append({"card_id": o["id"], "why": why, "exported": bool(om.get("exported"))})
    return sorted(out, key=lambda x: ("same photo" not in x["why"], x["card_id"]))

def _req_ids(c, f2, cs, metas, body):
    if body.get("keep_apart") == "all":   # "none of these are the same person": every look-alike that isn't a duplicate scan
        return {x["card_id"] for x in dupes(c | {"fields": f2}, cs, metas)["queue"] if not x["strong"]}
    if body.get("keep_apart"): return {int(x) for x in body["keep_apart"] if str(x).isdigit()}
    return {x["card_id"] for x in dupes(c | {"fields": f2}, cs, metas)["queue"]}   # legacy: all current matches

def _keep_ids(c, f2, cs, metas, body):
    q = dupes(c | {"fields": f2}, cs, metas)["queue"]; want = _req_ids(c, f2, cs, metas, body)
    return [x["card_id"] for x in q if x["card_id"] in want and not x["strong"]]

def _recheck_approved(cid, f, rv, why):
    """An approved card that was edited or merged into is checked again; if it no longer passes it goes back to pending."""
    errs = validate(f) | hard_errors(f)
    if not errs: return False
    store.update(cid, status="pending", reviewer=rv, note=(store.get(cid) or {}).get("note"))
    set_meta(cid, override=None)
    log(cid, rv, "back_to_pending", "approved", "pending", {"why": why, "problems": list(errs.values())})
    return True

# ---------------------------------------------------------------- reviewer corrections -> labelled benchmark data
CORR = os.environ.get("CORRECTIONS_DIR", paths.data("corrections") if os.environ.get("GAC_DATA_DIR") else os.path.join(os.path.dirname(__file__), "..", "bench", "corrections"))
GT_KEYS = ("first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address")
def save_correction(cid, final):
    """When a card a person edited is approved, keep (photo, approved fields) as a labelled example in bench/corrections/.
    Off with setting corrections_enabled=0. Photos here follow the same photo-retention period (see purge)."""
    if auth.get_setting("corrections_enabled") != "1": return
    src = sources(cid); edited = sorted(k for k, v in src.items() if str(v).startswith(("edited", "ai")))
    if not edited: return
    c = store.get(cid); img = c.get("image") or ""; p = os.path.join(UP, os.path.basename(img))
    if not img or not os.path.isfile(p): return
    os.makedirs(CORR, exist_ok=True)
    name = f"card{cid}_{(meta(cid).get('sha256') or uuid.uuid4().hex)[:8]}{os.path.splitext(img)[1] or '.jpg'}"
    import shutil; shutil.copyfile(p, os.path.join(CORR, name))
    gp = os.path.join(CORR, "gt.json")
    try:
        with open(gp) as fh: gt = json.load(fh)
    except (FileNotFoundError, ValueError): gt = {}
    gt = {k: v for k, v in gt.items() if not k.startswith(f"card{cid}_")}
    gt[name] = {k: final.get(k) or ([] if k in ("emails", "phones") else "") for k in GT_KEYS} | {
        "phones": [{"type": p_.get("type", "work"), "number": p_.get("number", "")} for p_ in final.get("phones") or []],
        "cat": ["correction"], "corrected_fields": edited, "saved": time.time()}
    with open(gp + ".tmp", "w") as fh: json.dump(gt, fh, indent=1)
    os.replace(gp + ".tmp", gp)

# ---------------------------------------------------------------- back of the card (optional second photo)
@router.post("/api/cards/{cid}/back")
async def add_back(cid: CardId, request: Request, image: UploadFile = File(...), confirm_other_person: str = Form("")):
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    if meta(cid).get("archived"): return _archived_409(cid)
    data = await image.read()
    if not data or len(data) > MAX_BYTES: return JSONResponse({"error": "File is empty or larger than 25 MB."}, 422)
    from starlette.concurrency import run_in_threadpool
    from . import formats
    try: data = await run_in_threadpool(formats.normalize_photo, data)
    except formats.FormatError as e: return JSONResponse({"error": str(e)}, 422)
    problem = await run_in_threadpool(_check_image, data)
    if problem: return JSONResponse({"error": problem}, 422)
    r = await run_in_threadpool(attach_back, cid, data, (".jpg" if formats.is_jpeg(data) else os.path.splitext(image.filename or "")[1].lower()), request.state.user["initials"], bool(confirm_other_person), request.state.user)
    if isinstance(r, tuple): return JSONResponse(*r)
    return r

def attach_back(cid, data, ext, initials, confirm_other_person=False, user=None):
    """Reads a back-of-card photo and fills gaps on card cid. Returns a dict, or (error_body, status) on refusal."""
    c = store.get(cid)
    # round 15 (reviewer r14): pause the AI double-check queue while this OCR runs
    BACK_BUSY.set()
    try:
        r = scan_limited(data, None, False)
    finally:
        BACK_BUSY.clear()
    f0, b0 = c["fields"], r["fields"]
    if not confirm_other_person and _other_person(f0, b0):
        who_b = f"{b0.get('first_name','')} {b0.get('last_name','')}".strip() or b0.get("company") or "someone else"
        return ({"error": f"This back photo looks like a different person's card ({who_b}), not "
                                      f"{(f0.get('first_name','') + ' ' + f0.get('last_name','')).strip() or 'this card'}. Nothing was added. "
                                      "Scan it as its own card, or confirm that it really is the back of this card.",
                             "need": "confirm_other_person", "back_name": who_b}, 409)
    name = uuid.uuid4().hex + "_back" + (ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg")
    with open(os.path.join(UP, name), "wb") as fh: fh.write(data)
    # audit 2026-10: a replaced back photo is no longer deleted here (Undo restores the old one and needs the file); it is
    # unreferenced from now on, so the retention clean-up removes it with its thumbnails as an orphan
    with WRITE_LOCK, store.tx(): return _attach_back_write(cid, c, r, name, initials, user)

from . import parser as _P
SITE_TLDS = _P.KNOWN_TLDS | set("com net org edu gov mil us io co info biz ca uk de fr it es nl be ch at au nz jp cn in br mx ie se no dk fi pl pt "
                "app dev ai tv me health law pro global group tech online site store shop church school example".split())   # audit 2026-10: one list with the parser
def plausible_site(w, emails=()):
    """Round 10 (skeptic R9-4): a website read from the back of a card is only filled in when its domain matches an email
    domain on the card, or it is a normal-looking domain with a known ending (OCR junk like 'wvw.c0m.xq' is dropped)."""
    d = re.sub(r"^[a-z]+://", "", str(w or "").strip().lower()).split("/")[0].split(":")[0]
    d = d[4:] if d.startswith("www.") else d
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d): return False
    root = ".".join(d.split(".")[-2:])
    if any((lambda ed: ed == root or ed.endswith("." + root))(str(e).lower().split("@")[-1]) for e in emails if "@" in str(e)): return True
    parts = d.split("."); name = parts[-2]
    return parts[-1] in SITE_TLDS and len(name) >= 2 and not name.isdigit() and not name.startswith("-") and not name.endswith("-")

def site_matches_email(w, emails):
    d = re.sub(r"^[a-z]+://", "", str(w or "").strip().lower()).split("/")[0]
    d = d[4:] if d.startswith("www.") else d
    root = ".".join(d.split(".")[-2:])
    return bool(root) and any((lambda ed: ed == root or ed.endswith("." + root))(str(e).lower().rsplit("@", 1)[-1]) for e in emails if "@" in str(e))

def _attach_back_write(cid, c0, r, name, initials, user):
    """Skeptic R8-2: the slow OCR runs outside the lock; the gap-fill is applied to the card AS IT IS NOW (a save made
    meanwhile is kept), unsafe OCR values are dropped, and an approved card is re-checked / flagged for re-export."""
    c = store.get(cid); f = c["fields"]; b = dict(r["fields"]); filled = {}; src = sources(cid); held = {}
    # round 11 (skeptic R10-1): only emails that are literally printed on the back are added (the parser can guess one
    # from a name + website line, e.g. st@strandline-analytics.net); a guessed one is reported, not saved
    txt_ = re.sub(r"\s+", "", (r.get("text") or "").lower())
    if b.get("emails"):
        lit = [e for e in b["emails"] if re.sub(r"\s+", "", str(e).lower()) in txt_]
        if len(lit) != len(b["emails"]): held["emails"] = [e for e in b["emails"] if e not in lit]
        b["emails"] = lit
    # round 11 (skeptic R10-4): a website from the back is filled only when it matches an email domain on the card; with
    # no email at all, a normal-looking domain printed on the back is used. Anything else is reported, not saved.
    if b.get("website") and not f.get("website"):
        em_ = list(f.get("emails") or []) + list(b.get("emails") or [])
        w_ = b["website"]
        dom_ok = plausible_site(w_, em_) and (any("@" in str(e) for e in em_) and site_matches_email(w_, em_) or not any("@" in str(e) for e in em_))
        printed = re.sub(r"^(https?://)?(www\.)?", "", str(w_).lower()).split("/")[0] in txt_
        if not (dom_ok and printed): held["website"] = w_; b.pop("website")
    for k in QR_KEYS + ("credentials", "other_address"):
        if b.get(k) and not f.get(k) and not str(src.get(k, "")).startswith("edited") and not payload_problems({k: b[k]}):
            if k == "website" and not plausible_site(b[k], list(f.get("emails") or []) + list(b.get("emails") or [])): continue   # skeptic R9-4
            f[k] = b[k]; filled[k] = b[k]; src[k] = "back"
    for k in ("emails", "phones"):
        if f.get(k) and b.get(k):
            have = {json.dumps(x, sort_keys=True) for x in f[k]}
            add = [x for x in b[k] if json.dumps(x, sort_keys=True) not in have and (k != "phones" or _digits(x["number"]) not in {_digits(y["number"]) for y in f[k]})]
            add = [x for x in add if not payload_problems({k: [x]})]
            if add: f[k] = f[k] + add; filled[k] = add; src[k] = src.get(k) or "back"
    if user: snapshot([cid], user, f"Add back of card #{cid}")
    store.update(cid, fields=f)
    if filled and c["status"] == "approved":
        if meta(cid).get("exported"): set_meta(cid, reexport=time.time()); log(cid, initials, "reexport_needed", detail={"why": "back of card added after export"})
        _recheck_approved(cid, f, initials, "back of card added after approval")
    with db() as x: x.execute("UPDATE cards SET raw_text=? WHERE id=?", ((c.get("raw_text") or "") + "\n\n--- back of card ---\n" + r["text"], cid))
    set_meta(cid, back_image=name, field_sources=json.dumps(src))
    log(cid, initials, "back_added", detail={"filled": list(filled)} | ({"not_added": held} if held else {})); _seal()
    return {"filled": list(filled), "not_added": held, "card": card(cid)}

def _other_person(f, b):
    """The back names a different person (both sides have a last name and they differ), or a different company with
    no name in common. A plain back (logo, services list) never counts as another person."""
    from . import mctrade_export as mx
    fl, bl = mx._nm(f.get("last_name")), mx._nm(b.get("last_name"))
    ff, bf = mx._nm(f.get("first_name")), mx._nm(b.get("first_name"))
    if bl and fl and bl != fl: return True
    if bf and ff and bl and bf != ff and bf[:1] != ff[:1]: return True
    return False

@router.post("/api/cards-bulk")
def bulk(request: Request, body: dict = Body(...)):
    for k_ in ("confirm_cross_batch", "confirm_redecide"):   # round 11 (skeptic R10-2): only a real true confirms ("no" is not yes)
        if k_ in body: body[k_] = body[k_] is True
    with WRITE_LOCK, store.tx():
        try: return _bulk(request, body)
        finally: _seal()
def _bulk(request, body):
    if not isinstance(body, dict): return JSONResponse({"error": "Send a JSON object."}, 422)
    """body: ids, status, versions {id: version} (round 7: required per card; a stale or missing one skips that card)."""
    st = body.get("status"); user = request.state.user; rv = user["initials"]
    if st not in ("pending", "approved", "rejected"): raise HTTPException(400, "bad status")
    raw = body.get("ids")   # round 13 (skeptic r11 R11-2): a list of strict card ids (empty = nothing to do), all valid, no repeats; else 422 and nothing changes
    if not isinstance(raw, list) or len(raw) > 5000: return JSONResponse({"error": "ids must be a list of card numbers.", "need": "bad_id"}, 422)
    ids = [strict_id(i, "ids entry") for i in raw]
    if len(set(ids)) != len(ids): return JSONResponse({"error": "ids lists a card more than once.", "need": "bad_id"}, 422)
    miss = [i for i in ids if not store.get(i)]
    if miss: return JSONResponse({"error": "These cards don't exist: " + ", ".join(f"#{i}" for i in miss[:20]), "need": "bad_id"}, 422)
    arc = [i for i in ids if meta(i).get("archived")]
    if arc: return JSONResponse({"error": "These cards are archived and can't be changed: " + ", ".join(f"#{i}" for i in arc[:20]) + ". Nothing was changed.", "need": "archived"}, 409)
    sb = body.get("batch")   # round 15 (newcomer r14 BLOCKER): a bulk action made from a one-batch queue only touches THAT batch
    if isinstance(sb, str) and sb and sb != "all":
        out_ = [i for i in ids if ((meta(i).get("batch") or "__none__") != sb)]
        if out_: return JSONResponse({"error": f"{len(out_)} selected {_s(len(out_), 'card')} are not in the batch shown ({', '.join(f'#{i}' for i in out_[:20])}). Nothing was changed: reload the queue and select again.", "need": "wrong_batch", "ids": out_}, 409)
    todo, skipped, warnings = [], [], []
    vers = body.get("versions") if isinstance(body.get("versions"), dict) else {}
    cs, metas = _active()
    for i in ids:
        c = store.get(i)
        if not c or c["status"] == st: continue
        v_ = vers.get(str(i), vers.get(i))
        if not v_ or v_ != card_version(c):
            skipped.append({"id": i, "need": "stale", "why": "changed since the list was loaded (or no version sent): reload and try again"}); continue
        if c["status"] != "pending" and not body.get("confirm_redecide"):
            skipped.append({"id": i, "why": f"already {c['status']}"}); continue
        if st == "approved":
            _e = {**validate(c["fields"]), **hard_errors(c["fields"])}   # round 14 (coordinator r6 #1): name the problem
            if _e: skipped.append({"id": i, "why": "; ".join(dict.fromkeys(_e.values()))[:300]}); continue
            ref = approval_check(c, c["fields"], {"confirm_cross_batch": True})   # cross-batch look-alikes: approved, with a warning
            if ref is not None and json.loads(ref.body).get("need") == "crm_choice" and auth.get_setting("mctrade_updates_enabled") != "1":
                # round 20 (newcomer r19): with updating switched off there is no choice to make: bulk adds the person as new
                set_meta(i, crm_action="create_new"); log(i, _who(request), "mc_trade_choice", detail="create_new")
                ref = approval_check(store.get(i), c["fields"], {"confirm_cross_batch": True})
            if ref is not None:   # say WHICH check stopped it (newcomer r6: the old reason was vague)
                need = json.loads(ref.body).get("need"); oth = json.loads(ref.body).get("other")
                skipped.append({"id": i, "need": need, "why": {"crm_choice": "MC Trade choice needed (open it: update existing or add as new)",
                                "confirm_cross_batch": f"an approved card #{oth} in another batch looks like the same person (open it to confirm)",
                                "resolve_duplicate": f"possible duplicate of approved card #{oth} (open it to merge or keep both)"}.get(need, "possible duplicate (open it)")}); continue
            d = dupes(c, cs, metas)
            if d["unresolved_queue"]:   # round 15: name WHICH cards
                bl = [x for x in d["open"] if x["blocking"]]
                skipped.append({"id": i, "need": "resolve_duplicate", "others": [x["card_id"] for x in bl], "why": "possible duplicate of " + ", ".join(f"#{x['card_id']}" + (f" {x.get('name')}" if x.get("name") else "") + f" ({', '.join(x.get('why') or [])})" for x in bl[:5]) + " (open it to merge or keep both)"}); continue
            _mi = metas.get(i) or {}
            xb = [] if _mi.get("dup_resolution") == "keep_both" else [x for x in _cross_batch(c, c["fields"], cs, metas) if x["card_id"] not in _kept(_mi)]   # round 21
            if xb: warnings.append({"id": i, "others": [x["card_id"] for x in xb],
                                    "why": "approved cards in another batch look like the same person: "
                                           + ", ".join(f"#{x['card_id']} ({_why(x['why'] + (['already exported'] if x.get('exported') else []))})" for x in xb[:10]) + (f" …and {len(xb) - 10} more" if len(xb) > 10 else "")})
        todo.append(c)
    if body.get("dry_run") is True:   # round 14 (coordinator r6): everything the ONE confirmation dialog needs, nothing changed
        return {"dry_run": True, "would_approve": [c["id"] for c in todo], "skipped": skipped, "lookalikes": warnings,
                "ai_pending": [c["id"] for c in todo if (metas.get(c["id"]) or {}).get("ai_status") in ("queued", "checking")]}
    # Round 9 (coordinator N7): ask BEFORE approving, like the single-card path. Nothing is changed until the person
    # confirms (confirm_cross_batch) or leaves those cards out (the browser re-sends without them).
    if st == "approved" and warnings and not body.get("confirm_cross_batch"):
        return JSONResponse({"error": f"{len(warnings)} of these {_s(len(warnings), 'card')} look like a person already approved in another batch. Nothing was changed yet.",
                             "need": "confirm_cross_batch", "lookalikes": warnings, "would_approve": [c["id"] for c in todo],
                             "skipped": skipped}, 409)
    if todo:
        snapshot([c["id"] for c in todo], user, f"Bulk {({'approved': 'approve', 'rejected': 'reject', 'pending': 'move to pending'})[st]} {len(todo)} {_s(len(todo), 'card')}")
        for c in todo:
            nt = c.get("note")
            if st == "approved" and STALE_DUP.search(nt or ""): nt = STALE_DUP.sub("", nt).strip(" |"); set_meta(c["id"], dup_resolution=None)
            store.update(c["id"], status=st, reviewer=rv, note=nt); log(c["id"], rv, "decision", c["status"], st, {"bulk": True})
            if st in ("approved", "rejected") and meta(c["id"]).get("ai_status") == "queued":
                AI_WAIT.pop(c["id"], None); set_meta(c["id"], ai_status="skipped", ai_detail=json.dumps({"note": "the card was decided before the AI got to it"}))
        done_ids = {c["id"] for c in todo}
        for w_ in warnings:
            if w_["id"] in done_ids: log(w_["id"], rv, "cross_batch_confirmed", detail={"note": "bulk approve although " + w_["why"], "cards": w_["others"], "via": "bulk"})
    done_ids = {c["id"] for c in todo}
    return {"updated": [c["id"] for c in todo], "skipped": skipped, "warnings": [w_ for w_ in warnings if w_["id"] in done_ids]}

@router.post("/api/batches/archive")
def archive(request: Request, body: dict = Body(...)):
    user = request.state.user; rv = user["initials"]; b = body.get("batch")
    if user["role"] != "admin": return JSONResponse({"error": "Only an admin can archive a batch (see the privacy note)."}, 403)
    if not isinstance(b, str) or not b: return JSONResponse({"error": "Choose the batch to archive (batch: its name)."}, 422)   # fuzz 2026-10: batch: {} was a 500
    if b == "__all__":
        if user["role"] != "admin": return JSONResponse({"error": "Only an admin can clear all data."}, 403)
        if body.get("confirm") != "CLEAR": return JSONResponse({"error": "Type CLEAR (capital letters) to confirm archiving everything."}, 422)
        ids = [c["id"] for c in store.all_(None)]
    elif b == "__none__": ids = [r[0] for r in db().execute("SELECT c.id FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id WHERE m.batch IS NULL")]
    else: ids = [r[0] for r in db().execute("SELECT card_id FROM card_meta WHERE batch=?", (b,))]
    with WRITE_LOCK, store.tx():   # audit 2026-10 P1: like every other card change (snapshot, write, seal as one step)
        ids = [i for i in ids if not meta(i).get("archived")]
        try:
            if ids: snapshot(ids, user, f"Archive {len(ids)} {_s(len(ids), 'card')}")
            for i in ids: set_meta(i, archived=1); log(i, rv, "archived", detail={"batch": b})
        finally: _seal()
    if b == "__all__": auth.alog(user["username"], f"Clear all test data: archived {len(ids)} {_s(len(ids), 'card')} (nothing deleted; Undo restores them): " + ", ".join(f"#{i}" for i in ids[:200]))
    return {"archived": len(ids)}

# ---------------------------------------------------------------- undo
@router.get("/api/undo")
def undo_peek(request: Request):
    r = db().execute("SELECT id,ts,label FROM actions WHERE user_id=? AND undone IS NULL ORDER BY id DESC LIMIT 1", (request.state.user["id"],)).fetchone()
    return dict(r) if r else {}

@router.post("/api/undo")
def undo(request: Request, body: dict = Body(default={})):
    user = request.state.user
    if not isinstance(body, dict): return JSONResponse({"error": "Send a JSON object."}, 422)
    if "id" in body:   # round 11 (skeptic R10-3): a given id must be a real action number; it never falls back to "latest"
        aid = body["id"]
        try: aid = strict_id(aid, "id")   # round 13: same strict rule (2**63 used to give 500)
        except BadId: aid = None
        if aid is None:
            return JSONResponse({"error": "id must be the number of an action from your undo list."}, 422)
    q = "SELECT * FROM actions WHERE user_id=? AND undone IS NULL" + (" AND id=?" if "id" in body else "") + " ORDER BY id DESC LIMIT 1"
    a = db().execute(q, (user["id"], aid) if "id" in body else (user["id"],)).fetchone()
    if not a: return JSONResponse({"error": "Nothing to undo."}, 404)
    if time.time() - a["ts"] > 24 * 3600: return JSONResponse({"error": "That action is more than a day old and can't be undone here."}, 409)
    snap = json.loads(a["snapshot"])
    # Round 9 (skeptic R9-1): undo only what THAT action changed. Each value is put back only while it still holds
    # what the action wrote; a value someone changed afterwards is kept and reported as a conflict.
    CARD_COLS = ("status", "raw_text", "reviewer", "note", "decided")
    conflicts = {}; restored = {}
    with WRITE_LOCK:
        if any("after" not in s_ for s_ in snap):
            return JSONResponse({"error": "This action can't be undone safely. Change the card by hand.", "need": "legacy_action"}, 409)
        with db() as c:
            for s_ in snap:
                b_c, b_m = s_["card"], s_["meta"] or {}; a_c, a_m = s_["after"]["card"] or {}, s_["after"]["meta"] or {}
                n_c, n_m = _row_state(b_c["id"]); n_c = n_c or {}; n_m = n_m or {}
                cid_ = b_c["id"]; conf_ = []; done_ = []
                bf, af, nf = (json.loads(x.get("fields") or "{}") for x in (b_c, a_c, n_c))
                newf = dict(nf)
                for k in set(bf) | set(af):
                    if bf.get(k) == af.get(k): continue
                    if nf.get(k) == af.get(k):
                        if k in bf: newf[k] = bf[k]
                        else: newf.pop(k, None)
                        done_.append(k)
                    else: conf_.append(k)
                sets = {"fields": json.dumps(newf)}
                for k in CARD_COLS:
                    if b_c.get(k) == a_c.get(k): continue
                    if n_c.get(k) == a_c.get(k): sets[k] = b_c.get(k); done_.append(k)
                    else: conf_.append(k)
                c.execute("UPDATE cards SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?", list(sets.values()) + [cid_])
                msets = {}
                for k in META_COLS:
                    if k == "card_id" or b_m.get(k) == a_m.get(k): continue
                    if n_m.get(k) == a_m.get(k): msets[k] = b_m.get(k)
                    else: conf_.append("meta:" + k)
                if msets:
                    if not n_m: c.execute("INSERT OR IGNORE INTO card_meta(card_id) VALUES(?)", (cid_,))
                    c.execute("UPDATE card_meta SET " + ",".join(f"{k}=?" for k in msets) + " WHERE card_id=?", list(msets.values()) + [cid_])
                c.execute("INSERT INTO card_history(card_id,ts,reviewer,action,detail) VALUES(?,?,?,?,?)",
                          (cid_, time.time(), user["initials"], "undo", json.dumps({"undid": a["label"], "restored": done_, "kept_later_changes": conf_})))
                restored[cid_] = done_
                if conf_: conflicts[cid_] = conf_
            c.execute("UPDATE actions SET undone=? WHERE id=?", (time.time(), a["id"]))
    moved = [s["card"]["id"] for s in snap if s["card"]["status"] == "approved" and (store.get(s["card"]["id"]) or {}).get("status") == "approved"
             and _recheck_approved(s["card"]["id"], store.get(s["card"]["id"])["fields"], user["initials"], "undo restored an approval that no longer passes the checks")]
    out = {"undone": a["label"], "cards": [s["card"]["id"] for s in snap], "moved_to_pending": moved, "restored": restored}
    if conflicts:
        out["kept_later_changes"] = conflicts
        out["notice"] = "Some values were changed after that action, so they were kept: " + "; ".join(f"#{i}: {', '.join(v)}" for i, v in conflicts.items())
    return out

def recover():
    """After a crash or restart: re-queue uploads that were accepted but not yet read (same job id, so an open browser
    keeps tracking them), and reset AI checks that were in flight."""
    n = 0
    for fn in os.listdir(DONE):
        p = os.path.join(DONE, fn)
        if time.time() - os.path.getmtime(p) > 86400: os.remove(p)
    for fn in sorted(os.listdir(INBOX), key=lambda x: os.path.getmtime(os.path.join(INBOX, x))):
        if not fn.endswith(".json"): continue
        jid = fn[:-5]
        try:
            with open(os.path.join(INBOX, fn)) as fh: args = json.load(fh)
            bp = os.path.join(INBOX, jid + (".pdf" if args.get("kind") == "pdf" else ".bin"))
            if not os.path.isfile(bp): raise FileNotFoundError(bp)
        except Exception:
            _inbox_clear(jid); continue
        if os.path.exists(os.path.join(INBOX, jid + ".reading")):
            # round 20 (skeptic C1): the server died while reading this file. Re-queueing it could crash it again (a
            # crash loop), so it is set aside as failed with a calm message instead.
            j = {"id": jid, "kind": args.get("kind"), "state": "error", "file": args.get("fname"), "batch": args.get("batch") or "",
                 "error": CALM_POISON, "finished": time.time()}
            # audit 2026-10 P1: the crash may have come AFTER the card was saved (history, AI check, enrich). Then the
            # file was read fine: report the job as done with that card instead of blaming the file.
            r_ = args.get("sha") and args.get("kind") != "pdf" and db().execute(
                "SELECT m.card_id FROM card_meta m JOIN cards c ON c.id=m.card_id WHERE m.sha256=? AND COALESCE(m.batch,'')=? AND c.created>=? ORDER BY m.card_id DESC LIMIT 1",
                (args["sha"], args.get("batch") or "", os.path.getmtime(os.path.join(INBOX, fn)) - 5)).fetchone()
            if r_: j |= {"state": "done", "error": None, "card": {"id": r_[0]}}
            _done_record(jid, j); _inbox_clear(jid); print("set aside a file that was being read when the server stopped:", jid)
            continue
        if args.get("kind") == "pdf":
            with JLOCK: JOBS[jid] = {"id": jid, "kind": "pdf", "state": "queued", "file": args["fname"], "batch": args["batch"] or "",
                                     "created": time.time(), "who": args.get("who"), "pages": args.get("pages"), "page": 0, "children": [], "recovered": True}
            SPLIT_POOL.submit(_split_pdf, jid); n += 1; continue
        with JLOCK: JOBS[jid] = {"id": jid, "state": "queued", "file": args["fname"], "batch": args["batch"] or "", "sha": args["sha"],
                                 "created": time.time(), "ahead": n, "recovered": True, "who": args.get("who")}   # round 20 (M1): keep the owner
        POOL.submit(_run, jid, None, **args); n += 1
    try:
        for r in db().execute("SELECT card_id FROM card_meta WHERE ai_status IN ('queued','checking')").fetchall():
            set_meta(r[0], ai_status=None); maybe_ai_check(r[0])
    except Exception as e: print("ai recovery error:", e)
    if n: print(f"recovered {n} unfinished upload(s)")
    return n

# ---------------------------------------------------------------- background workers (round 6)
# Importing app.ui (a script, a test, an offline check) must NOT touch data/inbox or run jobs: in round 5 an offline import
# re-queued the live inbox and lost an upload. Workers start only from the served app's startup (app/main.py lifespan),
# and only in the ONE process that holds an exclusive file lock on the data dir.
WORKERS = {"started": False, "lock_fd": None, "why": "not started (module imported, not served)"}
LOCK_PATH = os.path.join(DATA, ".workers.lock")
def _take_lock(path=None):
    """Non-blocking exclusive flock on data/.workers.lock -> open fd, or None if another process holds it."""
    path = path or LOCK_PATH
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if not paths.try_lock(fd): os.close(fd); return None
    if os.name == "nt": os.lseek(fd, 1, 0); os.write(fd, f" {os.getpid()}\n".encode()); return fd   # byte 0 is the locked byte on Windows
    os.ftruncate(fd, 0); os.write(fd, f"{os.getpid()}\n".encode()); return fd
def start_workers():
    """Start upload recovery, the AI double-check worker and the retention loop once. Returns True if this process runs them."""
    if WORKERS["started"]: return True
    fd = _take_lock()
    if fd is None:
        try: other = open(LOCK_PATH).read().strip()
        except Exception: other = "?"
        WORKERS["why"] = f"another process (pid {other}) already runs the workers on this data dir"
        print("\n" + "!" * 78 + "\nWORKERS NOT STARTED: " + WORKERS["why"] + ".\nUploads to THIS server are read, but crash recovery,"
              " AI double-checks and retention run only in the other process.\n" + "!" * 78 + "\n", flush=True)
        return False
    WORKERS.update(started=True, lock_fd=fd, why="running")
    threading.Thread(target=_ai_worker, daemon=True, name="ai-check").start()
    threading.Thread(target=_retention_loop, daemon=True, name="retention").start()
    threading.Thread(target=recover, daemon=True, name="recover").start()
    try: apply_tombstones()
    except Exception as e: print("re-applying removal requests failed:", e, flush=True)
    try:   # round 8: nightly backup (02:30, 7 kept); GAC_BACKUP=0 turns it off
        from . import backup as _bk; _bk.start()
    except Exception as e: print("backup scheduler not started:", e)
    return True

# ---------------------------------------------------------------- audit 2026-10 P2: modules split out of this file
# They are imported last (they use this module's names as U.<name> at call time) and their names are re-exported here,
# so `from app import ui; ui.<name>` keeps working everywhere.
from . import pages as _pages  # noqa: E402,F401  (module handle, e.g. for tests that patch it)
from .pages import (  # noqa: E402,F401
    PLACEHOLDER, THUMBS, THUMB_SIZES, _thumb, app_alias, drop_thumbs, legacy_card, legacy_card_post, legacy_csv,
    legacy_home, legacy_queue, legacy_scan, legacy_sync, legacy_vcf, legacy_xlsx, privacy, remove_photo,
    strip_admin, ui)
from . import privacy as _privacy  # noqa: E402,F401  (module handle, e.g. for tests that patch it)
from .privacy import (  # noqa: E402,F401
    JOB_KEEP_S, TOMBSTONES, _add_tombstone, _hard_delete, _redact, _retention_loop, _tombstones, _unmerge, _vals,
    apply_tombstones, hard_delete, prune_memory, purge, purge_preview, run_purge)
from . import exporting as _exporting  # noqa: E402,F401  (module handle, e.g. for tests that patch it)
from .exporting import (  # noqa: E402,F401
    ADMIN_ONLY_FILTERS, AUDIT, COMPANION, EXPORT_BUSY, FILTERS, HANDLE, MORE, MT, NUMBERISH, PLAINNUM,
    REVIEWER_FILTERS, SUSPECT_WEB, XCOLS, _EXL, _bname, _do_export_real, _export_claim, _export_release,
    _export_set, _filter_refused, _fname, _note, _slug, _stale_export, _wdom, _when, build_export, comp_name,
    crm_look, do_export, exact_email_profile, export_again, export_check, export_companion, export_history,
    export_versions, ids3, plural, readme_totals, safe_cell, same_names, strict_profile_id, website_warnings)
from . import audit_log as _audit_log  # noqa: E402,F401  (module handle, e.g. for tests that patch it)
from .audit_log import (  # noqa: E402,F401
    NAMES, _audit_text, _fmtv, audit)
from . import admin_files as _admin_files  # noqa: E402,F401  (module handle, e.g. for tests that patch it)
from .admin_files import (  # noqa: E402,F401
    TPL_BAKS, _check_contacts, _check_template, _last_admin_change, _refused, _rotate_bak, _safe_fname,
    contacts_info, contacts_version, export_dryrun, file_version, mctrade_source, remove_contacts, revert_template,
    stale_admin, template_info, template_version, upload_contacts, upload_template)
