"""Getting results out: XMP for Lightroom, copies of the picks, CSV.

Nothing here modifies, moves or deletes an original photo.
"""

KEEP, REVIEW, REJECT = "KEEP", "REVIEW", "REJECT"


def effective_label(row: dict) -> str | None:
    """The photographer's decision when there is one, otherwise the engine's recommendation."""
    return row.get("user_label") or row.get("label")


def select_rows(rows: list[dict], selection: str) -> list[dict]:
    """Filter grid rows: ``picked`` (you marked KEEP), ``keep`` (you or the engine say KEEP),
    ``decided`` (anything you marked), or ``all``."""
    if selection == "picked":
        return [r for r in rows if r.get("user_label") == KEEP]
    if selection == "keep":
        return [r for r in rows if effective_label(r) == KEEP]
    if selection == "decided":
        return [r for r in rows if r.get("user_label") or (r.get("user_rating") or 0) > 0]
    if selection == "all":
        return list(rows)
    raise ValueError(f"Unknown selection: {selection}")
