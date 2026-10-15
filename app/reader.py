"""Round 20 (skeptic C1/H1, coordinator r19 OOM): uploads are READ (PDF pages rendered, HEIC converted, sheets of cards
split) in a short-lived child process with a hard memory limit (RLIMIT_AS) and a time budget. A hostile or simply huge
file can then only kill that child, never the web server (or the AI checker next to it). Each PDF page is its own child
process, so memory is returned to the system after every page.

    python -m app.reader count FILE           -> {"pages": n}
    python -m app.reader page FILE I N OUTDIR  -> {"parts": [[path, label], ...]}   (page I, 0-based)
    python -m app.reader photo FILE OUTDIR     -> {"parts": null | [[path, label], ...]}
Errors meant for the user come back as {"error": "..."} (exit 0)."""
import json, os, subprocess, sys, tempfile

MEM_MB = int(os.environ.get("READER_MEM_MB", "1200"))      # address-space cap of one reader child
TIMEOUT = float(os.environ.get("READER_TIMEOUT", "90"))     # seconds per page / photo
CALM = "This file couldn't be read safely (it is too large or unusual). Save it as JPG or a smaller PDF and try again."
RUNNING = {}   # key -> Popen, so Cancel can stop a page that is being rendered


class ReaderError(Exception):
    """Message is shown to the user as is."""


# Round 23 (skeptic r22 M2): a HARD backstop under the RSS watch. The RSS cap is polled, so a very fast allocation could
# overshoot between polls; the kernel now refuses any address space above BACKSTOP_MB (default: 4x the RSS cap, at least
# 4 GB). Measured virtual peaks: PDF page ~1.0 GB, HEIC ~0.9 GB, OCR ~2.6 GB (onnxruntime reserves), so normal files
# never reach it (the r21 regression was a cap AT the RSS size).
def backstop_mb(cap_mb): return int(os.environ.get("READER_BACKSTOP_MB") or max(4 * cap_mb, 4096))
def _limiter(cap_mb):
    def _limit():
        try: os.nice(5)
        except Exception: pass
        try:
            import resource
            b = backstop_mb(cap_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
        except Exception: pass
    return _limit


def _call(args, data, key=None, mem_mb=None, timeout=None):
    # audit 2026-10 P1 (C3): the limits are per call; run_ocr used to swap the module globals while other reads ran
    mem_mb = mem_mb or MEM_MB; timeout = timeout or TIMEOUT
    root = os.path.join(os.path.dirname(__file__), "..")
    with tempfile.TemporaryDirectory(prefix="gac-read-") as td:
        src = os.path.join(td, "in.bin")
        with open(src, "wb") as fh: fh.write(data)
        out = os.path.join(td, "out"); os.mkdir(out)
        rest = [args[0], src, *[str(a) for a in args[1:]]] + ([out] if args[0] not in ("count", "ocr") else [])
        # v0.3: in the desktop app (PyInstaller) there is no 'python -m': the app's own exe runs the reader (launcher --gac-reader)
        argv = [sys.executable, "--gac-reader", *rest] if getattr(sys, "frozen", False) else [sys.executable, "-m", "app.reader", *rest]
        res_f = os.path.join(td, "result.json")   # the answer comes back in a file (a windowed exe may have no stdout)
        env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", GAC_READER_OUT=res_f)
        kw = {"preexec_fn": _limiter(mem_mb)} if os.name == "posix" else {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        p = subprocess.Popen(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env, text=True, **kw)
        if key: RUNNING[key] = p
        import threading, time
        killed = []
        def watch():
            t0 = time.time()
            while p.poll() is None:
                # audit 2026-10: the hard backstop is enforced here too; macOS ignores RLIMIT_AS and Windows has no RLIMIT
                if _rss_mb(p.pid) > min(mem_mb, backstop_mb(mem_mb)) or time.time() - t0 > timeout:
                    killed.append(1)
                    try: p.kill()
                    except Exception: pass
                    return
                time.sleep(0.1)
        threading.Thread(target=watch, daemon=True).start()
        try: so, se = p.communicate()
        finally:
            if key: RUNNING.pop(key, None)
        if killed: raise ReaderError(CALM)
        if p.returncode != 0:
            if p.returncode == -9 and key and key in CANCELLED: raise ReaderError("Cancelled.")
            raise ReaderError(CALM)
        try:
            if os.path.exists(res_f):
                with open(res_f, encoding="utf-8") as fh: r = json.load(fh)
            else: r = json.loads(so.strip().splitlines()[-1])
        except Exception: raise ReaderError(CALM)
        if r.get("error"): raise ReaderError(r["error"])
        if "ocr" in r: return r["ocr"]
        if "parts" in r and r["parts"] is not None:
            parts = []
            for path, label in r["parts"]:
                with open(path, "rb") as fh: parts.append((fh.read(), label))
            return parts
        return r


def _rss_mb(pid):
    """Resident memory of the child in MB. Audit 2026-10 P1 (C4): /proc only exists on Linux; Windows and macOS have no
    RLIMIT backstop either, so without this the memory cap did nothing there (only the time limit applied)."""
    try:
        with open(f"/proc/{pid}/status") as fh:
            for ln in fh:
                if ln.startswith("VmRSS:"): return int(ln.split()[1]) / 1024
    except FileNotFoundError: pass
    except Exception: return 0
    if os.name == "nt": return _rss_windows(pid)
    if sys.platform == "darwin": return _rss_ps(pid)
    return 0
def _rss_windows(pid):
    try:
        import ctypes
        from ctypes import wintypes
        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.windll.kernel32; h = k32.OpenProcess(0x1000 | 0x0010, False, pid)   # QUERY_LIMITED_INFORMATION | VM_READ
        if not h: return 0
        try:
            m = PMC(); m.cb = ctypes.sizeof(PMC)
            if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb): return m.WorkingSetSize / (1024 * 1024)
        finally: k32.CloseHandle(h)
    except Exception: pass
    return 0
_PS_LAST = {}
def _rss_ps(pid):
    import time
    t, v = _PS_LAST.get(pid, (0, 0))
    if time.time() - t < 0.5: return v   # ps costs a process start: at most twice a second
    try: v = int(subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=2).stdout.strip() or 0) / 1024
    except Exception: v = 0
    _PS_LAST[pid] = (time.time(), v); return v


