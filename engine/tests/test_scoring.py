from __future__ import annotations

import numpy as np

from culler.config import Settings
from culler.scoring.reasons import describe, one_line, order_codes
from culler.scoring.rules import PhotoSignals, blend_weight, finalize, score_shoot, shoot_sharp_ref
from culler.similarity.bursts import Frame, group_bursts, rank_burst


def _sharp_shoot(n=40, sharp=300.0):
    """A shoot of ``n`` good photos; tests append the special cases they care about."""
    return [PhotoSignals(photo_id=i, subject_sharpness=sharp + i, tile_max_sharpness=sharp * 2, exposure_mean=120, clip_high_pct=0.2) for i in range(n)]


def _result(signals, photo_id, settings=None):
    return next(r for r in score_shoot(signals, settings or Settings()) if r.photo_id == photo_id)


def test_good_photo_is_kept_with_reason():
    r = _result(_sharp_shoot(), 20)
    assert r.label == "KEEP" and not r.hard and "sharp" in r.codes and 0.55 <= r.confidence <= 0.95


def test_out_of_focus_is_rejected():
    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=8, tile_max_sharpness=12, exposure_mean=120)]
    r = _result(s, 99)
    assert r.label == "REJECT" and r.codes[0] == "out_of_focus" and r.confidence > 0.8


def test_camera_shake_and_missed_focus_are_named():
    s = _sharp_shoot() + [
        PhotoSignals(photo_id=98, subject_sharpness=9, tile_max_sharpness=15, motion_anisotropy=0.8, exposure_mean=120),
        PhotoSignals(photo_id=99, subject_sharpness=9, tile_max_sharpness=500, motion_anisotropy=0.1, exposure_mean=120),
    ]
    assert _result(s, 98).codes[0] == "camera_shake"
    assert _result(s, 99).codes[0] == "missed_focus"


def test_uniformly_sharp_shoot_loses_nothing():
    """The softest 10% of a shoot is only rejected if it is also soft in absolute terms."""
    results = score_shoot(_sharp_shoot(60), Settings())
    assert not any(r.label == "REJECT" for r in results)


def test_slightly_soft_goes_to_review_not_reject():
    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=80, tile_max_sharpness=100, exposure_mean=120)]
    r = _result(s, 99)
    assert r.label != "REJECT" and not r.hard


def test_eyes_closed_on_main_face_is_rejected():
    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=320, exposure_mean=120, face_count=1, main_eyes_closed=1, main_eye_open=0.05)]
    r = _result(s, 99)
    assert r.label == "REJECT" and r.codes[0] == "eyes_closed"


def test_bystander_blinking_is_only_a_note():
    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=320, exposure_mean=120, face_count=3, main_eyes_closed=0, eyes_closed_count=1, main_eye_open=0.9)]
    r = _result(s, 99)
    assert r.label != "REJECT" and "someone_blinking" in r.codes


def test_unknown_eye_state_never_rejects():
    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=320, exposure_mean=120, face_count=1, main_eyes_closed=None)]
    r = _result(s, 99)
    assert r.label == "KEEP" and "eyes_unknown" in r.codes


def test_blown_face_and_blank_frame_are_rejected():
    s = _sharp_shoot() + [
        PhotoSignals(photo_id=97, subject_sharpness=320, exposure_mean=150, face_count=1, main_eyes_closed=0, face_clip_high_pct=30),
        PhotoSignals(photo_id=98, subject_sharpness=0.1, exposure_mean=2),
        PhotoSignals(photo_id=99, subject_sharpness=0.1, exposure_mean=254),
    ]
    assert _result(s, 97).codes[0] == "face_blown"
    assert _result(s, 98).codes[0] == "blank_frame" and _result(s, 98).confidence > 0.95
    assert _result(s, 99).codes[0] == "blank_frame"


def test_badly_underexposed_is_review():
    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=320, exposure_mean=22)]
    r = _result(s, 99)
    assert r.label == "REVIEW" and "underexposed" in r.codes


def test_weaker_burst_frames_go_to_review_never_reject():
    s = _sharp_shoot() + [
        PhotoSignals(photo_id=97, subject_sharpness=330, exposure_mean=120, burst_size=3, burst_rank=0),
        PhotoSignals(photo_id=98, subject_sharpness=325, exposure_mean=120, burst_size=3, burst_rank=1),
        PhotoSignals(photo_id=99, subject_sharpness=320, exposure_mean=120, burst_size=3, burst_rank=2),
    ]
    best, alt = _result(s, 97), _result(s, 98)
    assert best.label == "KEEP" and "best_of_burst" in best.codes
    assert alt.label == "REVIEW" and "burst_alt" in alt.codes
    assert describe(best.codes, 3)[0] == "Best frame of 3"


