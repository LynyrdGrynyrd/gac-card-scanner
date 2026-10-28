"""Exports: CSV, vCard and the MC Trade Excel, sign-off versions, export history and re-download. Split out of app/ui.py (audit 2026-10 P2)."""
import io, os, re, csv, json, time, uuid, hashlib, datetime, threading
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from . import store, export, mctrade_sync, auth, crm_source
from . import ui as U

# ---------------------------------------------------------------- exports (reviewer, duplicate guard, history)
XCOLS = ["IndFirstName", "IndLastName", "IndTitle", "OrgName", "IndEmail", "IndEmail2", "IndPhone", "IndCellPhone", "IndFax",
         "WebAddress", "Address", "AffCode1"]
MORE = ["Credentials", "Department", "OtherAddress", "AllEmails", "AllPhones", "Note"]
AUDIT = ["ScanCardID", "ReviewedBy", "DecidedAt", "Batch", "MCTradeAction", "Check"]
FILTERS = {"approved_new": "approved, not yet exported", "approved": "all approved", "all": "all cards", "pending": "pending only", "rejected": "rejected only"}

def _export_set(status, batch=""):
    cs, metas = U._active()
    mm = lambda c: metas.get(c["id"]) or {}
    if status == "approved_new": sel = [c for c in cs if c["status"] == "approved" and (not mm(c).get("exported") or mm(c).get("reexport"))]
    else: sel = [c for c in cs if status == "all" or c["status"] == status]
    if batch: sel = [c for c in sel if (mm(c).get("batch") or "__none__") == batch]
    probs = []
    if batch:   # a batch export is only blocked by look-alikes inside the same batch; other people's batches don't block it
        inb = {c["id"] for c in cs if (mm(c).get("batch") or "__none__") == batch}
    for c in sel:   # all batches: look-alikes anywhere in the active queue (pending ones too)
        d = U.dupes(c, cs, metas)
        if batch: d["open"] = [x for x in d["open"] if x["card_id"] in inb]
        # round 15 (reviewer r14): rejected look-alikes stay as review hints but never block an export
        clash = [x["card_id"] for x in d["open"] if (store.get(x["card_id"]) or {}).get("status") != "rejected"]
        if clash: probs.append({"id": c["id"], "with": clash, "strong": [x["card_id"] for x in d["open"] if x.get("strong") and (store.get(x["card_id"]) or {}).get("status") != "rejected"],
                                "batch": mm(c).get("batch_label") or mm(c).get("batch") or ""})
    return sel, metas, probs

ADMIN_ONLY_FILTERS = ("all", "pending")
REVIEWER_FILTERS = ("approved_new", "approved")      # anything else (rejected, any free text) is admin-only
def _filter_refused(status, user):
    if user["role"] == "admin": return status not in FILTERS and status != "rejected"
    return status not in REVIEWER_FILTERS

def batch_owner(batch):
    """Initials of whoever scanned the batch's first card ('' if unknown)."""
    r = U.db().execute("""SELECT h.reviewer FROM card_meta m JOIN card_history h ON h.card_id=m.card_id AND h.action='scanned'
        WHERE m.batch=? ORDER BY h.id LIMIT 1""", (batch,)).fetchone()
    return str(r[0] or "") if r else ""
BATCH_MSG = "You can export only your own batch. Ask an admin to export other batches or all batches."
def _batch_refused(batch, user):
    """v0.4.2 #1 (mctrade-admin M1): enforced here, not only in the page. A reviewer exports only a batch they started;
    another person's batch, cards with no batch and all batches are admin-only."""
    if user.get("role") == "admin": return False
    from . import demo
    if demo.enabled(): return False   # public demo: every export is a preview of fictional cards
    if not batch or batch == "__none__": return True
    oid = U.batch_owner_id(batch)   # v0.4.3 #8: by user id
    return oid != user.get("id") if oid is not None else batch_owner(batch) != user.get("initials")

PLAINNUM = re.compile(r"[+-]\d+(?:\.\d+)?"); HANDLE = re.compile(r"@[A-Za-z0-9_.]{1,40}(?:\s+@[A-Za-z0-9_.]{1,40})*")

NUMBERISH = re.compile(r"[+-][\d\s().-]*\d[\d\s().-]*(?:\s*(?:x|ext\.?|extension|#)\s*\d+)?", re.I)
def safe_cell(v):
    """CSV formula-injection guard. A leading ' is added ONLY when a spreadsheet would evaluate the text: it starts with
    = or @ or TAB/CR, or with + / - followed by something that is not a plain phone number or number
    ('+1 330-555-0181' and '-5' stay as they are; '+SUM(1)' and '-2+3' get the '). XLSX cells are always typed as text,
    so the Excel file needs (and gets) no prefix at all."""
    if not isinstance(v, str) or not v: return v
    if HANDLE.fullmatch(v): return " " + v      # '@gachamber' (social handle): a leading space keeps it text without a stray '
    if v[0] in "=@\t\r": return "'" + v
    if v[0] in "+-":
        if PLAINNUM.fullmatch(v): return v          # '-5', '+3.5': a number either way, nothing changes
        if NUMBERISH.fullmatch(v) and re.search(r"[\s()]", v) and not re.search(r"\d\s+[+-]\s*\d|\s[+-]\s", v): return v   # '+1 330-555-0181' stays; '+1 -1' is arithmetic
        return "'" + v                              # '+1-330-555-0182', '+1-1', '+SUM(1)': Excel WOULD calculate it
    return v

def _when(t): return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else ""
def _slug(s, n=40): return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:n].strip("-")
def _bname(label):
    """Batch name for file names. Round 8: names are stored as typed; labels from before round 8 had ' · <date/time> · <initials>'
    appended by the page, and only that old suffix is dropped."""
    return re.sub(r"(?: · [^·]*\d{1,2}:\d{2}\s*[AP]M)(?: · [A-Z]{1,4})?$", "", label or "")
def _fname(kind, status, ext, batch_label=""):
    tag = {"approved_new": "new", "approved": "approved", "all": "all", "pending": "pending"}.get(status, _slug(status))
    if batch_label: tag += "-" + _slug(_bname(batch_label), 28)
    kind = {"contacts-for-MC-Trade": "MCTrade"}.get(kind, kind)
    fn = f"GAC-{kind}-{tag}-{datetime.datetime.now().strftime('%Y-%m-%d_%H%M')}.{ext}"
    # round 15 (manager r14 M-1): two exports never share a file name ("-2", "-3" ... when the name was used before)
    try:
        used = {r[0] for r in U.db().execute("SELECT filename FROM exports WHERE filename LIKE ?", (fn.rsplit(".", 1)[0] + "%",))}
    except Exception: used = set()
    n = 2; base, dot = fn.rsplit(".", 1)
    while fn in used: fn = f"{base}-{n}.{dot}"; n += 1
    return fn
