"""Admin uploads: the MC Trade import template and contacts export, with optimistic versions, and the dry run. Split out of app/ui.py (audit 2026-10 P2)."""
import io, os, re, hashlib, html as _html
from fastapi import UploadFile, File, Request
from fastapi.responses import Response, JSONResponse
from . import auth, crm_source
from . import ui as U

# ---------------------------------------------------------------- round 6/7: MC Trade template + contacts upload, in-app dry run
def _safe_fname(n):
    """Filename for the audit log: no control characters, no markup, short (mctrade-r4 R4-7)."""
    import urllib.parse
    n = urllib.parse.unquote(str(n or ""))
    return re.sub(r"[^\w .()\-]", "_", n)[:80] or "(no name)"

TPL_BAKS = 5
# ---------------- round 15 (manager r14 H-r14-1 / M-r14-1): optimistic locking for the shared admin state
# Each shared thing (template file, contacts file, the 'update existing' switch + other settings) has a short version.
# The Settings page sends back the version it showed; if another admin changed it meanwhile the change is refused with 409
# 'stale_admin' and says who changed it and when. Nothing is overwritten silently.
def file_version(p):
    if not p or not os.path.isfile(p): return "none"
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:12]
def template_version():
    from . import mctrade_export as mx
    return file_version(mx.TEMPLATE_XLSX)
def contacts_version():
    p = crm_source.uploaded_path()
    return file_version(p) if p else "none"
def _last_admin_change(prefix):
    r = U.db().execute("SELECT ts, username, event FROM auth_log WHERE event LIKE ? AND event NOT LIKE '%REFUSED%' ORDER BY id DESC LIMIT 1", (prefix + "%",)).fetchone()
    return {"by": r["username"], "at": U._when(r["ts"]), "what": r["event"][:200]} if r else None
def stale_admin(thing, expected, current, prefix, user=None, action=""):
    """None when the page's version is current; else the answer. Round 16 (manager r15 H-1): a MISSING version is refused
    too (428 'version_required'), so a script or old page can't overwrite blindly. Every refusal is an audit row (M-1)."""
    if expected == current: return None
    lc = _last_admin_change(prefix)
    # round 17 (manager r16 L-2): the refused row says WHAT was tried (upload / revert / remove, and the file name)
    if user: auth.alog(user, f"refused (stale admin page): {action or 'change'} of the {thing} " + (f"made from version {_safe_fname(expected)}, current version is {current}" if expected else f"sent without a version (current version {current})") + ": nothing was changed")
    if not expected:
        return JSONResponse({"error": f"Nothing was changed: the page is out of date. Reload Admin → Settings and try again.",
                             "need": "version_required", "thing": thing, "version": current, "last_change": lc}, 428)
    # round 17 (manager r16 L-3): a version this server never issued is not "changed by X after you opened this page"
    known = expected == "none" or bool(re.fullmatch(r"[0-9a-f]{12}", expected or "")) and U.db().execute(
        "SELECT 1 FROM auth_log WHERE event LIKE ? AND event NOT LIKE '%refused%' LIMIT 1", ("%" + expected + "%",)).fetchone() is not None
    if expected and not known:
        return JSONResponse({"error": f"The version sent for the {thing} ({_safe_fname(expected)[:40]}) is not one this server has ever had (current version {current}). Nothing was changed: reload Admin → Settings and try again.",
                             "need": "stale_admin", "unknown_version": True, "thing": thing, "version": current, "last_change": lc}, 409)
    msg = (f"The {thing} was changed by {lc['by']} at {lc['at']} after you opened this page. Nothing was changed: reload Admin → Settings, check their change, then try again."
           if lc else f"The {thing} changed after you opened this page. Nothing was changed: reload Admin → Settings and try again.") if expected else \
          f"This request didn't say which version of the {thing} it was made from. Reload Admin → Settings and try again."
    return JSONResponse({"error": msg, "need": "stale_admin", "thing": thing, "version": current, "last_change": lc}, 409)
def _rotate_bak(dst):
    """Keep several generations: .bak (newest) .bak2 ... .bak5 (manager-r4 L-r4-2)."""
    if not os.path.isfile(dst): return False
    for k in range(TPL_BAKS, 1, -1):
        a = dst + (".bak" if k == 2 else f".bak{k-1}"); b = dst + f".bak{k}"
        if os.path.isfile(a): os.replace(a, b)
    os.replace(dst, dst + ".bak"); return True

