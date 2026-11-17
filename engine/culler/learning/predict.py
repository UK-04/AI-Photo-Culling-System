"""Load the active personal model and predict keep-probabilities."""

from __future__ import annotations

import threading

import joblib
import numpy as np

from ..db import Repo
from .features import build_matrix

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def load_active(repo: Repo, embedder_name: str) -> dict | None:
    """The active model bundle if it matches the embedder in use, else ``None``."""
    info = repo.active_model()
    if info is None or info["embedder"] != embedder_name:
        return None
    with _lock:
        bundle = _cache.get(info["path"])
        if bundle is None:
            try:
                bundle = joblib.load(info["path"])
            except Exception:
                return None
            _cache.clear()
            _cache[info["path"]] = bundle
    return {**bundle, "n_decisions": info["n_decisions"], "metrics": info["metrics"]}


def predict_keep(repo: Repo, embedder_name: str, shoot_id: int) -> tuple[dict[int, float], str | None]:
    """Return ``({photo_id: keep probability}, model version)`` for a shoot, or ``({}, None)``."""
    bundle = load_active(repo, embedder_name)
    if bundle is None:
        return {}, None
    rows = repo.feature_rows(embedder_name, shoot_id=shoot_id)
    if not rows:
        return {}, bundle["version"]
    X = build_matrix(rows)
    if X.shape[1] != bundle.get("n_features", X.shape[1]):
        return {}, None
    proba = bundle["estimator"].predict_proba(X)[:, 1]
    return {int(r["photo_id"]): float(np.clip(p, 0.0, 1.0)) for r, p in zip(rows, proba, strict=True)}, bundle["version"]
