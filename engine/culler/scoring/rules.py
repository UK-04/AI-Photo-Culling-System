"""Rule-based scoring: the baseline that works from the first shoot, before any learning.

Design rules (from the build spec):

* A photo is only REJECTED for a clear technical failure. Anything uncertain is REVIEW.
* Being a weaker frame of a burst is never a reason to reject, only to review.
* Every result carries reason codes that explain it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..analysis.blur import classify_blur, relative_sharpness
from ..analysis.exposure import exposure_score
from ..analysis.normalize import percentile_ranks
from ..config import Settings, Thresholds
from .reasons import HARD, order_codes

KEEP, REVIEW, REJECT = "KEEP", "REVIEW", "REJECT"


@dataclass
class PhotoSignals:
    """Everything the rules need to know about one photo."""

    photo_id: int
    subject_sharpness: float | None = None
    tile_max_sharpness: float | None = None
    motion_anisotropy: float | None = None
    exposure_mean: float | None = None
    clip_high_pct: float | None = None
    clip_low_pct: float | None = None
    face_clip_high_pct: float | None = None
    face_count: int = 0
    eyes_closed_count: int = 0
    main_eyes_closed: int | None = None
    main_eye_open: float | None = None
    burst_size: int = 1
    burst_rank: int = 0  # 0 = best of its burst, or not in a burst


@dataclass
class RuleResult:
    photo_id: int
    rule_score: float
    label: str
    confidence: float
    codes: list[str] = field(default_factory=list)
    sharp_pct: float | None = None
    rel_sharp: float = 0.0
    blur_kind: str = "none"
    exposure_score: float = 1.0
    hard: bool = False
    burst_size: int = 1
    burst_rank: int = 0


def shoot_sharp_ref(sharpness: list[float | None], th: Thresholds) -> float:
    """What "sharp" means for this shoot: its 75th percentile, kept within sane bounds."""
    vals = [v for v in sharpness if v is not None]
    if len(vals) < th.min_shoot_for_ref:
        return th.sharp_ref
    return float(np.clip(np.percentile(vals, 75), th.sharp_ref_min, th.sharp_ref_max))


def _face_component(s: PhotoSignals) -> tuple[float, list[str]]:
    if s.face_count == 0:
        return 0.7, []  # neutral: plenty of good photos have no faces
    if s.main_eyes_closed == 1:
        return 0.0, ["eyes_closed"]
    if s.main_eyes_closed is None:
        return 0.7, ["eyes_unknown"]
    if s.eyes_closed_count > 0:
        return 0.55, ["someone_blinking"]
    return 1.0, ["eyes_open"]


def score_photo(s: PhotoSignals, sharp_pct: float | None, ref: float, settings: Settings) -> RuleResult:
    th, wt = settings.thresholds, settings.weights
    codes: list[str] = []
    hard_conf: list[float] = []

    # ---- sharpness ----
    subject = s.subject_sharpness or 0.0
    rel = relative_sharpness(subject, ref, th.sharp_floor)
    pct = 0.5 if sharp_pct is None else sharp_pct
    sharp_c = 0.5 * pct + 0.5 * rel
    kind = classify_blur(rel, subject, s.tile_max_sharpness or 0.0, s.motion_anisotropy or 0.0, ref, th.shake_anisotropy)
    reject_below = max(th.sharp_floor, th.reject_sharp_ratio * ref)
    if kind != "none" and subject < reject_below and pct <= th.reject_sharp_percentile:
        codes.append({"shake": "camera_shake", "missed_focus": "missed_focus"}.get(kind, "out_of_focus"))
        severity = float(np.clip(1.0 - subject / reject_below, 0.0, 1.0))
        hard_conf.append(0.65 + 0.3 * severity)
    elif kind != "none":
        codes.append("soft_focus")
    elif rel >= 0.85:
        codes.append("sharp")

    # ---- exposure ----
    mean = s.exposure_mean if s.exposure_mean is not None else 128.0
    clip_high = s.clip_high_pct or 0.0
    expo_c = exposure_score(mean, clip_high, th.under_mean, th.over_mean, th.clip_high_soft_pct)
    if mean < th.blank_low or mean > th.blank_high:
        codes.append("blank_frame")
        hard_conf.append(0.98)
    else:
        if mean < th.under_mean:
            codes.append("underexposed")
        elif mean > th.over_mean:
            codes.append("overexposed")
        elif clip_high > 4 * th.clip_high_soft_pct:
            codes.append("highlights_clipped")
        elif expo_c >= 0.95:
            codes.append("well_exposed")
    if s.face_clip_high_pct is not None and s.face_clip_high_pct > th.face_clip_reject_pct:
        codes.append("face_blown")
        hard_conf.append(min(0.95, 0.6 + (s.face_clip_high_pct - th.face_clip_reject_pct) / 50.0))

    # ---- faces ----
    face_c, face_codes = _face_component(s)
    codes += face_codes
    if "eyes_closed" in face_codes:
        openness = s.main_eye_open if s.main_eye_open is not None else 0.0
        hard_conf.append(0.6 + 0.35 * (1.0 - float(np.clip(openness, 0.0, 1.0))))

    # ---- burst ----
    in_burst = s.burst_size > 1
    is_alt = in_burst and s.burst_rank > 0
    burst_c = 0.5 if is_alt else 1.0
    if is_alt:
        codes.append("burst_alt")
    elif in_burst:
        codes.append("best_of_burst")

    score = wt.sharpness * sharp_c + wt.faces * face_c + wt.exposure * expo_c + wt.burst * burst_c
    score = float(np.clip(score, 0.0, 1.0))

    hard = any(c in HARD for c in codes)
    if hard:
        label = REJECT
        confidence = min(0.99, max(hard_conf) + 0.03 * (len(hard_conf) - 1))
        score = min(score, 0.25)
    elif score >= th.keep_score and not is_alt and expo_c >= th.keep_min_exposure:
        label = KEEP
        confidence = 0.55 + 0.4 * (score - th.keep_score) / max(1e-6, 1.0 - th.keep_score)
    else:
        # Weaker burst frames and badly exposed frames are for the photographer to judge.
        label = REVIEW
        confidence = 0.6 if score >= th.keep_score else float(np.clip(0.5 + (th.keep_score - score) * 0.6, 0.5, 0.8))

    return RuleResult(
        photo_id=s.photo_id, rule_score=score, label=label, confidence=float(confidence),
        codes=order_codes(codes), sharp_pct=sharp_pct, rel_sharp=rel, blur_kind=kind,
        exposure_score=expo_c, hard=hard, burst_size=s.burst_size, burst_rank=s.burst_rank,
    )


def score_shoot(signals: list[PhotoSignals], settings: Settings) -> list[RuleResult]:
    """Score every photo of one shoot. Sharpness is judged relative to the shoot itself."""
    sharp = [s.subject_sharpness for s in signals]
    ref = shoot_sharp_ref(sharp, settings.thresholds)
    pcts = percentile_ranks(sharp)
    return [score_photo(s, pct, ref, settings) for s, pct in zip(signals, pcts, strict=True)]


@dataclass
class FinalScore:
    photo_id: int
    rule_score: float
    personal_score: float | None
    final_score: float
    label: str
    confidence: float
    codes: list[str]


def blend_weight(n_decisions: int, settings: Settings) -> float:
    """How much the personal model counts: 0 before it exists, rising to ``max_blend``."""
    lr = settings.learning
    if n_decisions < lr.min_decisions:
        return 0.0
    return lr.max_blend * min(1.0, n_decisions / lr.full_blend_at)


def finalize(rule: RuleResult, p_keep: float | None, n_decisions: int, settings: Settings) -> FinalScore:
    """Combine the rule result with the personal model's keep-probability, if there is one."""
    lr, th = settings.learning, settings.thresholds
    w = blend_weight(n_decisions, settings) if p_keep is not None else 0.0
    if w == 0.0 or p_keep is None:
        return FinalScore(rule.photo_id, rule.rule_score, p_keep, rule.rule_score, rule.label, rule.confidence, rule.codes)

    final = rule.rule_score * (1.0 - w) + p_keep * w
    codes = list(rule.codes)
    is_alt = rule.burst_size > 1 and rule.burst_rank > 0
    if rule.hard:
        if p_keep >= lr.rescue_above:  # the photographer keeps photos like this one
            label, confidence = REVIEW, 0.6
            codes.append("you_keep_similar")
        else:
            label, confidence = REJECT, rule.confidence
    elif p_keep <= lr.taste_reject_below:
        label = REJECT
        confidence = 0.55 + 0.4 * (1.0 - p_keep / max(1e-6, lr.taste_reject_below))
        codes.append("taste_reject")
    elif final >= th.keep_score and not is_alt:
        label = KEEP
        confidence = 0.55 + 0.4 * (final - th.keep_score) / max(1e-6, 1.0 - th.keep_score)
        if p_keep >= 0.8:
            codes.append("taste_keep")
    else:
        label = REVIEW
        confidence = 0.6 if final >= th.keep_score else float(np.clip(0.5 + (th.keep_score - final) * 0.6, 0.5, 0.8))
    return FinalScore(rule.photo_id, rule.rule_score, p_keep, float(final), label, float(confidence), order_codes(codes))
