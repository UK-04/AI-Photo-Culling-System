"""Build the feature vector the personal model sees for one photo.

Features = image embedding (what the photo is of, how it looks) + technical scores
normalized within the shoot + face counts + position in its burst.
"""

from __future__ import annotations

import numpy as np

from ..similarity.embeddings import from_blob

TECH_FEATURES = (
    "sharp_pct", "rule_score", "blur_score", "motion_anisotropy", "exposure_mean", "clip_high",
    "clip_low", "face_count", "has_face", "main_eyes_closed", "eyes_unknown", "main_eye_open",
    "blinkers", "in_burst", "burst_rank", "is_burst_best",
)


def _f(value, default: float = 0.0) -> float:
    return default if value is None else float(value)


def tech_vector(row: dict) -> np.ndarray:
    face_count = int(row.get("face_count") or 0)
    in_burst = row.get("burst_id") is not None
    rank = int(row.get("burst_rank") or 0)
    eyes = row.get("main_eyes_closed")
    return np.array(
        [
            _f(row.get("sharp_pct"), 0.5),
            _f(row.get("rule_score"), 0.5),
            _f(row.get("blur_score")),
            _f(row.get("motion_anisotropy")),
            _f(row.get("exposure_mean"), 128.0) / 255.0,
            np.log1p(_f(row.get("clip_high_pct"))) / 5.0,
            np.log1p(_f(row.get("clip_low_pct"))) / 5.0,
            min(face_count, 10) / 10.0,
            1.0 if face_count else 0.0,
            1.0 if eyes == 1 else 0.0,
            1.0 if (face_count and eyes is None) else 0.0,
            _f(row.get("main_eye_open"), 0.5),
            min(int(row.get("eyes_closed_count") or 0), 5) / 5.0,
            1.0 if in_burst else 0.0,
            min(rank, 10) / 10.0,
            1.0 if (in_burst and rank == 0) else 0.0,
        ],
        dtype=np.float32,
    )


def build_matrix(rows: list[dict]) -> np.ndarray:
    """Stack ``[embedding | technical features]`` for each row from ``Repo.feature_rows``."""
    if not rows:
        return np.zeros((0, 0), dtype=np.float32)
    return np.stack([np.concatenate([from_blob(r["vector"]), tech_vector(r)]) for r in rows]).astype(np.float32)


def labels(rows: list[dict]) -> np.ndarray:
    """1 = the photographer kept it, 0 = rejected."""
    return np.array([1 if r["user_label"] == "KEEP" else 0 for r in rows], dtype=np.int64)
