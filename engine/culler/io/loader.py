"""Load a screen-sized preview of any supported photo, upright, as RGB.

Full-resolution decodes are avoided: JPEGs are decoded at reduced size straight from the
DCT data, and RAW files use the JPEG preview the camera embedded. Culling does not need
more than ~2000 px, and this is what makes a 2,000-photo shoot take minutes.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from ..config import RAW_EXTS
from .exif import fallback_capture_time, read_exif

try:  # HEIC/HEIF support
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - optional at import time
    pillow_heif = None

# LibRaw "flip" codes -> PIL transpose operations
_RAW_FLIP = {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90, 6: Image.Transpose.ROTATE_270}
_MIN_EMBEDDED_PX = 1000


class PhotoLoadError(Exception):
    """The file could not be decoded (corrupt, truncated, or not really an image)."""


@dataclass
class LoadedPhoto:
    image: Image.Image  # RGB, upright, long edge <= max_px
    width: int  # original pixel size (upright)
    height: int
    exif: dict[str, Any] = field(default_factory=dict)
    source: str = "file"  # file | companion | raw-embedded | raw-decoded


def _finish(img: Image.Image, max_px: int) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    return img


def _load_standard(path: Path, max_px: int) -> LoadedPhoto:
    with Image.open(path) as img:
        full_w, full_h = img.size
        exif = read_exif(img)
        if img.format == "JPEG":
            img.draft("RGB", (max_px, max_px))  # decode at 1/2, 1/4 or 1/8 scale
        img.load()
        out = _finish(img, max_px)
    if exif.get("orientation") in (5, 6, 7, 8):
        full_w, full_h = full_h, full_w
    return LoadedPhoto(image=out, width=full_w, height=full_h, exif=exif)


def _load_raw(path: Path, max_px: int) -> LoadedPhoto:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        sizes = raw.sizes
        full_w, full_h = sizes.width, sizes.height
        flip = sizes.flip
        if flip in (5, 6):
            full_w, full_h = full_h, full_w

        try:
            thumb = raw.extract_thumb()
        except Exception:
            thumb = None

        if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
            with Image.open(io.BytesIO(thumb.data)) as emb:
                if max(emb.size) >= _MIN_EMBEDDED_PX:
                    exif = read_exif(emb)
                    emb.draft("RGB", (max_px, max_px))
                    emb.load()
                    had_orientation = exif.get("orientation", 1) != 1
                    img = _finish(emb, max_px)
                    if not had_orientation and flip in _RAW_FLIP:
                        img = img.transpose(_RAW_FLIP[flip])
                    return LoadedPhoto(image=img, width=full_w, height=full_h, exif=exif, source="raw-embedded")

        # No usable embedded preview: half-size demosaic (slower, still far from a full decode).
        rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
        img = Image.fromarray(rgb)
        if max(img.size) > max_px:
            img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        return LoadedPhoto(image=img, width=full_w, height=full_h, exif={}, source="raw-decoded")


def load_photo(path: str | os.PathLike, max_px: int = 2048, companion: str | os.PathLike | None = None) -> LoadedPhoto:
    """Load an upright RGB preview no larger than ``max_px`` on its long edge.

    Raises ``PhotoLoadError`` for unreadable files; never raises anything else for bad input.
    """
    p = Path(path)
    try:
        if p.suffix.lower() in RAW_EXTS:
            if companion is not None and Path(companion).is_file():
                try:
                    loaded = _load_standard(Path(companion), max_px)
                    loaded.source = "companion"
                except Exception:
                    loaded = _load_raw(p, max_px)
            else:
                loaded = _load_raw(p, max_px)
        else:
            loaded = _load_standard(p, max_px)
    except PhotoLoadError:
        raise
    except Exception as exc:
        raise PhotoLoadError(f"{type(exc).__name__}: {exc}") from exc

    if loaded.image.width < 8 or loaded.image.height < 8:
        raise PhotoLoadError("image is too small to analyze")
    if not loaded.exif.get("captured_at"):
        iso, ts = fallback_capture_time(p)
        loaded.exif.setdefault("orientation", 1)
        loaded.exif["captured_at"], loaded.exif["capture_ts"] = iso, ts
        loaded.exif["time_source"] = "file"
    return loaded
