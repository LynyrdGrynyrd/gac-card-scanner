"""Round 8 (manager-r8 L-r8-2): scheduled nightly backup + tested restore.

A backup is ONE file: backups/gac-backup-YYYYmmdd-HHMMSS.tgz holding
  cards.db         a consistent copy made with SQLite's online backup API (safe while the scanner runs)
  data/...         card photos (uploads/), stored export files (exports/), the MC Trade template, settings files
  MANIFEST.json    when, which files, card count, sha256 of cards.db
The MC Trade contacts export (data/mctrade_contacts.*) is NOT backed up: it is GAC's member list, kept only as long as an
admin leaves it uploaded (see Admin > Settings). Thumbnails, the AI/job inbox and lock files are not backed up either.
Seven backups are kept (BACKUP_KEEP); older ones are deleted. Put GAC_BACKUP_DIR on another disk (a USB drive, a synced
folder) so a dead disk doesn't take the backups with it.

    python -m app.backup              make a backup now
    python -m app.backup --list       list backups
    python -m app.backup --restore F  restore F (the scanner must be stopped; the current data is first moved aside)
"""
import os, sys, io, json, time, sqlite3, tarfile, hashlib, shutil, datetime, threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KEEP = int(os.environ.get("BACKUP_KEEP", "7"))
SKIP_DIRS = {"thumbs", "inbox", "jobs_done", "__pycache__"}
def _skip(name): return name.startswith("mctrade_contacts.") or name.startswith(".workers") or name.endswith((".db-wal", ".db-shm", ".db-journal"))

def data_dir(): return os.environ.get("GAC_DATA_DIR") or os.path.join(ROOT, "data")
def db_path():
    if os.environ.get("GAC_DB"): return os.environ["GAC_DB"]
    if os.environ.get("GAC_DATA_DIR"): return os.path.join(os.environ["GAC_DATA_DIR"], "cards.db")
    try:
        from . import store; return os.path.abspath(store.DB)
    except Exception: return os.path.join(data_dir(), "cards.db")
def backup_dir(): return os.environ.get("GAC_BACKUP_DIR") or os.path.join(ROOT, "backups")

