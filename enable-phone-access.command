#!/bin/bash
# RETIRED (round 11). Phones no longer need the whole scanner on the Wi-Fi or an HTTPS certificate.
echo "Phone scanning is now built in: in the scanner, open Scan cards -> 'Scan with phone' and scan the QR code"
echo "with the phone (same office Wi-Fi). The scanner opens a short-lived phone link on port 8766 only while"
echo "a pairing is live. See docs/PHONE-MODE.md. (Advanced: 'python -m app.make_cert' still creates a"
echo "certificate for live camera preview; it is optional.)"
read -r -p "Press Enter to close..."
