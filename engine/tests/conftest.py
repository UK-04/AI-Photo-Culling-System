from __future__ import annotations

import numpy as np
import pytest

from culler.config import Settings
from culler.service import Engine
from culler.similarity.embeddings import FallbackEmbedder
from culler.synth import _scene, make_shoot


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", embedder="fallback", workers=1)
    s.ensure_dirs()
    return s


@pytest.fixture
def engine(settings) -> Engine:
    return Engine(settings, embedder=FallbackEmbedder())


@pytest.fixture
def scene() -> np.ndarray:
    """A sharp, detailed 640x427 RGB test image."""
    return _scene(np.random.default_rng(7), 640, 427, warm=True)


@pytest.fixture
def shoot(tmp_path):
    """A small synthetic shoot on disk plus the truth about each file."""
    folder = tmp_path / "shoot"
    photos = make_shoot(folder, scenes=24, seed=3, size=(480, 320), corrupt_files=1, defect_share=0.5)
    return folder, photos