def plural(n, one, many=None): return f"{n} {one if n == 1 else (many or one + 's')}"
def ids3(ids, k=3):
    """Round 20: '#4, #9, #12 and 7 more' (never a wall of ids)."""
    ids = list(ids); h = ", ".join("#" + str(i) for i in ids[:k])
    return h + (f" and {len(ids) - k} more" if len(ids) > k else "")

def same_names(sel, contacts_from=None):
    """Round 15 (mctrade r14 M1): rows of one export that share a first + last name with another row of the export or with
    an MC Trade contact (real export only). MC Trade's import may treat same first+last as one duplicate: review first."""
    by = {}
    for c in sel:
        n = U._nm(c["fields"])
        if n and " " in n: by.setdefault(n, []).append(c["id"])
    out = [{"name": n.title(), "cards": ids, "with": "export"} for n, ids in by.items() if len(ids) > 1]
    if contacts_from is not None:   # round 20: the MC Trade match looks at every exported card, the 'twice' check at file rows
        by = {}
        for c in contacts_from:
            n = U._nm(c["fields"])
            if n and " " in n: by.setdefault(n, []).append(c["id"])
    rows = crm_source.real()
    if rows:
        have = {}
        for r in rows:
            n = re.sub(r"\s+", " ", (r.get("name") or f"{r.get('first_name','')} {r.get('last_name','')}").strip().lower())
            if n: have.setdefault(n, []).append(str(r.get("profile_id") or r.get("id") or ""))
        for n, ids in by.items():
            if n in have: out.append({"name": n.title(), "cards": ids, "with": "contacts", "profiles": have[n][:5]})
    return out

def _check_ids(sel, metas, status):
    res = build_export("xlsx", sel, metas, status, "summary", "", preview=True)
    sm = res[4] if len(res) > 4 else {}
    dz = {str(k): v for k, v in (sm.get("decisions") or {}).items()}
    return set(sm.get("check_ids") or []) | {x[0] for x in (sm.get("_view") or {}).get("left") or [] if dz.get(str(x[0])) == "review"}

@U.router.get("/api/export/check")
def export_check(request: Request, status: str = "approved_new", batch: str = ""):
    if _filter_refused(status, request.state.user):
        return JSONResponse({"error": "Only an admin can export pending, rejected or all cards.", "admin_only": True}, 403)
    if _batch_refused(batch, request.state.user): return JSONResponse({"error": BATCH_MSG, "admin_only": True}, 403)
    sel, metas, probs = _export_set(status, batch)
    flagged = [c["id"] for c in sel if (metas.get(c["id"]) or {}).get("override") or U.validate(c["fields"])]
    if sel and len(sel) <= 500:   # v0.4.2 #4: ONE source: the page line uses the sheet's own "to check" list
        try: flagged = summary_counts(sel, metas, status)["check_ids"]
        except Exception: pass
    ok_batches = []
    if probs and not batch:   # all batches is blocked: say which single batches can be exported right now
        for b in sorted({(metas.get(c["id"]) or {}).get("batch") or "__none__" for c in sel}):
            s2, m2, p2 = _export_set(status, b)
            if s2 and not p2: ok_batches.append({"batch": b, "label": (m2.get(s2[0]["id"]) or {}).get("batch_label") or b, "count": len(s2)})
    cs_, metas_ = U._active()
    pend = [{"id": c["id"], "name": f"{c['fields'].get('first_name','')} {c['fields'].get('last_name','')}".strip() or "(no name)"}
            for c in cs_ if c["status"] == "pending" and (not batch or ((metas_.get(c["id"]) or {}).get("batch") or "__none__") == batch)]
    return {"count": len(sel), "duplicates": probs, "flagged": flagged, "same_names": same_names(sel), "ok_batches": ok_batches, "pending": pend[:200], "pending_count": len(pend),
            "cards": [{"id": c["id"], "name": f"{c['fields'].get('first_name','')} {c['fields'].get('last_name','')}".strip()} for c in sel[:300]],
            "admin_only": _filter_refused(status, request.state.user), "versions": export_versions(sel)}

def strict_profile_id(c, existing=None):
    """MC Trade Profile ID for an 'update existing' card, ONLY when certain (round 6, R3-8): the card's email matches the
    profile exactly, or the exact same name + the same phone with a high score. Two different certain candidates, or
    anything weaker (e.g. a similar name + a shared office line) -> None, and the card goes to review."""
    sure = []
    existing = existing if existing is not None else crm_source.real()
    if existing is None: return None      # round 7: never a Profile ID from SAMPLE data
    for m_ in U._crm_index(existing).match(c["fields"]):
        exact_name = mctrade_sync._nname(m_["name"]) == mctrade_sync._nname(f"{c['fields'].get('first_name','')} {c['fields'].get('last_name','')}")
        if "email exact" in m_["why"] or (exact_name and "phone exact" in m_["why"] and m_["score"] >= 0.5): sure.append(m_["profile_id"])
    sure = list(dict.fromkeys(sure))
    return sure[0] if len(sure) == 1 else None
def exact_email_profile(c, existing=None):
    """Profile ID of an existing MC Trade profile with exactly this card's email (create-new cards: would duplicate it)."""
    existing = existing if existing is not None else crm_source.real()
    if existing is None: return None
    hits = list(dict.fromkeys(m_["profile_id"] for m_ in U._crm_index(existing).match(c["fields"]) if "email exact" in m_["why"]))
    return hits[0] if hits else None

def crm_look(c, existing=None):
    """Round 8: everything classify() needs about one card vs the REAL MC Trade contacts (see mctrade_export.classify)."""
    existing = existing if existing is not None else crm_source.real()
    if existing is None: return {}
    f = c["fields"]; nm = mctrade_sync._nname(f"{f.get('first_name','')} {f.get('last_name','')}")
    byid = U._crm_index(existing).byid
    cem = {e.strip().lower() for e in f.get("emails") or [] if (e or "").strip()}
    email, strong, name = [], [], []
    for m_ in U._crm_index(existing).match(f):
        pid = str(m_["profile_id"]); exact = bool(nm) and mctrade_sync._nname(m_["name"]) == nm
        if "email exact" in m_["why"]: email.append(pid); strong.append(pid)
        elif exact and ("phone exact" in m_["why"] or any(w.startswith("org~") for w in m_["why"])): strong.append(pid)
        elif exact: name.append(pid)
    email, strong, name = (list(dict.fromkeys(x)) for x in (email, strong, name))
    sure = None if len(email) > 1 else strict_profile_id(c, existing)
    pe = ((byid.get(str(sure)) or {}).get("email") or "").strip().lower() if sure else ""
    return {"email": email, "strong": strong, "name": name, "sure": sure,
            # round 11 (mctrade-r7 F1): the UPDATES row writes the card's FIRST email; any difference from the profile's email
            # holds the card back (a match on the card's second email would otherwise overwrite the profile email)
            "email_differs": bool(sure and pe and (f.get("emails") or [""])[0].strip().lower() not in ("", pe))}

