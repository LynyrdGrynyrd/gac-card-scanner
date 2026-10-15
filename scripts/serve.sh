#!/bin/bash
# Headless launcher (servers / the pilot box). Round 9: listens on 127.0.0.1 unless GAC_HOST says otherwise.
#   GAC_HOST=0.0.0.0 scripts/serve.sh      # open the whole app to the network on purpose
#   PORT=8765 VLM_URL=http://127.0.0.1:8090 scripts/serve.sh
# Round 20: SUPERVISED. If the scanner process dies (crash, out of memory) it is started again by itself after a short
# pause (2 s, growing to 30 s if it keeps dying quickly). Stop it with Ctrl+C or `kill <pid of this script>`.
#   GAC_SUPERVISE=0 scripts/serve.sh        # old behaviour: run once, no restart
cd "$(dirname "$0")/.." || exit 1
HOST="${GAC_HOST:-127.0.0.1}"; PORT="${PORT:-8765}"
[ "$HOST" = "127.0.0.1" ] || echo "!! GAC_HOST=$HOST: the whole scanner is reachable from the network." >&2
PY="${GAC_PYTHON:-.venv/bin/python}"
if [ "${GAC_SUPERVISE:-1}" = "0" ]; then exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"; fi
child=0; stopping=0
trap 'stopping=1; [ $child -gt 0 ] && kill -TERM $child 2>/dev/null' TERM INT
delay=2
while :; do
  start=$(date +%s)
  "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@" &
  child=$!
  wait $child; code=$?
  [ $stopping = 1 ] && wait $child 2>/dev/null && exit 0
  [ $stopping = 1 ] && exit 0
  ran=$(( $(date +%s) - start ))
  [ $ran -gt 60 ] && delay=2
  echo "$(date '+%F %T') scanner stopped (exit $code) after ${ran}s; restarting in ${delay}s" >&2
  sleep $delay & wait $!
  delay=$(( delay * 2 > 30 ? 30 : delay * 2 ))
done
