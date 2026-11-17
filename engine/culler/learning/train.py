"""Train the personal model and decide whether it is good enough to ship.

Steps, in order:

1. Collect every photo the photographer has marked KEEP or REJECT.
2. Below ``min_decisions`` there is no model. From there, logistic regression; from
   ``boosting_from`` on, gradient boosting. Probabilities are calibrated either way.
3. Measure honestly: leave-one-shoot-out when there are 2+ shoots (the model is always
   tested on a shoot it never saw), otherwise 5-fold.
4. Ship only if the candidate is at least as good as the model in use, judged on the
   most recent shoot, which the candidate is not allowed to train on for that test.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..config import Settings
from ..db import Repo
from .features import build_matrix, labels


@dataclass
class TrainResult:
    status: str  # trained | not_enough_data | one_class | kept_current
    message: str
    n_decisions: int = 0
    n_shoots: int = 0
    version: str | None = None
    kind: str | None = None
    metrics: dict | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def make_estimator(n: int, settings: Settings):
    """Return (kind, unfitted calibrated classifier) for a dataset of ``n`` decisions."""
    if n >= settings.learning.boosting_from:
        base = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, max_leaf_nodes=15, l2_regularization=1.0, random_state=0)
        kind = "boosting"
    else:
        base = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.05, class_weight="balanced", max_iter=3000),
        )
        kind = "logistic"
    return kind, CalibratedClassifierCV(base, method="sigmoid", cv=3)


def _cv_predictions(X: np.ndarray, y: np.ndarray, groups: np.ndarray, settings: Settings) -> tuple[np.ndarray, str]:
    """Out-of-sample keep-probabilities for every row."""
    n_groups = len(np.unique(groups))
    if n_groups >= 2:
        splits = list(GroupKFold(n_splits=min(n_groups, 8)).split(X, y, groups))
        how = "leave-shoot-out"
    else:
        splits = list(StratifiedKFold(n_splits=5, shuffle=True, random_state=0).split(X, y))
        how = "5-fold"
    proba = np.full(len(y), np.nan)
    for train_idx, test_idx in splits:
        if len(np.unique(y[train_idx])) < 2 or np.bincount(y[train_idx]).min() < 3:
            continue
        _, est = make_estimator(len(train_idx), settings)
        est.fit(X[train_idx], y[train_idx])
        proba[test_idx] = est.predict_proba(X[test_idx])[:, 1]
    return proba, how


def _metrics(y: np.ndarray, proba: np.ndarray) -> dict:
    ok = ~np.isnan(proba)
    if ok.sum() == 0:
        return {}
    yy, pp = y[ok], proba[ok]
    out = {"accuracy": float(accuracy_score(yy, pp >= 0.5)), "n_evaluated": int(ok.sum())}
    if len(np.unique(yy)) == 2:
        out["auc"] = float(roc_auc_score(yy, pp))
    return out


def train_model(repo: Repo, settings: Settings, embedder_name: str, force: bool = False) -> TrainResult:
    rows = repo.feature_rows(embedder_name, labeled_only=True)
    n = len(rows)
    n_shoots = len({r["shoot_id"] for r in rows})
    need = settings.learning.min_decisions
    if n < need:
        return TrainResult("not_enough_data", f"{n} of {need} decisions needed before the first model.", n, n_shoots)

    X, y = build_matrix(rows), labels(rows)
    groups = np.array([r["shoot_id"] for r in rows])
    if len(np.unique(y)) < 2 or np.bincount(y).min() < 10:
        return TrainResult("one_class", "Need at least 10 keeps and 10 rejects to learn the difference.", n, n_shoots)

    kind, estimator = make_estimator(n, settings)

    # --- honest performance estimate, and the rule-based baseline on the same photos ---
    proba, how = _cv_predictions(X, y, groups, settings)
    metrics = {"validation": how, **_metrics(y, proba)}
    rule_keep = np.array([1 if r["ai_label"] == "KEEP" else 0 for r in rows])
    rule_scores = np.array([r["rule_score"] if r["rule_score"] is not None else 0.5 for r in rows])
    metrics["rules_accuracy"] = float(accuracy_score(y, rule_keep))
    if len(np.unique(y)) == 2:
        metrics["rules_auc"] = float(roc_auc_score(y, rule_scores))
    metrics["keep_share"] = float(y.mean())

    # --- ship only if it does not lose to the model in use ---
    current = repo.active_model()
    if current is not None and current["embedder"] == embedder_name and n_shoots >= 2 and not force:
        newest = max(rows, key=lambda r: r["last_decision"] or 0)["shoot_id"]
        test, train = groups == newest, groups != newest
        if test.sum() >= 30 and len(np.unique(y[train])) == 2 and np.bincount(y[train]).min() >= 10:
            try:
                old = joblib.load(current["path"])["estimator"]
                _, cand = make_estimator(int(train.sum()), settings)
                cand.fit(X[train], y[train])
                acc_new = float(accuracy_score(y[test], cand.predict_proba(X[test])[:, 1] >= 0.5))
                acc_old = float(accuracy_score(y[test], old.predict_proba(X[test])[:, 1] >= 0.5))
                metrics["holdout_new"], metrics["holdout_current"] = acc_new, acc_old
                if acc_new + 0.01 < acc_old:
                    return TrainResult(
                        "kept_current",
                        f"New model scored {acc_new:.0%} on the latest shoot, the current one {acc_old:.0%}. Keeping the current model.",
                        n, n_shoots, current["version"], current["kind"], metrics,
                    )
            except Exception as exc:  # an unreadable old model must not block a new one
                metrics["holdout_error"] = f"{type(exc).__name__}: {exc}"

    estimator.fit(X, y)
    version = time.strftime("m%Y%m%d-%H%M%S")
    path = Path(settings.models_dir) / f"personal-{version}.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"estimator": estimator, "version": version, "kind": kind, "embedder": embedder_name, "n_features": int(X.shape[1])},
        path,
    )
    repo.register_model(version, kind, embedder_name, n, n_shoots, metrics, str(path))
    acc = metrics.get("accuracy")
    msg = f"Trained on {n} decisions from {n_shoots} shoot{'s' if n_shoots != 1 else ''}."
    if acc is not None:
        msg += f" Agrees with you {acc:.0%} of the time on photos it had not seen (rules alone: {metrics['rules_accuracy']:.0%})."
    return TrainResult("trained", msg, n, n_shoots, version, kind, metrics)
