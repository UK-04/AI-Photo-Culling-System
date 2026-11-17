"""Per-shoot normalization.

Lighting, lenses and ISO differ between events, so an absolute sharpness number means
different things on different nights. Ranking each photo against the rest of its own
shoot gives a number that means the same thing everywhere.
"""

from __future__ import annotations

import numpy as np


def percentile_ranks(values: list[float | None]) -> list[float | None]:
    """Rank of each value among the non-missing ones, from 0 (lowest) to 1 (highest).

    Ties share their average rank. A lone value gets 0.5. Missing values stay ``None``.
    """
    idx = [i for i, v in enumerate(values) if v is not None and not np.isnan(v)]
    out: list[float | None] = [None] * len(values)
    if not idx:
        return out
    if len(idx) == 1:
        out[idx[0]] = 0.5
        return out
    arr = np.array([values[i] for i in idx], dtype=np.float64)
    order = arr.argsort(kind="mergesort")
    ranks = np.empty(len(arr), dtype=np.float64)
    ranks[order] = np.arange(len(arr), dtype=np.float64)
    # average the ranks of ties
    sorted_vals = arr[order]
    start = 0
    for end in range(1, len(arr) + 1):
        if end == len(arr) or sorted_vals[end] != sorted_vals[start]:
            if end - start > 1:
                ranks[order[start:end]] = (start + end - 1) / 2.0
            start = end
    ranks /= len(arr) - 1
    for i, r in zip(idx, ranks, strict=True):
        out[i] = float(r)
    return out
