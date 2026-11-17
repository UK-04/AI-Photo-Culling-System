"""All database access goes through ``Repo``.

One SQLite file in WAL mode. Each thread gets its own connection, so the scan worker
thread and the API threads never share one.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
UNSET: Any = object()

_ANALYSIS_COLS = (
    "sharpness", "subject_sharpness", "face_sharpness", "tile_max_sharpness", "blur_score", "blur_kind",
    "motion_anisotropy", "motion_direction", "exposure_mean", "clip_high_pct", "clip_low_pct",
    "face_clip_high_pct", "face_count", "eyes_closed_count", "main_eyes_closed", "main_eye_open",
    "faces_json", "face_backend", "analyzer_version",
)
_META_COLS = (
    "file_hash", "file_size", "captured_at", "capture_ts", "camera", "lens", "iso", "shutter",
    "aperture", "focal", "width", "height",
)


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class Repo:
    def __init__(self, db_path: str | os.PathLike):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.migrate()

    # ------------------------------------------------------------------ connection
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30.0)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        c = self.conn()
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise

    def migrate(self) -> int:
        """Apply numbered ``NNNN_name.sql`` files that have not run yet. Returns the version."""
        c = self.conn()
        c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL)")
        current = c.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        for sql_file in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
            version = int(sql_file.name.split("_")[0])
            if version > current:
                c.executescript("BEGIN;\n" + sql_file.read_text() + "\nCOMMIT;")
                c.execute("INSERT INTO schema_version VALUES (?, ?)", (version, now_iso()))
                c.commit()
                current = version
        return current

    # ------------------------------------------------------------------ shoots
    def add_shoot(self, folder_path: str, name: str | None = None) -> int:
        folder_path = str(Path(folder_path).expanduser().resolve())
        with self.tx() as c:
            row = c.execute("SELECT id FROM shoots WHERE folder_path = ?", (folder_path,)).fetchone()
            if row:
                c.execute("UPDATE shoots SET archived = 0 WHERE id = ?", (row["id"],))
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO shoots (folder_path, name, created_at) VALUES (?, ?, ?)",
                (folder_path, name or Path(folder_path).name, now_iso()),
            )
            return int(cur.lastrowid)

    def get_shoot(self, shoot_id: int) -> dict | None:
        row = self.conn().execute("SELECT * FROM shoots WHERE id = ?", (shoot_id,)).fetchone()
        return dict(row) if row else None

    def list_shoots(self) -> list[dict]:
        rows = self.conn().execute("SELECT * FROM shoots WHERE archived = 0 ORDER BY created_at DESC, id DESC").fetchall()
        return [dict(r) for r in rows]

    def update_shoot(self, shoot_id: int, **fields: Any) -> None:
        allowed = {"name", "status", "photo_count", "finished_at", "archived"}
        sets = [k for k in fields if k in allowed]
        if not sets:
            return
        with self.tx() as c:
            c.execute(
                f"UPDATE shoots SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                [fields[k] for k in sets] + [shoot_id],
            )

    # ------------------------------------------------------------------ photos
    def sync_photos(self, shoot_id: int, found: Iterable[tuple[str, str | None]]) -> dict[str, int]:
        """Reconcile the photo rows of a shoot with what is on disk now.

        ``found`` is ``(path, companion_path)`` pairs. New files get rows, files that
        vanished are marked ``missing`` (their decisions are kept), files that came back
        are revived.
        """
        found = list(found)
        on_disk = {p for p, _ in found}
        added = revived = missing = 0
        with self.tx() as c:
            existing = {r["path"]: r for r in c.execute("SELECT id, path, status FROM photos WHERE shoot_id = ?", (shoot_id,))}
            for path, companion in found:
                row = existing.get(path)
                if row is None:
                    c.execute(
                        "INSERT INTO photos (shoot_id, path, companion_path) VALUES (?, ?, ?)", (shoot_id, path, companion)
                    )
                    added += 1
                elif row["status"] == "missing":
                    c.execute("UPDATE photos SET status = 'new', companion_path = ? WHERE id = ?", (companion, row["id"]))
                    revived += 1
            for path, row in existing.items():
                if path not in on_disk and row["status"] != "missing":
                    c.execute("UPDATE photos SET status = 'missing' WHERE id = ?", (row["id"],))
                    missing += 1
        return {"added": added, "revived": revived, "missing": missing}

    def pending_photos(self, shoot_id: int, analyzer_version: int) -> list[dict]:
        """Photos that still need ingest or analysis (new, failed, or analyzed by an older version)."""
        rows = self.conn().execute(
            """SELECT p.id, p.path, p.companion_path FROM photos p
               LEFT JOIN analysis a ON a.photo_id = p.id
               WHERE p.shoot_id = ? AND p.status != 'missing'
                 AND (p.status != 'done' OR a.photo_id IS NULL OR a.analyzer_version != ?)
               ORDER BY p.path""",
            (shoot_id, analyzer_version),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_ingest(self, photo_id: int, meta: dict, analysis: dict, embedding: tuple[str, bytes] | None) -> int:
        """Store one processed photo. Returns the id it was stored under.

        If the same file content already exists in this shoot as a ``missing`` row, the
        file was moved or renamed: the old row (with its decisions) takes the new path.
        """
        with self.tx() as c:
            me = c.execute("SELECT shoot_id, path, companion_path FROM photos WHERE id = ?", (photo_id,)).fetchone()
            if me is None:
                return photo_id
            moved = c.execute(
                "SELECT id FROM photos WHERE shoot_id = ? AND file_hash = ? AND status = 'missing' AND id != ?",
                (me["shoot_id"], meta.get("file_hash"), photo_id),
            ).fetchone()
            if moved is not None:
                c.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
                c.execute(
                    "UPDATE photos SET path = ?, companion_path = ? WHERE id = ?",
                    (me["path"], me["companion_path"], moved["id"]),
                )
                photo_id = int(moved["id"])
            c.execute(
                f"UPDATE photos SET {', '.join(f'{k} = ?' for k in _META_COLS)}, status = 'done', error = NULL WHERE id = ?",
                [meta.get(k) for k in _META_COLS] + [photo_id],
            )
            c.execute(
                f"INSERT OR REPLACE INTO analysis (photo_id, {', '.join(_ANALYSIS_COLS)}) "
                f"VALUES (?, {', '.join('?' for _ in _ANALYSIS_COLS)})",
                [photo_id] + [analysis.get(k) for k in _ANALYSIS_COLS],
            )
            if embedding is not None:
                c.execute("INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?)", (photo_id, embedding[0], embedding[1]))
        return photo_id

    def mark_error(self, photo_id: int, message: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE photos SET status = 'error', error = ? WHERE id = ?", (message[:500], photo_id))

    def get_photo(self, photo_id: int) -> dict | None:
        row = self.conn().execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return dict(row) if row else None

    def photo_detail(self, photo_id: int) -> dict | None:
        c = self.conn()
        row = c.execute(
            """SELECT p.*, a.sharpness, a.subject_sharpness, a.face_sharpness, a.blur_score, a.blur_kind,
                      a.motion_anisotropy, a.exposure_mean, a.clip_high_pct, a.clip_low_pct, a.face_clip_high_pct,
                      a.face_count, a.eyes_closed_count, a.main_eyes_closed, a.main_eye_open, a.faces_json, a.face_backend,
                      s.rule_score, s.personal_score, s.final_score, s.label, s.confidence, s.reason_primary,
                      s.reason_secondary, s.reason_codes, s.sharp_pct, s.model_version
               FROM photos p LEFT JOIN analysis a ON a.photo_id = p.id LEFT JOIN scores s ON s.photo_id = p.id
               WHERE p.id = ?""",
            (photo_id,),
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["faces"] = json.loads(out.pop("faces_json") or "[]")
        out["reason_codes"] = json.loads(out.get("reason_codes") or "[]")
        out["burst"] = None
        if out.get("burst_id"):
            b = c.execute("SELECT photo_ids, best_photo_id FROM bursts WHERE id = ?", (out["burst_id"],)).fetchone()
            if b:
                out["burst"] = {"id": out["burst_id"], "photo_ids": json.loads(b["photo_ids"]), "best_photo_id": b["best_photo_id"]}
        out["decisions"] = [
            dict(r) for r in c.execute("SELECT * FROM decisions WHERE photo_id = ? ORDER BY id DESC LIMIT 20", (photo_id,))
        ]
        return out

    # ------------------------------------------------------------------ embeddings
    def photos_missing_embedding(self, shoot_id: int, model_name: str) -> list[dict]:
        rows = self.conn().execute(
            """SELECT p.id, p.file_hash FROM photos p
               LEFT JOIN embeddings e ON e.photo_id = p.id AND e.model_name = ?
               WHERE p.shoot_id = ? AND p.status = 'done' AND e.photo_id IS NULL ORDER BY p.id""",
            (model_name, shoot_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_embeddings(self, model_name: str, items: Iterable[tuple[int, bytes]]) -> None:
        with self.tx() as c:
            c.executemany("INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?)", [(pid, model_name, blob) for pid, blob in items])

    def load_embeddings(self, shoot_id: int, model_name: str) -> dict[int, bytes]:
        rows = self.conn().execute(
            """SELECT e.photo_id, e.vector FROM embeddings e JOIN photos p ON p.id = e.photo_id
               WHERE p.shoot_id = ? AND e.model_name = ?""",
            (shoot_id, model_name),
        ).fetchall()
        return {int(r["photo_id"]): r["vector"] for r in rows}

    # ------------------------------------------------------------------ bursts
    def replace_bursts(self, shoot_id: int, ranked_groups: list[list[int]]) -> None:
        """Store the bursts of a shoot. Each group is photo ids, best first."""
        with self.tx() as c:
            c.execute("DELETE FROM bursts WHERE shoot_id = ?", (shoot_id,))
            c.execute("UPDATE photos SET burst_id = NULL, burst_rank = NULL WHERE shoot_id = ?", (shoot_id,))
            for group in ranked_groups:
                cur = c.execute(
                    "INSERT INTO bursts (shoot_id, photo_ids, best_photo_id) VALUES (?, ?, ?)",
                    (shoot_id, json.dumps(group), group[0]),
                )
                c.executemany(
                    "UPDATE photos SET burst_id = ?, burst_rank = ? WHERE id = ?",
                    [(cur.lastrowid, rank, pid) for rank, pid in enumerate(group)],
                )

    def burst_sizes(self, shoot_id: int) -> dict[int, int]:
        rows = self.conn().execute("SELECT id, photo_ids FROM bursts WHERE shoot_id = ?", (shoot_id,)).fetchall()
        return {int(r["id"]): len(json.loads(r["photo_ids"])) for r in rows}

    def list_bursts(self, shoot_id: int) -> list[dict]:
        rows = self.conn().execute("SELECT * FROM bursts WHERE shoot_id = ? ORDER BY id", (shoot_id,)).fetchall()
        return [{"id": r["id"], "photo_ids": json.loads(r["photo_ids"]), "best_photo_id": r["best_photo_id"]} for r in rows]

    # ------------------------------------------------------------------ analysis + scores
    def analysis_rows(self, shoot_id: int) -> list[dict]:
        """Analysis joined with capture time and burst position, for bursts and scoring."""
        rows = self.conn().execute(
            """SELECT p.id AS photo_id, p.path, p.capture_ts, p.burst_id, p.burst_rank, a.*
               FROM photos p JOIN analysis a ON a.photo_id = p.id
               WHERE p.shoot_id = ? AND p.status = 'done' ORDER BY p.capture_ts, p.path""",
            (shoot_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_scores(self, rows: list[dict]) -> None:
        cols = (
            "photo_id", "rule_score", "personal_score", "final_score", "label", "confidence",
            "reason_primary", "reason_secondary", "reason_codes", "sharp_pct", "model_version", "scored_at",
        )
        stamp = now_iso()
        with self.tx() as c:
            c.executemany(
                f"INSERT OR REPLACE INTO scores ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [[{**r, "scored_at": stamp}.get(k) for k in cols] for r in rows],
            )

    def grid(self, shoot_id: int) -> list[dict]:
        """One compact row per photo, in shooting order, for the review grid."""
        sizes = self.burst_sizes(shoot_id)
        rows = self.conn().execute(
            """SELECT p.id, p.path, p.file_hash, p.captured_at, p.capture_ts, p.width, p.height,
                      p.burst_id, p.burst_rank, p.user_label, p.user_rating, p.status, p.error,
                      s.label, s.confidence, s.final_score, s.rule_score, s.personal_score,
                      s.reason_primary, s.reason_secondary, s.sharp_pct,
                      a.subject_sharpness, a.face_count
               FROM photos p LEFT JOIN scores s ON s.photo_id = p.id LEFT JOIN analysis a ON a.photo_id = p.id
               WHERE p.shoot_id = ? AND p.status IN ('done', 'error')
               ORDER BY (p.status = 'error'), p.capture_ts, p.path""",
            (shoot_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["name"] = os.path.basename(d["path"])
            d["burst_size"] = sizes.get(d["burst_id"], 1) if d["burst_id"] else 1
            out.append(d)
        return out

    def counts(self, shoot_id: int) -> dict[str, int]:
        """Counts for the sidebar. A photo's effective label is the user's call, else the engine's."""
        r = self.conn().execute(
            """SELECT COUNT(*) AS total,
                      SUM(COALESCE(p.user_label, s.label) = 'KEEP') AS keep,
                      SUM(p.user_label IS NULL AND s.label = 'REVIEW') AS review,
                      SUM(COALESCE(p.user_label, s.label) = 'REJECT') AS reject,
                      SUM(p.user_label IS NULL) AS undecided,
                      SUM(p.user_label = 'KEEP') AS picked,
                      SUM(p.user_label = 'REJECT') AS rejected,
                      SUM(p.user_rating >= 3) AS rated3,
                      SUM(p.status = 'error') AS errors
               FROM photos p LEFT JOIN scores s ON s.photo_id = p.id
               WHERE p.shoot_id = ? AND p.status IN ('done', 'error')""",
            (shoot_id,),
        ).fetchone()
        return {k: int(r[k] or 0) for k in r.keys()}

    # ------------------------------------------------------------------ decisions
    def add_decision(self, photo_id: int, label: Any = UNSET, rating: Any = UNSET, reason: str | None = None) -> dict:
        """Record a decision and update the photo's current state.

        Pass only what changed: ``label`` ("KEEP", "REJECT" or None to unflag) and/or
        ``rating`` (0-5). The log row stores the resulting state next to the engine's
        recommendation at that moment.
        """
        if label is not UNSET and label not in ("KEEP", "REJECT", None):
            raise ValueError("label must be KEEP, REJECT or None")
        if rating is not UNSET and not (isinstance(rating, int) and 0 <= rating <= 5):
            raise ValueError("rating must be an integer 0-5")
        with self.tx() as c:
            photo = c.execute("SELECT user_label, user_rating FROM photos WHERE id = ?", (photo_id,)).fetchone()
            if photo is None:
                raise KeyError(photo_id)
            new_label = photo["user_label"] if label is UNSET else label
            new_rating = photo["user_rating"] if rating is UNSET else rating
            ai = c.execute(
                "SELECT label, confidence, reason_primary, reason_secondary, model_version FROM scores WHERE photo_id = ?",
                (photo_id,),
            ).fetchone()
            ai_reason = None
            if ai is not None:
                ai_reason = ai["reason_primary"] + (f"; {ai['reason_secondary']}" if ai["reason_secondary"] else "")
            c.execute(
                """INSERT INTO decisions (photo_id, ai_label, ai_confidence, ai_reason, user_label, user_rating,
                                          user_reason, decided_at, model_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    photo_id, ai["label"] if ai else None, ai["confidence"] if ai else None, ai_reason,
                    new_label, new_rating, reason, now_iso(), ai["model_version"] if ai else None,
                ),
            )
            c.execute("UPDATE photos SET user_label = ?, user_rating = ? WHERE id = ?", (new_label, new_rating, photo_id))
        return {"photo_id": photo_id, "user_label": new_label, "user_rating": new_rating}

    def labeled_count(self) -> int:
        """How many photos currently carry a KEEP or REJECT from the photographer (all shoots)."""
        return int(self.conn().execute("SELECT COUNT(*) FROM photos WHERE user_label IN ('KEEP', 'REJECT')").fetchone()[0])

    def feature_rows(self, embedder: str, shoot_id: int | None = None, labeled_only: bool = False) -> list[dict]:
        """Rows with everything the personal model uses, for training or prediction."""
        where, args = ["p.status IN ('done', 'missing')"], [embedder]
        if shoot_id is not None:
            where.append("p.shoot_id = ?")
            args.append(shoot_id)
        if labeled_only:
            where.append("p.user_label IN ('KEEP', 'REJECT')")
        rows = self.conn().execute(
            f"""SELECT p.id AS photo_id, p.shoot_id, p.user_label, p.user_rating, p.burst_id, p.burst_rank,
                       e.vector, s.sharp_pct, s.rule_score, s.label AS ai_label,
                       a.subject_sharpness, a.face_sharpness, a.blur_score, a.motion_anisotropy, a.exposure_mean,
                       a.clip_high_pct, a.clip_low_pct, a.face_count, a.eyes_closed_count, a.main_eyes_closed,
                       a.main_eye_open,
                       (SELECT MAX(d.id) FROM decisions d WHERE d.photo_id = p.id) AS last_decision
                FROM photos p
                JOIN embeddings e ON e.photo_id = p.id AND e.model_name = ?
                JOIN analysis a ON a.photo_id = p.id
                LEFT JOIN scores s ON s.photo_id = p.id
                WHERE {' AND '.join(where)} ORDER BY p.id""",
            args,
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ models
    def active_model(self) -> dict | None:
        row = self.conn().execute("SELECT * FROM models WHERE active = 1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        out = dict(row)
        out["metrics"] = json.loads(out.pop("metrics_json") or "{}")
        return out

    def register_model(self, version: str, kind: str, embedder: str, n_decisions: int, n_shoots: int, metrics: dict, path: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE models SET active = 0")
            c.execute(
                "INSERT INTO models VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (version, kind, embedder, n_decisions, n_shoots, json.dumps(metrics), path, now_iso()),
            )
