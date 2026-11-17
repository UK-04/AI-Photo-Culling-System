"""The engine: scan a shoot end to end, re-score it, train the personal model.

Used by both the CLI and the API, so everything the app can do is testable from a
terminal.

A scan has five stages. Each skips work that is already done, which is what makes a
re-scan (or resuming after a cancel or a crash) quick:

1. discover   find files, add rows for new ones
2. analyze    per photo: hash, preview + thumbnail cache, EXIF, sharpness/exposure/faces
3. embed      image vectors (CLIP, or the built-in fallback)
4. group      bursts, best frame first
5. score      rules, blended with the personal model when there is one
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .analysis.exposure import exposure_score
from .analysis.faces import build_face_backend
from .analysis.pipeline import analyze_image
from .config import ANALYZER_VERSION, Settings
from .db import Repo
from .io.discover import find_photos
from .io.hashing import file_hash
from .io.loader import PhotoLoadError, load_photo
from .io.thumbs import cache_path, write_cache
from .learning.predict import predict_keep
from .learning.train import TrainResult, train_model
from .scoring.reasons import describe
from .scoring.rules import PhotoSignals, finalize, score_shoot
from .similarity.bursts import Frame, group_bursts, rank_burst
from .similarity.embeddings import Embedder, FallbackEmbedder, build_embedder, from_blob, to_blob

# ----------------------------------------------------------------------------- worker side
_worker: dict[str, Any] = {}


def _init_worker(settings: Settings) -> None:
    try:
        import cv2

        cv2.setNumThreads(1)  # one process per core already; do not oversubscribe
    except Exception:
        pass
    _worker["settings"] = settings
    _worker["faces"] = build_face_backend(settings)


def process_photo(task: dict) -> dict:
    """Ingest and analyze one photo. Runs in a worker process and never raises."""
    settings: Settings = _worker["settings"]
    photo_id, path = task["photo_id"], task["path"]
    try:
        digest, size = file_hash(path)
        loaded = load_photo(path, settings.preview_px, task.get("companion"))
        write_cache(settings.cache_dir, digest, loaded.image, settings.thumb_px)
        rgb = np.asarray(loaded.image)
        analysis = analyze_image(rgb, _worker["faces"], settings)
        exif = loaded.exif
        meta = {
            "file_hash": digest, "file_size": size, "width": loaded.width, "height": loaded.height,
            **{k: exif.get(k) for k in ("captured_at", "capture_ts", "camera", "lens", "iso", "shutter", "aperture", "focal")},
        }
        return {"photo_id": photo_id, "ok": True, "meta": meta, "analysis": analysis}
    except PhotoLoadError as exc:
        return {"photo_id": photo_id, "ok": False, "error": f"Could not read this file ({exc})"}
    except Exception as exc:  # a single bad file must never stop a scan
        return {"photo_id": photo_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ----------------------------------------------------------------------------- progress
@dataclass
class ScanProgress:
    shoot_id: int
    stage: str = "idle"  # idle | discovering | analyzing | embedding | grouping | scoring | done | cancelled | error
    done: int = 0
    total: int = 0
    errors: int = 0
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def running(self) -> bool:
        return self.stage not in ("idle", "done", "cancelled", "error")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["running"] = self.running
        d["elapsed"] = round((self.finished_at or time.time()) - self.started_at, 1)
        return d


ProgressFn = Callable[[ScanProgress], None]


class ScanCancelled(Exception):
    pass


# ----------------------------------------------------------------------------- engine
class Engine:
    def __init__(self, settings: Settings, repo: Repo | None = None, embedder: Embedder | None = None):
        self.settings = settings
        settings.ensure_dirs()
        self.repo = repo or Repo(settings.db_path)
        self._embedder = embedder
        self._embedder_lock = threading.Lock()
        self._face_backend_name: str | None = None

    # ---- lazily built models
    @property
    def embedder(self) -> Embedder:
        with self._embedder_lock:
            if self._embedder is None:
                self._embedder = build_embedder(self.settings)
            return self._embedder

    @property
    def embedder_loaded(self) -> bool:
        return self._embedder is not None

    @property
    def face_backend_name(self) -> str:
        if self._face_backend_name is None:
            self._face_backend_name = build_face_backend(self.settings).name
        return self._face_backend_name

    # ---- scan
    def scan(
        self,
        shoot_id: int,
        on_progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
        inline: bool = False,
    ) -> ScanProgress:
        """Run (or resume) the full pipeline for a shoot. Safe to call again at any time."""
        shoot = self.repo.get_shoot(shoot_id)
        if shoot is None:
            raise KeyError(f"No shoot {shoot_id}")
        prog = ScanProgress(shoot_id=shoot_id)

        def emit(stage: str | None = None, **kw: Any) -> None:
            if stage:
                prog.stage = stage
            for k, v in kw.items():
                setattr(prog, k, v)
            if on_progress:
                on_progress(prog)

        def check() -> None:
            if cancel is not None and cancel.is_set():
                raise ScanCancelled()

        self.repo.update_shoot(shoot_id, status="scanning")
        try:
            folder = Path(shoot["folder_path"])
            if not folder.is_dir():
                raise FileNotFoundError(f"Folder not found: {folder}. Is the drive connected?")

            emit("discovering", message="Looking for photos")
            found = find_photos(folder)
            self.repo.sync_photos(shoot_id, [(str(f.path), str(f.companion) if f.companion else None) for f in found])
            check()

            self._analyze(shoot_id, emit, check, cancel, inline)
            check()
            self._embed(shoot_id, emit, check)
            check()
            emit("grouping", done=0, total=0, message="Grouping bursts")
            self._group(shoot_id)
            emit("scoring", message="Scoring")
            self.rescore(shoot_id)

            counts = self.repo.counts(shoot_id)
            self.repo.update_shoot(shoot_id, status="ready", photo_count=counts["total"])
            prog.finished_at = time.time()
            emit("done", errors=counts["errors"], message=f"{counts['total']} photos ready")
        except ScanCancelled:
            self.repo.update_shoot(shoot_id, status="paused")
            prog.finished_at = time.time()
            emit("cancelled", message="Paused. Scan again to pick up where it stopped.")
        except Exception as exc:
            self.repo.update_shoot(shoot_id, status="error")
            prog.finished_at = time.time()
            emit("error", message=str(exc))
        return prog

    def _analyze(self, shoot_id: int, emit, check, cancel: threading.Event | None, inline: bool) -> None:
        pending = self.repo.pending_photos(shoot_id, ANALYZER_VERSION)
        emit("analyzing", done=0, total=len(pending), message="Analyzing photos")
        if not pending:
            return
        tasks = [{"photo_id": p["id"], "path": p["path"], "companion": p["companion_path"]} for p in pending]
        done = errors = 0

        def store(result: dict) -> None:
            nonlocal done, errors
            if result["ok"]:
                self.repo.save_ingest(result["photo_id"], result["meta"], result["analysis"], None)
            else:
                errors += 1
                self.repo.mark_error(result["photo_id"], result["error"])
            done += 1
            if done % 5 == 0 or done == len(tasks):
                emit(done=done, errors=errors)

        workers = self.settings.worker_count()
        if inline or workers == 1 and len(tasks) < 8:
            _init_worker(self.settings)
            for task in tasks:
                check()
                store(process_photo(task))
            return

        ctx = multiprocessing.get_context("spawn")
        pool = ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_init_worker, initargs=(self.settings,))
        try:
            futures = [pool.submit(process_photo, t) for t in tasks]
            for fut in as_completed(futures):
                if cancel is not None and cancel.is_set():
                    raise ScanCancelled()
                try:
                    store(fut.result())
                except Exception as exc:  # a worker died (out of memory, bad native lib call)
                    errors += 1
                    done += 1
                    emit(done=done, errors=errors, message=f"A worker stopped: {exc}")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _embed(self, shoot_id: int, emit, check) -> None:
        if not self.embedder_loaded:
            emit("embedding", done=0, total=0, message="Loading the vision model (first run downloads it)")
        embedder = self.embedder
        missing = self.repo.photos_missing_embedding(shoot_id, embedder.name)
        emit("embedding", done=0, total=len(missing), message="Comparing photos")
        batch = 32
        for start in range(0, len(missing), batch):
            check()
            chunk = missing[start : start + batch]
            images, ids = [], []
            for row in chunk:
                img = self._open_cached(row["id"], row["file_hash"], "thumb")
                if img is not None:
                    images.append(img)
                    ids.append(row["id"])
            if images:
                vecs = embedder.embed(images)
                self.repo.save_embeddings(embedder.name, [(pid, to_blob(v)) for pid, v in zip(ids, vecs, strict=True)])
            emit(done=min(start + batch, len(missing)))

    def _group(self, shoot_id: int) -> None:
        th = self.settings.thresholds
        embedder = self.embedder
        rows = self.repo.analysis_rows(shoot_id)
        vectors = self.repo.load_embeddings(shoot_id, embedder.name)
        frames = [
            Frame(r["photo_id"], r["capture_ts"], from_blob(vectors[r["photo_id"]]) if r["photo_id"] in vectors else None, r["path"])
            for r in rows
        ]
        sim = th.burst_sim_fallback if isinstance(embedder, FallbackEmbedder) else th.burst_sim_clip
        by_id = {r["photo_id"]: r for r in rows}
        ranked: list[list[int]] = []
        for group in group_bursts(frames, th.burst_gap_s, sim):
            candidates = []
            for pid in group:
                r = by_id[pid]
                candidates.append({
                    "photo_id": pid,
                    "main_eyes_closed": r["main_eyes_closed"],
                    "eyes_closed_count": r["eyes_closed_count"],
                    "subject_sharpness": r["subject_sharpness"],
                    "exposure_score": exposure_score(
                        r["exposure_mean"] or 128.0, r["clip_high_pct"] or 0.0, th.under_mean, th.over_mean, th.clip_high_soft_pct
                    ),
                })
            ranked.append(rank_burst(candidates))
        self.repo.replace_bursts(shoot_id, ranked)

    # ---- scoring
    def rescore(self, shoot_id: int) -> int:
        """Recompute every recommendation for a shoot from stored analysis. Fast; no image work."""
        rows = self.repo.analysis_rows(shoot_id)
        if not rows:
            return 0
        sizes = self.repo.burst_sizes(shoot_id)
        signals = [
            PhotoSignals(
                photo_id=r["photo_id"],
                subject_sharpness=r["subject_sharpness"], tile_max_sharpness=r["tile_max_sharpness"],
                motion_anisotropy=r["motion_anisotropy"], exposure_mean=r["exposure_mean"],
                clip_high_pct=r["clip_high_pct"], clip_low_pct=r["clip_low_pct"],
                face_clip_high_pct=r["face_clip_high_pct"], face_count=r["face_count"] or 0,
                eyes_closed_count=r["eyes_closed_count"] or 0, main_eyes_closed=r["main_eyes_closed"],
                main_eye_open=r["main_eye_open"],
                burst_size=sizes.get(r["burst_id"], 1) if r["burst_id"] else 1,
                burst_rank=r["burst_rank"] or 0,
            )
            for r in rows
        ]
        rule_results = score_shoot(signals, self.settings)

        # Rule scores must be stored before the personal model runs: they are one of its inputs.
        def to_rows(results, version):
            out = []
            for f, rule in results:
                primary, secondary = describe(f.codes, rule.burst_size, f.label)
                out.append({
                    "photo_id": f.photo_id, "rule_score": f.rule_score, "personal_score": f.personal_score,
                    "final_score": f.final_score, "label": f.label, "confidence": f.confidence,
                    "reason_primary": primary, "reason_secondary": secondary,
                    "reason_codes": json.dumps(f.codes), "sharp_pct": rule.sharp_pct, "model_version": version,
                })
            return out

        self.repo.save_scores(to_rows([(finalize(r, None, 0, self.settings), r) for r in rule_results], None))

        model = self.repo.active_model()
        if model is not None:  # only load the vision model when there is a personal model to feed
            keep_prob, version = predict_keep(self.repo, self.embedder.name, shoot_id)
            if keep_prob:
                n = model["n_decisions"]
                blended = [(finalize(r, keep_prob.get(r.photo_id), n, self.settings), r) for r in rule_results]
                self.repo.save_scores(to_rows(blended, version))
        return len(rule_results)

    # ---- learning
    def train(self, force: bool = False) -> TrainResult:
        result = train_model(self.repo, self.settings, self.embedder.name, force=force)
        if result.status == "trained":
            for shoot in self.repo.list_shoots():
                if shoot["status"] == "ready":
                    self.rescore(shoot["id"])
        return result

    def model_status(self) -> dict:
        lr = self.settings.learning
        n = self.repo.labeled_count()
        active = self.repo.active_model()
        return {
            "decisions": n,
            "needed": lr.min_decisions,
            "ready": active is not None,
            "embedder": self._embedder.name if self._embedder is not None else None,
            "face_backend": self.face_backend_name,
            "model": None if active is None else {
                "version": active["version"], "kind": active["kind"], "n_decisions": active["n_decisions"],
                "n_shoots": active["n_shoots"], "created_at": active["created_at"], "metrics": active["metrics"],
            },
        }

    # ---- cached images
    def cached_image_path(self, photo_id: int, kind: str) -> Path | None:
        """Path of the cached thumb/preview for a photo, rebuilding it if the cache was cleared."""
        photo = self.repo.get_photo(photo_id)
        if photo is None or not photo.get("file_hash"):
            return None
        path = cache_path(self.settings.cache_dir, kind, photo["file_hash"])
        if path.exists():
            return path
        if not os.path.exists(photo["path"]):
            return None
        try:
            loaded = load_photo(photo["path"], self.settings.preview_px, photo.get("companion_path"))
            write_cache(self.settings.cache_dir, photo["file_hash"], loaded.image, self.settings.thumb_px)
        except Exception:
            return None
        return path if path.exists() else None

    def _open_cached(self, photo_id: int, digest: str | None, kind: str) -> Image.Image | None:
        path = self.cached_image_path(photo_id, kind)
        if path is None:
            return None
        try:
            with Image.open(path) as im:
                return im.convert("RGB")
        except Exception:
            return None