def _note(c):
    """Note as exported: a stale 'Duplicate of #N (details merged)' on a card that is no longer rejected is dropped."""
    n = c.get("note") or ""
    return U.STALE_DUP.sub("", n).strip(" |") if c.get("status") != "rejected" else n
def build_export(kind, sel, metas, status, who, batch_label="", preview=False):
    def flag(c):
        m = metas.get(c["id"]) or {}; ov = U._ov(m); errs = U.validate(c["fields"]); out = []
        if ov: out.append(f"APPROVED ANYWAY by {ov.get('by')}: {ov.get('reason')}")
        if errs: out.append("CHECK: " + "; ".join(errs.values()))
        out += U.confirmed_lines(c["fields"])   # round 22: hard-check overrides are visible to the importer
        xb = U.db().execute("SELECT detail FROM card_history WHERE card_id=? AND action='cross_batch_confirmed' ORDER BY id DESC LIMIT 1", (c["id"],)).fetchone()
        if xb:
            try: oth = (json.loads(xb[0] or "{}") or {}).get("cards") or []
            except Exception: oth = []
            # v0.4.2 #3 (data-manager): look-alikes later answered 'Different' are not a double-import risk
            kp_ = set(U._kept(m)); oth = [o for o in oth if o not in kp_ and c["id"] not in set(U._kept(metas.get(o) or {}))] if oth else oth
            if xb_ok(c, oth): out.append("Also in another batch: approved over a look-alike" + (" (" + ", ".join(f"#{o}" for o in oth) + ")" if oth else "") + ": check for a double import")
        return " | ".join(out)
    def xb_ok(c, oth):
        m = metas.get(c["id"]) or {}
        if oth: return True
        return not (U._kept(m) or m.get("dup_resolution") == "keep_both")
    def aud(c):
        m = metas.get(c["id"]) or {}
        return [c["id"], c.get("reviewer") or "", _when(c.get("decided")), m.get("batch_label") or "",
                {"update_existing": "update existing", "create_new": "create new"}.get(m.get("crm_action"), "create new (no MC Trade match)" if c["status"] == "approved" else ""), flag(c)]   # round 13 (newcomer r11 #6): never blank for an exported new profile
    def more(c):
        f = c["fields"]
        return [f.get("credentials") or "", f.get("department") or "", f.get("other_address") or "",
                "; ".join(f.get("emails") or []), "; ".join(f"{p.get('type')}: {p.get('number')}" for p in f.get("phones") or []), _note(c)]
    if kind == "csv":
        b = io.StringIO(); w = csv.writer(b)
        w.writerow(export.COLS + ["credentials", "department", "other_address", "all_emails", "all_phones", "note",
                                  "reviewed_by", "decided_at", "batch", "mc_trade_action", "needs_attention"])
        for c in sel:
            r = export._flat(c); r["social"] = r["social"]; a = aud(c); w.writerow([safe_cell(x) for x in [r[k] for k in export.COLS] + more(c) + a[1:]])
        return ("\ufeff" + b.getvalue()).encode(), "text/csv", _fname("contacts", status, "csv", batch_label)   # BOM: Excel opens UTF-8 correctly
    if kind == "vcf":
        return export.to_vcard(sel).encode(), "text/vcard", _fname("contacts", status, "vcf", batch_label)
    if kind == "xlsx":   # MC Trade import file: template columns only, one sheet, one row per person (see mctrade_export.py)
        from openpyxl import Workbook
        from . import mctrade_export as mx
        aff = auth.get_setting("mctrade_affcode") or ""; style = auth.get_setting("phone_format") or "gac"
        def _kept_pair(a, b_): return b_ in U._kept(metas.get(a) or {}) or a in U._kept(metas.get(b_) or {})
        _real = crm_source.real(); _hint_rows, _ = crm_source.rows_for_hints()
        def _hint(c):
            m_ = U._crm_index(_hint_rows).match(c["fields"])
            return f"{m_[0]['name']} ({m_[0]['organization']})" if m_ else None
        res = mx.build(sel, aff, style, U.hard_errors, kept=_kept_pair, confirmed=lambda f_: list(U.valid_confirmations(f_)), crm_look=lambda c: crm_look(c, _real),
                       crm_real=_real is not None, crm_hint=_hint, updates_on=auth.get_setting("mctrade_updates_enabled") == "1",
                       action=lambda c: (metas.get(c["id"]) or {}).get("crm_action") or "")
        hdr, source, rows, left, upd = res["headers"], res["source"], res["rows"], res["left"], res["updates"]
        def _book(rws):
            wb = Workbook(); ws = wb.active; ws.title = "Sheet1"; ws.append(hdr)
            for c, r_ in rws: ws.append(mx.cells(hdr, r_))
            for rw in ws.iter_rows():
                for cell in rw:
                    if isinstance(cell.value, str): cell.data_type = "s"   # plain text, never a formula; no ' prefix needed
            b_ = io.BytesIO(); wb.save(b_); return b_.getvalue()
        body_x = _book(rows)
        fn = _fname("contacts-for-MC-Trade", status, "xlsx", batch_label)
        rfn = ("PREVIEW-" if preview else "") + fn   # round 10 (coordinator r3 3c): the READ-ME names the files as they are saved
        # companion files (not for import): every non-template column + rows left out, and the READ ME notes
        e = io.StringIO(); w = csv.writer(e)
        w.writerow(["ScanCardID", "InImportFile", "Why left out", "FirstName", "LastName", "Email2", "Website", "Credentials", "Department", "OtherAddress",
                    "AllEmails", "AllPhones", "Social", "Note", "ReviewedBy", "DecidedAt", "Batch", "MCTradeAction", "Check"])
        why = {c["id"]: r for c, r in left}; updids = {c["id"] for c, _ in upd}
        cinfo = crm_source.info()
        _smp = []   # round 9 (newcomer r9 N1): cards in the new file that match a SAMPLE contact by email (SAMPLE data only)
        if not cinfo["real"]:
            _sr = crm_source.sample_rows(); _in = {x["id"] for x, _ in rows}
            _smp = [c_["id"] for c_ in sel if c_["id"] in _in and any("email exact" in m_["why"] for m_ in mctrade_sync.match(c_["fields"], _sr))]
        # v0.4.3 #4 (mctrade-admin L3): a possible MC Trade match is a note in the CSV Check column too
        _mcn = {i: "may already be in MC Trade (test list)" for i in _smp} | {i: "may already be in MC Trade" for i in res["possible"] if i not in _smp}
        def aud(c, _a=aud):
            a_ = _a(c)
            if c["id"] in _mcn and _mcn[c["id"]] not in a_[-1]: a_[-1] = " | ".join(x for x in (a_[-1], _mcn[c["id"]][0].upper() + _mcn[c["id"]][1:]) if x)
            return a_
        for c in sel:
            f_ = c["fields"]; a = aud(c); em = f_.get("emails") or []
            inimp = "updates file" if c["id"] in updids else "no" if c["id"] in why else "yes"
            w.writerow([safe_cell(x) for x in [c["id"], inimp, why.get(c["id"], ""), mx.clean(f_.get("first_name")), mx.clean(f_.get("last_name")),
                        em[1] if len(em) > 1 else "", mx.clean(f_.get("website"))] + [mx.clean(x) for x in more(c)[:5]] + [" ".join(f_.get("social") or []), mx.clean(_note(c))] + a[1:]])
        nflag = sum(1 for c in sel if aud(c)[-1])
        _flagged = {c["id"] for c in sel if aud(c)[-1]}
        xb_ids = {}
        for c in sel:   # cards approved over a cross-batch look-alike warning (coordinator r1 #6): risk of a double import
            for h in U.history(c["id"]):
                if h["action"] == "cross_batch_confirmed":
                    d_ = h.get("detail") if isinstance(h.get("detail"), dict) else {}
                    xb_ids[c["id"]] = d_.get("cards") or []
            # v0.4.1 #5 (datamanager #4): 'Different' reaches the export: look-alikes marked different are not a double-import risk
            kp_ = set(U._kept(metas.get(c["id"]) or {}))
            if c["id"] in xb_ids:
                xb_ids[c["id"]] = [o for o in xb_ids[c["id"]] if o not in kp_ and c["id"] not in set(U._kept(metas.get(o) or {}))]
                if not xb_ids[c["id"]] or (metas.get(c["id"]) or {}).get("dup_resolution") == "keep_both" and not kp_: xb_ids.pop(c["id"])
        tpl_real = source == "GAC template file"
        cnt_ = mx.counts(res["decisions"])   # round 22 (mctrade-admin r21 H1): ONE source for every count (README, sign-off, dry run)
        conf_ = [(c["id"], ln) for c in sel for ln in U.confirmed_lines(c["fields"])]
        ovr_ = [c["id"] for c in sel if U._ov(metas.get(c["id"]) or {})]
        # v0.3.2 (newcomer v0.3.1): short and plain; empty/zero lines left out; ONE warning line per card
        _warn = {}
        for i in _smp: _warn.setdefault(i, []).append("may already be in MC Trade (test list)")
        for i in res["possible"]:
            if i not in _smp: _warn.setdefault(i, []).append("may already be in MC Trade")
        for i in xb_ids: _warn.setdefault(i, []).append("may match someone approved in another batch")
        _wl = [f"Check #{i}: {' and '.join(v)}." for i, v in sorted(_warn.items())]
        _named = set(_warn) | {i for i, _ in conf_[:20]} | set(ovr_) | {i for i, _w, _y in website_warnings(sel, metas, rows + upd, res.get("merged"))} \
            | {k for k, v in res["decisions"].items() if v[0] == mx.REVIEW}
        _more = _flagged - _named
        # v0.4.4 #3 (data-manager M1, reviewer): ONE 'To check' set: the Check-line cards + the cards a person must decide (NEEDS REVIEW).
        # Screen, Save dialog, READ-ME Totals, dry run and Preview all use it.
        _chk0 = set(_warn) | {i for i, _ in conf_} | set(ovr_) | _flagged | {i for i, _w, _y in website_warnings(sel, metas, rows + upd, res.get("merged"))}
        _tc = _chk0 | {int(k) for k, v in res["decisions"].items() if v[0] == mx.REVIEW}
        # v0.4.5 #8 (data-manager: Why said only "see the READ-ME"): the real reasons, so the summary works on its own
        _why = {i: list(v) for i, v in _warn.items()}
        for i, ln in conf_: _why.setdefault(i, []).append(str(ln).rstrip("."))
        for i in ovr_: _why.setdefault(i, []).append("approved with a reason despite a warning")
        for i, w_, y_ in website_warnings(sel, metas, rows + upd, res.get("merged")): _why.setdefault(i, []).append(f"website {w_}: {y_}")
        for k, v in res["decisions"].items():
            if v[0] == mx.REVIEW: _why.setdefault(int(k), []).append("needs a decision: " + str(v[1] or "possible match in MC Trade").rstrip("."))
        for c in sel:
            if c["id"] in _flagged and c["id"] not in _why: _why[c["id"]] = [str(aud(c)[-1]).rstrip(".")]
        _has_web = any(mx.canonical(h) in ("Website", "IndWebsite") for h in hdr if h)
        readme = "\n".join([
            *(["*** PREVIEW ONLY: DO NOT IMPORT. These files were not marked as exported; use the real export for MC Trade. ***"] if preview else []),
            "GAC Card Scanner: MC Trade import file",
            readme_totals(cnt_, len(_tc)),
            ("Before importing: read the “Check” lines. " if _tc else "") + "An import can't be undone." + (" Test 2 rows first." if len(rows) + len(upd) > 2 else "")
            + (" Import new contacts and updates separately." if upd else ""),
            f"Created {_when(time.time())} by {who}" + (f" · batch {batch_label}" if batch_label else "") + f" · {plural(len(sel), 'card')}.",
            f"Import this file only: {rfn}" + (f" (and {comp_name(rfn, '-UPDATES.xlsx')} for updates)" if upd else "") + f". Not for import: {comp_name(rfn, '-SUMMARY.xlsx')}, the CSV and this READ-ME.",
            *[f"Check: #{i} {ln}" for i, ln in conf_[:20]],
            (f"… and {len(conf_) - 20} more confirmed values in the CSV." if len(conf_) > 20 else ""),
            (f"Check: {plural(len(ovr_), 'card')} approved anyway (see the CSV)." if ovr_ else ""),
            ("Compared with MC Trade contacts: " + cinfo["source"] + "." if cinfo["real"] else
             "Test MC Trade list: no real contacts file is loaded, so no MC Trade numbers were assigned."),
            (f"Updates: {comp_name(rfn, '-UPDATES.xlsx')} ({plural(len(upd), 'row')}). MemberSince is left blank so it can't overwrite a member's real date."
             if upd else ""),
            (f"Template columns the scanner leaves blank: {', '.join(res['unknown_cols'])}." if res["unknown_cols"] else
             "" if tpl_real else "Columns not checked against MC Trade's template."),
            (f"Not in this template (CSV only): {', '.join(res['unfilled'])}." if res["unfilled"] else ""),
            f"Affiliation code: '{aff}' (it must already exist in MC Trade).",
            ("" if _has_web else "Websites: this template has no website column, so websites are only in the CSV."),
            (f"Left out: {plural(cnt_[mx.LEFT], 'card')} (combined with another row, or to fix first). The CSV says why." if cnt_[mx.LEFT] else ""),
            # round 20 (mctrade-admin r19 F1): 'in this export N times' only when 2+ ROWS of the import files share the name
            *[f"Check, same name: {g['name']} is on {plural(len(g['cards']), 'card')} {ids3(g['cards'])}"
              + (f" ({plural(len(g['cards']), 'row')} in this export)" if g["with"] == "export" else f" and already in MC Trade (profile {', '.join(g.get('profiles') or [])})")
              + ". MC Trade may merge people with the same name: check they are different, or merge them." for g in same_names([c for c, _ in rows] + [c for c, _ in upd], contacts_from=sel)],
            (f"Check, to review: {cnt_[mx.REVIEW]} {U._s(cnt_[mx.REVIEW], 'card')} ({ids3([k for k, v in res['decisions'].items() if v[0] == mx.REVIEW])}) "
             "are in neither file: a person must decide (the CSV says why)." if cnt_[mx.REVIEW] else ""),
            *_wl[:10],
            (f"… and {len(_wl) - 10} more cards to check (see the CSV)." if len(_wl) > 10 else ""),
            *(["Check, marked different but identical: " + x for x in res["conflicts"]] if len(res["conflicts"]) <= 3 else
              [f"Check, marked different but identical: {len(res['conflicts'])} cards, each exported once (the CSV says which)."]),
            *[f"Check website: #{i} has {w} ({why}). Compare it with the photo." for i, w, why in website_warnings(sel, metas, rows + upd, res.get("merged"))],
            # v0.4.2 #4 (coordinator L): plain wording; the same cards are in the sheet's "To check" count
            # v0.4.3 #8 (data-manager/newcomer): "More notes" counts only cards NOT already named on a Check line above
            (f"More notes: {plural(len(_more), 'other card')} {'has' if len(_more) == 1 else 'have'} a note in the CSV “Check” column. Read them before importing." if _more else ""),
            "Second emails and phones, notes and reviewer are in the CSV, not in the import file."])
        readme = "\n".join(x for x in readme.split("\n") if x.strip())
        _seen = set(); readme = "\n".join(x for x in readme.split("\n") if not x.strip() or not (x in _seen or _seen.add(x)))   # round 24: each warning once
        comp = {"extra.csv": ("\ufeff" + e.getvalue()).encode(), "readme.txt": readme.encode()}
        if upd: comp["updates.xlsx"] = _book(upd)
        # v0.4.4 #8 (data-manager): the summary sheet is back, as its own workbook (the import file stays one template sheet)
        _sw = Workbook(); _ss = _sw.active; _ss.title = "Summary"
        for rw_ in (["GAC Card Scanner export summary (not for import)"], ["Batch", batch_label or "All batches"], ["Cards", len(sel)],
                    ["New contacts", cnt_[mx.NEW]], ["Updates", cnt_[mx.UPDATE]], ["To check", len(_tc)], ["Left out", cnt_[mx.LEFT]], [],
                    ["Card", "Why to check it"], *[[f"#{i}", "; ".join(dict.fromkeys(_why.get(i, []))) or (_mcn.get(i) or "a note in the CSV Check column")] for i in sorted(_tc)]):
            _ss.append([safe_cell(x) if isinstance(x, str) else x for x in rw_])
        for rw in _ss.iter_rows():
            for cell in rw:
                if isinstance(cell.value, str): cell.data_type = "s"
        _sb = io.BytesIO(); _sw.save(_sb); comp["summary.xlsx"] = _sb.getvalue()
        # round 9 (mctrade-r6): what each update row would overwrite in MC Trade, old value next to new
        _byid = {str(r_["profile_id"]): r_ for r_ in (crm_source.real() or [])}; _udiff = []
        _inhdr = {mx.canonical(h) for h in hdr if h}   # round 13 (mctrade-r8 R2): only columns that are really in the file (no phantom IndWebsite)
        for c_, r_ in upd:
            old_ = _byid.get(str(r_.get("ProfileID"))) or {}; f_ = c_["fields"]
            pairs = [("Name", f"{old_.get('first_name', '')} {old_.get('last_name', '')}".strip(), f"{f_.get('first_name', '')} {f_.get('last_name', '')}".strip()),
                     ("Organization", old_.get("organization", ""), f_.get("company", "")),
                     ("Email", old_.get("email", ""), (f_.get("emails") or [""])[0]),
                     ("Phone", old_.get("phone", ""), ((f_.get("phones") or [{}])[0] or {}).get("number", ""))]
            _udiff.append({"card": c_["id"], "profile_id": str(r_.get("ProfileID")),
                           "fields": [{"field": k, "old": o or "", "new": n or "", "changes": U._digits(o) != U._digits(n) if k == "Phone" else (o or "").strip().lower() != (n or "").strip().lower()} for k, o, n in pairs]
                           # round 11 (mctrade-r7 F2): EVERY other column the UPDATES row writes is listed too. The contacts export
                           # doesn't hold MC Trade's current value for these, so it is shown as unknown (old=None).
                           + [{"field": h_, "old": None, "new": str(v_), "changes": None}
                              for h_, v_ in r_.items() if v_ not in (None, "") and mx.canonical(h_) in _inhdr and h_ not in ("ProfileID", "MemberSince", "OrgInd", "IndFirstName", "IndLastName", "OrgName", "IndEmail", "IndPhone")]})
        summ = {"mc_possible": {str(k): v for k, v in sorted(_mcn.items())}, "check_ids": sorted(_chk0), "to_check_ids": sorted(_tc),   # v0.4.1 #4: the cards behind the READ-ME "Check" lines
                "new_rows": len(rows), "update_rows": len(upd), "cards": len(sel), "left_out": len(left), "sample_email_matches": _smp,
                "left_ids": [c["id"] for c, _ in left if c["id"] not in {x["id"] for x, _ in rows}],
                "review": res["review"], "possible": res["possible"], "crm_real": cinfo["real"],
                "decisions": {str(k): v[0] for k, v in res["decisions"].items()}, "counts": mx.counts(res["decisions"]),
                # v0.4.2 #3 (reviewer Med): the preview says which new rows may already be in MC Trade, instead of a plain "new profile"
                "_view": {"headers": [h for h in hdr], "rows": [mx.cells(hdr, r_) for _, r_ in rows], "row_notes": ["; ".join(_warn.get(c["id"], [])) for c, _ in rows], "row_ids": [c["id"] for c, _ in rows], "updates": [mx.cells(hdr, r_) for _, r_ in upd], "update_diff": _udiff,
                          "left": [[c["id"], why_] for c, why_ in left], "source_text": f"Columns: {source}. MC Trade contacts: {cinfo['source']}.",
                          "warnings": [f"#{i}: approved although approved cards {', '.join('#' + str(o) for o in os_)} in another batch look like the same person" for i, os_ in xb_ids.items()] + [f"#{i}: check the website {w} ({why})" for i, w, why in website_warnings(sel, metas, rows + upd, res.get("merged"))]}}
        return body_x, MT["xlsx"], fn, comp, summ
    raise HTTPException(404)

