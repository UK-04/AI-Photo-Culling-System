"""Read the handful of EXIF fields culling needs."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from PIL import Image

_EXIF_IFD = 0x8769
_TAG_MAKE, _TAG_MODEL, _TAG_ORIENTATION, _TAG_DATETIME = 271, 272, 274, 306
_TAG_EXPOSURE, _TAG_FNUMBER, _TAG_ISO = 33434, 33437, 34855
_TAG_DT_ORIGINAL, _TAG_SUBSEC_ORIGINAL = 36867, 37521
_TAG_FOCAL, _TAG_LENS = 37386, 42036


def _num(value: Any) -> float | None:
    try:
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[0]) / float(value[1]) if value[1] else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    text = str(value).replace("\x00", "").strip()
    return text or None


def parse_capture_time(dt: str | None, subsec: str | None = None) -> tuple[str | None, float | None]:
    """Turn EXIF ``YYYY:MM:DD HH:MM:SS`` (+ sub-seconds) into an ISO string and a sortable number.

    EXIF capture time carries no time zone; it is treated as naive local time, which is all
    burst grouping needs (differences between frames).
    """
    if not dt:
        return None, None
    try:
        parsed = datetime.strptime(dt.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None
    frac = 0.0
    if subsec:
        digits = "".join(ch for ch in str(subsec) if ch.isdigit())
        if digits:
            frac = float("0." + digits)
    ts = parsed.replace(tzinfo=UTC).timestamp() + frac
    iso = parsed.strftime("%Y-%m-%dT%H:%M:%S") + (f"{frac:.3f}"[1:] if frac else "")
    return iso, ts


def read_exif(img: Image.Image) -> dict[str, Any]:
    """Extract capture time, camera, lens and exposure settings from an opened image."""
    out: dict[str, Any] = {
        "captured_at": None, "capture_ts": None, "camera": None, "lens": None,
        "iso": None, "shutter": None, "aperture": None, "focal": None, "orientation": 1,
    }
    try:
        exif = img.getexif()
    except Exception:
        return out
    if not exif:
        return out
    try:
        sub = exif.get_ifd(_EXIF_IFD)
    except Exception:
        sub = {}

    make, model = _text(exif.get(_TAG_MAKE)), _text(exif.get(_TAG_MODEL))
    if model:
        out["camera"] = model if (not make or model.lower().startswith(make.lower().split()[0])) else f"{make} {model}"
    out["lens"] = _text(sub.get(_TAG_LENS))
    try:
        out["orientation"] = int(exif.get(_TAG_ORIENTATION) or 1)
    except (TypeError, ValueError):
        out["orientation"] = 1

    iso = sub.get(_TAG_ISO)
    if isinstance(iso, tuple | list):
        iso = iso[0] if iso else None
    iso_n = _num(iso)
    out["iso"] = int(iso_n) if iso_n else None
    out["shutter"] = _num(sub.get(_TAG_EXPOSURE))
    out["aperture"] = _num(sub.get(_TAG_FNUMBER))
    out["focal"] = _num(sub.get(_TAG_FOCAL))

    dt = _text(sub.get(_TAG_DT_ORIGINAL)) or _text(exif.get(_TAG_DATETIME))
    out["captured_at"], out["capture_ts"] = parse_capture_time(dt, _text(sub.get(_TAG_SUBSEC_ORIGINAL)))
    return out


def fallback_capture_time(path: str | os.PathLike) -> tuple[str, float]:
    """File modification time, for files with no EXIF capture time."""
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S"), ts


def format_shutter(seconds: float | None) -> str | None:
    if not seconds:
        return None
    if seconds >= 1:
        return f"{seconds:g}s"
    return f"1/{round(1 / seconds)}"
