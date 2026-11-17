"""FastAPI app. Every route except ``/health`` needs the per-launch token.

The token arrives as the ``X-Culler-Token`` header, or as ``?token=`` for the things a
browser cannot send headers with (``<img>`` tags and the progress event stream).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..db.repo import UNSET
from ..export import select_rows
from ..export.csv_export import export_csv
from ..export.folders import copy_photos
from ..export.xmp import export_sidecars
from ..io.exif import format_shutter
from ..learning.active import teach_queue
from ..scoring.reasons import USER_REASONS
from ..service import Engine
from .jobs import JobManager

DEFAULT_ORIGINS = [
    "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
    "http://localhost:1420", "http://127.0.0.1:1420",
]
_IMAGE_HEADERS = {"Cache-Control": "private, max-age=31536000, immutable"}


class ShootIn(BaseModel):
    folder_path: str
    name: str | None = None


class DecisionIn(BaseModel):
    label: Literal["KEEP", "REJECT"] | None = None
    rating: int | None = Field(default=None, ge=0, le=5)
    reason: str | None = Field(default=None, max_length=200)


class BatchDecisionIn(DecisionIn):
    photo_ids: list[int] = Field(min_length=1, max_length=20000)


class ExportIn(BaseModel):
    kind: Literal["xmp", "folder", "csv"]
    selection: Literal["picked", "keep", "decided", "all"] = "all"
    dest: str | None = None
    write_ratings: bool = True
    reject_rating: int | None = -1


class TrainIn(BaseModel):
    force: bool = False


def create_app(engine: Engine, token: str | None = None, ui_dir: str | os.PathLike | None = None) -> FastAPI:
    jobs = JobManager(engine)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="Culler engine", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    repo = engine.repo
    app.state.engine, app.state.jobs = engine, jobs

    origins = DEFAULT_ORIGINS + [o for o in os.environ.get("CULLER_ALLOWED_ORIGINS", "").split(",") if o]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["X-Culler-Token", "Content-Type"]
    )

    def auth(request: Request) -> None:
        if token is None:
            return
        given = request.headers.get("x-culler-token") or request.query_params.get("token") or ""
        if not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="Missing or wrong token")

    secured = [Depends(auth)]

    def need_shoot(shoot_id: int) -> dict:
        shoot = repo.get_shoot(shoot_id)
        if shoot is None:
            raise HTTPException(404, "No such shoot")
        return shoot

    def shoot_out(shoot: dict) -> dict:
        return {**shoot, "counts": repo.counts(shoot["id"]), "progress": jobs.progress(shoot["id"])}

    # ------------------------------------------------------------------ health
    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "name": "culler", "version": __version__}

    @app.get("/info", dependencies=secured)
    def info() -> dict:
        return {"version": __version__, "data_dir": str(engine.settings.data_dir), "user_reasons": USER_REASONS, **engine.model_status()}

    # ------------------------------------------------------------------ shoots
    @app.get("/shoots", dependencies=secured)
    def list_shoots() -> list[dict]:
        return [shoot_out(s) for s in repo.list_shoots()]

    @app.post("/shoots", dependencies=secured)
    def add_shoot(body: ShootIn) -> dict:
        folder = Path(body.folder_path).expanduser()
        if not folder.is_dir():
            raise HTTPException(400, f"Not a folder: {folder}")
        shoot_id = repo.add_shoot(str(folder), body.name)
        return shoot_out(need_shoot(shoot_id))

    @app.get("/shoots/{shoot_id}", dependencies=secured)
    def get_shoot(shoot_id: int) -> dict:
        return shoot_out(need_shoot(shoot_id))

    @app.delete("/shoots/{shoot_id}", dependencies=secured)
    def remove_shoot(shoot_id: int) -> dict:
        """Hide a shoot from the library. Its decisions stay, because the model learns from them."""
        need_shoot(shoot_id)
        jobs.cancel_scan(shoot_id)
        repo.update_shoot(shoot_id, archived=1)
        return {"ok": True}

    @app.post("/shoots/{shoot_id}/scan", dependencies=secured)
    def scan(shoot_id: int) -> dict:
        need_shoot(shoot_id)
        return jobs.start_scan(shoot_id)

    @app.post("/shoots/{shoot_id}/cancel", dependencies=secured)
    def cancel(shoot_id: int) -> dict:
        need_shoot(shoot_id)
        return jobs.cancel_scan(shoot_id)

    @app.get("/shoots/{shoot_id}/progress", dependencies=secured)
    async def progress(shoot_id: int, request: Request, stream: bool = True):
        need_shoot(shoot_id)
        if not stream:
            return jobs.progress(shoot_id)

        async def events():
            last = None
            while True:
                if await request.is_disconnected():
                    break
                state = jobs.progress(shoot_id)
                payload = json.dumps(state)
                if payload != last:
                    yield f"data: {payload}\n\n"
                    last = payload
                if not state["running"]:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/shoots/{shoot_id}/photos", dependencies=secured)
    def photos(shoot_id: int, filter: str = "all", sort: str = "time") -> dict:
        need_shoot(shoot_id)
        rows = repo.grid(shoot_id)
        rows = _filter(rows, filter)
        if sort == "score":
            rows.sort(key=lambda r: -(r["final_score"] if r["final_score"] is not None else -1))
        elif sort == "sharpness":
            rows.sort(key=lambda r: -(r["sharp_pct"] if r["sharp_pct"] is not None else -1))
        elif sort != "time":
            raise HTTPException(400, "sort must be time, score or sharpness")
        return {"photos": rows, "counts": repo.counts(shoot_id)}

    @app.get("/shoots/{shoot_id}/teach", dependencies=secured)
    def teach(shoot_id: int, limit: int = 50) -> dict:
        need_shoot(shoot_id)
        ids = teach_queue(repo.grid(shoot_id), engine.settings.thresholds.keep_score, max(1, min(limit, 500)))
        return {"photo_ids": ids}

    @app.post("/shoots/{shoot_id}/finish", dependencies=secured)
    def finish(shoot_id: int) -> dict:
        """Mark the cull as done and retrain the personal model on the new decisions."""
        need_shoot(shoot_id)
        from ..db.repo import now_iso

        repo.update_shoot(shoot_id, finished_at=now_iso())
        return {"ok": True, "training": jobs.start_training()}

    @app.post("/shoots/{shoot_id}/export", dependencies=secured)
    def export(shoot_id: int, body: ExportIn) -> dict:
        shoot = need_shoot(shoot_id)
        rows = [r for r in select_rows(repo.grid(shoot_id), body.selection) if r["status"] == "done"]
        if body.kind == "xmp":
            report = export_sidecars(rows, reject_rating=body.reject_rating).to_dict()
        elif body.kind == "folder":
            if not body.dest:
                raise HTTPException(400, "Choose a destination folder")
            report = copy_photos(rows, body.dest, write_ratings=body.write_ratings, reject_rating=body.reject_rating).to_dict()
        else:
            if not body.dest:
                raise HTTPException(400, "Choose where to save the CSV")
            dest = Path(body.dest).expanduser()
            if dest.is_dir() or not dest.suffix:
                dest = dest / f"{shoot['name']}-cull.csv"
            report = {"dest": str(export_csv(rows, dest)), "rows": len(rows)}
        return {"kind": body.kind, "selected": len(rows), **report}

    # ------------------------------------------------------------------ photos
    @app.get("/photos/{photo_id}", dependencies=secured)
    def photo(photo_id: int) -> dict:
        detail = repo.photo_detail(photo_id)
        if detail is None:
            raise HTTPException(404, "No such photo")
        detail["name"] = os.path.basename(detail["path"])
        detail["shutter_text"] = format_shutter(detail.get("shutter"))
        return detail

    def _image(photo_id: int, kind: str) -> FileResponse:
        path = engine.cached_image_path(photo_id, kind)
        if path is None:
            raise HTTPException(404, "Image not available. Is the drive with the originals connected?")
        return FileResponse(path, media_type="image/jpeg", headers=_IMAGE_HEADERS)

    @app.get("/photos/{photo_id}/thumb", dependencies=secured)
    def thumb(photo_id: int) -> FileResponse:
        return _image(photo_id, "thumb")

    @app.get("/photos/{photo_id}/preview", dependencies=secured)
    def preview(photo_id: int) -> FileResponse:
        return _image(photo_id, "preview")

    def _decide(photo_id: int, body: DecisionIn) -> dict:
        label = body.label if "label" in body.model_fields_set else UNSET
        rating = body.rating if ("rating" in body.model_fields_set and body.rating is not None) else UNSET
        if label is UNSET and rating is UNSET:
            raise HTTPException(400, "Send a label and/or a rating")
        try:
            return repo.add_decision(photo_id, label=label, rating=rating, reason=body.reason)
        except KeyError:
            raise HTTPException(404, "No such photo") from None

    @app.post("/photos/{photo_id}/decision", dependencies=secured)
    def decide(photo_id: int, body: DecisionIn) -> dict:
        return _decide(photo_id, body)

    @app.post("/decisions", dependencies=secured)
    def decide_many(body: BatchDecisionIn) -> dict:
        return {"results": [_decide(pid, body) for pid in body.photo_ids]}

    # ------------------------------------------------------------------ model
    @app.get("/model/status", dependencies=secured)
    def model_status() -> dict:
        return {**engine.model_status(), "training": jobs.training()}

    @app.post("/model/train", dependencies=secured)
    def model_train(body: TrainIn | None = None) -> dict:
        return jobs.start_training(force=bool(body and body.force))

    # Optional: serve the built UI from the same origin (browser mode, no desktop shell).
    if ui_dir is not None and Path(ui_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    return app


def _filter(rows: list[dict], name: str) -> list[dict]:
    def eff(r: dict) -> str | None:
        return r.get("user_label") or r.get("label")

    tests = {
        "all": lambda r: True,
        "keep": lambda r: eff(r) == "KEEP",
        "review": lambda r: r.get("user_label") is None and r.get("label") == "REVIEW",
        "reject": lambda r: eff(r) == "REJECT",
        "undecided": lambda r: r.get("user_label") is None,
        "picked": lambda r: r.get("user_label") == "KEEP",
        "rated3": lambda r: (r.get("user_rating") or 0) >= 3,
    }
    if name not in tests:
        raise HTTPException(400, f"filter must be one of: {', '.join(tests)}")
    return [r for r in rows if tests[name](r)]
