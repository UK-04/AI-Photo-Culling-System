"""Tell apart the kinds of blur: camera shake, missed focus, or general softness.

Camera shake smears the whole frame along one direction, which wipes out fine detail
along that direction and leaves the detail across it. Measuring how lopsided the
fine-detail gradients are ("anisotropy") detects exactly that.

The measurement is taken on a high-pass copy of the image so that large shapes in the
scene (a horizon, a table edge) do not look like motion.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

_FACTOR_START = 0.5  # anisotropy where the sharpness penalty begins


def gradient_anisotropy(gray: np.ndarray) -> tuple[float, float]:
    """Return ``(anisotropy 0-1, blur direction in degrees)`` for the fine detail.

    Around 0-0.3 for ordinary photos (sharp or evenly soft); 0.5-0.95 for motion blur.
    """
    g = gray.astype(np.float32)
    fine = g - cv2.GaussianBlur(g, (0, 0), 2.0)
    gx = cv2.Sobel(fine, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(fine, cv2.CV_32F, 0, 1, ksize=3)
    jxx, jyy, jxy = float((gx * gx).mean()), float((gy * gy).mean()), float((gx * gy).mean())
    trace = jxx + jyy
    if trace < 1e-6:
        return 0.0, 0.0
    anisotropy = float(np.hypot(jxx - jyy, 2.0 * jxy) / trace)
    # Dominant gradient direction; the blur runs perpendicular to it.
    grad_angle = 0.5 * np.degrees(np.arctan2(2.0 * jxy, jxx - jyy))
    return anisotropy, float((grad_angle + 90.0) % 180.0)


def motion_factor(anisotropy: float) -> float:
    """Multiplier (0.1-1) applied to sharpness when the frame shows directional blur.

    Laplacian variance alone overrates motion-blurred frames, because the detail across
    the blur direction survives. This brings them down to where they belong.
    """
    if anisotropy <= _FACTOR_START:
        return 1.0
    return max(0.1, ((1.0 - anisotropy) / (1.0 - _FACTOR_START)) ** 2)


def relative_sharpness(subject_sharp: float, ref: float, floor: float) -> float:
    """Map sharpness to 0-1 on a log scale: ``floor`` (clearly blurred) -> 0, ``ref`` (sharp) -> 1.

    Laplacian variance falls off roughly with the fourth power of blur size, so a log
    scale matches how blur looks far better than a linear one.
    """
    if subject_sharp <= floor or ref <= floor:
        return 0.0 if subject_sharp <= floor else 1.0
    return float(np.clip(math.log(subject_sharp / floor) / math.log(ref / floor), 0.0, 1.0))


def classify_blur(
    rel_sharp: float,
    subject_sharp: float,
    tile_max: float,
    anisotropy: float,
    ref: float,
    shake_anisotropy: float,
) -> str:
    """Name the blur: ``none`` | ``shake`` | ``missed_focus`` | ``soft``."""
    if rel_sharp >= 0.6:
        return "none"
    if anisotropy >= shake_anisotropy:
        return "shake"
    # Something in the frame is clearly sharper than the subject: focus landed elsewhere.
    if tile_max >= 0.6 * ref and tile_max > 4.0 * max(subject_sharp, 1e-6):
        return "missed_focus"
    return "soft"
