"""Background work for the API: scans and training run one at a time on a worker thread."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from ..service import Engine, ScanProgress


class JobManager:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="culler-job")
        self._lock = threading.Lock()
        self._progress: dict[int, dict] = {}
        self._cancel: dict[int, threading.Event] = {}
        self._training: dict = {"running": False, "last": None}

    # ---- scans
    def start_scan(self, shoot_id: int) -> dict:
        with self._lock:
            current = self._progress.get(shoot_id)
            if current and current.get("running"):
                return current
            cancel = threading.Event()
            self._cancel[shoot_id] = cancel
            queued = ScanProgress(shoot_id=shoot_id, stage="queued", message="Waiting to start").to_dict()
            queued["running"] = True
            self._progress[shoot_id] = queued

        def on_progress(p: ScanProgress) -> None:
            with self._lock:
                self._progress[shoot_id] = p.to_dict()

        def run() -> None:
            try:
                result = self.engine.scan(shoot_id, on_progress=on_progress, cancel=cancel)
                with self._lock:
                    self._progress[shoot_id] = result.to_dict()
            except Exception as exc:  # scan() reports its own errors; this is a last resort
                with self._lock:
                    failed = ScanProgress(shoot_id=shoot_id, stage="error", message=str(exc)).to_dict()
                    self._progress[shoot_id] = failed
            finally:
                self.engine.repo.close()

        self._pool.submit(run)
        return queued

    def cancel_scan(self, shoot_id: int) -> dict:
        with self._lock:
            event = self._cancel.get(shoot_id)
            if event is not None:
                event.set()
        return self.progress(shoot_id)

    def progress(self, shoot_id: int) -> dict:
        with self._lock:
            current = self._progress.get(shoot_id)
            if current is not None:
                return dict(current)
        idle = ScanProgress(shoot_id=shoot_id).to_dict()
        shoot = self.engine.repo.get_shoot(shoot_id)
        if shoot and shoot["status"] == "ready":
            idle["stage"] = "done"
        return idle

    # ---- training
    def start_training(self, force: bool = False) -> dict:
        with self._lock:
            if self._training["running"]:
                return dict(self._training)
            self._training["running"] = True

        def run() -> None:
            try:
                result = self.engine.train(force=force).to_dict()
            except Exception as exc:
                result = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
            finally:
                self.engine.repo.close()
            with self._lock:
                self._training = {"running": False, "last": result}

        self._pool.submit(run)
        return {"running": True, "last": self._training["last"]}

    def training(self) -> dict:
        with self._lock:
            return dict(self._training)

    def shutdown(self) -> None:
        with self._lock:
            for event in self._cancel.values():
                event.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
