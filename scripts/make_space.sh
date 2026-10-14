#!/bin/sh
# Build the Hugging Face Space folder from this repo: ./scripts/make_space.sh [out-dir]   (default ../gac-card-scanner-space)
# The Space needs README.md (with the YAML header) and Dockerfile at its root; everything else is copied as is.
set -eu
OUT="${1:-../gac-card-scanner-space}"; SRC="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"
for p in app data/existing_contacts.csv tests/synth2 tests/synth2_gt.json space requirements.txt LICENSE THIRD-PARTY-NOTICES.md; do
  mkdir -p "$OUT/$(dirname "$p")"; rm -rf "$OUT/$p"; cp -r "$SRC/$p" "$OUT/$p"
done
find "$OUT" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$SRC/Dockerfile.space" "$OUT/Dockerfile"
cp "$SRC/space/README.md" "$OUT/README.md"
echo "Space folder ready: $OUT"
