#!/bin/sh
# Serve HTTPS when a certificate is mounted at /srv/gac/certs (see HANDOFF.md), otherwise plain HTTP.
if [ -f certs/cert.pem ] && [ -f certs/key.pem ]; then
  exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --ssl-certfile certs/cert.pem --ssl-keyfile certs/key.pem
fi
exec python -m uvicorn app.main:app --host "${GAC_HOST:-0.0.0.0}" --port 8765   # inside a container 0.0.0.0 is needed; publish the port on 127.0.0.1 only (docker-compose.yml)