def _check_template(data):
    """-> (header row) or raises ValueError. Size/zip-bomb caps, read_only parse, <=200 columns, name columns, no formula/HTML headers."""
    from openpyxl import load_workbook
    from . import mctrade_export as mx
    if not data or len(data) > crm_source.MAX_UPLOAD: raise ValueError("Empty file or larger than 5 MB.")
    crm_source.check_xlsx(data)
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
        try: sheets = [[("" if x is None else str(x)) for x in (next(w.iter_rows(min_row=1, max_row=1, max_col=1000, values_only=True), ()) or ())] for w in wb.worksheets]
        finally: wb.close()
    except Exception: raise ValueError("That isn't an Excel (.xlsx) file.")
    hdr = next((r for r in sheets if any(mx._hnorm(x) in ("indemail", "affcode1") for x in r)), None)
    if hdr is None: raise ValueError("No sheet has an IndEmail or AffCode1 column in its first row: this doesn't look like the MC Trade import template.")
    while hdr and not hdr[-1].strip(): hdr.pop()
    if any(not h.strip() for h in hdr):   # mctrade-r5 F5: a blank cell between headers silently shifted the counts
        raise ValueError(f"Header cell {next(i for i, h in enumerate(hdr) if not h.strip()) + 1} of the first row is blank: an MC Trade template has a name in every column.")
    long_ = [h for h in hdr if len(h) > 200]
    if long_: raise ValueError(f"A header cell is {len(long_[0])} characters long (limit 200): not an MC Trade template.")
    if len(hdr) > 200: raise ValueError(f"The header row has {len(hdr)} columns; an MC Trade import template has far fewer (limit 200).")
    norm = {mx._hnorm(h) for h in hdr}
    if not {"indfirstname", "indlastname"} <= norm: raise ValueError("The header row has no IndFirstName / IndLastName columns: people's names would be lost.")
    bad = [h for h in hdr if h and (re.match(r"\s*[=+\-@]", h) or re.search(r"[<>]", h))]
    if bad: raise ValueError("Header cells look like formulas or HTML (" + ", ".join(b[:30] for b in bad[:3]) + "): not an MC Trade template.")
    return hdr

def _refused(user, what, fname, why):
    auth.alog(user, f"settings: REFUSED {what} upload ({_safe_fname(fname)}): {why}")

@U.router.post("/api/admin/mctrade-template")
async def upload_template(request: Request, image: UploadFile = File(...)):
    """Admin: GAC's MC Trade import template -> data/mctrade_template.xlsx. Checked (sizes, zip ratio, columns, headers) in a
    worker thread so a bad file can't block the server. Up to 5 previous files are kept (.bak ... .bak5); revert in Settings."""
    import asyncio
    from . import mctrade_export as mx
    u = request.state.user["username"]
    st_ = stale_admin("MC Trade template", (await request.form()).get("expected_version") or request.query_params.get("expected_version"), template_version(), "settings: %template%", request.state.user["username"], f"upload ({_safe_fname(image.filename)})")
    if st_: return st_
    data = await image.read(crm_source.MAX_UPLOAD + 1)
    try: hdr = await asyncio.wait_for(asyncio.to_thread(_check_template, data), timeout=20)
    except asyncio.TimeoutError: _refused(u, "template", image.filename, "took too long to read"); return JSONResponse({"error": "The file took too long to read: refused."}, 422)
    except ValueError as e: _refused(u, "template", image.filename, str(e)); return JSONResponse({"error": str(e)}, 422)
    dst = mx.TEMPLATE_XLSX
    prev = len([h for h in mx.headers()[0] if h]) if os.path.isfile(dst) else 0
    tmp = dst + ".uploading"   # audit 2026-10 P1 (F03): written in full first; the current template is only replaced after that
    with open(tmp, "wb") as fh: fh.write(data); fh.flush(); os.fsync(fh.fileno())
    had = _rotate_bak(dst)
    os.replace(tmp, dst)
    hdr, src = mx.headers()
    unknown = [h for h in hdr if h and not mx.canonical(h)]
    auth.alog(u, f"settings: uploaded the MC Trade import template ({_safe_fname(image.filename)}, {len([h for h in hdr if h])} columns"
              + (f"; replaced the previous template ({prev} columns), kept as .bak" if had else "; there was no template before") + f"; template version {template_version()})")
    return {"ok": True, "columns": hdr, "unknown": unknown, "source": src, "had_previous": had, "version": template_version()}

