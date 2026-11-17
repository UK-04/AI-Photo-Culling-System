#!/usr/bin/env bash
# Launch the built Culler.app the way a user would and check that its engine comes up and
# answers. Catches packaging mistakes (a missing library, a sidecar that cannot start)
# that no unit test can see.
#   ./scripts/smoke_test_app.sh [expected version]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$(ls -d "$ROOT"/app/src-tauri/target/*/release/bundle/macos/Culler.app | head -1)"
EXPECTED="${1:-}"
echo "Testing $APP"
ls "$APP/Contents/MacOS" "$APP/Contents/Resources" | head -20

MAIN="$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$APP/Contents/Info.plist")"
"$APP/Contents/MacOS/$MAIN" > "${TMPDIR:-/tmp}/culler-app.log" 2>&1 &
APP_PID=$!
cleanup() { kill "$APP_PID" 2>/dev/null || true; }
trap cleanup EXIT

for _ in $(seq 1 90); do
  LINE="$(pgrep -fl "culler-engine.* serve " | grep -v pgrep | head -1 || true)"
  if [[ -n "$LINE" ]]; then
    PORT="$(sed -n 's/.*--port \([0-9]*\).*/\1/p' <<<"$LINE")"
    TOKEN="$(sed -n 's/.*--token \([^ ]*\).*/\1/p' <<<"$LINE")"
    if [[ -n "$PORT" ]] && curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      INFO="$(curl -fsS -H "X-Culler-Token: $TOKEN" "http://127.0.0.1:$PORT/info")"
      echo "Engine answered: $INFO"
      if [[ -n "$EXPECTED" ]] && ! grep -q "\"version\": *\"$EXPECTED\"" <<<"$INFO"; then
        echo "The engine reports a different version than $EXPECTED" >&2
        exit 1
      fi
      # Quitting the app must take the engine down with it.
      kill "$APP_PID"; sleep 6
      if pgrep -f "culler-engine.* serve " >/dev/null; then
        echo "The engine kept running after the app quit" >&2
        exit 1
      fi
      echo "App smoke test passed"
      exit 0
    fi
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "The app exited early. Its output:" >&2; cat "${TMPDIR:-/tmp}/culler-app.log" >&2; exit 1
  fi
  sleep 1
done
echo "The engine never answered. App output:" >&2
cat "${TMPDIR:-/tmp}/culler-app.log" >&2
exit 1
