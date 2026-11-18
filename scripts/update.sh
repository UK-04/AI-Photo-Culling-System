#!/usr/bin/env bash
# Install an update and rebuild Culler in one step:
#
#   ./scripts/update.sh                       # uses the newest culler-update-*.zip in ~/Downloads
#   ./scripts/update.sh ~/Downloads/some.zip
#
# It quits Culler, unpacks the update over this project, rebuilds the engine only if the
# engine changed, rebuilds the app, puts it in /Applications and opens it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ZIP="${1:-$(ls -t "$HOME"/Downloads/culler-update-*.zip 2>/dev/null | head -1 || true)}"
if [[ -z "$ZIP" || ! -f "$ZIP" ]]; then
  echo "No update found. Download the culler-update zip to your Downloads folder, or pass its path." >&2
  exit 1
fi
echo "Installing $(basename "$ZIP")"

osascript -e 'quit app "Culler"' >/dev/null 2>&1 || true
unzip -oq "$ZIP" -d "$ROOT"

# shellcheck source=/dev/null
source "$ROOT/scripts/engine_signature.sh"
BIN="$ROOT/app/src-tauri/binaries"
if [[ ! -f "$BIN/.engine-signature" || "$(cat "$BIN/.engine-signature")" != "$(engine_signature "$ROOT")" ]]; then
  echo "The engine changed: rebuilding it (several minutes)"
  "$ROOT/scripts/build_engine.sh"
else
  echo "The engine did not change: skipping its rebuild"
fi

"$ROOT/scripts/build_app.sh"

APP="$(ls -d "$ROOT"/app/src-tauri/target/*/release/bundle/macos/Culler.app 2>/dev/null | head -1 || true)"
if [[ -z "$APP" ]]; then
  echo "The build finished but Culler.app was not found. Paste the output above to get it fixed." >&2
  exit 1
fi
rm -rf /Applications/Culler.app
ditto "$APP" /Applications/Culler.app
echo "Updated /Applications/Culler.app"
open /Applications/Culler.app
