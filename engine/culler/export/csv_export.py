"""Write the results of a shoot as CSV (one row per photo)."""

from __future__ import annotations

import csv
import os
from pathlib import Path

from . import effective_label

COLUMNS = (
    "file", "path", "captured_at", "decision", "your_label", "your_rating", "ai_label", "ai_confidence",
    "reason", "reason_2", "score", "rule_score", "personal_score", "sharpness_percentile", "burst_id",
    "burst_rank", "burst_size", "status",
)


def to_record(row: dict) -> dict:
    def r(value, digits=3):
        return "" if value is None else round(float(value), digits)

    return {
        "file": row.get("name") or os.path.basename(row["path"]),
        "path": row["path"],
        "captured_at": row.get("captured_at") or "",
        "decision": effective_label(row) or "",
        "your_label": row.get("user_label") or "",
        "your_rating": row.get("user_rating") or 0,
        "ai_label": row.get("label") or "",
        "ai_confidence": r(row.get("confidence"), 2),
        "reason": row.get("reason_primary") or (row.get("error") or ""),
        "reason_2": row.get("reason_secondary") or "",
        "score": r(row.get("final_score")),
        "rule_score": r(row.get("rule_score")),
        "personal_score": r(row.get("personal_score")),
        "sharpness_percentile": r(row.get("sharp_pct"), 2),
        "burst_id": row.get("burst_id") or "",
        "burst_rank": "" if row.get("burst_id") is None else row.get("burst_rank"),
        "burst_size": row.get("burst_size") or 1,
        "status": row.get("status") or "",
    }


def export_csv(rows: list[dict], dest: str | os.PathLike) -> Path:
    path = Path(dest).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(to_record(row))
    return path
