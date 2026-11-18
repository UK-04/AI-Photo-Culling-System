#!/usr/bin/env bash
# Check that this Mac has what the app build needs, and say how to get what is missing.
ok=1
need() { # name, test command, how to install
  if eval "$2" >/dev/null 2>&1; then echo "ok       $1"; else echo "MISSING  $1  ->  $3"; ok=0; fi
}
[[ "$(uname -s)" == "Darwin" ]] || { echo "This must run on a Mac."; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || echo "note     This Mac is Intel. In scripts/build_app.sh and engine/engine.spec, change aarch64/arm64 to x86_64."
need "Xcode command line tools" "xcode-select -p" "xcode-select --install"
need "Homebrew"                 "command -v brew" 'see https://brew.sh'
need "Node 20+"                 'node -e "process.exit(process.versions.node.split(\".\")[0] >= 20 ? 0 : 1)"' "brew install node"
need "Rust"                     "command -v cargo" "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh   (then open a new Terminal window)"
need "Python 3.11+"             'python3 -c "import sys; sys.exit(sys.version_info < (3, 11))"' "brew install python@3.12"
need "Face models"              "test -f \"$(dirname "$0")/../engine/culler/assets/models/face_landmarker.task\"" "./scripts/fetch_models.sh"
[[ $ok == 1 ]] && echo "Ready. Next: ./scripts/build_engine.sh && ./scripts/build_app.sh" || { echo "Install what is missing, then run this again."; exit 1; }
