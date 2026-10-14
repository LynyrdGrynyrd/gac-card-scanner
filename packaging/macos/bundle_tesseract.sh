#!/bin/bash
# Copies Homebrew's tesseract + its dylibs into packaging/build/tesseract and rewrites load paths to @executable_path/libs.
set -euo pipefail
brew install tesseract dylibbundler
D=packaging/build/tesseract; rm -rf "$D"; mkdir -p "$D/libs" "$D/tessdata"
cp "$(brew --prefix tesseract)/bin/tesseract" "$D/tesseract"; chmod u+w "$D/tesseract"
dylibbundler -of -cd -b -x "$D/tesseract" -d "$D/libs" -p @executable_path/libs/
TD="$(brew --prefix tesseract)/share/tessdata"
cp "$TD/eng.traineddata" "$TD/osd.traineddata" "$D/tessdata/"
for f in "$D/tesseract" "$D"/libs/*.dylib; do codesign --force --sign - "$f"; done
# prove it runs without Homebrew paths
otool -L "$D/tesseract"; ! otool -L "$D/tesseract" "$D"/libs/*.dylib | grep -E "/opt/homebrew|/usr/local/(opt|Cellar)"
TESSDATA_PREFIX="$D/tessdata" "$D/tesseract" --version