def test_shoot_reference_is_bounded_and_needs_enough_photos():
    th = Settings().thresholds
    assert shoot_sharp_ref([500.0] * 5, th) == th.sharp_ref  # too few photos: default
    assert shoot_sharp_ref([500.0] * 50, th) == 500.0
    assert shoot_sharp_ref([1.0] * 50, th) == th.sharp_ref_min
    assert shoot_sharp_ref([1e6] * 50, th) == th.sharp_ref_max


def test_reason_text():
    assert order_codes(["sharp", "eyes_closed", "sharp"]) == ["eyes_closed", "sharp"]
    assert one_line(["well_exposed", "out_of_focus"]) == "Subject out of focus, well exposed"
    assert describe([]) == ("No issues found", None)


# ---------------------------------------------------------------- personal model blending
def test_no_taste_rejects_before_enough_decisions():
    settings = Settings()
    rule = _result(_sharp_shoot(), 5)
    final = finalize(rule, 0.01, n_decisions=settings.learning.min_decisions - 1, settings=settings)
    assert final.label == "KEEP" and final.final_score == rule.rule_score
    assert blend_weight(0, settings) == 0.0


def test_blend_weight_grows_to_cap():
    s = Settings()
    assert blend_weight(300, s) == 0.8 * 300 / 2000
    assert blend_weight(2000, s) == 0.8 and blend_weight(50000, s) == 0.8


def test_taste_reject_and_rescue_with_a_model():
    settings = Settings()
    good = _result(_sharp_shoot(), 5)
    disliked = finalize(good, 0.05, 1000, settings)
    assert disliked.label == "REJECT" and "taste_reject" in disliked.codes

    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=320, exposure_mean=120, face_count=1, main_eyes_closed=1, main_eye_open=0.0)]
    blink = _result(s, 99)
    assert finalize(blink, 0.3, 1000, settings).label == "REJECT"
    rescued = finalize(blink, 0.95, 1000, settings)
    assert rescued.label == "REVIEW" and "you_keep_similar" in rescued.codes


def test_personal_model_can_lift_a_review_to_keep():
    settings = Settings()
    s = _sharp_shoot() + [PhotoSignals(photo_id=99, subject_sharpness=70, tile_max_sharpness=90, exposure_mean=70)]
    rule = _result(s, 99)
    assert rule.label == "REVIEW"
    lifted = finalize(rule, 0.98, 2000, settings)
    assert lifted.label == "KEEP" and "taste_keep" in lifted.codes


# ---------------------------------------------------------------- bursts
def _vec(*xs):
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_bursts_need_both_time_and_similarity():
    a, b = _vec(1, 0, 0), _vec(0, 1, 0)
    frames = [
        Frame(1, 0.0, a), Frame(2, 0.3, _vec(1, 0.05, 0)), Frame(3, 0.6, _vec(1, 0.1, 0)),  # a burst
        Frame(4, 1.0, b),  # close in time, different picture
        Frame(5, 30.0, a), Frame(6, 60.0, a),  # same picture, far apart in time
        Frame(7, 61.0, a),  # ...then one right after
        Frame(8, None, a), Frame(9, 62.0, None),  # unusable
    ]
    assert group_bursts(frames, gap_s=2.0, sim_threshold=0.9) == [[1, 2, 3], [6, 7]]


def test_burst_does_not_drift_across_a_slow_pan():
    frames = [Frame(i, i * 0.5, _vec(np.cos(i * 0.25), np.sin(i * 0.25))) for i in range(8)]
    groups = group_bursts(frames, gap_s=2.0, sim_threshold=0.95)
    assert all(len(g) < 8 for g in groups)


def test_rank_burst_prefers_open_eyes_then_sharpness():
    order = rank_burst([
        {"photo_id": 1, "main_eyes_closed": 1, "subject_sharpness": 900, "exposure_score": 1.0},
        {"photo_id": 2, "main_eyes_closed": 0, "subject_sharpness": 200, "exposure_score": 1.0},
        {"photo_id": 3, "main_eyes_closed": 0, "subject_sharpness": 400, "exposure_score": 1.0},
        {"photo_id": 4, "main_eyes_closed": 0, "subject_sharpness": 400, "exposure_score": 1.0, "eyes_closed_count": 2},
    ])
    assert order == [3, 2, 4, 1]
