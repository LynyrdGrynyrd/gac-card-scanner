#!/bin/bash
# Optional AI double-check: ./start-ai-checker.command in another window (see HANDOFF.md).
# GAC Card Scanner: double-click to start (macOS). Leave this window open while you work.
cd "$(dirname "$0")" || exit 1
PORT=8765
echo "=== Greater Akron Chamber · Card Scanner (internal pilot) ==="
# Round 9: the scanner listens on THIS computer only (127.0.0.1) by default, with or without certificates.
# Phone mode (Upload → "Scan with a phone") opens its own small LAN listener just for the phone page while a pairing
# is live. To open the whole app to the network on purpose, start it with GAC_HOST=0.0.0.0 (or a LAN address).
HOST="${GAC_HOST:-127.0.0.1}"
if [ -f certs/cert.pem ] && [ -f certs/key.pem ]; then
  SCHEME=https; SSL="--ssl-certfile certs/cert.pem --ssl-keyfile certs/key.pem"
else
  SCHEME=http; SSL=""
fi
if [ "$HOST" = "127.0.0.1" ] || [ "$HOST" = "localhost" ]; then echo "Listening on this computer only ($HOST). Phones: use Upload -> Scan with a phone.";
else echo "!! GAC_HOST=$HOST: the whole scanner is reachable from the network. Unset GAC_HOST to go back to this computer only."; fi
URL="$SCHEME://localhost:$PORT/ui"
if curl -ks "$SCHEME://localhost:$PORT/health" >/dev/null 2>&1; then echo "Already running."; open "$URL"; exit 0; fi
PY=$(command -v python3)
if [ -z "$PY" ]; then echo; echo "Python 3 is not installed. Install it from https://www.python.org/downloads/ then double-click this file again."; read -r -p "Press Enter to close..."; exit 1; fi
if [ ! -x .venv/bin/python ]; then echo "First-time setup (takes a few minutes)..."; "$PY" -m venv .venv || { read -r -p "Could not create environment. Press Enter..."; exit 1; }; fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
.venv/bin/python -m pip install -q -r requirements.txt || { echo "Installing components failed (check the internet connection)."; read -r -p "Press Enter to close..."; exit 1; }
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v tesseract >/dev/null 2>&1; then
  echo; echo "!! The card-reading engine (Tesseract) is not installed."
  echo "   Ask IT to install it, or: install Homebrew (https://brew.sh) then run:  brew install tesseract"
  echo "   The app will open, but scanning will fail until Tesseract is installed."; echo
fi
(sleep 4; open "$URL") &
echo "Starting... your browser will open $URL"
echo "First time? The browser asks you to create the admin account."
echo "To stop the scanner, close this window."
exec .venv/bin/python -m uvicorn app.main:app --host $HOST --port $PORT $SSL
