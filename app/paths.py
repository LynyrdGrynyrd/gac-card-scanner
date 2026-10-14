"""Where runtime data lives. Default: <repo>/data (developer/Docker installs, unchanged).
Packaged desktop builds set GAC_DATA_DIR (e.g. %LOCALAPPDATA%\\GAC Card Scanner, ~/Library/Application Support/GAC Card Scanner)."""
import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.abspath(os.environ.get("GAC_DATA_DIR") or os.path.join(ROOT, "data"))
os.makedirs(DATA, exist_ok=True)
def data(*p): return os.path.join(DATA, *p)
def try_lock(fd):
    """Non-blocking exclusive lock on an open fd (flock on macOS/Linux, msvcrt on Windows). True if taken."""
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); return True
    except ImportError:
        import msvcrt
        try: os.lseek(fd, 0, 0); msvcrt.locking(fd, msvcrt.LK_NBLCK, 1); return True
        except OSError: return False
    except OSError: return False
