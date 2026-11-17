"""Find faces and decide whether eyes are open.

Two models, each doing what it is good at:

* **YuNet** (OpenCV) finds faces. It copes with the small and off-centre faces that
  are normal in event photos.
* **MediaPipe Face Landmarker** then looks at each face crop and reports eyelid
  landmarks and blink scores, which is what closed-eye detection needs.

If the landmark model file is missing, faces are still found but eye state is
reported as unknown (``None``), never guessed. If no model is available at all,
the analyzer reports zero faces and says so in ``backend``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from ..config import Settings, find_model_file

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
LANDMARKER_FILE = "face_landmarker.task"

# MediaPipe face-mesh indices around each eye: corner, upper x2, corner, lower x2
_LEFT_EYE = (33, 160, 158, 133, 153, 144)
_RIGHT_EYE = (362, 385, 387, 263, 373, 380)


@dataclass
class Face:
    box: tuple[float, float, float, float]  # x, y, w, h in pixels of the analyzed image
    score: float
    eye_open: float | None = None  # 0 = shut, 1 = wide open; None = not measured
    eyes_closed: bool | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["box"] = [round(float(v), 1) for v in self.box]
        return d


class FaceBackend(Protocol):
    name: str

    def detect(self, rgb: np.ndarray) -> list[Face]: ...


def eye_aspect_ratio(points: np.ndarray) -> float:
    """EAR for six eye landmarks ordered corner, top, top, corner, bottom, bottom.

    Around 0.25-0.35 for an open eye, under ~0.15 when shut.
    """
    p1, p2, p3, p4, p5, p6 = points
    width = float(np.linalg.norm(p1 - p4))
    if width < 1e-6:
        return 0.0
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2.0 * width))


def eye_state(
    ear_left: float,
    ear_right: float,
    blink_left: float | None,
    blink_right: float | None,
    blink_closed: float,
    ear_closed: float,
) -> tuple[float, bool]:
    """Combine EAR and blink scores into ``(openness 0-1, closed?)``.

    A face counts as eyes-closed only when BOTH eyes are closed: a wink or a face in
    profile (one eye hidden) should not be rejected.
    """
    ear_open = float(np.clip((min(ear_left, ear_right) - ear_closed) / 0.15, 0.0, 1.0))
    both_ear_closed = ear_left < ear_closed and ear_right < ear_closed
    if blink_left is None or blink_right is None:
        return ear_open, both_ear_closed
    blink_open = 1.0 - max(blink_left, blink_right)
    both_blink_closed = blink_left > blink_closed and blink_right > blink_closed
    # The blink score is the trained signal; EAR must not contradict it strongly.
    closed = both_blink_closed and max(ear_left, ear_right) < ear_closed * 1.6
    return float(0.5 * ear_open + 0.5 * blink_open), bool(closed or both_ear_closed)


class NullBackend:
    name = "none"

    def detect(self, rgb: np.ndarray) -> list[Face]:
        return []


class YuNetBackend:
    """Face boxes from OpenCV's YuNet. Does not measure eyes."""

    name = "yunet"

    def __init__(self, model_path: Path, score_threshold: float = 0.7, detect_px: int = 960):
        self._model_path = str(model_path)
        self._score = score_threshold
        self._detect_px = detect_px
        self._det = None
        self._size: tuple[int, int] | None = None

    def _detector(self, w: int, h: int):
        if self._det is None:
            try:  # OpenCV 5 prints a harmless backend warning on first use
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            except Exception:
                pass
            self._det = cv2.FaceDetectorYN.create(self._model_path, "", (w, h), self._score, 0.3, 200)
            self._size = (w, h)
        elif self._size != (w, h):
            self._det.setInputSize((w, h))
            self._size = (w, h)
        return self._det

    def detect(self, rgb: np.ndarray) -> list[Face]:
        H, W = rgb.shape[:2]
        scale = min(1.0, self._detect_px / max(H, W))
        small = rgb if scale == 1.0 else cv2.resize(rgb, (round(W * scale), round(H * scale)), interpolation=cv2.INTER_AREA)
        bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
        _, found = self._detector(bgr.shape[1], bgr.shape[0]).detect(bgr)
        faces: list[Face] = []
        if found is None:
            return faces
        for row in found:
            x, y, w, h = (float(v) / scale for v in row[:4])
            x, y = max(0.0, x), max(0.0, y)
            w, h = min(w, W - x), min(h, H - y)
            if w > 4 and h > 4:
                faces.append(Face(box=(x, y, w, h), score=float(row[-1])))
        return faces


