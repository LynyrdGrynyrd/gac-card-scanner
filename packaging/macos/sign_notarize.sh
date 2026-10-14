#!/bin/bash
# Developer ID sign + notarize + staple a .app and its .dmg. Does nothing (exit 0) unless the secrets are present,
# so unsigned/ad-hoc builds keep working. Needs (GitHub secrets -> env):
#   MACOS_CERT_P12_BASE64, MACOS_CERT_PASSWORD   Developer ID Application certificate (.p12, base64)
#   MACOS_SIGN_IDENTITY                          e.g. "Developer ID Application: Greater Akron Chamber (TEAMID1234)"
#   APPLE_API_KEY_BASE64, APPLE_API_KEY_ID, APPLE_API_ISSUER   App Store Connect API key (.p8) for notarytool
# Usage: sign_notarize.sh "dist/GAC Card Scanner.app" [dist/file.dmg]
set -euo pipefail
APP="$1"; DMG="${2:-}"
if [ -z "${MACOS_CERT_P12_BASE64:-}" ] || [ -z "${MACOS_SIGN_IDENTITY:-}" ]; then echo "macOS signing secrets not set: keeping ad-hoc signature."; exit 0; fi
KC="$RUNNER_TEMP/gac-sign.keychain-db"; KCPW="$(openssl rand -hex 16)"
echo "$MACOS_CERT_P12_BASE64" | base64 --decode > "$RUNNER_TEMP/cert.p12"
security create-keychain -p "$KCPW" "$KC"; security set-keychain-settings -lut 3600 "$KC"; security unlock-keychain -p "$KCPW" "$KC"
security import "$RUNNER_TEMP/cert.p12" -k "$KC" -P "$MACOS_CERT_PASSWORD" -T /usr/bin/codesign
security set-key-partition-list -S apple-tool:,apple: -s -k "$KCPW" "$KC" >/dev/null
security list-keychains -d user -s "$KC" $(security list-keychains -d user | tr -d '"')
rm -f "$RUNNER_TEMP/cert.p12"
ENT="$(dirname "$0")/entitlements.plist"
# sign inside-out: nested dylibs/so/executables first, then the bundle (hardened runtime + timestamp are required for notarization)
find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) -print0 | while IFS= read -r -d '' f; do
  codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$MACOS_SIGN_IDENTITY" "$f" 2>/dev/null || true; done
codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$MACOS_SIGN_IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
if [ -n "${APPLE_API_KEY_BASE64:-}" ]; then
  echo "$APPLE_API_KEY_BASE64" | base64 --decode > "$RUNNER_TEMP/AuthKey.p8"
  TARGET="$DMG"; if [ -z "$TARGET" ]; then TARGET="$RUNNER_TEMP/app.zip"; ditto -c -k --keepParent "$APP" "$TARGET"; fi
  [ -n "$DMG" ] && codesign --force --timestamp --sign "$MACOS_SIGN_IDENTITY" "$DMG"
  xcrun notarytool submit "$TARGET" --key "$RUNNER_TEMP/AuthKey.p8" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER" --wait --timeout 30m
  if [ -n "$DMG" ]; then xcrun stapler staple "$DMG"; else xcrun stapler staple "$APP"; fi
  rm -f "$RUNNER_TEMP/AuthKey.p8"; spctl -a -vv -t install "${DMG:-$APP}" || true
else echo "No App Store Connect API key: signed but NOT notarized (Gatekeeper will still warn)."; fi
security delete-keychain "$KC" || true