def readme_totals(cnt, to_check=None):
    """v0.4.4 #3: 'to check' is the same number as on the screen and in the Save dialog (was '0 to review' next to Check lines)."""
    from . import mctrade_export as mx
    tc = cnt[mx.REVIEW] if to_check is None else to_check
    return (f"Totals: {cnt[mx.NEW]} new · {cnt[mx.UPDATE]} {U._s(cnt[mx.UPDATE], 'update')} · {tc} to check · "
            f"{cnt[mx.LEFT]} left out.")

def comp_name(fn, suf):
    """Companion file name. The UPDATES file never says '-new-' (it holds updates of EXISTING profiles, not new ones)."""
    base = os.path.splitext(fn)[0]
    if suf == "-UPDATES.xlsx": base = base.replace("-MCTrade-new-", "-MCTrade-")
    return base + suf

# round 15 (second-round bots): only ONE real export of a batch (or of overlapping cards) runs at a time. A second one
# started while the first is still building gets 409 'export_busy' instead of exporting (and marking) the same cards twice.
EXPORT_BUSY = {}; _EXL = threading.Lock()

def _export_claim(key, ids, who):
    with _EXL:
        for k, (ids2, w2, t2) in EXPORT_BUSY.items():
            if k == key or (ids & ids2): return {"by": w2, "since": t2}
        EXPORT_BUSY[key] = (ids, who, time.time()); return None
