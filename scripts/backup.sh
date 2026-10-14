#!/bin/sh
# Make a backup of the scanner's data now (the scanner also does this every night at 02:30 and keeps 7).
# GAC_BACKUP_DIR=/path/on/another/disk scripts/backup.sh
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" -m app.backup "$@"
