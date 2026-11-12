#!/bin/bash
# Builds Tesseract (with Leptonica and libpng) from pinned sources as ONE self-contained binary in
# packaging/build/tesseract, for macOS 14 or newer.
# Why (v0.4.14): Homebrew's tesseract on the macos-15 build machine needs macOS 15.8.1+, and inside the app its
# libtesseract dylib could be swapped for OpenCV's older copy (cv2/.dylibs) -> "Symbol not found" on Apple silicon.
# A static binary has no bundled dylibs to mix up; it links only system libraries (libz, libc++, libSystem, Accelerate).
# The language data (eng, osd) still comes from Homebrew's tesseract package, as before.
set -euo pipefail
MIN_MACOS="${GAC_MIN_MACOS:-14.0}"; export MACOSX_DEPLOYMENT_TARGET="$MIN_MACOS"
ARCH="$(uname -m)"; JOBS="$(sysctl -n hw.ncpu)"
TESS_V=5.5.4;  TESS_SHA=a8dbf8b8c8ee427ff6ad1d99116502feaf59440af1adb893caf60a6576826cf4
LEPT_V=1.87.0; LEPT_SHA=c73363397f96eb1295602bf44d708a994ad42046c791bf03ea0505d829bdb6a7
PNG_V=1.6.59;  PNG_SHA=d80dd2a38a37f803cb9b6ac7b14bd6e74ddc3b654780a8380bdf93523fdb4389
brew install cmake tesseract   # cmake to build; tesseract only for its eng/osd language data
ROOT="$(pwd)"; W="$ROOT/packaging/build/tess-src"; P="$W/prefix"; rm -rf "$W"; mkdir -p "$W" "$P"; cd "$W"
fetch() { curl -fsSL --retry 3 -o "$2" "$1"; echo "$3  $2" | shasum -a 256 -c -; }
fetch "https://download.sourceforge.net/libpng/libpng-$PNG_V.tar.xz" png.tar.xz "$PNG_SHA"
fetch "https://github.com/DanBloomberg/leptonica/releases/download/$LEPT_V/leptonica-$LEPT_V.tar.gz" lept.tar.gz "$LEPT_SHA"
fetch "https://github.com/tesseract-ocr/tesseract/archive/refs/tags/$TESS_V.tar.gz" tess.tar.gz "$TESS_SHA"
for t in png.tar.xz lept.tar.gz tess.tar.gz; do tar xf "$t"; done
COMMON=(-DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$P" -DCMAKE_PREFIX_PATH="$P" -DCMAKE_OSX_DEPLOYMENT_TARGET="$MIN_MACOS"
        -DCMAKE_OSX_ARCHITECTURES="$ARCH" -DBUILD_SHARED_LIBS=OFF -DCMAKE_FIND_FRAMEWORK=NEVER -DCMAKE_IGNORE_PREFIX_PATH="/opt/homebrew;/usr/local")
cmake -S "libpng-$PNG_V" -B b-png "${COMMON[@]}" -DPNG_SHARED=OFF -DPNG_STATIC=ON -DPNG_TESTS=OFF -DPNG_TOOLS=OFF -DPNG_FRAMEWORK=OFF
cmake --build b-png -j "$JOBS" && cmake --install b-png
cmake -S "leptonica-$LEPT_V" -B b-lept "${COMMON[@]}" -DSW_BUILD=OFF -DBUILD_PROG=OFF -DENABLE_ZLIB=ON -DENABLE_PNG=ON \
      -DENABLE_GIF=OFF -DENABLE_JPEG=OFF -DENABLE_TIFF=OFF -DENABLE_WEBP=OFF -DENABLE_OPENJPEG=OFF
cmake --build b-lept -j "$JOBS" && cmake --install b-lept
cmake -S "tesseract-$TESS_V" -B b-tess "${COMMON[@]}" -DBUILD_TRAINING_TOOLS=OFF -DBUILD_TESTS=OFF -DGRAPHICS_DISABLED=ON \
      -DDISABLE_ARCHIVE=ON -DDISABLE_CURL=ON -DDISABLE_TIFF=ON -DOPENMP_BUILD=OFF -DENABLE_CCACHE=OFF -DINSTALL_CONFIGS=ON
cmake --build b-tess -j "$JOBS" && cmake --install b-tess
cd "$ROOT"; D=packaging/build/tesseract; rm -rf "$D"; mkdir -p "$D/tessdata" "$D/licenses"
cp "$P/bin/tesseract" "$D/tesseract"; strip -x "$D/tesseract" || true
TD="$(brew --prefix tesseract)/share/tessdata"
cp "$TD/eng.traineddata" "$TD/osd.traineddata" "$D/tessdata/"
[ -d "$P/share/tessdata/configs" ] && cp -R "$P/share/tessdata/configs" "$D/tessdata/" || cp -R "$TD/configs" "$D/tessdata/"
cp "$W/tesseract-$TESS_V/LICENSE" "$D/licenses/tesseract-LICENSE"
cp "$W/leptonica-$LEPT_V/leptonica-license.txt" "$D/licenses/leptonica-LICENSE" 2>/dev/null || cp "$W/leptonica-$LEPT_V/LICENSE" "$D/licenses/leptonica-LICENSE"
cp "$W/libpng-$PNG_V/LICENSE" "$D/licenses/libpng-LICENSE"
codesign --force --sign - "$D/tesseract"
# prove: only system libraries, built for macOS $MIN_MACOS, and it runs
otool -L "$D/tesseract"; ! otool -L "$D/tesseract" | tail -n +2 | grep -vE "^\s*(/usr/lib/|/System/Library/)"
vtool -show-build "$D/tesseract" | grep -E "minos|sdk"
mo="$(vtool -show-build "$D/tesseract" | awk '/minos/{print $2; exit}')"; [ "$mo" = "$MIN_MACOS" ] || { echo "minos $mo != $MIN_MACOS"; exit 1; }
TESSDATA_PREFIX="$D/tessdata" "$D/tesseract" --version
TESSDATA_PREFIX="$D/tessdata" "$D/tesseract" --list-langs
rm -rf "$W"
