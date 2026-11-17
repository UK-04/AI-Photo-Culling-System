"""The "Teach me" queue: undecided photos where one answer teaches the model the most."""

from __future__ import annotations


def teach_queue(grid_rows: list[dict], keep_threshold: float, limit: int = 50) -> list[int]:
    """Photo ids ordered most-uncertain first.

    With a personal model, uncertainty is how close its keep-probability is to 50/50.
    Before there is one, it is how close the rule score sits to the keep threshold.
    Only the best frame of a burst is offered, so a burst does not fill the queue.
    """

    def uncertainty(r: dict) -> float:
        if r.get("personal_score") is not None:
            return abs(r["personal_score"] - 0.5)
        score = r.get("final_score")
        return 1.0 if score is None else abs(score - keep_threshold)

    candidates = [
        r for r in grid_rows
        if r.get("user_label") is None and r.get("status") == "done" and not (r.get("burst_rank") or 0)
    ]
    candidates.sort(key=lambda r: (uncertainty(r), r["id"]))
    return [r["id"] for r in candidates[:limit]]
