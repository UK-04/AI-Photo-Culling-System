#!/usr/bin/env bash
# Build the Python engine into a self-contained binary and place it where Tauri expects
# its sidecar. Run on the Mac you are building for (Apple Silicon).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/engine"

"$ROOT/scripts/fetch_models.sh"

python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip
pip install -e ".[clip,build]"

pyinstaller engine.spec --noconfirm --clean

TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"     # e.g. aarch64-apple-darwin
BIN="$ROOT/app/src-tauri/binaries"
rm -rf "$BIN" && mkdir -p "$BIN"
# One-folder build: Tauri ships the launcher as the sidecar and the folder as a resource.
cp -R dist/culler-engine "$BIN/culler-engine-dist"
cat > "$BIN/culler-engine-$TRIPLE" <<'LAUNCH'
#!/bin/sh
# Sidecar launcher: runs the real engine from the app's Resources folder.
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/../Resources/binaries/culler-engine-dist/culler-engine" "$@"
LAUNCH
chmod +x "$BIN/culler-engine-$TRIPLE"
# Prove the packaged engine really starts before anything is built on top of it.
"$ROOT/engine/dist/culler-engine/culler-engine" --version
"$ROOT/engine/dist/culler-engine/culler-engine" selftest --vision
source "$ROOT/scripts/engine_signature.sh"
engine_signature "$ROOT" > "$BIN/.engine-signature"   # lets update.sh skip this step when nothing changed
echo "Engine built and starts correctly: $BIN/culler-engine-$TRIPLE"
