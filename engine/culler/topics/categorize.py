"""Give each photo a topic category, and measure how much it belongs with the rest of the shoot."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .taxonomy import SHOOT_TYPES, Category

OTHER = "Other"


@dataclass
class Topic:
    photo_id: int
    category: str
    confidence: float
    method: str  # 'vision' or 'faces'


def people_bucket(face_count: int, main_face_height: float | None) -> str:
    """Category from faces alone. ``main_face_height`` is the main face's share of the frame height."""
    if face_count >= 7:
        return "Large groups"
    if face_count >= 3:
        return "Small groups"
    if face_count == 2:
        return "Pairs and couples"
    if face_count == 1:
        return "Single portraits" if (main_face_height or 0.0) >= 0.12 else "One person, wide"
    return "No people"


def face_prior(category: Category, face_count: int) -> float:
    """How well a face count fits a category: 1.0 inside its usual range, lower the further outside."""
    low, high = category.faces
    if low <= face_count <= high:
        return 1.0
    distance = (low - face_count) if face_count < low else (face_count - high)
    return 0.35 if distance == 1 else 0.12


def text_matrix(categories: tuple[Category, ...], embed_text) -> np.ndarray:
    """One unit vector per category: the average of its descriptions' embeddings."""
    rows = []
    for cat in categories:
        vecs = np.asarray(embed_text(list(cat.prompts)), dtype=np.float32)
        mean = vecs.mean(axis=0)
        rows.append(mean / max(float(np.linalg.norm(mean)), 1e-12))
    return np.stack(rows)


def categorize_by_vision(
    photo_ids: list[int],
    vectors: np.ndarray,
    face_counts: list[int],
    shoot_type: str,
    embed_text,
    min_confidence: float = 0.40,
    temperature: float = 100.0,
) -> list[Topic]:
    """Pick the closest category for each photo: CLIP similarity, nudged by the face count."""
    _, categories = SHOOT_TYPES.get(shoot_type, SHOOT_TYPES["general"])
    if len(photo_ids) == 0:
        return []
    logits = temperature * (np.asarray(vectors, dtype=np.float32) @ text_matrix(categories, embed_text).T)
    logits -= logits.max(axis=1, keepdims=True)
    probs = np.exp(logits)
    prior = np.array([[face_prior(c, n) for c in categories] for n in face_counts], dtype=np.float32)
    probs *= prior
    probs /= np.maximum(probs.sum(axis=1, keepdims=True), 1e-12)
    out = []
    for pid, row in zip(photo_ids, probs, strict=True):
        best = int(row.argmax())
        conf = float(row[best])
        out.append(Topic(pid, categories[best].name if conf >= min_confidence else OTHER, conf, "vision"))
    return out


def categorize_by_faces(photo_ids: list[int], face_counts: list[int], face_heights: list[float | None]) -> list[Topic]:
    return [
        Topic(pid, people_bucket(n, h), 1.0, "faces")
        for pid, n, h in zip(photo_ids, face_counts, face_heights, strict=True)
    ]


def relevance(vectors: np.ndarray, burst_ids: list[int | None], min_photos: int = 12) -> tuple[list[float | None], list[bool]]:
    """How much each photo belongs with the rest of the shoot.

    A photo "belongs" when the shoot contains other photos like it. For each photo this
    takes its most similar neighbours (ignoring frames of its own burst, which would
    always match) and averages their similarity. The result is ranked within the shoot
    to give a 0-1 meter. A photo is flagged off-topic when it sits far below the shoot's
    typical value (3 robust standard deviations, and at least 0.08 in similarity), so a shoot
    with no odd photos flags none.

    Returns ``(relevance per photo, off-topic flag per photo)``. Shoots smaller than
    ``min_photos`` get ``None``: there is too little to compare against.
    """
    n = len(vectors)
    if n < min_photos:
        return [None] * n, [False] * n
    v = np.asarray(vectors, dtype=np.float32)
    k = int(np.clip(round(0.03 * n), 4, 20))
    density = np.empty(n, dtype=np.float32)
    bursts = np.array([-1 if b is None else b for b in burst_ids])
    for start in range(0, n, 1024):  # in blocks, so a 10,000-photo shoot does not need a 10,000 x 10,000 table
        block = v[start : start + 1024] @ v.T
        for i in range(block.shape[0]):
            row = block[i]
            row[start + i] = -1.0
            if bursts[start + i] >= 0:
                row[bursts == bursts[start + i]] = -1.0
            top = np.partition(row, -k)[-k:]
            density[start + i] = float(top[top > -1.0].mean()) if (top > -1.0).any() else 0.0

    order = density.argsort(kind="mergesort")
    rank = np.empty(n, dtype=np.float32)
    rank[order] = np.arange(n, dtype=np.float32) / (n - 1)
    median = float(np.median(density))
    mad = float(np.median(np.abs(density - median))) * 1.4826
    # Far below typical for this shoot, and by a real margin: in a very uniform shoot the
    # spread is tiny, and a hair's difference must not count as off-topic.
    cutoff = median - max(3.0 * mad, 0.08)
    return [float(r) for r in rank], [bool(d < cutoff) for d in density]