def _export_release(key):
    with _EXL: EXPORT_BUSY.pop(key, None)
def export_versions(sel):
    """Round 16 (manager/coordinator r15 H1): what an export sign-off was reviewed against: the template, the contacts file
    and the exact cards (id + version). The page sends these back with the real export; if any changed meanwhile the
    export is refused (409 'stale_review') instead of building a file nobody looked at."""
    cv = hashlib.sha256(",".join(f"{c['id']}:{U.card_version(c)}" for c in sorted(sel, key=lambda c: c["id"])).encode()).hexdigest()[:12]
    return {"template": U.template_version(), "contacts": U.contacts_version(), "cards": cv}
SUSPECT_WEB = re.compile(r"phish|login|verify|secure-?|account|update-?info|signin|wallet|bit\.ly|tinyurl|xn--|^\d+\.\d+\.\d+\.\d+$", re.I)
def _wdom(w):
    w = re.sub(r"^[a-z]+://", "", str(w or "").strip().lower()).split("/")[0].split(":")[0]
    return w[4:] if w.startswith("www.") else w
def website_warnings(sel, metas, rows=None, merged=None):
    """Round 16 (mctrade r15 M2): a website that does not match the card's email domain(s) AND either came in through a
    merge or looks like a phishing / login / short-link / IP address domain. -> [(card id, website, why)] for the READ-ME."""
    merged_into = {}
    for cid_, m_ in (metas or {}).items():
        d_ = str((m_ or {}).get("dup_resolution") or "")
        if d_.startswith("merged_into:"):
            try: merged_into.setdefault(int(d_.split(":", 1)[1]), []).append(cid_)
            except ValueError: pass
    for tgt, ids_ in (merged or {}).items():   # round 17 (mctrade r16): rows merged at export time count as merges too
        for x_ in ids_:
            if x_ not in merged_into.get(tgt, []): merged_into.setdefault(tgt, []).append(x_)
    out = []
    # round 17 (mctrade r16): with the export's rows, only cards that ARE in an import file are listed, under the exported
    # row's card id, with the website the row really carries (it may have come from a merged-away card)
    items = [(c, str(r_.get("Website") or r_.get("IndWebsite") or "")) for c, r_ in rows] if rows is not None else [(c, c["fields"].get("website") or "") for c in sel]
    for c, w in items:
        w = (w or "").strip(); d = _wdom(w)
        if not d: continue
        eds = {e.split("@")[-1].strip().lower() for e in c["fields"].get("emails") or [] if "@" in e}
        if any(d == e or d.endswith("." + e) or e.endswith("." + d) for e in eds): continue
        why = []
        if SUSPECT_WEB.search(d): why.append("the domain looks like a phishing, login or short-link address")
        if c["id"] in merged_into: why.append("it came in through a merge (from #" + ", #".join(str(x) for x in merged_into[c["id"]]) + ")")
        if why: out.append((c["id"], w, "; ".join(why) + (f"; it doesn't match the email domain {', '.join(sorted(eds))}" if eds else "")))
    return out
