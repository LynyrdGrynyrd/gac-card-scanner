#!/bin/sh
# Restore a scanner backup.  Usage:  scripts/restore_backup.sh [backups/gac-backup-YYYYmmdd-HHMMSS.tgz]
# Without an argument it lists the backups.  STOP THE SCANNER FIRST (close its window / stop the service).
# The current data folder is moved aside to data.before-restore-<time> (nothing is deleted), the backup is checked
# (checksum + SQLite integrity) and unpacked, and the uploaded MC Trade contacts export (never in a backup) is kept.
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
if [ -z "$1" ]; then "$PY" -m app.backup --list; echo "Usage: $0 <backup file>"; exit 1; fi
[ -f "$1" ] || { echo "No such backup: $1"; exit 1; }
"$PY" -m app.backup --verify "$1" >/dev/null || { echo "The backup is damaged: not restored."; exit 1; }
if [ -z "$GAC_RESTORE_YES" ]; then
  printf "Restore %s over the scanner's data? The current data is moved aside first. Type YES: " "$1"; read ans
  [ "$ans" = "YES" ] || { echo "Not restored."; exit 1; }
fi
exec "$PY" -m app.backup --restore "$1"
