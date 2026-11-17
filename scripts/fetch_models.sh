#!/usr/bin/env bash
# Download the two small face models into engine/culler/assets/models (git-ignored).
# Both come from their publishers' official locations and are checked against pinned hashes.
set -euo pipefail
DEST="$(cd "$(dirname "$0")/.." && pwd)/engine/culler/assets/models"
mkdir -p "$DEST"

fetch() { # url, file, sha256 ("" = print the hash so it can be pinned)
  local url="$1" file="$DEST/$2" want="$3"
  if [[ ! -f "$file" ]]; then
    echo "Downloading $2"
    curl -fL --retry 3 -o "$file.part" "$url"
    mv "$file.part" "$file"
  fi
  local got; got="$(shasum -a 256 "$file" | cut -d' ' -f1)"
  if [[ -z "$want" ]]; then
    echo "  $2 sha256: $got  (pin this in scripts/fetch_models.sh after checking the file)"
  elif [[ "$got" != "$want" ]]; then
    echo "Checksum mismatch for $2: got $got" >&2; rm -f "$file"; exit 1
  fi
}

# Face detection: YuNet, from the OpenCV Zoo (github.com/opencv/opencv_zoo).
fetch "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
      "face_detection_yunet_2023mar.onnx" \
      "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"

# Eye state: MediaPipe Face Landmarker, from Google's model storage.
# Its hash is not pinned yet: this file could not be downloaded in the build sandbox.
fetch "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" \
      "face_landmarker.task" \
      ""
echo "Models are in $DEST"
