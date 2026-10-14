#!/bin/bash
# Turns on phone access: creates an HTTPS certificate so phones on the same Wi-Fi can use the scanner and camera.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then echo "Run start.command once first (it installs the components)."; read -r -p "Press Enter..."; exit 1; fi
.venv/bin/python -m app.make_cert
echo; echo "Now close the scanner window (if open) and double-click start.command again."
echo "To turn phone access off again, delete the 'certs' folder."
read -r -p "Press Enter to close..."