def make(dest=None, data=None, db=None, keep=KEEP):
    """-> path of the new backup file."""
    data, db, dest = data or data_dir(), db or db_path(), dest or backup_dir()
    os.makedirs(dest, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(dest, f"gac-backup-{stamp}.tgz"); k = 1
    while os.path.exists(out): k += 1; out = os.path.join(dest, f"gac-backup-{stamp}-{k}.tgz")
    tmp = out + ".part"
    snap = os.path.join(dest, f".cards-{stamp}.db")
    src = sqlite3.connect(db); dst = sqlite3.connect(snap)
    with dst: src.backup(dst)
    n = dst.execute("SELECT COUNT(*) FROM cards").fetchone()[0] if dst.execute("SELECT name FROM sqlite_master WHERE name='cards'").fetchone() else 0
    ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    src.close(); dst.close()
    if ok != "ok": os.remove(snap); raise RuntimeError("database integrity check failed: " + ok)
    files = []
    try:
        with tarfile.open(tmp, "w:gz") as t:
            t.add(snap, "cards.db")
            for dp, dns, fns in os.walk(data):
                dns[:] = [d for d in dns if d not in SKIP_DIRS]
                for fn in fns:
                    p = os.path.join(dp, fn)
                    if os.path.abspath(p) == os.path.abspath(db) or _skip(fn) or fn == os.path.basename(db): continue
                    rel = os.path.relpath(p, data); t.add(p, "data/" + rel); files.append(rel)
            sha = hashlib.sha256(open(snap, "rb").read()).hexdigest()
            man = json.dumps({"made": time.time(), "cards": n, "cards_db_sha256": sha, "files": len(files)}, indent=1).encode()
            ti = tarfile.TarInfo("MANIFEST.json"); ti.size = len(man); ti.mtime = time.time(); t.addfile(ti, io.BytesIO(man))
        os.chmod(tmp, 0o600); os.replace(tmp, out)
    finally:
        for p in (snap, tmp):
            if os.path.exists(p): os.remove(p)
    prune(dest, keep)
    return out

def listing(dest=None):
    dest = dest or backup_dir()
    if not os.path.isdir(dest): return []
    fs = [os.path.join(dest, f) for f in os.listdir(dest) if f.startswith("gac-backup-") and f.endswith(".tgz")]
    return sorted(fs, key=lambda p: (os.stat(p).st_mtime_ns, p))   # oldest first

def prune(dest=None, keep=KEEP):
    bs = listing(dest)
    for p in bs[:-keep] if keep > 0 else []: os.remove(p)

def verify(path):
    """-> manifest dict; raises if the archive or its database is damaged."""
    with tarfile.open(path, "r:gz") as t:
        man = json.load(t.extractfile("MANIFEST.json"))
        raw = t.extractfile("cards.db").read()
    if hashlib.sha256(raw).hexdigest() != man["cards_db_sha256"]: raise RuntimeError("cards.db checksum mismatch")
    return man

def restore(path, data=None, db=None):
    """Restore a backup over data/ (the scanner must be stopped). The current data folder is first moved to
    data.before-restore-<time> so a wrong restore can itself be undone. -> dict(manifest, moved_aside)."""
    data, db = os.path.abspath(data or data_dir()), os.path.abspath(db or db_path())
    man = verify(path)
    lock = os.path.join(data, ".workers.lock")
    if os.path.exists(lock):
        from . import paths
        fd = os.open(lock, os.O_RDWR)
        try:
            if not paths.try_lock(fd): raise RuntimeError("the scanner is still running on this data folder: stop it first")
        finally: os.close(fd)
    aside = data + ".before-restore-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    keep_contacts = [f for f in (os.listdir(data) if os.path.isdir(data) else []) if f.startswith("mctrade_contacts.")]
    if os.path.isdir(data): shutil.move(data, aside)
    os.makedirs(data)
    with tarfile.open(path, "r:gz") as t:
        for m in t.getmembers():
            if m.name == "MANIFEST.json" or not m.isfile(): continue
            if m.name == "cards.db": target = db
            elif m.name.startswith("data/"):
                rel = os.path.normpath(m.name[5:])
                if rel.startswith("..") or os.path.isabs(rel): continue          # never write outside data/
                target = os.path.join(data, rel)
            else: continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with t.extractfile(m) as src, open(target, "wb") as fh: shutil.copyfileobj(src, fh)
    for sub in ("uploads", "exports", "inbox", "jobs_done", "thumbs"): os.makedirs(os.path.join(data, sub), exist_ok=True)
    for f in keep_contacts:   # the contacts export is never in a backup: keep the one that was uploaded
        shutil.copy2(os.path.join(aside, f), os.path.join(data, f))
    c = sqlite3.connect(db); ok = c.execute("PRAGMA integrity_check").fetchone()[0]; c.close()
    if ok != "ok": raise RuntimeError("restored database failed its integrity check: " + ok)
    return {"manifest": man, "moved_aside": aside if os.path.isdir(aside) else None}

# ---------------------------------------------------------------- nightly schedule (runs inside the scanner)
def _next_run(now=None, hour=None):
    hour = int(os.environ.get("BACKUP_HOUR", "2")) if hour is None else hour
    now = now or datetime.datetime.now(); t = now.replace(hour=hour, minute=30, second=0, microsecond=0)
    return t if t > now else t + datetime.timedelta(days=1)
def _loop():
    while True:
        try:
            if os.environ.get("GAC_BACKUP", "1") != "1": time.sleep(3600); continue
            last = listing(); age = time.time() - os.path.getmtime(last[-1]) if last else 1e9
            if age > 26 * 3600:   # missed (the computer was off at night): back up soon after start
                time.sleep(600)
            else:
                time.sleep(max(60, (_next_run() - datetime.datetime.now()).total_seconds()))
            p = make(); print("nightly backup:", p, flush=True)
            try:
                from . import auth; auth.alog("backup", f"nightly backup made ({os.path.basename(p)}; {len(listing())} kept)")
            except Exception: pass
        except Exception as e:
            print("backup error:", e, flush=True); time.sleep(3600)
def same_disk():
    """Round 9 (manager-r9 L-r9-5): True when the backups sit on the same disk as the data (set GAC_BACKUP_DIR)."""
    try:
        d = backup_dir(); os.makedirs(d, exist_ok=True)
        return os.stat(d).st_dev == os.stat(data_dir()).st_dev
    except Exception: return None
def start():
    if same_disk():
        print("!! Backups are on the SAME disk as the data (" + backup_dir() + "). Set GAC_BACKUP_DIR to another disk "
              "(USB drive, network share) so a disk failure can't take both. See the Admin & MC Trade Guide, section 2.5.", flush=True)
    threading.Thread(target=_loop, daemon=True, name="nightly-backup").start()

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--list"]:
        for p in listing(): print(p, verify(p))
    elif a[:1] == ["--restore"] and len(a) == 2:
        r = restore(a[1]); print("restored", a[1], "; previous data moved to", r["moved_aside"], "; cards:", r["manifest"]["cards"])
    elif a[:1] == ["--verify"] and len(a) == 2: print(verify(a[1]))
    else: print(make())
