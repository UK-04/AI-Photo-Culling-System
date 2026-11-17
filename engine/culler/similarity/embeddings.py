"""Turn a photo into a vector, for "how alike are these two frames" and for taste learning.

``ClipEmbedder`` (open_clip ViT-B/32) is the real one: it understands content, so it
powers the personal model. ``FallbackEmbedder`` needs no model download and no PyTorch;
it compares layout, colour and edges, which is enough to group bursts and keeps the
engine and its tests working on any machine.

Vectors from different embedders are never mixed: every stored vector carries the
embedder's ``name``.
"""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from ..config import Settings


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        """Return float32 array (n, dim), each row L2-normalized."""
        ...


def _l2(x: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(x, axis=-1, keepdims=True)
    return (x / np.maximum(norm, 1e-12)).astype(np.float32)


class FallbackEmbedder:
    """512-d handcrafted descriptor: coarse layout + colour histogram + edge directions."""

    name = "fallback-v1"
    dim = 512

    def _one(self, img: Image.Image) -> np.ndarray:
        rgb = np.asarray(img.convert("RGB").resize((128, 128), Image.Resampling.BILINEAR))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        # 1) layout: 16x16 grayscale, mean-removed (256 values)
        layout = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
        layout -= layout.mean()

        # 2) colour: HSV histogram 8x4x4 (128 values)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()

        # 3) edges: orientation histograms on a 4x4 grid, 8 bins each (128 values)
        g = gray.astype(np.float32)
        gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
        mag = np.hypot(gx, gy)
        bins = (np.mod(np.arctan2(gy, gx), np.pi) / np.pi * 8).astype(np.int32).clip(0, 7)
        edges = np.zeros((4, 4, 8), dtype=np.float32)
        for i in range(4):
            for j in range(4):
                sl = (slice(i * 32, (i + 1) * 32), slice(j * 32, (j + 1) * 32))
                edges[i, j] = np.bincount(bins[sl].ravel(), weights=mag[sl].ravel(), minlength=8)

        parts = [_l2(layout), _l2(np.sqrt(hist)), _l2(np.sqrt(edges.ravel()))]
        return np.concatenate([parts[0] * 1.0, parts[1] * 0.8, parts[2] * 0.8])

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        if not images:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _l2(np.stack([self._one(im) for im in images]))


class ClipEmbedder:
    """open_clip image encoder. Weights download once on first use (several hundred MB)."""

    dim = 512

    def __init__(
        self, model: str, pretrained: str | None, cache_dir: str | None = None, batch_size: int = 32, tag: str | None = None
    ):
        """``pretrained`` is a weights name or a file path. ``tag`` names the weights when a path is given,
        so stored vectors carry the same model name on every machine."""
        import open_clip
        import torch

        self._torch = torch
        if torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            model, pretrained=pretrained, cache_dir=cache_dir
        )
        self._model.eval().to(self.device)
        self._batch = batch_size
        self._tokenizer = open_clip.get_tokenizer(model)
        self.name = f"clip-{model}-{tag or pretrained or 'random'}"
        self.dim = int(getattr(self._model.visual, "output_dim", 512))

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        torch = self._torch
        out: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, len(images), self._batch):
                batch = torch.stack([self._preprocess(im.convert("RGB")) for im in images[start : start + self._batch]])
                feats = self._model.encode_image(batch.to(self.device))
                out.append(feats.float().cpu().numpy())
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _l2(np.concatenate(out))

    def embed_text(self, texts: list[str]) -> np.ndarray:
        """Embed descriptions into the same space as images, for sorting photos by topic."""
        torch = self._torch
        with torch.inference_mode():
            feats = self._model.encode_text(self._tokenizer(texts).to(self.device))
        return _l2(feats.float().cpu().numpy())


def build_embedder(settings: Settings) -> Embedder:
    """CLIP when it is installed and its weights can be loaded, otherwise the fallback."""
    if settings.embedder == "fallback":
        return FallbackEmbedder()
    try:
        settings.models_dir.mkdir(parents=True, exist_ok=True)
        try:
            return ClipEmbedder(settings.clip_model, settings.clip_pretrained, cache_dir=str(settings.models_dir))
        except ImportError:
            raise
        except Exception:
            # The usual download host failed. Many weights are also published as a plain file.
            path = _download_weights(settings)
            if path is None:
                raise
            return ClipEmbedder(settings.clip_model, str(path), tag=settings.clip_pretrained)
    except Exception:
        if settings.embedder == "clip":
            raise
        return FallbackEmbedder()


def _download_weights(settings: Settings):
    """Fetch the weights file from the model's direct URL, if it has one. Returns the path or None."""
    import os
    import urllib.request
    from pathlib import Path

    import open_clip

    cfg = open_clip.pretrained.get_pretrained_cfg(settings.clip_model, settings.clip_pretrained) or {}
    url = cfg.get("url")
    if not url:
        return None
    target = Path(settings.models_dir) / url.rsplit("/", 1)[-1]
    if not target.exists():
        tmp = target.with_suffix(f".{os.getpid()}.part")
        try:
            with urllib.request.urlopen(url, timeout=60) as response, open(tmp, "wb") as out:  # noqa: S310 (fixed https URL from open_clip)
                while chunk := response.read(1 << 20):
                    out.write(chunk)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
    return target


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float16).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float16).astype(np.float32)
