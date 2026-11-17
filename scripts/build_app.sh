#!/usr/bin/env bash
# Build Culler.app and the DMG. Signs when APPLE_SIGNING_IDENTITY is set, e.g.
#   export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

[[ -d "$ROOT/app/src-tauri/binaries" ]] || "$ROOT/scripts/build_engine.sh"
if ! "$ROOT/app/src-tauri/binaries/culler-engine-dist/culler-engine" --version; then
  echo "The packaged engine does not start. Run ./scripts/build_engine.sh and fix its error first." >&2
  exit 1
fi

if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  # Every Mach-O file inside the engine must be signed with the hardened runtime
  # before the app is sealed, or notarization rejects the bundle.
  echo "Signing engine binaries"
  find "$ROOT/app/src-tauri/binaries/culler-engine-dist" -type f \( -name "*.so" -o -name "*.dylib" -o -perm +111 \) -print0 |
    while IFS= read -r -d '' f; do
      if file "$f" | grep -q "Mach-O"; then
        codesign --force --options runtime --timestamp \
          --entitlements "$ROOT/app/src-tauri/entitlements.plist" \
          --sign "$APPLE_SIGNING_IDENTITY" "$f"
      fi
    done
else
  echo "APPLE_SIGNING_IDENTITY is not set: building an unsigned app (fine for your own Mac)."
fi

cd "$ROOT/app"
npm ci
npm run tauri build -- --target aarch64-apple-darwin
echo "Built: $ROOT/app/src-tauri/target/aarch64-apple-darwin/release/bundle/"
