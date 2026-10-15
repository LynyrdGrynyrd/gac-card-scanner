"""Schemathesis API fuzzing: the same hermetic set-up as tests/unit/conftest.py. ALL runtime data goes to a temp folder that is
set before any app module is imported; the app is called in-process (no server, no lifespan: no workers, no update check)."""
import os, tempfile
os.environ.setdefault("OCR_CHILD", "0")
os.environ["GAC_ALLOW_REMOTE_SETUP"] = "1"; os.environ["GAC_ALLOWED_HOSTS"] = "testserver"; os.environ["VLM_URL"] = "http://127.0.0.1:9"
os.environ["GAC_DATA_DIR"] = tempfile.mkdtemp(prefix="gac-fuzz-")
os.environ["GAC_DB"] = os.path.join(os.environ["GAC_DATA_DIR"], "cards.db")
os.environ["MCTRADE_TEMPLATE"] = os.path.join(tempfile.mkdtemp(prefix="gac-fuzz-tpl-"), "mctrade_template.xlsx")
os.environ["GAC_BACKUP"] = "0"
