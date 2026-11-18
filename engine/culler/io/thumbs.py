"""On-disk JPEG cache for thumbnails and previews, keyed by the file's content hash."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

_QUALITY = {"thumb": 80, "preview": 88, "full": 92}


def cache_path(cache_dir: Path, kind: str, file_hash: str) -> Path:
    return cache_dir / kind / file_hash[:2] / f"{file_hash}.jpg"


def _save_atomic(img: Image.Image, dest: Path, quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(f".{os.getpid()}.tmp")
    img.save(tmp, "JPEG", quality=quality, optimize=False)
    os.replace(tmp, dest)


def write_cache(cache_dir: Path, file_hash: str, preview: Image.Image, thumb_px: int) -> tuple[Path, Path]:
    """Store the preview and a thumbnail made from it. Existing files are left alone."""
    preview_path = cache_path(cache_dir, "preview", file_hash)
    thumb_path = cache_path(cache_dir, "thumb", file_hash)
    if not preview_path.exists():
        _save_atomic(preview, preview_path, _QUALITY["preview"])
    if not thumb_path.exists():
        thumb = preview.copy()
        thumb.thumbnail((thumb_px, thumb_px), Image.Resampling.LANCZOS)
        _save_atomic(thumb, thumb_path, _QUALITY["thumb"])
    return thumb_path, preview_path


_TRANSPOSE = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}


def rotate_image(img: Image.Image, degrees_cw: int) -> Image.Image:
    """Rotate clockwise by 0/90/180/270 degrees."""
    degrees_cw %= 360
    return img if degrees_cw == 0 else img.transpose(_TRANSPOSE[degrees_cw])


def rotated_path(cache_dir: Path, kind: str, file_hash: str, rotation: int) -> Path:
    """Cache file for a photo at a rotation. Rotation 0 is the plain cache file."""
    base = cache_path(cache_dir, kind, file_hash)
    return base if rotation % 360 == 0 else base.with_name(f"{file_hash}-r{rotation % 360}.jpg")


def ensure_rotated(cache_dir: Path, kind: str, file_hash: str, rotation: int) -> Path | None:
    """Make (once) the rotated copy of a cached image from its upright cache file."""
    target = rotated_path(cache_dir, kind, file_hash, rotation)
    if target.exists():
        return target
    base = cache_path(cache_dir, kind, file_hash)
    if not base.exists():
        return None
    with Image.open(base) as img:
        _save_atomic(rotate_image(img.convert("RGB"), rotation), target, _QUALITY.get(kind, 92))
    return target