class LandmarkEyes:
    """Eye openness for one face crop, from MediaPipe Face Landmarker."""

    def __init__(self, model_path: Path, blink_closed: float, ear_closed: float):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            num_faces=1,
            output_face_blendshapes=True,
            min_face_detection_confidence=0.3,
            min_face_presence_confidence=0.3,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._blink_closed, self._ear_closed = blink_closed, ear_closed

    def measure(self, crop_rgb: np.ndarray) -> tuple[float, bool] | None:
        h, w = crop_rgb.shape[:2]
        if min(h, w) < 256:  # the landmark model wants a reasonably large face
            s = 256 / min(h, w)
            crop_rgb = cv2.resize(crop_rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_CUBIC)
            h, w = crop_rgb.shape[:2]
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop_rgb))
        result = self._landmarker.detect(image)
        if not result.face_landmarks:
            return None
        lm = result.face_landmarks[0]
        pts = np.array([[p.x * w, p.y * h] for p in lm], dtype=np.float32)
        ear_l, ear_r = eye_aspect_ratio(pts[list(_LEFT_EYE)]), eye_aspect_ratio(pts[list(_RIGHT_EYE)])
        blink_l = blink_r = None
        if result.face_blendshapes:
            scores = {c.category_name: c.score for c in result.face_blendshapes[0]}
            blink_l, blink_r = scores.get("eyeBlinkLeft"), scores.get("eyeBlinkRight")
        return eye_state(ear_l, ear_r, blink_l, blink_r, self._blink_closed, self._ear_closed)


class FacePipeline:
    """YuNet detection, then eye measurement on each large-enough face."""

    def __init__(self, detector: FaceBackend, eyes: LandmarkEyes | None, min_face_px: int, max_eye_faces: int = 6):
        self._detector, self._eyes = detector, eyes
        self._min_face_px, self._max_eye_faces = min_face_px, max_eye_faces
        self.name = detector.name + ("+landmarks" if eyes is not None else "")

    def detect(self, rgb: np.ndarray) -> list[Face]:
        faces = self._detector.detect(rgb)
        if self._eyes is None or not faces:
            return faces
        H, W = rgb.shape[:2]
        largest = sorted(faces, key=lambda f: f.box[2] * f.box[3], reverse=True)[: self._max_eye_faces]
        for face in largest:
            x, y, w, h = face.box
            if min(w, h) < self._min_face_px:
                continue
            pad = 0.35 * max(w, h)
            x0, y0 = int(max(0, x - pad)), int(max(0, y - pad))
            x1, y1 = int(min(W, x + w + pad)), int(min(H, y + h + pad))
            try:
                measured = self._eyes.measure(rgb[y0:y1, x0:x1])
            except Exception:
                measured = None
            if measured is not None:
                face.eye_open, face.eyes_closed = measured
        return faces


def build_face_backend(settings: Settings) -> FaceBackend:
    """Best available backend for this install. Never raises."""
    yunet = find_model_file(YUNET_FILE, settings)
    if yunet is None or not hasattr(cv2, "FaceDetectorYN"):
        return NullBackend()
    detector = YuNetBackend(yunet)
    eyes: LandmarkEyes | None = None
    landmarker = find_model_file(LANDMARKER_FILE, settings)
    if landmarker is not None:
        try:
            eyes = LandmarkEyes(landmarker, settings.thresholds.blink_closed, settings.thresholds.ear_closed)
        except Exception:
            eyes = None
    return FacePipeline(detector, eyes, settings.thresholds.min_face_px)


def main_face(faces: list[Face], width: int, height: int) -> Face | None:
    """The face the photo is most likely about: big and near the middle."""
    if not faces:
        return None
    cx, cy = width / 2.0, height / 2.0
    diag = float(np.hypot(width, height))

    def weight(f: Face) -> float:
        x, y, w, h = f.box
        dist = float(np.hypot(x + w / 2 - cx, y + h / 2 - cy)) / diag  # 0 centre .. 0.5 corner
        return w * h * (1.0 - dist)

    return max(faces, key=weight)