@U.router.get("/api/export/summary")
def export_summary(request: Request, status: str = "approved_new", batch: str = ""):
    """v0.4 #5: the counts for the export sheet ("12 new, 1 to check"), from the same server re-check the export runs.
    Counts only: no names, no file, nothing marked as exported."""
    if _filter_refused(status, request.state.user):
        return JSONResponse({"error": "Only an admin can export pending, rejected or all cards.", "admin_only": True}, 403)
    if _batch_refused(batch, request.state.user): return JSONResponse({"error": BATCH_MSG, "admin_only": True}, 403)
    sel, metas, probs = _export_set(status, batch)
    return {"blocked": bool(probs)} | summary_counts(sel, metas, status)

def summary_counts(sel, metas, status):
    """v0.4.2 #4: the one count source for the Export page line, the sheet, the README and the CSV Check column."""
    out = {"count": len(sel), "new": 0, "updated": 0, "to_check": 0, "left_out": 0, "need_decision": 0, "check_ids": []}
    if sel:
        res = build_export("xlsx", sel, metas, status, "summary", "", preview=True)
        sm = res[4] if len(res) > 4 else {}
        view = sm.get("_view") or {}
        # v0.4.1 #4 (mctrade-admin H1): the view's decisions have STRING keys ('647'); the left-out ids are numbers
        dz = {str(k): v for k, v in (sm.get("decisions") or view.get("decisions") or {}).items()}; left = view.get("left") or []
        rv = {x[0] for x in left if dz.get(str(x[0])) == "review"}
        chk = set(sm.get("check_ids") or [])
        out |= {"new": len(view.get("rows") or []), "updated": len(view.get("updates") or []), "to_check": len(chk | rv), "left_out": len(left) - len(rv),
                "need_decision": len(rv), "check_ids": sorted(chk | rv)}
    return out