@U.router.post("/api/admin/mctrade-template/revert")
def revert_template(request: Request):
    """Undo of a template upload: the newest .bak becomes the template again (or no template if there was none)."""
    from . import mctrade_export as mx
    dst = mx.TEMPLATE_XLSX; bak = dst + ".bak"; u = request.state.user["username"]
    st_ = stale_admin("MC Trade template", request.query_params.get("expected_version"), template_version(), "settings: %template%", request.state.user["username"],
                      "remove" if request.query_params.get("to_none") == "1" else "revert to the previous file")
    if st_: return st_
    if os.path.isfile(bak):
        os.replace(bak, dst)
        for k in range(2, TPL_BAKS + 1):   # shift the older generations up
            a = dst + f".bak{k}"; b = dst + (".bak" if k == 2 else f".bak{k-1}")
            if os.path.isfile(a): os.replace(a, b)
        hdr, _ = mx.headers(); auth.alog(u, f"settings: reverted the MC Trade import template to the previous file ({len([h for h in hdr if h])} columns); template version now {template_version()}")
        return {"ok": True, "present": True, "columns": hdr, "version": template_version()}
    if os.path.isfile(dst) and request.query_params.get("to_none") == "1":
        old_v = template_version(); os.remove(dst)   # round 16 (manager r15 L-3): no .removed leftover on disk
        if os.path.isfile(dst + ".removed"): os.remove(dst + ".removed")
        auth.alog(u, f"settings: removed the MC Trade import template version {old_v} (default columns are used again); template version now none")
        return {"ok": True, "present": False, "version": template_version()}
    return JSONResponse({"error": "There is no earlier template to go back to."}, 404)

@U.router.get("/api/admin/mctrade-template")
def template_info():
    from . import mctrade_export as mx
    if os.path.isfile(mx.TEMPLATE_XLSX + ".removed"):   # round 16: leftovers of earlier rounds' removals
        try: os.remove(mx.TEMPLATE_XLSX + ".removed")
        except OSError: pass
    hdr, src = mx.headers()
    return {"present": os.path.isfile(mx.TEMPLATE_XLSX), "path": "data/mctrade_template.xlsx", "columns": hdr, "source": src,
            "unknown": [h for h in hdr if h and not mx.canonical(h)], "can_revert": os.path.isfile(mx.TEMPLATE_XLSX + ".bak"),
            "previous": sum(1 for k in ["", "2", "3", "4", "5"] if os.path.isfile(mx.TEMPLATE_XLSX + ".bak" + k)),
            "version": template_version(), "last_change": _last_admin_change("settings: %template%")}

def _check_contacts(data, ext):
    """-> (rows, n_people). A real MC Trade contacts export (Profile Selector / Query Tool: .xlsx or .csv). Raises ValueError."""
    import tempfile
    if not data or len(data) > 20 * 1024 * 1024: raise ValueError("Empty file or larger than 20 MB.")
    if ext == "xlsx":
        crm_source.check_xlsx(data)
    else:
        try: data.decode("utf-8-sig")
        except UnicodeDecodeError: raise ValueError("The CSV isn't UTF-8 text: save it from Excel as 'CSV UTF-8'.")
    fd, tmp = tempfile.mkstemp(suffix="." + ext)
    try:
        with os.fdopen(fd, "wb") as fh: fh.write(data)
        rows, is_sample, n = crm_source.parse(tmp)
    except ValueError: raise
    except Exception: raise ValueError("The file could not be read as an MC Trade contacts export.")
    finally: os.unlink(tmp)
    if is_sample or crm_source.looks_like_sample(rows, data):
        raise ValueError("This is the scanner's own SAMPLE contacts file (fake test people, Profile IDs 1001-1005), not GAC's real MC Trade export.")
    rows, skipped = crm_source.skip_sample_rows(rows)
    if not rows: raise ValueError("No people with a Profile ID found in the file" + (" (rows with the scanner's SAMPLE emails are skipped)." if skipped else "."))
    return rows, n, skipped

