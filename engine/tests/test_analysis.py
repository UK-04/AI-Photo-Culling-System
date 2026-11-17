from __future__ import annotations

import cv2
import numpy as np
import pytest

from culler.analysis.blur import classify_blur, gradient_anisotropy, motion_factor, relative_sharpness
from culler.analysis.exposure import analyze_exposure, exposure_score
from culler.analysis.faces import Face, NullBackend, eye_aspect_ratio, eye_state, main_face
from culler.analysis.normalize import percentile_ranks
from culler.analysis.pipeline import analyze_image
from culler.analysis.sharpness import frame_sharpness, region_sharpness, to_gray
from culler.synth import _motion


def _subject(img):
    return frame_sharpness(to_gray(img))["subject"]


def test_blur_lowers_sharpness_monotonically(scene):
    values = [_subject(scene)] + [_subject(cv2.GaussianBlur(scene, (0, 0), s)) for s in (1.0, 2.0, 4.0)]
    assert values == sorted(values, reverse=True)
    assert values[0] > 20 * values[-1]


def test_sharpness_ignores_overall_brightness(scene):
    dark = (scene.astype(np.float32) * 0.3).astype(np.uint8)
    assert _subject(dark) == pytest.approx(_subject(scene), rel=0.25)


def test_blank_frame_has_no_sharpness():
    assert _subject(np.full((300, 400, 3), 128, np.uint8)) < 1.0


def test_subject_sharpness_survives_blurred_background(scene):
    """A sharp subject in a blurred frame (shallow depth of field) still reads as sharp."""
    shallow = cv2.GaussianBlur(scene, (0, 0), 5.0)
    shallow[140:300, 220:420] = scene[140:300, 220:420]
    s = frame_sharpness(to_gray(shallow))
    assert s["subject"] > 5 * s["tile_median"]
    assert s["subject"] > 0.3 * _subject(scene)


def test_region_sharpness_tracks_local_blur(scene):
    gray = to_gray(scene)
    half = scene.copy()
    half[:, :320] = cv2.GaussianBlur(scene[:, :320], (0, 0), 4.0)
    gray_half = to_gray(half)
    assert region_sharpness(gray_half, (360, 100, 200, 200)) > 10 * region_sharpness(gray_half, (40, 100, 200, 200))
    assert region_sharpness(gray, (0, 0, 2, 2)) == 0.0  # too small to measure


@pytest.mark.parametrize("angle", [0, 45, 90, 135])
def test_motion_blur_is_detected_in_any_direction(scene, angle):
    plain, _ = gradient_anisotropy(to_gray(scene))
    soft, _ = gradient_anisotropy(to_gray(cv2.GaussianBlur(scene, (0, 0), 3.0)))
    shaken, direction = gradient_anisotropy(to_gray(_motion(scene, 21, angle)))
    assert plain < 0.35 and soft < 0.35
    assert shaken > 0.55
    assert motion_factor(shaken) < 0.8 and motion_factor(plain) == 1.0
    # OpenCV's rotation is counter-clockwise with y pointing down
    expected = (180 - angle) % 180
    assert min(abs(direction - expected), 180 - abs(direction - expected)) < 20


def test_relative_sharpness_is_log_scaled():
    assert relative_sharpness(5, 150, 10) == 0.0
    assert relative_sharpness(150, 150, 10) == 1.0
    assert relative_sharpness(1500, 150, 10) == 1.0
    assert relative_sharpness(38.7, 150, 10) == pytest.approx(0.5, abs=0.01)


def test_classify_blur_kinds():
    ref = 150.0
    assert classify_blur(0.9, 120, 300, 0.1, ref, 0.55) == "none"
    assert classify_blur(0.2, 15, 20, 0.8, ref, 0.55) == "shake"
    assert classify_blur(0.2, 15, 400, 0.1, ref, 0.55) == "missed_focus"
    assert classify_blur(0.2, 15, 20, 0.1, ref, 0.55) == "soft"


