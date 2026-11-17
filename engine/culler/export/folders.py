"""Copy selected photos to a folder. Originals are copied, never moved."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..io.hashing import file_hash
from .xmp import DEFAULT_LABELS, XmpMergeError, embed_in_jpeg_bytes, rating_and_label, sidecar_path, write_sidecar

_JPEG = {".jpg", ".jpeg"}


@dataclass
class CopyReport:
    copied: int = 0
    already_there: int = 0
    skipped_missing: int = 0
    ratings_embedded: int = 0
    dest: str = ""
    failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _free_name(dest_dir: Path, name: str) -> Path:
    target = dest_dir / name
    stem, suffix, n = target.stem, target.suffix, 2
    while target.exists():
        target = dest_dir / f"{stem}-{n}{suffix}"
        n += 1
    return target


def _same_file(a: Path, b: Path) -> bool:
    try:
        return file_hash(a) == file_hash(b)
    except OSError:
        return False


def copy_photos(
    rows: list[dict],
    dest_dir: str | os.PathLike,
    write_ratings: bool = True,
    labels: dict[str, str] | None = None,
    reject_rating: int | None = -1,
) -> CopyReport:
    """Copy each photo (and a RAW's companion JPEG) into ``dest_dir``.

    With ``write_ratings``, JPEG copies get the rating and colour label written into
    the copy itself, and RAW copies get a sidecar next to them, so the destination
    folder imports into Lightroom with everything in place.
    """
    labels = labels or DEFAULT_LABELS
    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    report = CopyReport(dest=str(dest))

    for row in rows:
        src = Path(row["path"])
        if not src.exists():
            report.skipped_missing += 1
            continue
        try:
            if src.resolve().parent == dest.resolve():
                report.already_there += 1  # exporting into the source folder: nothing to copy
                continue
            target = dest / src.name
            if target.exists() and _same_file(src, target):
                report.already_there += 1
            else:
                target = _free_name(dest, src.name)
                rating, label = rating_and_label(row, labels, reject_rating) if write_ratings else (None, None)
                wrote = False
                if (rating is not None or label) and src.suffix.lower() in _JPEG:
                    try:
                        target.write_bytes(embed_in_jpeg_bytes(src.read_bytes(), rating, label))
                        shutil.copystat(src, target)
                        report.ratings_embedded += 1
                        wrote = True
                    except (XmpMergeError, UnicodeDecodeError):
                        wrote = False
                if not wrote:
                    shutil.copy2(src, target)
                report.copied += 1
                if src.suffix.lower() not in _JPEG:
                    existing_sidecar = sidecar_path(src)
                    if existing_sidecar.exists():
                        shutil.copy2(existing_sidecar, sidecar_path(target))
                    if rating is not None or label:
                        try:
                            write_sidecar(target, rating, label)
                        except (XmpMergeError, UnicodeDecodeError):
                            pass
            companion = row.get("companion_path")
            if companion and Path(companion).exists():
                ctarget = dest / Path(companion).name
                if not ctarget.exists():
                    shutil.copy2(companion, ctarget)
        except OSError as exc:
            report.failed.append(f"{src.name}: {exc}")
    return report
