"""Topic categories and the relevance measure."""

from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from culler.api import create_app
from culler.topics.categorize import (
    OTHER,
    categorize_by_faces,
    categorize_by_vision,
    face_prior,
    people_bucket,
    relevance,
)
from culler.topics.taxonomy import SHOOT_TYPES, shoot_type_list

AUTH = {"X-Culler-Token": "t"}
DIM = 64


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


class FakeText:
    """Stands in for CLIP's text side: every description of a category maps near that category's axis."""

    def __init__(self, shoot_type):
        self.axis = {}
        for i, cat in enumerate(SHOOT_TYPES[shoot_type][1]):
            for prompt in cat.prompts:
                self.axis[prompt] = i

    def __call__(self, texts):
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            out[row, self.axis[text]] = 1.0
        return out

    def image(self, category_index, rng, noise=0.02):
        v = rng.normal(0, noise, DIM).astype(np.float32)
        v[category_index] += 1.0
        return _unit(v)


def test_every_shoot_type_is_well_formed():
    assert {t["id"] for t in shoot_type_list()} == {"general", "wedding", "portrait", "event", "travel"}
    for _key, (name, categories) in SHOOT_TYPES.items():
        names = [c.name for c in categories]
        assert name and len(names) == len(set(names)) >= 5
        assert all(c.prompts and c.faces[0] <= c.faces[1] for c in categories)
    wedding = [c.name for c in SHOOT_TYPES["wedding"][1]]
    assert {"Group photos", "Couple portraits", "Single portraits"} <= set(wedding)


def test_people_buckets():
    assert people_bucket(0, None) == "No people"
    assert people_bucket(1, 0.30) == "Single portraits" and people_bucket(1, 0.05) == "One person, wide"
    assert people_bucket(2, 0.2) == "Pairs and couples"
    assert people_bucket(4, 0.1) == "Small groups" and people_bucket(12, 0.05) == "Large groups"
    topics = categorize_by_faces([7, 8], [0, 2], [None, 0.2])
    assert [(t.photo_id, t.category, t.method) for t in topics] == [(7, "No people", "faces"), (8, "Pairs and couples", "faces")]


def test_face_prior_falls_off_outside_the_usual_range():
    group = next(c for c in SHOOT_TYPES["wedding"][1] if c.name == "Group photos")
    assert face_prior(group, 5) == 1.0 and face_prior(group, 2) == 0.35 and face_prior(group, 0) == 0.12


def test_vision_categories_follow_the_closest_description():
    rng = np.random.default_rng(0)
    fake = FakeText("wedding")
    names = [c.name for c in SHOOT_TYPES["wedding"][1]]
    faces_for = {"Group photos": 6, "Couple portraits": 2, "Single portraits": 1, "Ceremony": 4, "Reception and dancing": 5,
                 "Getting ready": 2, "Details": 0, "Venue and scenery": 0}
    vectors = np.stack([fake.image(i, rng) for i in range(len(names))])
    topics = categorize_by_vision(list(range(len(names))), vectors, [faces_for[n] for n in names], "wedding", fake)
    assert [t.category for t in topics] == names
    assert all(t.confidence > 0.9 and t.method == "vision" for t in topics)
    assert categorize_by_vision([], np.zeros((0, DIM)), [], "wedding", fake) == []
    # an unknown shoot type falls back to the general categories instead of failing
    general = categorize_by_vision([1], np.stack([FakeText("general").image(0, rng)]), [5], "no-such-type", FakeText("general"))
    assert general[0].category == "Group photos"


def test_face_count_settles_a_close_call_and_weak_matches_become_other():
    fake = FakeText("wedding")
    # equally like "Group photos" (axis 0) and "Couple portraits" (axis 1)
    v = np.zeros(DIM, dtype=np.float32)
    v[0] = v[1] = 1.0
    both = np.stack([_unit(v), _unit(v)])
    two, many = categorize_by_vision([1, 2], both, [2, 7], "wedding", fake)
    assert two.category == "Couple portraits" and many.category == "Group photos"
    # like nothing in particular: no category is confident
    vague = categorize_by_vision([3], np.stack([_unit(np.ones(DIM))]), [3], "wedding", fake)
    assert vague[0].category == OTHER and vague[0].confidence < 0.4


def _clusters(rng, sizes, spread=0.05):
    out = []
    for size in sizes:
        centre = _unit(rng.normal(0, 1, DIM))
        out += [_unit(centre + rng.normal(0, spread, DIM)) for _ in range(size)]
    return out


