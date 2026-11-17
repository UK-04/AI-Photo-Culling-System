"""Group frames shot in quick succession of the same thing, and pick the best of each group."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Frame:
    photo_id: int
    ts: float | None  # capture time in seconds
    vec: np.ndarray | None  # L2-normalized embedding
    name: str = ""


def group_bursts(frames: list[Frame], gap_s: float, sim_threshold: float) -> list[list[int]]:
    """Return groups (2+ photo ids, in shooting order) of consecutive look-alike frames.

    A frame joins the running group when it was shot within ``gap_s`` of the previous
    frame AND looks like it (cosine similarity >= ``sim_threshold``). It must also still
    resemble the group's first frame, so a slow pan cannot chain unrelated photos together.
    """
    usable = [f for f in frames if f.ts is not None and f.vec is not None]
    usable.sort(key=lambda f: (f.ts, f.name))
    groups: list[list[int]] = []
    current: list[Frame] = []

    def flush() -> None:
        if len(current) >= 2:
            groups.append([f.photo_id for f in current])

    for frame in usable:
        if current:
            prev, first = current[-1], current[0]
            close_in_time = (frame.ts - prev.ts) <= gap_s
            alike = float(frame.vec @ prev.vec) >= sim_threshold
            same_scene = float(frame.vec @ first.vec) >= sim_threshold - 0.08
            if close_in_time and alike and same_scene:
                current.append(frame)
                continue
            flush()
        current = [frame]
    flush()
    return groups


def rank_burst(candidates: list[dict]) -> list[int]:
    """Order a burst best-first.

    Each candidate: ``{"photo_id", "main_eyes_closed" (0/1/None), "subject_sharpness",
    "exposure_score", "eyes_closed_count"}``.
    Open eyes beat closed eyes; then fewer blinking faces; then sharpness, with exposure
    as a tie-breaker. Earlier frames win exact ties so the order is stable.
    """

    def key(item: tuple[int, dict]):
        i, c = item
        closed = 1 if c.get("main_eyes_closed") == 1 else 0
        blinkers = int(c.get("eyes_closed_count") or 0)
        sharp = float(c.get("subject_sharpness") or 0.0)
        expo = float(c.get("exposure_score") or 0.0)
        return (closed, blinkers, -(sharp * (0.85 + 0.15 * expo)), i)

    ordered = sorted(enumerate(candidates), key=key)
    return [c["photo_id"] for _, c in ordered]
