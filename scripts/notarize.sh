#!/usr/bin/env bash
# Notarize and staple the DMG. One-time setup:
#   xcrun notarytool store-credentials culler-notary --apple-id you@example.com --team-id TEAMID
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DMG="$(ls "$ROOT"/app/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg/*.dmg | head -1)"
PROFILE="${NOTARY_PROFILE:-culler-notary}"

xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"
spctl --assess --type open --context context:primary-signature -v "$DMG"
echo "Notarized: $DMG"
