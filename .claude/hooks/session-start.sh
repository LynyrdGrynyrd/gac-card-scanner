#!/bin/bash
# Claude Code cloud sessions: install what the unit tests, the accuracy gates and ruff need (see CLAUDE.md).
# Idempotent; the container is cached after this runs, so later sessions start fast.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "$CLAUDE_PROJECT_DIR"

# Tesseract 5 (system package): OCR in tests/eval.py, bench/eval_bench.py and several unit tests
if ! command -v tesseract >/dev/null 2>&1; then
  SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  $SUDO apt-get update -q && $SUDO apt-get install -y -q tesseract-ocr
fi

# Python deps in a project venv (.venv is git-ignored): the fully pinned lock, plus the test tools CI uses
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.lock.txt
if [ -f requirements-dev.txt ]; then .venv/bin/python -m pip install -q --disable-pip-version-check -r requirements-dev.txt
else .venv/bin/python -m pip install -q --disable-pip-version-check pytest==9.1.1 httpx==0.28.1; fi
.venv/bin/python -m pip install -q --disable-pip-version-check ruff==0.17.0   # the version the CI lint job pins

# put the venv first on PATH for the session (python, pytest, ruff)
echo "export VIRTUAL_ENV=\"$CLAUDE_PROJECT_DIR/.venv\"" >> "$CLAUDE_ENV_FILE"
echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
