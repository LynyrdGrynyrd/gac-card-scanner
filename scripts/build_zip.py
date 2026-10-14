"""Build the portable pilot zip next to the project folder: ../gac-card-scanner-pilot.zip
Excludes the virtualenv, databases, card photos, export copies, certificates, QA backups and caches."""
import os, sys, zipfile, fnmatch, stat
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "gac-card-scanner-pilot"; OUT = os.path.join(os.path.dirname(ROOT), NAME + ".zip")
EXCL_DIRS = {".venv", "__pycache__", ".git", "certs", "qa-backup-uploads", "vlm_cache", "newcomer", "skeptic", "reviewer", "newcomer-r2", "skeptic-r2", "reviewer-r2", "newcomer-r3", "skeptic-r3", "reviewer-r3", "newcomer-r4", "skeptic-r4", "reviewer-r4", "manager-r1", "mctrade-r1", "mctrade-r1-shots", "mctrade-r1-exports", "newcomer-r5", "skeptic-r5", "reviewer-r5", "manager-r2", "mctrade-r2-exports", "manager-r1-shots", "inbox", "jobs_done", "raw", "corrections", "thumbs", "backups"}   # round 9: never ship backups
EXCL_FILES = ["*.pyc", "*.db", "*.db-*", "server.log", "server.log.*", "mctrade_contacts.*", "*.zip", ".workers.lock"]
EXCLUDE_EXTRA = {"qa/TEST-LOGINS.md"}
EMPTY_DIRS = ["data/uploads", "data/exports"]
EXEC = {"start.command", "start-ai-checker.command", "enable-phone-access.command", "docker-entrypoint.sh", "reset_demo.sh", "build_zip.sh", "serve.sh", "backup.sh", "restore_backup.sh"}
def main():
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for d, dirs, files in os.walk(ROOT):
            rel = os.path.relpath(d, ROOT)
            dirs[:] = [x for x in dirs if x not in EXCL_DIRS and os.path.join(rel, x).replace("\\", "/").lstrip("./") not in EMPTY_DIRS]
            for f in files:
                if any(fnmatch.fnmatch(f, p) for p in EXCL_FILES): continue
                if os.path.relpath(os.path.join(d, f), ROOT).replace("\\", "/") in EXCLUDE_EXTRA: continue
                p = os.path.join(d, f); arc = os.path.join(NAME, os.path.relpath(p, ROOT)).replace("\\", "/")
                zi = zipfile.ZipInfo.from_file(p, arc); zi.compress_type = zipfile.ZIP_DEFLATED
                if f in EXEC: zi.external_attr = (0o100755 & 0xFFFF) << 16
                with open(p, "rb") as fh: z.writestr(zi, fh.read()); n += 1
        try:   # round 11: the install knows which commit it was built from (shown in the footer and /health)
            import subprocess
            c = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
            if c: z.writestr(f"{NAME}/COMMIT", c + "\n")
        except Exception: pass
        for e in EMPTY_DIRS:
            zd = zipfile.ZipInfo(f"{NAME}/{e}/"); zd.external_attr = ((0o40755 & 0xFFFF) << 16) | 0x10; z.writestr(zd, "")
    print(f"Built {OUT}: {n} files, {os.path.getsize(OUT)/1e6:.1f} MB")
if __name__ == "__main__": sys.exit(main())
