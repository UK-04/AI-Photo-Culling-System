"""Generate a synthetic "shoot" with known defects, for tests and demos.

Real photos are the real test (see ``culler benchmark``), but these let the whole
pipeline be exercised anywhere, with a known right answer for every file: which
frames are blurred, shaken, dark, blown out, or weaker frames of a burst.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, TiffImagePlugin

DEFECTS = ("none", "blur", "shake", "dark", "bright", "black")


@dataclass
class SynthPhoto:
    file: str
    scene: int
    defect: str
    burst: int  # burst number, or -1
    burst_best: bool
    warm: bool  # scene colour family, used as a stand-in for "taste" in learning tests
    label: str  # the right answer: KEEP | REJECT


def _scene(rng: np.random.Generator, w: int, h: int, warm: bool) -> np.ndarray:
    """A colourful scene with large shapes and plenty of fine detail."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.array([200, 140, 90] if warm else [80, 130, 200], dtype=np.float32)
    tint = rng.uniform(-30, 30, 3).astype(np.float32)
    img = np.empty((h, w, 3), dtype=np.float32)
    grad = (xx / w * rng.uniform(-60, 60) + yy / h * rng.uniform(-60, 60))[..., None]
    img[:] = base + tint + grad
    canvas = np.clip(img, 0, 255).astype(np.uint8)
    for _ in range(int(rng.integers(10, 18))):
        color = tuple(int(c) for c in np.clip(base + rng.uniform(-110, 110, 3), 0, 255))
        cx, cy = int(rng.uniform(0, w)), int(rng.uniform(0, h))
        size = int(rng.uniform(0.04, 0.22) * w)
        kind = rng.integers(0, 3)
        if kind == 0:
            cv2.circle(canvas, (cx, cy), size, color, -1, cv2.LINE_AA)
        elif kind == 1:
            cv2.rectangle(canvas, (cx, cy), (cx + size, cy + int(size * rng.uniform(0.4, 1.6))), color, -1, cv2.LINE_AA)
        else:
            end = (cx + int(rng.uniform(-1, 1) * size * 2), cy + int(rng.uniform(-1, 1) * size * 2))
            cv2.line(canvas, (cx, cy), end, color, int(rng.integers(2, 7)), cv2.LINE_AA)
    # fine texture, so that "sharp" has something to be sharp about
    texture = rng.normal(0, 14, (h, w, 1)).astype(np.float32)
    texture = cv2.GaussianBlur(texture, (0, 0), 0.7)[..., None] * 1.6
    return np.clip(canvas.astype(np.float32) + texture, 0, 255).astype(np.uint8)


def _shift(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _motion(img: np.ndarray, length: int, angle: float) -> np.ndarray:
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle, 1.0)
    kernel = cv2.warpAffine(kernel, rot, (length, length))
    return cv2.filter2D(img, -1, kernel / max(kernel.sum(), 1e-6))


def apply_defect(img: np.ndarray, defect: str, rng: np.random.Generator) -> np.ndarray:
    scale = img.shape[1] / 640.0
    if defect == "blur":
        return cv2.GaussianBlur(img, (0, 0), float(rng.uniform(3.0, 5.0)) * scale)
    if defect == "shake":
        return _motion(img, int(rng.integers(17, 25) * scale) | 1, float(rng.uniform(0, 180)))
    if defect == "dark":
        return (img.astype(np.float32) * rng.uniform(0.12, 0.2)).astype(np.uint8)
    if defect == "bright":
        return (255.0 - (255.0 - img.astype(np.float32)) * 0.12).astype(np.uint8)  # washed out, not pure white
    if defect == "black":
        return np.clip(rng.normal(2, 1.5, img.shape), 0, 255).astype(np.uint8)
    return img


def _exif(when: datetime, iso: int) -> Image.Exif:
    exif = Image.Exif()
    exif[271], exif[272] = "Synth", "Synth Camera 1"
    ifd = exif.get_ifd(0x8769)
    ifd[36867] = when.strftime("%Y:%m:%d %H:%M:%S")
    ifd[37521] = f"{when.microsecond // 1000:03d}"
    ifd[34855] = iso
    ifd[33434] = TiffImagePlugin.IFDRational(1, 250)
    ifd[33437] = TiffImagePlugin.IFDRational(28, 10)
    ifd[37386] = TiffImagePlugin.IFDRational(50, 1)
    ifd[42036] = "Synth 50mm F1.8"
    return exif


def make_shoot(
    folder: str | Path,
    scenes: int = 20,
    seed: int = 0,
    size: tuple[int, int] = (640, 427),
    burst_share: float = 0.35,
    defect_share: float = 0.3,
    start: datetime | None = None,
    prefix: str = "IMG",
    corrupt_files: int = 0,
    warm_share: float = 0.5,
) -> list[SynthPhoto]:
    """Write a synthetic shoot into ``folder`` and return what each file is.

    Also writes ``truth.csv`` (file,label) next to the photos for ``culler benchmark``.
    """
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    w, h = size
    when = start or datetime(2026, 10, 3, 18, 0, 0)
    photos: list[SynthPhoto] = []
    counter = burst_no = defect_no = 0
    defect_cycle = [str(d) for d in rng.permutation(DEFECTS[1:])]  # every defect shows up in turn

    def save(img: np.ndarray, scene: int, defect: str, burst: int, best: bool, warm: bool) -> None:
        nonlocal counter
        counter += 1
        name = f"{prefix}_{counter:04d}.jpg"
        Image.fromarray(img).save(out / name, "JPEG", quality=90, exif=_exif(when, int(rng.choice([200, 400, 800, 1600]))))
        label = "KEEP" if defect == "none" and (burst < 0 or best) else "REJECT"
        photos.append(SynthPhoto(name, scene, defect, burst, best, warm, label))

    for scene in range(scenes):
        when += timedelta(seconds=float(rng.uniform(8, 90)))
        warm = bool(rng.random() < warm_share)
        base = _scene(rng, w, h, warm)
        if rng.random() < burst_share:
            frames = int(rng.integers(3, 6))
            best = int(rng.integers(0, frames))
            for i in range(frames):
                frame = _shift(base, float(rng.uniform(-3, 3)), float(rng.uniform(-3, 3)))
                if i != best:  # the other frames are a little soft
                    frame = cv2.GaussianBlur(frame, (0, 0), float(rng.uniform(1.0, 1.8)) * w / 640.0)
                save(frame, scene, "none", burst_no, i == best, warm)
                when += timedelta(milliseconds=int(rng.integers(120, 400)))
            burst_no += 1
        else:
            defect = "none"
            if rng.random() < defect_share:
                defect = defect_cycle[defect_no % len(defect_cycle)]
                defect_no += 1
            save(apply_defect(base, defect, rng), scene, defect, -1, False, warm)

    for i in range(corrupt_files):
        (out / f"{prefix}_BAD{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0" + bytes(rng.integers(0, 255, 300, dtype=np.uint8)))

    with open(out / "truth.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(photos[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(p) for p in photos)
    return photos