@U.router.post("/api/admin/mctrade-contacts")
async def upload_contacts(request: Request, image: UploadFile = File(...)):
    """Admin: GAC's real MC Trade contacts export. Used for Profile IDs in the export AND by the in-app dry run (same source)."""
    import asyncio
    u = request.state.user["username"]; ext = os.path.splitext(image.filename or "")[1].lower().lstrip(".")
    if ext not in ("xlsx", "csv"): _refused(u, "MC Trade contacts", image.filename, "not .xlsx/.csv"); return JSONResponse({"error": "Upload the MC Trade export as .xlsx or .csv."}, 422)
    st_ = stale_admin("MC Trade contacts file", (await request.form()).get("expected_version") or request.query_params.get("expected_version"), contacts_version(), "settings: %contacts%", request.state.user["username"], f"upload ({_safe_fname(image.filename)})")
    if st_: return st_
    data = await image.read(20 * 1024 * 1024 + 1)
    try: rows, n, skipped = await asyncio.wait_for(asyncio.to_thread(_check_contacts, data, ext), timeout=30)
    except asyncio.TimeoutError: _refused(u, "MC Trade contacts", image.filename, "took too long"); return JSONResponse({"error": "The file took too long to read: refused."}, 422)
    except ValueError as e: _refused(u, "MC Trade contacts", image.filename, str(e)); return JSONResponse({"error": str(e)}, 422)
    # audit 2026-10 P1 (F03): the new file is written in full BEFORE the old one goes (a failed write used to leave no
    # contacts file at all); the old one is still wiped, not kept (round 8)
    _cp = os.path.join(crm_source.DATA, f"mctrade_contacts.{ext}"); tmp = _cp + ".uploading"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as fh: fh.write(data); fh.flush(); os.fsync(fh.fileno())
    os.chmod(tmp, 0o600)
    if os.path.isfile(_cp): os.replace(_cp, _cp + ".old")
    os.replace(tmp, _cp)
    for p_ in [_cp + ".old"] + [os.path.join(crm_source.DATA, f"mctrade_contacts.{e_}") + sfx for e_ in ("xlsx", "csv") for sfx in ("", ".bak") if not (e_ == ext and sfx == "")]:
        crm_source.secure_delete(p_)
    crm_source.write_loader(request.state.user)   # round 11 (mctrade-r7 C1): who loaded it, and when, is shown with the source
    auth.alog(u, f"settings: uploaded the MC Trade contacts export ({_safe_fname(image.filename)}, {len(rows)} people with a Profile ID); "
                 "exports and the dry run now use it" + (f"; {skipped} {U._s(skipped, 'row')} with the scanner's SAMPLE emails skipped" if skipped else "") + f"; contacts version {contacts_version()}")
    return {"ok": True, "skipped_sample_rows": skipped} | contacts_info()

@U.router.post("/api/admin/mctrade-contacts/remove")
def remove_contacts(request: Request):
    st_ = stale_admin("MC Trade contacts file", request.query_params.get("expected_version"), contacts_version(), "settings: %contacts%", request.state.user["username"], "remove")
    if st_: return st_
    gone = 0
    for e_ in ("xlsx", "csv"):
        p_ = os.path.join(crm_source.DATA, f"mctrade_contacts.{e_}")
        if crm_source.secure_delete(p_): gone += 1
        crm_source.secure_delete(p_ + ".bak")   # leftovers of round 7, which renamed instead of deleting
    crm_source.secure_delete(crm_source.loader_path())
    if gone: auth.alog(request.state.user["username"], "settings: removed the MC Trade contacts export: file overwritten and deleted, no copy kept (back to SAMPLE data: no Profile IDs)")
    return {"ok": True, "deleted": gone} | contacts_info()

@U.router.get("/api/admin/mctrade-contacts")
def contacts_info(): return crm_source.info() | {"version": contacts_version(), "last_change": _last_admin_change("settings: %contacts%")}

@U.router.get("/api/mctrade-source")
def mctrade_source():   # any signed-in user: which MC Trade list the review box / export / dry run use
    i = crm_source.info(); return {"real": i["real"], "source": i["source"]}

