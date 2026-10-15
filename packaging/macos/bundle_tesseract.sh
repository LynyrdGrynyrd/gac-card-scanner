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
# license texts of Tesseract and of every Homebrew library bundled with it (Leptonica, libtiff, libpng, ...), shipped in
# the app as tesseract/licenses/ (THIRD-PARTY-NOTICES.md points there); the Windows build copies UB-Mannheim's doc folder
mkdir -p "$D/licenses"
for p in tesseract $(brew deps --installed tesseract); do
  pre="$(brew --prefix "$p")"
  for f in "$pre"/LICENSE* "$pre"/LICENCE* "$pre"/COPYING* "$pre"/COPYRIGHT* "$pre"/NOTICE*; do
    if [ -f "$f" ]; then cp "$f" "$D/licenses/$p-$(basename "$f")"; fi
  done
done
ls "$D/licenses"
# prove it runs without Homebrew paths
otool -L "$D/tesseract"; ! otool -L "$D/tesseract" "$D"/libs/*.dylib | grep -E "/opt/homebrew|/usr/local/(opt|Cellar)"
TESSDATA_PREFIX="$D/tessdata" "$D/tesseract" --version
