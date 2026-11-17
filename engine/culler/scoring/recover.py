"""Estimate how fixable a photo's problems are in editing.

This is a rule-of-thumb estimate from the measurements Culler already has, not a
simulation of an edit:

* Exposure is fixable up to a point. RAW files have roughly 3 stops of clean shadow
  recovery and about 1 stop of highlight recovery; JPEGs have much less, and high ISO
  eats into both because lifting shadows lifts noise.
* Blown highlights are data that is gone. A little is fine, a blown face is not.
* Blur, missed focus and closed eyes cannot be fixed. Slight softness sharpens up a bit.

For RAW files the numbers are measured on the camera's embedded preview, so the real
file usually holds a little more than this suggests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

LEVELS = ((0.75, "Easy fix"), (0.5, "Fixable"), (0.25, "Hard to fix"), (0.0, "Not fixable"))
TARGET_MEAN = 118.0  # mid-grey-ish average for a normally exposed frame (0-255)


@dataclass
class Recovery:
    score: float  # 0-1; 1 means nothing needs fixing
    label: str
    note: str

    @property
    def has_problem(self) -> bool:
        return self.score < 1.0


def _curve(ratio: float) -> float:
    """ratio = how much of the available headroom the fix needs. 1.0 lands on the Fixable line."""
    if ratio <= 1.0:
        return 1.0 - 0.5 * ratio
    return max(0.0, 0.5 - (ratio - 1.0))


def stops_under(mean: float) -> float:
    """Roughly how many stops the frame is below a normal exposure (sRGB gamma of 2.2)."""
    return max(0.0, 2.2 * math.log2(TARGET_MEAN / max(mean, 1.0)))


def assess(analysis: dict, codes: list[str], is_raw: bool, iso: int | None) -> Recovery:
    issues: list[tuple[float, str]] = []
    iso = iso or 0
    kind = "RAW" if is_raw else "JPEG"

    if "blank_frame" in codes:
        issues.append((0.0, "Nothing in the frame to recover."))
    if "eyes_closed" in codes:
        issues.append((0.0, "Closed eyes cannot be fixed in editing."))
    if {"camera_shake", "out_of_focus", "missed_focus"} & set(codes):
        issues.append((0.05, "Blur cannot be fixed in editing."))
    elif "soft_focus" in codes:
        issues.append((0.55, "Slightly soft. Sharpening helps a little."))

    mean = analysis.get("exposure_mean")
    if "underexposed" in codes and mean is not None:
        stops = stops_under(mean)
        headroom = 3.5 if is_raw else 2.0
        noise = ""
        if iso >= 6400:
            headroom -= 1.5
        elif iso >= 3200:
            headroom -= 1.0
        elif iso >= 1600:
            headroom -= 0.5
        if iso >= 1600:
            noise = f" At ISO {iso}, lifting it will show noise."
        if not is_raw and (analysis.get("clip_low_pct") or 0) > 20:
            headroom -= 0.5  # crushed shadows in a JPEG hold nothing to lift
        ratio = stops / max(headroom, 0.5)
        if ratio > 1.0:
            room = f"That is more than a {kind} can recover cleanly."
        else:
            room = "RAW has room to lift it." if is_raw else "A JPEG has limited room, so expect some loss."
        issues.append((_curve(ratio), f"About {stops:.1f} stops under. {room}{noise}"))

    if {"overexposed", "highlights_clipped", "face_blown"} & set(codes):
        frame = analysis.get("clip_high_pct") or 0.0
        face = analysis.get("face_clip_high_pct") or 0.0
        ratio = max(frame / (20.0 if is_raw else 6.0), face / (15.0 if is_raw else 4.0))
        if "overexposed" in codes and mean is not None and frame < 1.0:
            # bright but not clipped: the detail is still there
            ratio = max(ratio, 0.4 if is_raw else 0.7)
        where = f"{face:.0f}% of the main face" if face > frame else f"{frame:.0f}% of the frame"
        tail = "RAW can usually pull back about a stop." if is_raw else "Blown highlights in a JPEG are gone."
        issues.append((_curve(ratio), f"{where} is blown out. {tail}"))

    if not issues:
        return Recovery(1.0, "Nothing to fix", "")
    issues.sort(key=lambda i: i[0])
    score = issues[0][0]
    label = next(name for floor, name in LEVELS if score >= floor)
    return Recovery(score, label, " ".join(note for _, note in issues[:2]))