@U.router.get("/api/export/dryrun")
def export_dryrun(request: Request, status: str = "approved_new", batch: str = ""):
    """The MC Trade dry run inside the app. Round 8 (mctrade-r5 F2/F3, manager-r8 M-r8-1/2): the decisions come from the SAME
    classification as the export and the sign-off (mctrade_export.classify via build_export), so the three always agree.
    The built import file is also read back with mctrade-dryrun/dryrun.py's reader as a file check. Changes nothing; audited."""
    import tempfile, importlib.util, contextlib, shutil
    user = request.state.user
    sel0, metas0, _ = U._export_set(status, batch) if not U._filter_refused(status, user) else ([], {}, [])
    blabel0 = next(((metas0.get(c["id"]) or {}).get("batch_label") or "" for c in sel0), "") if batch else ""
    if batch and not blabel0:
        blabel0 = next(((m or {}).get("batch_label") or "" for m in U.all_metas().values() if (m or {}).get("batch") == batch), "")
    def refuse(code, msg):
        auth.alog(user["username"], f"dry run REFUSED ({code}): {msg} [filter {U.FILTERS.get(status, status)}, batch {('“' + blabel0 + '”') if blabel0 else (batch or 'all')}]")
        return JSONResponse({"error": msg}, code)
    if U._batch_refused(batch, user) and not U._filter_refused(status, user): return refuse(403, U.BATCH_MSG)
    if U._filter_refused(status, user) or (not batch and user.get("role") != "admin"):
        return refuse(403, "Choose your batch first (only an admin can check all batches).")
    sel, metas = sel0, metas0
    if not sel: return refuse(404, "No cards to check.")
    blabel = blabel0
    from .exporting import _inc
    from .exporting import waiting_ids as _wids
    res = U.build_export("xlsx", sel, metas, status, f"{user['display']} ({user['initials']})", "", include_changed=_inc(request), waiting=_wids(batch) if batch else None, viewer=user)
    body, comp, summ = res[0], res[3], res[4]; view = summ.pop("_view", None) or {}
    cinfo = crm_source.info(); dec = summ["decisions"]; cnt = summ["counts"]
    why = {int(i): w for i, w in view.get("left", [])}
    mcp = summ.get("mc_possible") or {}   # v0.4.3 #4: a possible MC Trade match
    tc_ = {str(i) for i in summ.get("to_check_ids") or []}   # v0.4.4 #3: the SAME 'To check' set as the screen, Save dialog and READ-ME
    filecheck = ""
    tmp = tempfile.mkdtemp(prefix="gac-dryrun-")
    try:
        open(os.path.join(tmp, "export.xlsx"), "wb").write(body)
        spec = importlib.util.spec_from_file_location("gac_dryrun", os.path.join(os.path.dirname(__file__), "..", "mctrade-dryrun", "dryrun.py"))
        dr = importlib.util.module_from_spec(spec); spec.loader.exec_module(dr)
        with contextlib.redirect_stdout(io.StringIO()): n_ = len(dr.read_export(os.path.join(tmp, "export.xlsx")))
        # round 11 (manager-r10 L-r9-3): the UPDATES file is read back too; "0 rows" alone no longer reads as "nothing to import"
        ub = comp.get("updates.xlsx") if isinstance(comp, dict) else None
        nu_ = None
        if ub:
            open(os.path.join(tmp, "updates.xlsx"), "wb").write(ub)
            with contextlib.redirect_stdout(io.StringIO()): nu_ = len(dr.read_export(os.path.join(tmp, "updates.xlsx")))
        parts_ = [f"new-profiles file: {n_} {U._s(n_, 'row')}" + (" (no new profiles in this export)" if not n_ else "")]
        if nu_ is not None: parts_.append(f"UPDATES file: {nu_} {U._s(nu_, 'row')}")
        filecheck = "The import files read back cleanly (" + "; ".join(parts_) + ")."
    except (Exception, SystemExit) as e: filecheck = f"The import file could not be read back: {_html.escape(str(e)[:200])}"
    finally: shutil.rmtree(tmp, ignore_errors=True)
    LBL = {"new": "CREATE (new-profiles file)", "update": "UPDATE (UPDATES file)", "review": "TO CHECK (in neither file)", "left": "NOT IN THE FILE"}
    COL = {"new": "#d9ead3", "update": "#ddebf7", "review": "#fce4d6", "left": "#eeeeee"}
    order = {"review": 0, "left": 1, "update": 2, "new": 3}
    def nm(c): return _html.escape(f"{c['fields'].get('first_name','')} {c['fields'].get('last_name','')}".strip() or "(no name)")
    trs = "".join(f"<tr data-card='{c['id']}' data-decision='{dec[str(c['id'])]}' style='background:{COL[dec[str(c['id'])]]}'><td>#{c['id']}</td><td>{nm(c)}</td><td>{_html.escape(c['fields'].get('company') or '')}</td>"
                  f"<td><b>{'TO CHECK (in the new-profiles file)' if str(c['id']) in tc_ and dec[str(c['id'])] in ('new', 'update') else LBL[dec[str(c['id'])]]}</b></td>"
                  f"<td>{_html.escape(why.get(c['id'], '') or ((lambda t_: t_[:1].upper() + t_[1:])(mcp.get(str(c['id']), '')) if dec[str(c['id'])] == 'new' else ''))}</td></tr>"
                  for c in sorted(sel, key=lambda c: (order['review' if str(c['id']) in tc_ else dec[str(c['id'])]], c["id"])))
    left = [int(i) for i, k in dec.items() if k in ("review", "left")]
    html_ = ("<!doctype html><html><head><meta charset='utf-8'><title>MC Trade dry run: match report</title></head><body style='font:14px sans-serif;margin:16px'>"
             f"<h1>MC Trade dry run: match report (nothing was sent to MC Trade)</h1>"
             f"<div style='background:#fff3cd;border:2px solid #b45309;padding:10px;margin:8px 0;font:15px sans-serif'><b>Compared against:</b> {_html.escape(cinfo['source'])}."
             + ("" if cinfo["real"] else " <b>SAMPLE DATA: this is a rehearsal; no Profile IDs are assigned.</b>")
             + f"<br><b>Cards checked:</b> {len(sel)}" + (f" · batch “{_html.escape(blabel)}”" if blabel else "")
             + f"<br><b>{_html.escape((summ.get('ready') or {}).get('text') or '')}</b>"   # v0.4.9 #1: the headline is the Ready line (one count source)
             + f"<br>UPDATE {cnt['update']} · CREATE {cnt['new']} · TO CHECK {(summ.get('ready') or {}).get('to_check', 0)} in the file · NOT IN THE FILE {cnt['left'] + cnt['review']}"
             + f" (the same decisions as the export and its sign-off: {summ['new_rows']} new {U._s(summ['new_rows'], 'row')}, {summ['update_rows']} update {U._s(summ['update_rows'], 'row')})"
             + ("<br>Updating existing MC Trade contacts is <b>switched off</b> (Admin → Settings): cards that match a profile are TO CHECK, never new rows." if auth.get_setting("mctrade_updates_enabled") != "1" else "")
             + f"<br>{filecheck}</div>"
             "<table border='1' cellpadding='4' style='border-collapse:collapse'><tr><th>Card</th><th>Name</th><th>Company</th><th>Decision</th><th>Why</th></tr>"
             + trs + "</table></body></html>")
    auth.alog(user["username"], f"dry run: ran the MC Trade dry-run check on {len(sel)} {U._s(len(sel), 'card')}, " + (f"batch “{blabel or batch}”" if batch else "all batches")
              + f", filter {U.FILTERS.get(status, status)}; data source: {'REAL ' + cinfo['file'] if cinfo['real'] else 'SAMPLE data'}; result: "
              + f"UPDATE {cnt['update']}, CREATE {cnt['new']}, TO CHECK {len(tc_)}, LEFT OUT {cnt['left']}"
              + f"; not in either file {len(left)} (TO CHECK in neither file + LEFT OUT)" + (": " + ", ".join(f"#{i}" for i in sorted(left)[:500]) if left else "")
              + "; cards checked: " + ", ".join(f"#{c['id']}" for c in sorted(sel, key=lambda c: c["id"])[:500]))   # manager-r9 L-r9-1/2
    return Response(html_, media_type="text/html", headers={"Cache-Control": "no-store"})
