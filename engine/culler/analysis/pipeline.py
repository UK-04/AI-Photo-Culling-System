"""Run every analyzer on one preview and return a flat dict ready for the database."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from ..config import ANALYZER_VERSION, Settings
from .blur import classify_blur, gradient_anisotropy, motion_factor, relative_sharpness
from .exposure import analyze_exposure
from .faces import FaceBackend, main_face
from .sharpness import frame_sharpness, region_sharpness, to_gray


def analyze_image(rgb: np.ndarray, faces_backend: FaceBackend, settings: Settings) -> dict[str, Any]:
    """Analyze an upright RGB preview (uint8, any size up to the preview size)."""
    th = settings.thresholds
    H, W = rgb.shape[:2]
    gray = to_gray(rgb, settings.analysis_px)
    scale = gray.shape[1] / W  # preview pixels -> analysis pixels

    sharp = frame_sharpness(gray)
    anisotropy, direction = gradient_anisotropy(gray)

    faces = faces_backend.detect(rgb)
    lead = main_face(faces, W, H)

    face_sharp = None
    if lead is not None:
        x, y, w, h = lead.box
        face_sharp = region_sharpness(gray, (x * scale, y * scale, w * scale, h * scale))
    # The subject is the main face when there is one, otherwise the sharpest part of the frame.
    # Directional (motion) blur is discounted, since plain Laplacian variance overrates it.
    subject_raw = face_sharp if face_sharp is not None else sharp["subject"]
    subject_sharp = subject_raw * motion_factor(anisotropy)

    # Stored against the default reference; scoring re-judges against the shoot's own reference.
    rel = relative_sharpness(subject_sharp, th.sharp_ref, th.sharp_floor)
    blur_kind = classify_blur(rel, subject_sharp, sharp["tile_max"], anisotropy, th.sharp_ref, th.shake_anisotropy)

    exposure = analyze_exposure(rgb, lead.box if lead is not None else None)

    measured = [f for f in faces if f.eyes_closed is not None]
    return {
        "sharpness": sharp["global"],
        "subject_sharpness": subject_sharp,
        "face_sharpness": face_sharp,
        "tile_max_sharpness": sharp["tile_max"],
        "blur_score": 1.0 - rel,
        "blur_kind": blur_kind,
        "motion_anisotropy": anisotropy,
        "motion_direction": direction,
        "exposure_mean": exposure["exposure_mean"],
        "clip_high_pct": exposure["clip_high_pct"],
        "clip_low_pct": exposure["clip_low_pct"],
        "face_clip_high_pct": exposure["face_clip_high_pct"],
        "face_count": len(faces),
        "eyes_closed_count": sum(1 for f in measured if f.eyes_closed),
        "main_eyes_closed": None if lead is None or lead.eyes_closed is None else int(lead.eyes_closed),
        "main_eye_open": None if lead is None else lead.eye_open,
        "faces_json": json.dumps(
            [
                {
                    **f.to_dict(),
                    "main": f is lead,
                    "box_rel": [round(f.box[0] / W, 4), round(f.box[1] / H, 4), round(f.box[2] / W, 4), round(f.box[3] / H, 4)],
                }
                for f in faces
            ]
        ),
        "face_backend": faces_backend.name,
        "analyzer_version": ANALYZER_VERSION,
    }
