#!/bin/bash
# Headless launcher (servers / the pilot box). Round 9: listens on 127.0.0.1 unless GAC_HOST says otherwise.
#   GAC_HOST=0.0.0.0 scripts/serve.sh      # open the whole app to the network on purpose
#   PORT=8765 VLM_URL=http://127.0.0.1:8090 scripts/serve.sh
cd "$(dirname "$0")/.." || exit 1
HOST="${GAC_HOST:-127.0.0.1}"; PORT="${PORT:-8765}"
[ "$HOST" = "127.0.0.1" ] || echo "!! GAC_HOST=$HOST: the whole scanner is reachable from the network." >&2
exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
