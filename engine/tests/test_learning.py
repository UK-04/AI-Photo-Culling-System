"""The personal model: it should learn a taste the rules cannot know about."""

from __future__ import annotations

import pytest

from culler.learning.active import teach_queue
from culler.synth import make_shoot


def _taste(photo) -> str:
    """A made-up photographer: rejects technical failures like anyone, and also dislikes
    every warm-toned scene. The second part is pure taste; no rule can know it."""
    if photo.defect in ("blur", "shake", "black") or photo.warm:
        return "REJECT"
    return "KEEP"


def _cull(engine, folder, photos, decide=_taste):
    shoot_id = engine.repo.add_shoot(str(folder))
    assert engine.scan(shoot_id, inline=True).stage == "done"
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    for p in photos:
        engine.repo.add_decision(rows[p.file]["id"], label=decide(p))
    return shoot_id


def _agreement(engine, shoot_id, photos, decide=_taste) -> float:
    """Share of photos where the engine's KEEP/not-KEEP matches the photographer."""
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    hits = [(rows[p.file]["label"] == "KEEP") == (decide(p) == "KEEP") for p in photos]
    return sum(hits) / len(hits)


@pytest.fixture
def culled(engine, tmp_path):
    """Three culled shoots, about 330 decisions in total."""
    shoots = []
    for seed in (11, 12, 13):
        folder = tmp_path / f"shoot{seed}"
        photos = make_shoot(folder, scenes=70, seed=seed, size=(320, 214), burst_share=0.2, defect_share=0.25)
        shoots.append((_cull(engine, folder, photos), folder, photos))
    return shoots


def test_no_model_before_enough_decisions(engine, tmp_path):
    photos = make_shoot(tmp_path / "small", scenes=12, seed=1, size=(320, 214))
    _cull(engine, tmp_path / "small", photos)
    result = engine.train()
    assert result.status == "not_enough_data" and "300" in result.message
    assert engine.repo.active_model() is None
    assert engine.model_status()["ready"] is False


def test_model_learns_taste_and_beats_rules_on_an_unseen_shoot(engine, culled, tmp_path):
    assert engine.repo.labeled_count() >= engine.settings.learning.min_decisions
    result = engine.train()
    assert result.status == "trained", result.message
    m = result.metrics
    assert m["validation"] == "leave-shoot-out"
    assert m["accuracy"] > 0.85 and m["accuracy"] > m["rules_accuracy"] + 0.1

    # A fourth shoot the model has never seen, culled by nobody yet.
    folder = tmp_path / "new"
    photos = make_shoot(folder, scenes=60, seed=99, size=(320, 214), burst_share=0.2, defect_share=0.25)
    shoot_id = engine.repo.add_shoot(str(folder))
    engine.scan(shoot_id, inline=True)
    rows = engine.repo.grid(shoot_id)
    assert all(r["personal_score"] is not None for r in rows if r["status"] == "done")
    with_model = _agreement(engine, shoot_id, photos)

    engine.repo.conn().execute("UPDATE models SET active = 0")
    engine.repo.conn().commit()
    engine.rescore(shoot_id)
    rules_only = _agreement(engine, shoot_id, photos)
    assert all(r["personal_score"] is None for r in engine.repo.grid(shoot_id))
    assert with_model > rules_only + 0.1, (with_model, rules_only)


def test_taste_rejects_carry_a_reason_and_hard_rejects_stay(engine, culled):
    engine.train()
    shoot_id, _, photos = culled[0]
    engine.rescore(shoot_id)
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    warm_clean = [rows[p.file] for p in photos if p.warm and p.defect == "none" and p.burst < 0]
    taste_rejected = [r for r in warm_clean if r["label"] == "REJECT"]
    assert len(taste_rejected) > 0.5 * len(warm_clean)
    assert all("usually reject" in r["reason_primary"].lower() for r in taste_rejected)
    blurred = [rows[p.file] for p in photos if p.defect in ("blur", "shake", "black")]
    assert all(r["label"] == "REJECT" for r in blurred)


def test_training_is_refused_with_one_class(engine, culled):
    # Flip every decision to KEEP: nothing to tell apart.
    for row in engine.repo.feature_rows(engine.embedder.name, labeled_only=True):
        engine.repo.add_decision(row["photo_id"], label="KEEP")
    assert engine.train().status == "one_class"


def test_retrain_keeps_or_replaces_model_and_reports_holdout(engine, culled):
    first = engine.train()
    again = engine.train()
    assert again.status in ("trained", "kept_current")
    assert "holdout_new" in again.metrics and "holdout_current" in again.metrics
    assert engine.repo.active_model()["version"] in (first.version, again.version)


def test_teach_queue_puts_uncertain_photos_first():
    rows = [
        {"id": 1, "status": "done", "user_label": None, "final_score": 0.95, "personal_score": None, "burst_rank": 0},
        {"id": 2, "status": "done", "user_label": None, "final_score": 0.63, "personal_score": None, "burst_rank": 0},
        {"id": 3, "status": "done", "user_label": "KEEP", "final_score": 0.62, "personal_score": None, "burst_rank": 0},
        {"id": 4, "status": "done", "user_label": None, "final_score": 0.62, "personal_score": None, "burst_rank": 2},
        {"id": 5, "status": "done", "user_label": None, "final_score": 0.20, "personal_score": 0.52, "burst_rank": None},
        {"id": 6, "status": "error", "user_label": None, "final_score": None, "personal_score": None, "burst_rank": None},
    ]
    assert teach_queue(rows, keep_threshold=0.62) == [2, 5, 1]
    assert teach_queue(rows, keep_threshold=0.62, limit=1) == [2]
