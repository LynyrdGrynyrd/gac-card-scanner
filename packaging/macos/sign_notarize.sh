#!/bin/bash
# Developer ID sign + notarize + staple a .app and its .dmg. Does nothing (exit 0) unless the secrets are present,
# so unsigned/ad-hoc builds keep working. Needs (GitHub secrets -> env):
#   MACOS_CERT_P12_BASE64, MACOS_CERT_PASSWORD   Developer ID Application certificate (.p12, base64)
#   MACOS_SIGN_IDENTITY                          e.g. "Developer ID Application: Greater Akron Chamber (TEAMID1234)"
#   APPLE_API_KEY_BASE64, APPLE_API_KEY_ID, APPLE_API_ISSUER   App Store Connect API key (.p8) for notarytool
# Usage (the release workflow runs both, in this order):
#   sign_notarize.sh --sign-only "dist/GAC Card Scanner.app"            sign the app (before the DMG is made)
#   sign_notarize.sh "dist/GAC Card Scanner.app" dist/file.dmg          sign the DMG, notarize it, staple it
#   sign_notarize.sh "dist/GAC Card Scanner.app"                        sign the app, notarize + staple the app itself
# Any signing failure stops the script (and the build): nothing is hidden with "|| true".
set -euo pipefail
SIGN_ONLY=0; if [ "${1:-}" = "--sign-only" ]; then SIGN_ONLY=1; shift; fi
APP="$1"; DMG="${2:-}"
if [ -z "${MACOS_CERT_P12_BASE64:-}" ] || [ -z "${MACOS_SIGN_IDENTITY:-}" ]; then echo "macOS signing secrets not set: keeping ad-hoc signature."; exit 0; fi
TMP="${RUNNER_TEMP:-$(mktemp -d)}"
KC="$TMP/gac-sign.keychain-db"; KCPW="$(openssl rand -hex 16)"
cleanup() { security delete-keychain "$KC" >/dev/null 2>&1 || true; rm -f "$TMP/cert.p12" "$TMP/AuthKey.p8"; }
trap cleanup EXIT
echo "$MACOS_CERT_P12_BASE64" | base64 --decode > "$TMP/cert.p12"
security create-keychain -p "$KCPW" "$KC"; security set-keychain-settings -lut 3600 "$KC"; security unlock-keychain -p "$KCPW" "$KC"
security import "$TMP/cert.p12" -k "$KC" -P "$MACOS_CERT_PASSWORD" -T /usr/bin/codesign
security set-key-partition-list -S apple-tool:,apple: -s -k "$KCPW" "$KC" >/dev/null
# shellcheck disable=SC2046  # one argument per existing keychain path (the list is newline-separated)
security list-keychains -d user -s "$KC" $(security list-keychains -d user | tr -d '"')
rm -f "$TMP/cert.p12"
ENT="$(dirname "$0")/entitlements.plist"

signed_by_us() {   # the app already carries a valid signature from our Developer ID (a check, not a hidden failure)
  codesign --verify --strict "$1" >/dev/null 2>&1 && codesign -dvv "$1" 2>&1 | grep -qF "Authority=$MACOS_SIGN_IDENTITY"
}
sign_app() {
  # inside-out: nested Mach-O code first (dylibs, .so, executables; deepest paths first), then the bundle.
  # Hardened runtime + timestamp are required for notarization. Non-Mach-O files (scripts, data marked executable) are
  # sealed by the bundle signature and are not signed one by one.
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q "Mach-O"; then
      codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$MACOS_SIGN_IDENTITY" "$f"
    fi
  done < <(find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) -print0 | sort -z -r)
  codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$MACOS_SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
}

if [ -n "$DMG" ]; then
  # the DMG already contains the app, so the app must have been signed BEFORE the DMG was made (--sign-only step)
  signed_by_us "$APP" || { echo "The app is not signed with '$MACOS_SIGN_IDENTITY': run '$0 --sign-only <app>' before making the DMG." >&2; exit 1; }
else
  sign_app
fi
[ "$SIGN_ONLY" = 1 ] && { echo "Signed $APP (notarization happens with the DMG)."; exit 0; }

[ -n "$DMG" ] && codesign --force --timestamp --sign "$MACOS_SIGN_IDENTITY" "$DMG"
if [ -n "${APPLE_API_KEY_BASE64:-}" ]; then
  echo "$APPLE_API_KEY_BASE64" | base64 --decode > "$TMP/AuthKey.p8"
  TARGET="$DMG"; if [ -z "$TARGET" ]; then TARGET="$TMP/app.zip"; ditto -c -k --keepParent "$APP" "$TARGET"; fi
  xcrun notarytool submit "$TARGET" --key "$TMP/AuthKey.p8" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER" --wait --timeout 30m
  if [ -n "$DMG" ]; then xcrun stapler staple "$DMG"; else xcrun stapler staple "$APP"; fi
  # Gatekeeper's verdict, for the log (a notarized + stapled image says "accepted, source=Notarized Developer ID")
  if [ -n "$DMG" ]; then spctl -a -vv -t open --context context:primary-signature "$DMG" || true; else spctl -a -vv "$APP" || true; fi
else echo "No App Store Connect API key: signed but NOT notarized (Gatekeeper will still warn)."; fi
