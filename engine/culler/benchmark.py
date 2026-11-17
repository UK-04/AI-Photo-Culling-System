"""Compare the engine's recommendations with a cull the photographer already did by hand.

Ground truth can come from three places, checked in this order:

1. ``--truth file.csv``  with columns ``file,label`` (label: keep/pick/1 or reject/0)
2. ``--picks-dir DIR``   a folder holding the photos that were kept (matched by file name
                         without extension, so edited JPEG exports match their RAW originals);
                         everything else in the shoot counts as rejected
3. sub-folders           photos under ``picks``/``keep``/``selects`` are keeps, photos under
                         ``rejects``/``rejected`` are rejects
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import numpy as np

from .config import SUPPORTED_EXTS

_KEEP_WORDS = {"keep", "keeps", "keeper", "keepers", "pick", "picks", "picked", "select", "selects", "selected", "1", "true", "yes"}
_REJECT_WORDS = {"reject", "rejects", "rejected", "cull", "culled", "0", "false", "no"}


def load_truth(shoot_folder: str | os.PathLike, truth_csv: str | None = None, picks_dir: str | None = None) -> dict[str, str]:
    """Return ``{file stem (lower-case): "KEEP" | "REJECT"}``."""
    truth: dict[str, str] = {}
    if truth_csv:
        with open(truth_csv, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                lowered = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                name = lowered.get("file") or lowered.get("filename") or lowered.get("name")
                label = (lowered.get("label") or lowered.get("decision") or "").lower()
                if not name:
                    continue
                if label in _KEEP_WORDS:
                    truth[Path(name).stem.lower()] = "KEEP"
                elif label in _REJECT_WORDS:
                    truth[Path(name).stem.lower()] = "REJECT"
        return truth

    root = Path(shoot_folder)
    if picks_dir:
        kept = {p.stem.lower() for p in Path(picks_dir).rglob("*") if p.is_file() and not p.name.startswith(".")}
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS and not p.name.startswith("."):
                truth[p.stem.lower()] = "KEEP" if p.stem.lower() in kept else "REJECT"
        return truth

    for p in root.rglob("*"):
        if not (p.is_file() and p.suffix.lower() in SUPPORTED_EXTS):
            continue
        parents = {part.lower() for part in p.relative_to(root).parts[:-1]}
        if parents & _KEEP_WORDS:
            truth[p.stem.lower()] = "KEEP"
        elif parents & _REJECT_WORDS:
            truth[p.stem.lower()] = "REJECT"
    return truth


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def evaluate(grid_rows: list[dict], bursts: list[dict], truth: dict[str, str]) -> dict:
    """Score the engine against the truth. ``grid_rows`` from ``Repo.grid``, ``bursts`` from ``Repo.list_bursts``."""
    matched = [(r, truth[Path(r["path"]).stem.lower()]) for r in grid_rows if Path(r["path"]).stem.lower() in truth and r["status"] == "done"]
    n = len(matched)
    out: dict = {"photos": len(grid_rows), "with_truth": n}
    if n == 0:
        return out

    def count(ai: str | None, true: str | None) -> int:
        return sum(1 for r, t in matched if (ai is None or r["label"] == ai) and (true is None or t == true))

    out["truth_keep"], out["truth_reject"] = count(None, "KEEP"), count(None, "REJECT")
    for label in ("KEEP", "REVIEW", "REJECT"):
        out[f"ai_{label.lower()}"] = count(label, None)
    # Precision on REJECT is the number that matters most: a wrong reject hides a good photo.
    out["reject_precision"] = _ratio(count("REJECT", "REJECT"), count("REJECT", None))
    out["reject_recall"] = _ratio(count("REJECT", "REJECT"), count(None, "REJECT"))
    out["keep_precision"] = _ratio(count("KEEP", "KEEP"), count("KEEP", None))
    out["keep_recall"] = _ratio(count("KEEP", "KEEP"), count(None, "KEEP"))
    out["good_photos_wrongly_rejected"] = count("REJECT", "KEEP")

    # Spec check: do the photographer's rejects sit at the soft end of the shoot?
    reject_pcts = [r["sharp_pct"] for r, t in matched if t == "REJECT" and r["sharp_pct"] is not None]
    keep_pcts = [r["sharp_pct"] for r, t in matched if t == "KEEP" and r["sharp_pct"] is not None]
    if reject_pcts:
        out["rejects_in_bottom_quarter_sharpness"] = float(np.mean(np.array(reject_pcts) <= 0.25))
        out["median_sharpness_pct_of_rejects"] = float(np.median(reject_pcts))
    if keep_pcts:
        out["median_sharpness_pct_of_keeps"] = float(np.median(keep_pcts))

    # Burst check: is the frame the engine put on top one the photographer kept?
    by_id = {r["id"]: t for r, t in matched}
    judged = agree = 0
    for b in bursts:
        labels = [by_id.get(pid) for pid in b["photo_ids"]]
        if "KEEP" not in labels:
            continue  # the photographer kept nothing from this burst: no right answer
        judged += 1
        agree += by_id.get(b["best_photo_id"]) == "KEEP"
    out["bursts"], out["bursts_judged"] = len(bursts), judged
    out["burst_best_is_a_pick"] = _ratio(agree, judged)
    return out


def format_report(m: dict) -> str:
    def pct(v) -> str:
        return "n/a" if v is None else f"{v:.0%}"

    if not m.get("with_truth"):
        return f"{m['photos']} photos analyzed, but none matched the ground truth. Check the file names."
    lines = [
        f"Photos with ground truth: {m['with_truth']} of {m['photos']}  (you kept {m['truth_keep']}, rejected {m['truth_reject']})",
        f"Engine said: KEEP {m['ai_keep']}  REVIEW {m['ai_review']}  REJECT {m['ai_reject']}",
        "",
        f"REJECT precision  {pct(m['reject_precision'])}   (target 85%+; good photos wrongly rejected: {m['good_photos_wrongly_rejected']})",
        f"REJECT recall     {pct(m['reject_recall'])}   (share of your rejects it caught outright)",
        f"KEEP precision    {pct(m['keep_precision'])}",
        f"KEEP recall       {pct(m['keep_recall'])}",
    ]
    if "rejects_in_bottom_quarter_sharpness" in m:
        lines.append(f"Your rejects in the softest quarter of the shoot: {pct(m['rejects_in_bottom_quarter_sharpness'])}")
    if m.get("bursts_judged"):
        lines.append(f"Bursts where the top frame is one you kept: {pct(m['burst_best_is_a_pick'])}  ({m['bursts_judged']} bursts)")
    return "\n".join(lines)
