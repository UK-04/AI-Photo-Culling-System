#!/usr/bin/env bash
# Run the engine and the UI in a browser, no desktop shell. Good for development.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/app" && npm install && npm run build)
cd "$ROOT/engine"
exec python3 -m culler serve --port 8765 --token dev --ui "$ROOT/app/dist" "$@"