def test_exposure_stats_and_clipping():
    img = np.full((100, 200, 3), 128, np.uint8)
    img[:, :50] = 255
    img[:, 150:] = 0
    e = analyze_exposure(img, face_box=(0, 0, 100, 100))
    assert e["clip_high_pct"] == pytest.approx(25.0)
    assert e["clip_low_pct"] == pytest.approx(25.0)
    assert e["face_clip_high_pct"] == pytest.approx(50.0)
    assert analyze_exposure(img)["face_mean"] is None


def test_exposure_score_penalizes_extremes():
    args = (60.0, 200.0, 2.0)
    assert exposure_score(128, 0.0, *args) == 1.0
    assert exposure_score(20, 0.0, *args) < exposure_score(50, 0.0, *args) < 1.0
    assert exposure_score(240, 0.0, *args) < 1.0
    assert exposure_score(128, 20.0, *args) < exposure_score(128, 3.0, *args)


def test_percentile_ranks():
    assert percentile_ranks([10, 30, 20]) == [0.0, 1.0, 0.5]
    assert percentile_ranks([5, None, 5, 9]) == [0.25, None, 0.25, 1.0]
    assert percentile_ranks([7]) == [0.5]
    assert percentile_ranks([]) == []
    assert percentile_ranks([None, None]) == [None, None]


def _eye(openness: float) -> np.ndarray:
    """Six landmarks for an eye 30 px wide and ``openness`` * 30 px tall."""
    half = openness * 30 / 2
    return np.array([[0, 0], [10, -half], [20, -half], [30, 0], [20, half], [10, half]], dtype=np.float32)


def test_eye_aspect_ratio():
    assert eye_aspect_ratio(_eye(0.3)) == pytest.approx(0.3)
    assert eye_aspect_ratio(_eye(0.05)) == pytest.approx(0.05)
    assert eye_aspect_ratio(np.zeros((6, 2), np.float32)) == 0.0


def test_eye_state_needs_both_eyes_closed():
    kw = dict(blink_closed=0.6, ear_closed=0.15)
    assert eye_state(0.30, 0.30, 0.05, 0.05, **kw)[1] is False  # open
    assert eye_state(0.05, 0.05, 0.9, 0.9, **kw)[1] is True  # shut
    assert eye_state(0.05, 0.30, 0.9, 0.1, **kw)[1] is False  # wink
    assert eye_state(0.05, 0.05, None, None, **kw)[1] is True  # no blink scores: EAR decides
    assert eye_state(0.30, 0.30, None, None, **kw)[1] is False
    # blink score says closed but the eyelids are clearly apart: trust the geometry
    assert eye_state(0.30, 0.30, 0.9, 0.9, **kw)[1] is False
    assert eye_state(0.30, 0.30, 0.0, 0.0, **kw)[0] > eye_state(0.16, 0.16, 0.5, 0.5, **kw)[0]


def test_main_face_prefers_large_and_central():
    small_centre = Face((480, 330, 40, 40), 0.9)
    big_corner = Face((0, 0, 200, 200), 0.9)
    big_centre = Face((400, 250, 200, 200), 0.9)
    assert main_face([small_centre, big_corner], 1000, 700) is big_corner
    assert main_face([big_corner, big_centre], 1000, 700) is big_centre
    assert main_face([], 1000, 700) is None


def test_analyze_image_reports_all_fields(scene, settings):
    a = analyze_image(scene, NullBackend(), settings)
    assert a["face_count"] == 0 and a["main_eyes_closed"] is None and a["face_sharpness"] is None
    assert a["blur_kind"] == "none" and a["blur_score"] < 0.3
    assert 0 <= a["clip_high_pct"] <= 100 and a["face_backend"] == "none"
    blurred = analyze_image(cv2.GaussianBlur(scene, (0, 0), 5.0), NullBackend(), settings)
    assert blurred["blur_kind"] in ("soft", "missed_focus") and blurred["blur_score"] > 0.7
    shaken = analyze_image(_motion(scene, 25, 30), NullBackend(), settings)
    assert shaken["blur_kind"] == "shake"
    assert shaken["subject_sharpness"] < 0.2 * a["subject_sharpness"]
