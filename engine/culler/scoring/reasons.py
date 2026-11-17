"""Plain-English reasons. Codes are stable identifiers; the text can change freely."""

from __future__ import annotations

# Hard problems (can reject), soft problems (cost score), then positives.
# The order here is the order of importance when picking a primary and secondary reason.
REASONS: dict[str, str] = {
    # hard
    "blank_frame": "Blank frame",
    "eyes_closed": "Eyes closed",
    "camera_shake": "Camera shake",
    "missed_focus": "Focus missed the subject",
    "out_of_focus": "Subject out of focus",
    "face_blown": "Face overexposed",
    "taste_reject": "Like photos you usually reject",
    # soft
    "you_keep_similar": "You usually keep ones like this",
    "burst_alt": "A better frame exists in this burst",
    "someone_blinking": "Someone is blinking",
    "soft_focus": "Slightly soft",
    "underexposed": "Underexposed",
    "overexposed": "Overexposed",
    "highlights_clipped": "Highlights blown out",
    "eyes_unknown": "Could not check eyes",
    # positive
    "best_of_burst": "Best frame of the burst",
    "taste_keep": "Matches what you keep",
    "sharp": "Sharp",
    "eyes_open": "Eyes open",
    "well_exposed": "Well exposed",
}

HARD = {"blank_frame", "eyes_closed", "camera_shake", "missed_focus", "out_of_focus", "face_blown"}
_ORDER = {code: i for i, code in enumerate(REASONS)}

# Reason chips the photographer can attach to a reject (also the labels for training notes).
USER_REASONS = ("focus", "eyes", "expression", "exposure", "duplicate", "composition", "other")


def order_codes(codes: list[str]) -> list[str]:
    seen: list[str] = []
    for c in sorted(codes, key=lambda c: _ORDER.get(c, 999)):
        if c not in seen:
            seen.append(c)
    return seen


def describe(codes: list[str], burst_size: int = 1) -> tuple[str, str | None]:
    """Return (primary, secondary) reason text for an ordered list of codes."""
    ordered = order_codes(codes)
    texts = []
    for c in ordered:
        text = REASONS.get(c, c)
        if c == "best_of_burst" and burst_size > 1:
            text = f"Best frame of {burst_size}"
        texts.append(text)
    if not texts:
        return "No issues found", None
    return texts[0], (texts[1] if len(texts) > 1 else None)


def one_line(codes: list[str], burst_size: int = 1) -> str:
    primary, secondary = describe(codes, burst_size)
    return primary if not secondary else f"{primary}, {secondary[0].lower()}{secondary[1:]}"
