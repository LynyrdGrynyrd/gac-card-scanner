#!/bin/bash
# make_dmg.sh <App.app> <out.dmg>: drag-to-Applications disk image via hdiutil (no extra tools needed).
set -euo pipefail
APP="$1"; OUT="$2"; STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/READ ME FIRST.txt" <<'TXT'
1. Drag "GAC Card Scanner" onto the Applications folder.
2. Open Applications, RIGHT-click (or Control-click) "GAC Card Scanner" and choose Open, then Open again.
   (macOS asks this once because the app is not notarized by Apple.)
   If macOS only offers "Move to Trash": System Settings > Privacy & Security > scroll down > "Open Anyway".
3. The scanner opens in its own window. Your data stays on this Mac:
   ~/Library/Application Support/GAC Card Scanner
TXT
rm -f "$OUT"
hdiutil create -volname "GAC Card Scanner" -srcfolder "$STAGE" -ov -format UDZO "$OUT"
rm -rf "$STAGE"; ls -la "$OUT"
