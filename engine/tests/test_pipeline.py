"""End-to-end: scan a synthetic shoot and check the results against the known truth."""

from __future__ import annotations

import shutil
import sqlite3
import threading

import pytest

from culler.benchmark import evaluate, load_truth
from culler.config import ANALYZER_VERSION
from culler.export import select_rows
from culler.export.folders import copy_photos


def _scan(engine, folder, **kw):
    shoot_id = engine.repo.add_shoot(str(folder))
    return shoot_id, engine.scan(shoot_id, inline=True, **kw)


def test_scan_labels_match_known_defects(engine, shoot):
    folder, truth = shoot
    shoot_id, result = _scan(engine, folder)
    assert result.stage == "done"
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    assert len(rows) == len(truth) + 1  # + the corrupt file

    bad = rows["IMG_BAD0.jpg"]
    assert bad["status"] == "error" and bad["label"] is None and "Could not read" in bad["error"]

    by_defect: dict[str, list[str]] = {}
    for p in truth:
        by_defect.setdefault(p.defect, []).append(rows[p.file]["label"])
    for defect in ("blur", "shake", "black"):
        assert by_defect.get(defect), f"fixture has no {defect} frames"
        assert all(label == "REJECT" for label in by_defect[defect]), (defect, by_defect[defect])
    # badly exposed frames are for the photographer to judge, not auto-rejected
    for defect in ("dark", "bright"):
        assert by_defect.get(defect) and all(label == "REVIEW" for label in by_defect[defect]), (defect, by_defect.get(defect))
    # no clean single frame may be rejected
    clean = [rows[p.file]["label"] for p in truth if p.defect == "none" and p.burst < 0]
    assert "REJECT" not in clean and clean.count("KEEP") >= 0.9 * len(clean)
    # every result explains itself
    assert all(r["reason_primary"] for r in rows.values() if r["status"] == "done")


def test_bursts_are_found_and_best_frame_is_the_sharp_one(engine, shoot):
    folder, truth = shoot
    shoot_id, _ = _scan(engine, folder)
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    expected = {}
    for p in truth:
        if p.burst >= 0:
            expected.setdefault(p.burst, []).append(p)
    bursts = engine.repo.list_bursts(shoot_id)
    assert len(bursts) == len(expected)
    for frames in expected.values():
        ids = {rows[p.file]["burst_id"] for p in frames}
        assert len(ids) == 1 and None not in ids  # all frames landed in one burst
        best = next(p for p in frames if p.burst_best)
        assert rows[best.file]["burst_rank"] == 0 and rows[best.file]["label"] == "KEEP"
        assert all(rows[p.file]["label"] != "KEEP" for p in frames if not p.burst_best)
        assert rows[best.file]["burst_size"] == len(frames)
    singles = [rows[p.file] for p in truth if p.burst < 0]
    assert all(r["burst_id"] is None for r in singles)


def test_benchmark_against_truth_csv(engine, shoot):
    folder, _ = shoot
    shoot_id, _ = _scan(engine, folder)
    truth = load_truth(folder, truth_csv=str(folder / "truth.csv"))
    m = evaluate(engine.repo.grid(shoot_id), engine.repo.list_bursts(shoot_id), truth)
    assert m["with_truth"] == len(truth)
    assert m["reject_precision"] == 1.0 and m["good_photos_wrongly_rejected"] == 0
    assert m["keep_precision"] >= 0.9
    assert m["burst_best_is_a_pick"] == 1.0


def test_rescan_does_no_work_and_new_files_are_picked_up(engine, shoot, tmp_path):
    folder, truth = shoot
    shoot_id, _ = _scan(engine, folder)
    assert engine.repo.pending_photos(shoot_id, ANALYZER_VERSION) == [] or all(
        p["path"].endswith("IMG_BAD0.jpg") for p in engine.repo.pending_photos(shoot_id, ANALYZER_VERSION)
    )
    stages = []
    _, again = _scan(engine, folder, on_progress=lambda p: stages.append((p.stage, p.total)))
    assert again.stage == "done"
    assert max(total for stage, total in stages if stage == "analyzing") <= 1  # only the unreadable file is retried
    assert max(total for stage, total in stages if stage == "embedding") == 0

    shutil.copy(folder / truth[0].file, folder / "NEW_0001.jpg")
    _scan(engine, folder)
    assert "NEW_0001.jpg" in {r["name"] for r in engine.repo.grid(shoot_id)}
    assert engine.repo.get_shoot(shoot_id)["photo_count"] == len(truth) + 2


