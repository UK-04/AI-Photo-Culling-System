"""Find supported photos under a folder."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import IMAGE_EXTS, RAW_EXTS, SUPPORTED_EXTS


@dataclass(frozen=True)
class FoundPhoto:
    path: Path
    # A JPEG shot alongside a RAW (same folder, same name). Used as a fast preview source.
    companion: Path | None = None


def find_photos(folder: str | os.PathLike) -> list[FoundPhoto]:
    """Recursively list supported files, sorted by path.

    Hidden files and folders are skipped (including macOS ``._`` resource forks).
    When a RAW and a JPEG share a folder and a name, the RAW is the photo and the
    JPEG rides along as its companion, so RAW+JPEG shooters do not see every frame twice.
    """
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")

    by_dir: dict[Path, list[Path]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in filenames:
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if p.suffix.lower() in SUPPORTED_EXTS:
                by_dir.setdefault(Path(dirpath), []).append(p)

    found: list[FoundPhoto] = []
    for _, paths in sorted(by_dir.items()):
        raws = {p.stem.lower(): p for p in paths if p.suffix.lower() in RAW_EXTS}
        used_as_companion: set[Path] = set()
        companions: dict[Path, Path] = {}
        for p in paths:
            if p.suffix.lower() in IMAGE_EXTS and p.suffix.lower() in {".jpg", ".jpeg"}:
                raw = raws.get(p.stem.lower())
                if raw is not None and raw not in companions:
                    companions[raw] = p
                    used_as_companion.add(p)
        for p in sorted(paths):
            if p in used_as_companion:
                continue
            found.append(FoundPhoto(path=p, companion=companions.get(p)))
    return found
