"""Settings for the engine.

Every threshold and weight lives here so it can be tuned against the owner's
benchmark shoots without touching code. Override any field with a TOML file
(``culler --config my.toml ...`` or ``CULLER_CONFIG=my.toml``).
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

APP_NAME = "Culler"

# Bump when an analyzer changes in a way that makes old rows stale.
ANALYZER_VERSION = 1

RAW_EXTS = frozenset({".cr3", ".cr2", ".nef", ".arw", ".raf", ".dng"})
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})
SUPPORTED_EXTS = RAW_EXTS | IMAGE_EXTS


def default_data_dir() -> Path:
    env = os.environ.get("CULLER_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower()


@dataclass
class Weights:
    """How much each signal counts toward the 0-1 rule score. Should sum to 1."""

    sharpness: float = 0.45
    faces: float = 0.25
    exposure: float = 0.20
    burst: float = 0.10


@dataclass
class Thresholds:
    # --- labels ---
    keep_score: float = 0.62  # rule score at or above this -> KEEP

    # --- sharpness (units: see analysis/sharpness.py) ---
    sharp_floor: float = 10.0  # at or below this a frame is clearly blurred
    # "Sharp" is learned per shoot (75th percentile of the shoot), because cameras, lenses
    # and ISO differ. These bound that reference, and sharp_ref is used for tiny shoots.
    sharp_ref: float = 150.0
    sharp_ref_min: float = 60.0
    sharp_ref_max: float = 3000.0
    min_shoot_for_ref: int = 20
    # Hard reject needs BOTH: bottom share of the shoot AND under this fraction of the
    # shoot's sharp reference, so a shoot where everything is sharp loses nothing.
    reject_sharp_percentile: float = 0.10
    reject_sharp_ratio: float = 0.20
    # Fine-detail anisotropy above which a soft frame is called camera shake.
    shake_anisotropy: float = 0.55

    # --- exposure ---
    under_mean: float = 60.0  # mean luminance (0-255) below this is underexposed
    over_mean: float = 200.0
    clip_high_soft_pct: float = 2.0  # frame-wide blown highlights that start to cost score
    keep_min_exposure: float = 0.65  # exposure score below this is never an automatic KEEP
    face_clip_reject_pct: float = 5.0  # blown highlights on the main face -> hard reject
    blank_low: float = 8.0  # mean luminance below this = accidental black frame
    blank_high: float = 250.0

    # --- eyes ---
    blink_closed: float = 0.60  # blendshape blink score above this = closed
    ear_closed: float = 0.15  # eye aspect ratio below this = closed
    min_face_px: int = 48  # faces smaller than this (in the 2048 preview) skip eye checks

    # --- bursts ---
    burst_gap_s: float = 2.0
    burst_sim_clip: float = 0.92
    burst_sim_fallback: float = 0.90


@dataclass
class Learning:
    min_decisions: int = 300  # no personal model, and no taste rejects, below this
    boosting_from: int = 2000  # switch from logistic regression to gradient boosting
    max_blend: float = 0.8  # most the personal model can count toward the final score
    full_blend_at: int = 2000  # decisions at which the blend reaches max_blend
    taste_reject_below: float = 0.15  # personal keep-probability below this -> REJECT
    rescue_above: float = 0.80  # hard rejects with keep-probability above this -> REVIEW


@dataclass
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    thumb_px: int = 512
    preview_px: int = 2048
    analysis_px: int = 1024
    workers: int = 0  # 0 = pick from CPU count
    embedder: str = "auto"  # auto | clip | fallback
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"
    weights: Weights = field(default_factory=Weights)
    thresholds: Thresholds = field(default_factory=Thresholds)
    learning: Learning = field(default_factory=Learning)

    # ---- derived paths ----
    @property
    def db_path(self) -> Path:
        return self.data_dir / "culler.sqlite3"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.models_dir):
            p.mkdir(parents=True, exist_ok=True)

    def worker_count(self) -> int:
        if self.workers > 0:
            return self.workers
        return max(1, min(8, (os.cpu_count() or 2) - 1))


def _apply(obj, data: dict) -> None:
    names = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in names:
            raise ValueError(f"Unknown setting: {key}")
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply(current, value)
        elif isinstance(current, Path):
            setattr(obj, key, Path(value).expanduser())
        else:
            setattr(obj, key, type(current)(value))


def load_settings(config_path: str | os.PathLike | None = None, **overrides) -> Settings:
    settings = Settings()
    path = config_path or os.environ.get("CULLER_CONFIG")
    if path:
        with open(path, "rb") as fh:
            _apply(settings, tomllib.load(fh))
    _apply(settings, {k: v for k, v in overrides.items() if v is not None})
    return settings


def find_model_file(name: str, settings: Settings | None = None) -> Path | None:
    """Look for a model file in: $CULLER_MODELS_DIR, the bundled assets, the data dir."""
    candidates: list[Path] = []
    env = os.environ.get("CULLER_MODELS_DIR")
    if env:
        candidates.append(Path(env) / name)
    candidates.append(Path(__file__).parent / "assets" / "models" / name)
    if settings is not None:
        candidates.append(settings.models_dir / name)
    for c in candidates:
        if c.is_file():
            return c
    return None