def test_relevance_flags_the_photos_that_do_not_belong():
    rng = np.random.default_rng(1)
    vectors = _clusters(rng, [30, 25, 20])
    strays = [_unit(rng.normal(0, 1, DIM)) for _ in range(2)]  # like nothing else in the shoot
    scores, off = relevance(np.stack(vectors + strays), [None] * 77)
    assert off[-2:] == [True, True] and not any(off[:-2])
    assert max(scores[-2:]) < min(scores[:-2])
    assert min(scores) == 0.0 and max(scores) == 1.0


def test_relevance_flags_nothing_in_a_consistent_shoot_and_skips_tiny_ones():
    rng = np.random.default_rng(2)
    scores, off = relevance(np.stack(_clusters(rng, [40, 40])), [None] * 80)
    assert not any(off)
    scores, off = relevance(np.stack(_clusters(rng, [5])), [None] * 5)
    assert scores == [None] * 5 and off == [False] * 5


def test_a_burst_does_not_vouch_for_itself():
    """Five near-identical frames of something unrelated are still off-topic."""
    rng = np.random.default_rng(3)
    vectors = _clusters(rng, [40, 40])
    odd = _unit(rng.normal(0, 1, DIM))
    burst = [_unit(odd + rng.normal(0, 0.01, DIM)) for _ in range(5)]
    _, off_with_burst = relevance(np.stack(vectors + burst), [None] * 80 + [9] * 5)
    assert all(off_with_burst[-5:]) and not any(off_with_burst[:80])
    _, off_unmarked = relevance(np.stack(vectors + burst), [None] * 85)
    assert not any(off_unmarked[-5:])  # without the burst marking they look like a small topic of their own


def test_clip_text_embedding_runs():
    """Random weights (no download in tests): checks the code path and shapes only."""
    pytest.importorskip("torch")
    pytest.importorskip("open_clip")
    from culler.similarity.embeddings import ClipEmbedder

    emb = ClipEmbedder("ViT-B-32", pretrained=None)
    text = emb.embed_text(["a group photo of several people", "a close-up of wedding rings"])
    assert text.shape == (2, emb.dim) and np.allclose(np.linalg.norm(text, axis=1), 1.0, atol=1e-4)


def test_scan_sorts_by_topic_and_exports_into_category_folders(engine, shoot, tmp_path):
    folder, truth = shoot
    shoot_id = engine.repo.add_shoot(str(folder))
    assert engine.scan(shoot_id, inline=True).stage == "done"
    rows = [r for r in engine.repo.grid(shoot_id) if r["status"] == "done"]
    # the test engine has no text model, so categories come from faces: these synthetic scenes have none
    assert {r["category"] for r in rows} == {"No people"}
    assert all(0.0 <= r["relevance"] <= 1.0 for r in rows)

    with TestClient(create_app(engine, token="t")) as client:
        info = client.get("/info", headers=AUTH).json()
        assert {"id": "wedding", "name": "Wedding"} in info["shoot_types"]
        assert client.get(f"/shoots/{shoot_id}", headers=AUTH).json()["shoot_type"] == "general"
        assert client.post(f"/shoots/{shoot_id}/type", json={"shoot_type": "wedding"}, headers=AUTH).json() == {
            "shoot_type": "wedding", "method": "faces"}
        assert client.get(f"/shoots/{shoot_id}", headers=AUTH).json()["shoot_type"] == "wedding"
        assert client.post(f"/shoots/{shoot_id}/type", json={"shoot_type": "nope"}, headers=AUTH).status_code == 400

        off = client.get(f"/shoots/{shoot_id}/photos", params={"filter": "offtopic"}, headers=AUTH).json()["photos"]
        assert all(p["off_topic"] for p in off)

        out = client.post(f"/shoots/{shoot_id}/export", json={
            "kind": "folder", "selection": "all", "dest": str(tmp_path / "sorted"), "by_category": True}, headers=AUTH).json()
        assert out["folders"] == {"No people": len(rows)} and out["copied"] == len(rows)
        assert len(list((tmp_path / "sorted" / "No people").glob("*.jpg"))) == len(rows)


def test_a_text_capable_embedder_gives_topic_categories(engine, shoot):
    """With a vision model that reads text, a scan uses the shoot type's own categories."""
    folder, _ = shoot
    fake = FakeText("travel")
    engine.embedder.embed_text = lambda texts: np.pad(fake(texts), ((0, 0), (0, 512 - DIM)))
    try:
        shoot_id = engine.repo.add_shoot(str(folder))
        engine.repo.update_shoot(shoot_id, shoot_type="travel")
        started = time.time()
        assert engine.scan(shoot_id, inline=True).stage == "done"
        assert engine.categorize(shoot_id) == "vision" and time.time() - started < 120
        cats = {r["category"] for r in engine.repo.grid(shoot_id) if r["status"] == "done"}
        assert cats <= {c.name for c in SHOOT_TYPES["travel"][1]} | {OTHER}
    finally:
        del engine.embedder.embed_text