def test_decisions_survive_a_rename_and_a_missing_file(engine, shoot):
    folder, truth = shoot
    shoot_id, _ = _scan(engine, folder)
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    moved, gone = truth[0].file, truth[1].file
    engine.repo.add_decision(rows[moved]["id"], label="KEEP", rating=4)
    engine.repo.add_decision(rows[gone]["id"], label="REJECT")

    (folder / moved).rename(folder / "RENAMED.jpg")
    (folder / gone).unlink()
    _scan(engine, folder)
    after = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    assert moved not in after and gone not in after
    assert after["RENAMED.jpg"]["id"] == rows[moved]["id"]
    assert (after["RENAMED.jpg"]["user_label"], after["RENAMED.jpg"]["user_rating"]) == ("KEEP", 4)
    # the vanished photo's decision is still in the log for training
    kept = engine.repo.conn().execute("SELECT COUNT(*) FROM decisions WHERE photo_id = ?", (rows[gone]["id"],)).fetchone()[0]
    assert kept == 1


def test_decision_log_is_append_only_and_records_the_ai_call(engine, shoot):
    folder, truth = shoot
    shoot_id, _ = _scan(engine, folder)
    row = next(r for r in engine.repo.grid(shoot_id) if r["label"] == "REJECT")
    engine.repo.add_decision(row["id"], label="KEEP", reason="expression")
    engine.repo.add_decision(row["id"], rating=3)
    engine.repo.add_decision(row["id"], label=None)  # unflag keeps the rating
    detail = engine.repo.photo_detail(row["id"])
    assert (detail["user_label"], detail["user_rating"]) == (None, 3)
    log = detail["decisions"]
    assert len(log) == 3 and log[-1]["ai_label"] == "REJECT" and log[-1]["user_reason"] == "expression"
    assert log[-1]["ai_reason"]
    c = engine.repo.conn()
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM decisions")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE decisions SET user_label = 'KEEP'")
    c.rollback()
    with pytest.raises(ValueError):
        engine.repo.add_decision(row["id"], label="MAYBE")
    with pytest.raises(ValueError):
        engine.repo.add_decision(row["id"], rating=9)


def test_counts_follow_decisions(engine, shoot):
    folder, _ = shoot
    shoot_id, _ = _scan(engine, folder)
    before = engine.repo.counts(shoot_id)
    assert before["keep"] + before["review"] + before["reject"] + before["errors"] == before["total"]
    assert before["undecided"] == before["total"] and before["picked"] == 0
    review = next(r for r in engine.repo.grid(shoot_id) if r["label"] == "REVIEW")
    engine.repo.add_decision(review["id"], label="KEEP", rating=3)
    after = engine.repo.counts(shoot_id)
    assert after["keep"] == before["keep"] + 1 and after["review"] == before["review"] - 1
    assert after["picked"] == 1 and after["rated3"] == 1 and after["undecided"] == before["undecided"] - 1


def test_cancel_then_resume(engine, shoot):
    folder, truth = shoot
    cancel = threading.Event()
    seen = []

    def on_progress(p):
        seen.append(p.stage)
        if p.stage == "analyzing" and p.done >= 5:
            cancel.set()

    shoot_id, result = _scan(engine, folder, on_progress=on_progress, cancel=cancel)
    assert result.stage == "cancelled" and engine.repo.get_shoot(shoot_id)["status"] == "paused"
    done_so_far = len(engine.repo.analysis_rows(shoot_id))
    assert 5 <= done_so_far < len(truth)
    _, resumed = _scan(engine, folder)
    assert resumed.stage == "done" and len(engine.repo.analysis_rows(shoot_id)) == len(truth)


def test_missing_folder_reports_an_error_instead_of_raising(engine, tmp_path):
    folder = tmp_path / "card"
    folder.mkdir()
    shoot_id = engine.repo.add_shoot(str(folder))
    folder.rmdir()
    result = engine.scan(shoot_id, inline=True)
    assert result.stage == "error" and "not found" in result.message.lower()


def test_originals_are_never_modified(engine, shoot, tmp_path):
    folder, truth = shoot
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir()}
    shoot_id, _ = _scan(engine, folder)
    rows = engine.repo.grid(shoot_id)
    for r in rows[:5]:
        if r["status"] == "done":
            engine.repo.add_decision(r["id"], label="KEEP", rating=5)
    copy_photos(select_rows(rows, "all"), tmp_path / "out")
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir()}
    assert after == before


def test_multiprocess_scan_matches_inline(settings, shoot, tmp_path):
    """The worker-pool path (what the app uses) gives the same answers as the inline path."""
    from culler.config import Settings
    from culler.service import Engine
    from culler.similarity.embeddings import FallbackEmbedder

    folder, _ = shoot
    inline_engine = Engine(settings, embedder=FallbackEmbedder())
    sid, _ = _scan(inline_engine, folder)
    expected = {r["name"]: (r["label"], r["burst_rank"]) for r in inline_engine.repo.grid(sid)}

    pooled_settings = Settings(data_dir=tmp_path / "data2", embedder="fallback", workers=2)
    pooled = Engine(pooled_settings, embedder=FallbackEmbedder())
    sid2 = pooled.repo.add_shoot(str(folder))
    assert pooled.scan(sid2).stage == "done"
    assert {r["name"]: (r["label"], r["burst_rank"]) for r in pooled.repo.grid(sid2)} == expected
