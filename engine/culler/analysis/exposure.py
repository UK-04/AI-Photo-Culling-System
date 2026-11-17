"""Exposure: brightness, and how much of the frame is clipped to pure white or black."""

from __future__ import annotations

import numpy as np

_HIGH, _LOW = 250, 5


def luminance(rgb: np.ndarray) -> np.ndarray:
    """Rec. 709 luma, 0-255 float32."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b).astype(np.float32)


def analyze_exposure(rgb: np.ndarray, face_box: tuple[float, float, float, float] | None = None) -> dict[str, float | None]:
    """Frame-wide exposure stats, plus the same for the main face when one is given.

    ``face_box`` is (x, y, w, h) in the pixel coordinates of ``rgb``.
    """
    lum = luminance(rgb)
    out: dict[str, float | None] = {
        "exposure_mean": float(lum.mean()),
        "exposure_median": float(np.median(lum)),
        "clip_high_pct": float((lum >= _HIGH).mean() * 100.0),
        "clip_low_pct": float((lum <= _LOW).mean() * 100.0),
        "face_mean": None,
        "face_clip_high_pct": None,
    }
    if face_box is not None:
        x, y, w, h = face_box
        H, W = lum.shape
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(W, int(x + w)), min(H, int(y + h))
        if x1 > x0 and y1 > y0:
            face = lum[y0:y1, x0:x1]
            out["face_mean"] = float(face.mean())
            out["face_clip_high_pct"] = float((face >= _HIGH).mean() * 100.0)
    return out


def exposure_score(mean: float, clip_high_pct: float, under_mean: float, over_mean: float, clip_soft_pct: float) -> float:
    """0-1, where 1 is a normal exposure. Low-key and high-key frames lose a little, not a lot."""
    score = 1.0
    if mean < under_mean:
        score -= 0.7 * (under_mean - mean) / under_mean
    elif mean > over_mean:
        score -= 0.7 * (mean - over_mean) / (255.0 - over_mean)
    if clip_high_pct > clip_soft_pct:
        score -= min(0.4, 0.02 * (clip_high_pct - clip_soft_pct))
    return float(np.clip(score, 0.0, 1.0))