CANCELLED = set()
def stop(key):
    """Cancel: kill the reader child working for this job, if any."""
    CANCELLED.add(key)
    p = RUNNING.get(key)
    if p and p.poll() is None:
        try: p.kill()
        except Exception: pass


OCR_MEM_MB = int(os.environ.get("OCR_MEM_MB", "1500"))    # OCR child RSS cap (round 22: RSS, not address space)
OCR_TIMEOUT = float(os.environ.get("OCR_TIMEOUT", "180"))
def run_ocr(data, engine=None, key=None):
    """Round 21: OCR + parsing run in a capped child process, so the web server's memory stays flat."""
    return _call(["ocr", engine or ""], data, key, mem_mb=OCR_MEM_MB, timeout=OCR_TIMEOUT)

def run_count(data): return _call(["count"], data)["pages"]
def run_page(data, i, n, fname, key=None): return _call(["page", i, n, os.path.basename(fname or "upload")], data, key)
def run_photo(data, fname, key=None):
    r = _call(["photo", os.path.basename(fname or "upload")], data, key)
    return r if isinstance(r, list) else None


def _main(argv):
    from . import formats
    mode, src = argv[0], argv[1]
    with open(src, "rb") as fh: data = fh.read()
    try:
        if mode == "count": return {"pages": formats.pdf_page_count(data)}
        if mode == "page":
            i, n, fname, out = int(argv[2]), int(argv[3]), argv[4], argv[5]
            stem = os.path.splitext(fname)[0]
            im = formats.render_page(data, i); del data
            parts = formats.page_parts(im, stem, i + 1, n); del im
            res = []
            for k, (jpg, lab) in enumerate(parts):
                p = os.path.join(out, f"{k}.jpg")
                with open(p, "wb") as fh: fh.write(jpg)
                res.append([p, lab])
            return {"parts": res}
        if mode == "ocr":
            from . import pipeline
            r = pipeline.scan(data, argv[2] or None, use_vlm=False)
            return {"ocr": {"engine": r["engine"], "text": r["text"], "fields": r["fields"]}}
        if mode == "photo":
            fname, out = argv[2], argv[3]
            parts = formats.expand(data, fname)
            if parts is None: return {"parts": None}
            res = []
            for k, (jpg, lab) in enumerate(parts):
                p = os.path.join(out, f"{k}.jpg")
                with open(p, "wb") as fh: fh.write(jpg)
                res.append([p, lab])
            return {"parts": res}
    except formats.FormatError as e:
        return {"error": str(e)}
    except MemoryError:
        return {"error": CALM}
    return {"error": "unknown mode"}


def cli(argv):
    """Entry point of the reader child (python -m app.reader …, or the desktop exe with --gac-reader …)."""
    res = json.dumps(_main(argv), default=str)
    if os.environ.get("GAC_READER_OUT"):
        with open(os.environ["GAC_READER_OUT"], "w", encoding="utf-8") as fh: fh.write(res)
    if sys.stdout is not None:
        try: print(res, flush=True)
        except Exception: pass


if __name__ == "__main__":
    cli(sys.argv[1:])
