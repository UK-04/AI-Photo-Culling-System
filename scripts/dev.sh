#!/usr/bin/env bash
# Run the engine and the UI in a browser, no desktop shell.
# Builds the UI only if it is missing and Node is installed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$ROOT/app/dist/index.html" ]]; then
  if command -v npm >/dev/null 2>&1; then
    (cd "$ROOT/app" && npm install && npm run build)
  else
    echo "The interface is not built and Node is not installed." >&2
    echo "Either install Node (brew install node) or unzip culler-ui.zip into the app folder." >&2
    exit 1
  fi
fi
cd "$ROOT/engine"
echo "Open http://127.0.0.1:8765/?token=dev"
exec python3 -m culler serve --port 8765 --token dev --ui "$ROOT/app/dist" "$@"
