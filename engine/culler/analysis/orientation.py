"""Work out when a photo is sideways even though the camera did not say so.

Cameras record orientation with a sensor that fails when the camera points up or down,
and some files lose the flag along the way. Faces give it away: the face detector finds
upright faces reliably and sideways ones poorly, so if faces only show up after turning
the picture, the picture needs turning.

This only works for photos with a clear face in them. Anything else is left as it is
and can be rotated by hand.
"""

from __future__ import annotations

import cv2
import numpy as np


def rotate_cw(rgb: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate an image clockwise by 0, 90, 180 or 270 degrees."""
    k = (degrees // 90) % 4
    return rgb if k == 0 else np.ascontiguousarray(np.rot90(rgb, k=-k))


def _best_face(rgb: np.ndarray, detector, min_face_px: int) -> float:
    scores = [f.score for f in detector.boxes(rgb) if min(f.box[2], f.box[3]) >= min_face_px]
    return max(scores, default=0.0)


def detect_rotation(rgb: np.ndarray, detector, min_score: float = 0.85, margin: float = 0.08, work_px: int = 640) -> int:
    """Degrees clockwise the image should be turned to stand upright (0 if it looks fine or is unclear)."""
    h, w = rgb.shape[:2]
    scale = work_px / max(h, w)
    small = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    min_face = max(16, work_px // 28)

    upright = _best_face(small, detector, min_face)
    if upright >= min_score:
        return 0
    best_deg, best = 0, 0.0
    for deg in (90, 270, 180):
        score = _best_face(rotate_cw(small, deg), detector, min_face)
        if score > best:
            best_deg, best = deg, score
    return best_deg if best >= min_score and best >= upright + margin else 0
