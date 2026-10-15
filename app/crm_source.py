"""Round 7: ONE source of 'existing MC Trade contacts' for the review box, the Excel export (Profile IDs) and the in-app dry run.

A REAL list exists only when an admin uploaded GAC's MC Trade contacts export (Admin > Settings, .xlsx or .csv) into
data/mctrade_contacts.<ext>, or MCTRADE_CRM_EXPORT points at one. Without it the scanner falls back to SAMPLE data
(data/existing_contacts.csv, 5 fake rows from the test fixtures): it may show 'possible existing member' hints, labelled
SAMPLE, but it NEVER assigns a Profile ID from it (mctrade-r4 R4-2: sample IDs would overwrite real profiles)."""
import os, csv, io, zipfile, importlib.util, contextlib, threading

ROOT = os.path.join(os.path.dirname(__file__), "..")
from . import paths
DATA = paths.DATA   # user data (uploaded contacts export); GAC_DATA_DIR in desktop builds
SAMPLE = os.path.join(ROOT, "data", "existing_contacts.csv")   # bundled fake sample
DRYRUN = os.path.join(ROOT, "mctrade-dryrun", "dryrun.py")
_cache = {"key": None, "rows": None}; _lock = threading.Lock()

def uploaded_path():
    env = os.environ.get("MCTRADE_CRM_EXPORT")
    if env and os.path.isfile(env): return env
    for ext in ("xlsx", "csv"):
        p = os.path.join(DATA, f"mctrade_contacts.{ext}")
        if os.path.isfile(p): return p
    return None

def _dryrun():
    spec = importlib.util.spec_from_file_location("gac_dryrun_crm", DRYRUN)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def parse(path):
    """-> (rows in mctrade_sync.match format, is_sample, n_people). Raises ValueError with a plain-language reason."""
    dr = _dryrun()
    try:
        with contextlib.redirect_stdout(io.StringIO()): people, orgs, pick, is_sample = dr.read_crm(path)
    except SystemExit as e:   # manager-r8 L-r8-4: no temp path, no developer advice
        raise ValueError(HEADER_MSG) from None
    if not dr_has_first(path, dr): raise ValueError(HEADER_MSG)
    orgname = {g["profile_id"]: g["org_name"] or g["report_name"] for g in orgs}
    rows = []
    for g in people:
        if not g["profile_id"]: continue
        rows.append({"profile_id": str(g["profile_id"]).strip(), "first_name": g["first_name"], "last_name": g["last_name"],
                     "organization": g["related_name"] or orgname.get(g["related_id"], "") or g["org_name"],
                     "email": (g["email"] or "").strip(), "phone": g["work_phone"] or g["cell_phone"]})
    return rows, is_sample, len(people)

HEADER_MSG = ("This doesn't look like an MC Trade contacts export: it needs Profile ID, First Name, Last Name and Email columns "
              "in the first row. Export the contacts again from MC Trade with those columns and upload that file.")
def dr_has_first(path, dr):
    """Header plausibility (round 8): Profile ID, First Name, Last Name and Email columns must all be there."""
    try:
        if path.lower().endswith(".xlsx"):
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True)
            try: hdr = [str(h or "") for h in next(wb.worksheets[-1].iter_rows(max_row=1, values_only=True), ())]
            finally: wb.close()   # audit 2026-10: else Windows can't delete or replace the file afterwards
        else:
            with open(path, newline="", encoding="utf-8-sig") as fh: hdr = next(csv.reader(fh), [])
    except Exception: return False
    low = {h.strip().lower() for h in hdr}
    return all(any(a.lower() in low for a in dr.ALIASES[k]) for k in ("profile_id", "first_name", "last_name", "email"))

def _sample_fp():
    """Fingerprint of the app's own SAMPLE contacts (data/existing_contacts.csv): file hash, IDs and emails."""
    import hashlib
    try:
        raw = open(SAMPLE, "rb").read(); rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except Exception: return "", set(), set()
    return (hashlib.sha256(raw).hexdigest(), {str(r["profile_id"]).strip() for r in rows},
            {(r.get("email") or "").strip().lower() for r in rows if r.get("email")})
SAMPLE_IDS_FIXED = {"1001", "1002", "1003", "1004", "1005"}
def looks_like_sample(rows, data=b""):
    """manager-r8 H-r8-1, round 9 (manager-r9 M-r9-1, mctrade-r6 F2): the app's own SAMPLE file (or a copy / re-save
    of it) must never count as GAC's real export, but one ID or one email in common must not refuse a real file.
    True when the bytes are the sample file, or 3+ rows carry a sample (Profile ID, email) pair together."""
    import hashlib
    h, ids, ems = _sample_fp(); ids = ids | SAMPLE_IDS_FIXED
    if data and h and hashlib.sha256(data).hexdigest() == h: return True
    pairs = sum(1 for r in rows if str(r.get("profile_id", "")).strip() in ids and (r.get("email") or "").strip().lower() in ems)
    return pairs >= 3