MT = {"csv": "text/csv", "vcf": "text/vcard", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
@U.router.get("/api/export/{kind}")
def do_export(kind: str, request: Request, status: str = "approved_new", batch: str = "", preview: bool = False):
    """preview=1: build and return the file(s) but change nothing (no 'exported' marks, no history, no stored copy)."""
    if kind == "dryrun": return U.export_dryrun(request, status, batch)   # same URL family; defined at the end of this module
    if kind not in MT: raise HTTPException(404)
    from . import demo
    if demo.enabled(): preview = True   # public demo: every export (incl. the MC Trade Excel) is a dry-run preview
    if _filter_refused(status, request.state.user):
        return JSONResponse({"error": "Only an admin can export pending, rejected or all cards. Reviewers export approved cards."}, 403)
    if _batch_refused(batch, request.state.user): return JSONResponse({"error": BATCH_MSG, "admin_only": True}, 403)
    if preview and not batch and request.state.user.get("role") != "admin":   # skeptic R6-1: no all-batches contact dump for reviewers
        return JSONResponse({"error": "Choose one batch under “Batch” to preview. Only admins can preview all batches."}, 403)
    sel, metas, probs = _export_set(status, batch)
    if probs and not preview:   # a preview changes nothing, so look-alikes don't block it
        msg = ("Some cards in this batch look like the same person. Resolve them in the review screen before exporting." if batch else
               "With “All batches”, look-alikes from anyone's batch block the export. Choose your batch under “Batch”, "
               "or ask an admin to resolve the cards listed.")
        return JSONResponse({"error": msg, "duplicates": probs}, 409)
    if not sel: return JSONResponse({"error": "No cards to export."}, 404)
    user = request.state.user
    if not preview:
        seen_ = {k: request.query_params.get("seen_" + k) for k in ("template", "contacts", "cards")}
        _cl = ": cards " + ", ".join(f"#{c['id']}" for c in sel[:500])   # round 17 (manager r16 L-1): refused rows name the cards
        if not all(seen_.values()):   # round 17 (manager r16 M-1, skeptic L1): the sign-off versions are REQUIRED for a real export
            miss = [k for k, v in seen_.items() if not v]
            auth.alog(user["username"], f"refused export ({kind}, " + (f"batch {batch}" if batch else "all batches") + "): sent without the sign-off versions (" + ", ".join("seen_" + k for k in miss) + "); nothing was exported" + _cl)
            return JSONResponse({"error": "Nothing was exported: the sign-off check is missing. Export from the Export page.",
                                 "need": "version_required", "missing": ["seen_" + k for k in miss]}, 428)   # round 21 (skeptic r20 L1): no versions in a 428
        if True:
            now_ = export_versions(sel); drift = [k for k, v in seen_.items() if v and v != now_[k]]
            if drift:
                words = {"template": "the MC Trade template", "contacts": "the MC Trade contacts file", "cards": "the cards (edited, approved or rejected)"}
                auth.alog(user["username"], f"refused export ({kind}, " + (f"batch {batch}" if batch else "all batches") + "): changed since the sign-off was shown: " + ", ".join(words[k] for k in drift) + "; nothing was exported" + _cl)
                return JSONResponse({"error": "Since you opened the export sign-off, " + " and ".join(words[k] for k in drift) + " changed. Nothing was exported: check the sign-off again, then export.",
                                     "need": "stale_review", "changed": drift, "now": now_}, 409)
        xkey = "batch:" + (batch or "__all__"); busy_ = _export_claim(xkey, {c["id"] for c in sel}, user["username"])
        if busy_: auth.alog(user["username"], f"refused export ({kind}, " + (f"batch {batch}" if batch else "all batches") + f"): another export of these cards was running (started by {busy_['by']} at {time.strftime('%H:%M:%S', time.localtime(busy_['since']))}); nothing was exported" + _cl)
        if busy_: return JSONResponse({"error": f"Another export of these cards is running right now (started by {busy_['by']} at {time.strftime('%H:%M:%S', time.localtime(busy_['since']))}). Nothing was exported: wait for it to finish, then check the export history before exporting again.", "need": "export_busy"}, 409)
        try: return _do_export_real(kind, request, status, batch, sel, metas, user, seen_)
        finally: _export_release(xkey)
    blabel = next(((metas.get(c["id"]) or {}).get("batch_label") or "" for c in sel), "") if batch else ""
    res = build_export(kind, sel, metas, status, f"{user['display']} ({user['initials']})", blabel, preview=preview)
    body, mt, fn = res[:3]; extras = res[3] if len(res) > 3 else {}
    view = res[4].pop("_view", None) if len(res) > 4 else None
    summ_h = {"X-Summary": json.dumps(res[4])} if len(res) > 4 else {}
    if preview and view is not None and request.query_params.get("view") == "1":   # on-screen preview (no file)
        auth.alog(user["username"], f"viewed the PREVIEW of the MC Trade files on screen ({len(sel)} {U._s(len(sel), 'card')}" + (f", batch {blabel or batch}" if batch else ", all batches") + "): " + ", ".join(f"#{c['id']}" for c in sel[:500]))
        return view | res[4] | {"versions": export_versions(sel)}
    if preview:
        fn = "PREVIEW-" + fn
        if request.query_params.get("companion") and request.query_params["companion"] not in extras:   # mctrade-r5 F1
            return JSONResponse({"error": "There is no such file in this export (for example no update rows, so no UPDATES file)."}, 404)
        nm_ = request.query_params.get("companion") or "main file"
        auth.alog(user["username"], f"downloaded the PREVIEW {kind} ({nm_}) of {len(sel)} {U._s(len(sel), 'card')}, {FILTERS.get(status, status)}"
                  + (f", batch {blabel or batch}" if batch else ", all batches") + ": " + ", ".join(f"#{c['id']}" for c in sel[:500]) + ("…" if len(sel) > 500 else ""))
        hdrs = {"Content-Disposition": f'attachment; filename="{fn}"', "X-Card-Count": str(len(sel)), "X-Preview": "1", "X-Companions": ",".join(extras)} | summ_h
        if request.query_params.get("companion"):
            nm = request.query_params["companion"]; mt2, suf = COMPANION[nm]
            return Response(extras[nm], media_type=mt2, headers=hdrs | {"Content-Disposition": f'attachment; filename="{comp_name(fn, suf)}"'})
        return Response(body, media_type=mt, headers=hdrs)
    raise AssertionError('unreachable')

def _stale_export(kind, batch, user, sel, changed, now_, when):
    words = {"template": "the MC Trade template", "contacts": "the MC Trade contacts file", "cards": "the cards (edited, approved or rejected)"}
    auth.alog(user["username"], f"refused export ({kind}, " + (f"batch {batch}" if batch else "all batches") + f"): changed {when}: "
              + ", ".join(words[k] for k in changed) + "; nothing was exported: cards " + ", ".join(f"#{c['id']}" for c in sel[:500]))
    return JSONResponse({"error": f"{' and '.join(words[k] for k in changed).capitalize()} changed {when}. Nothing was exported: check the sign-off again, then export.",
                         "need": "stale_review", "changed": changed, "now": now_}, 409)

def _do_export_real(kind, request, status, batch, sel, metas, user, seen=None):
    # re-read the set INSIDE the claim: cards exported by a run that just finished are not exported again by accident
    sel, metas, probs = _export_set(status, batch)
    if probs: return JSONResponse({"error": "Some cards in this batch look like the same person. Resolve them in the review screen before exporting.", "duplicates": probs}, 409)
    if not sel: return JSONResponse({"error": "No cards to export (they may have just been exported by someone else: see the export history)."}, 404)
    # audit 2026-10 P0-2 / F01: the re-read set must still be exactly what the sign-off showed (a card approved in between
    # would otherwise be exported without anyone having looked at it on the sign-off)
    built_v = export_versions(sel)
    if seen:
        drift = [k for k, v in seen.items() if v and v != built_v[k]]
        if drift: return _stale_export(kind, batch, user, sel, drift, built_v, "since the sign-off was shown")
    blabel = next(((metas.get(c["id"]) or {}).get("batch_label") or "" for c in sel), "") if batch else ""
    res = build_export(kind, sel, metas, status, f"{user['display']} ({user['initials']})", blabel)
    body, mt, fn = res[:3]; extras = res[3] if len(res) > 3 else {}
    if len(res) > 4: res[4].pop("_view", None)
    summ_h = {"X-Summary": json.dumps(res[4])} if len(res) > 4 else {}
    stored = uuid.uuid4().hex + "_" + fn
    with open(os.path.join(U.EXP, stored), "wb") as fh: fh.write(body)
    for nm, data in extras.items():
        with open(os.path.join(U.EXP, stored + "." + nm), "wb") as fh: fh.write(data)
    now = time.time()
    # audit 2026-10 P0-2: mark the cards only if nothing changed while the file was being built (an edit made meanwhile
    # is not in the file; marking it exported would hide it from the next export). Checked and written under WRITE_LOCK,
    # in one transaction, so no save can slip in between; the export id comes from this insert (F02), not MAX(id).
    with U.WRITE_LOCK:
        cur = [store.get(c["id"]) for c in sel]
        now_v = export_versions([x for x in cur if x]) if all(cur) else None
        if now_v != built_v:
            for p_ in [stored] + [stored + "." + nm for nm in extras]:
                try: os.remove(os.path.join(U.EXP, p_))
                except OSError: pass
            return _stale_export(kind, batch, user, sel, [k for k in built_v if not now_v or now_v[k] != built_v[k]], now_v, "while the file was being built")
        curm = U.all_metas(); tv = U.template_version()
        with U.db() as c:
            eid = c.execute("INSERT INTO exports(ts,username,initials,kind,filter,count,filename,card_ids,stored,batch_label) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (now, user["username"], user["initials"], kind, status, len(sel), fn, json.dumps([x["id"] for x in sel]), stored, blabel if batch else "")).lastrowid
            for x in sel:
                m = curm.get(x["id"]) or {}
                c.execute("INSERT INTO card_meta(card_id) VALUES(?) ON CONFLICT(card_id) DO NOTHING", (x["id"],))
                if not m.get("exported"): c.execute("UPDATE card_meta SET exported=? WHERE card_id=?", (now, x["id"]))
                if m.get("reexport"): c.execute("UPDATE card_meta SET reexport=NULL WHERE card_id=?", (x["id"],))
                c.execute("INSERT INTO card_history(card_id,ts,reviewer,action,from_status,to_status,detail) VALUES(?,?,?,?,?,?,?)",
                          (x["id"], now, user["initials"], "exported", None, None, json.dumps({"file": fn, "template_version": tv})))
    return Response(body, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{fn}"', "X-Card-Count": str(len(sel)),
                                                  "X-Export-Id": str(eid), "X-Companions": ",".join(extras)} | summ_h)

COMPANION = {"extra.csv": ("text/csv", "-extra-columns.csv"), "readme.txt": ("text/plain", "-READ-ME.txt"),
             "updates.xlsx": (MT["xlsx"], "-UPDATES.xlsx"), "summary.xlsx": (MT["xlsx"], "-SUMMARY.xlsx")}
@U.router.get("/api/exports/{eid}/companion/{name}")
def export_companion(eid: int, name: str, request: Request):
    """Companion files of an MC Trade import file: the non-template columns + rows left out, and the READ ME notes."""
    if name not in COMPANION: raise HTTPException(404)
    r = U.db().execute("SELECT * FROM exports WHERE id=?", (eid,)).fetchone() if 0 < eid < 2**63 else None   # fuzz 2026-10: a huge id was a 500
    u = request.state.user
    if r and u["role"] != "admin" and r["username"] != u["username"]:
        return JSONResponse({"error": "Only the person who made this export (or an admin) can download it."}, 403)
    p = os.path.join(U.EXP, (r["stored"] or "") + "." + name) if r and r["stored"] else ""
    if not p or not os.path.isfile(p): return JSONResponse({"error": "No such file (it may have been removed by the retention policy)."}, 404)
    mt, suf = COMPANION[name]
    ids_ = json.loads(r["card_ids"] or "[]")
    auth.alog(u["username"], f"downloaded the {suf.strip('-')} companion of export #{eid} ({r['filename']}; cards " + ", ".join(f"#{i}" for i in ids_[:500]) + ("…" if len(ids_) > 500 else "") + ")")
    return FileResponse(p, media_type=mt, filename=comp_name(r["filename"], suf))

@U.router.get("/api/exports")
def export_history(request: Request):
    out = []; u = request.state.user
    for r in U.db().execute("SELECT * FROM exports ORDER BY id DESC LIMIT 200"):
        d = dict(r); d["available"] = bool(d["stored"]) and os.path.isfile(os.path.join(U.EXP, d["stored"])); d["filter_text"] = FILTERS.get(d["filter"], d["filter"])
        d["own"] = d["username"] == u["username"]; d["mine"] = u["role"] == "admin" or d["own"]; d["available"] = d["available"] and d["mine"]
        if not d["mine"]: continue   # v0.4.3 #8 (mctrade-admin): a reviewer sees only their own export history
        d["companions"] = [n for n in COMPANION if d["available"] and os.path.isfile(os.path.join(U.EXP, d["stored"] + "." + n))]
        d["card_ids"] = json.loads(d["card_ids"] or "[]"); d.pop("stored"); out.append(d)
    return out

@U.router.get("/api/exports/{eid}/download")
def export_again(eid: int, request: Request):
    r = U.db().execute("SELECT * FROM exports WHERE id=?", (eid,)).fetchone() if 0 < eid < 2**63 else None   # fuzz 2026-10: a huge id was a 500
    if not r or not r["stored"] or not os.path.isfile(os.path.join(U.EXP, r["stored"])):
        return JSONResponse({"error": "That file is no longer stored. Export again."}, 404)
    u = request.state.user
    if u["role"] != "admin" and r["username"] != u["username"]:
        return JSONResponse({"error": "Only the person who made this export (or an admin) can download it again."}, 403)
    ids = json.loads(r["card_ids"] or "[]")
    auth.alog(request.state.user["username"], f"re-downloaded export #{eid} ({r['filename']}; {len(ids)} {U._s(len(ids), 'card')}: " + ", ".join(f"#{i}" for i in ids[:500]) + (" …" if len(ids) > 500 else "") + ")")
    for i in ids: U.log(i, request.state.user["initials"], "redownloaded", detail={"export_id": eid, "file": r["filename"]})
    return FileResponse(os.path.join(U.EXP, r["stored"]), media_type=MT.get(r["kind"]), filename=r["filename"])
