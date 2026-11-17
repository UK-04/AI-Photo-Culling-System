"""Sharpness from the variance of the Laplacian.

All measurements are taken on a grayscale image resized to a fixed long edge, so the
numbers are comparable between cameras and between JPEG and RAW previews.

The raw Laplacian variance scales with contrast squared, which makes dark or flat
frames look softer than they are. Dividing by the frame's own intensity variance
removes that: the score answers "how much of this frame's contrast is fine detail".
"""

from __future__ import annotations

import cv2
import numpy as np

_SCALE = 1000.0
_VAR_FLOOR = 25.0  # keeps near-blank frames from dividing by ~0


def to_gray(rgb: np.ndarray, long_edge: int = 1024) -> np.ndarray:
    """RGB uint8 -> grayscale uint8 with the long edge resized to ``long_edge``."""
    h, w = rgb.shape[:2]
    scale = long_edge / max(h, w)
    if scale < 1.0:
        rgb = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _laplacian(gray: np.ndarray) -> np.ndarray:
    # A light blur first so high-ISO noise is not mistaken for detail.
    smooth = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.Laplacian(smooth, cv2.CV_32F, ksize=3)


def laplacian_sharpness(gray: np.ndarray, contrast_var: float | None = None) -> float:
    """Contrast-normalized sharpness of a grayscale patch. Higher is sharper."""
    if gray.size == 0:
        return 0.0
    lap = _laplacian(gray)
    denom = (float(gray.var()) if contrast_var is None else contrast_var) + _VAR_FLOOR
    return float(lap.var()) / denom * _SCALE


def tile_sharpness(gray: np.ndarray, grid: int = 8) -> np.ndarray:
    """Sharpness of each cell in a ``grid`` x ``grid`` layout, normalized by frame contrast."""
    lap = _laplacian(gray)
    denom = float(gray.var()) + _VAR_FLOOR
    h, w = gray.shape
    ys = np.linspace(0, h, grid + 1, dtype=int)
    xs = np.linspace(0, w, grid + 1, dtype=int)
    out = np.zeros((grid, grid), dtype=np.float32)
    for i in range(grid):
        for j in range(grid):
            cell = lap[ys[i] : ys[i + 1], xs[j] : xs[j + 1]]
            out[i, j] = float(cell.var()) / denom * _SCALE if cell.size else 0.0
    return out


def frame_sharpness(gray: np.ndarray, grid: int = 8) -> dict[str, float]:
    """Whole-frame sharpness plus a subject estimate for photos without a detected face.

    ``subject`` is the 90th percentile of the tiles: with a blurred background (shallow
    depth of field) the sharpest tiles are where the photographer focused, so a portrait
    at f/1.8 is not marked soft just because most of the frame is bokeh.
    """
    tiles = tile_sharpness(gray, grid)
    return {
        "global": laplacian_sharpness(gray),
        "subject": float(np.percentile(tiles, 90)),
        "tile_min": float(tiles.min()),
        "tile_median": float(np.median(tiles)),
        "tile_max": float(tiles.max()),
    }


def region_sharpness(gray: np.ndarray, box: tuple[float, float, float, float], size: int = 160) -> float:
    """Sharpness inside ``box`` (x, y, w, h in ``gray`` pixels), resized to a fixed size.

    Resizing makes a small distant face and a large close face comparable.
    """
    x, y, w, h = box
    H, W = gray.shape
    x0, y0 = max(0, int(round(x))), max(0, int(round(y)))
    x1, y1 = min(W, int(round(x + w))), min(H, int(round(y + h)))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0
    patch = gray[y0:y1, x0:x1]
    interp = cv2.INTER_AREA if patch.shape[0] > size else cv2.INTER_LINEAR
    patch = cv2.resize(patch, (size, size), interpolation=interp)
    return laplacian_sharpness(patch)