def skip_sample_rows(rows):
    """Round 9: rows that carry one of the SAMPLE file's emails are skipped one by one (never matched or given a
    Profile ID); the rest of the file is used. -> (kept_rows, skipped_count)."""
    _, _, ems = _sample_fp()
    kept = [r for r in rows if (r.get("email") or "").strip().lower() not in ems]
    return kept, len(rows) - len(kept)

def secure_delete(p):
    """Overwrite the file with zeros, flush it to disk, then delete it (manager-r8 M-r8-3: no .bak copy of member data).
    On SSDs/copy-on-write file systems an overwrite can't be guaranteed to reach the old blocks; full-disk encryption covers that."""
    if not os.path.isfile(p): return False
    try:
        n = os.path.getsize(p)
        with open(p, "r+b") as fh:
            left = n
            while left > 0:
                k = min(left, 1 << 20); fh.write(b"\0" * k); left -= k
            fh.flush(); os.fsync(fh.fileno())
    except OSError: pass
    os.remove(p); return True

def real():
    """Rows of the REAL MC Trade export, or None when none was uploaded (or the uploaded file is the SAMPLE file)."""
    p = uploaded_path()
    if not p: return None
    key = (p, os.path.getmtime(p))
    with _lock:
        if _cache["key"] != key:
            try: rows, is_sample, _ = parse(p)
            except Exception: rows, is_sample = None, True
            if rows is not None and not is_sample and looks_like_sample(rows): is_sample = True
            if rows is not None and not is_sample: rows = skip_sample_rows(rows)[0]
            _cache.update(key=key, rows=None if is_sample else rows)
        return _cache["rows"]

def sample_rows():
    if not os.path.isfile(SAMPLE): return []   # round 10: a fresh install without the sample file still works
    with open(SAMPLE, encoding="utf-8", newline="") as fh: return list(csv.DictReader(fh))

def rows_for_hints():
    """-> (rows, is_sample). The review box may hint from SAMPLE data (labelled so); IDs never come from it."""
    r = real()
    return (r, False) if r is not None else (sample_rows(), True)

def loader_path(): return os.path.join(DATA, "mctrade_contacts.loader.json")
def write_loader(user):
    import json, time
    with open(os.open(loader_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
        json.dump({"by": f"{user.get('display') or user.get('username')} ({user.get('username')})", "at": time.time()}, fh)
def loader():
    import json, time
    try: d = json.load(open(loader_path(), encoding="utf-8"))
    except Exception: return ""
    return f"loaded by {d.get('by')} at {time.strftime('%b %d %H:%M', time.localtime(d.get('at') or 0))}"
def info():
    p = uploaded_path(); r = real(); ld = loader() if r is not None else ""
    return {"real": r is not None, "file": os.path.basename(p) if p else "", "people": len(r) if r is not None else 0, "loaded": ld,
            "source": (f"GAC's MC Trade contacts export ({os.path.basename(p)}, {len(r)} people{', ' + ld if ld else ''})" if r is not None
                       else "Test data (5 fake contacts): no real MC Trade contacts file, so no Profile IDs")}

# ---------------------------------------------------------------- upload safety (template + contacts)
MAX_UPLOAD = 5 * 1024 * 1024
MAX_UNZIPPED = 40 * 1024 * 1024        # all xlsx parts together
MAX_PART = 15 * 1024 * 1024            # any one part (sharedStrings.xml, sheet1.xml ...)
MAX_RATIO = 100                        # uncompressed / compressed per part (a zip bomb is ~1000x)
def check_xlsx(data):
    """Raise ValueError if the .xlsx is not a plain zip under the size/ratio caps (mctrade-r4 R4-3). Also refuses macros."""
    try: z = zipfile.ZipFile(io.BytesIO(data))
    except Exception: raise ValueError("That isn't an Excel (.xlsx) file.")
    total = 0
    for i in z.infolist():
        total += i.file_size
        if i.file_size > MAX_PART or (i.compress_size and i.file_size > 1024 * 1024 and i.file_size / i.compress_size > MAX_RATIO):
            raise ValueError("The file unpacks to far more data than a normal Excel file (possible zip bomb): refused.")
        if i.filename.lower().endswith("vbaproject.bin"): raise ValueError("The file contains macros (VBA): save it as a plain .xlsx first.")
    if total > MAX_UNZIPPED: raise ValueError("The file unpacks to more than 40 MB: refused (a template or contacts export is much smaller).")
    if "xl/workbook.xml" not in z.namelist(): raise ValueError("That isn't an Excel (.xlsx) file.")
