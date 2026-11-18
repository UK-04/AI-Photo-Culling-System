"""Auto-rotation, manual rotation, full-size images, and the editing-recoverability estimate."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from culler.analysis.faces import NullBackend, build_face_backend
from culler.analysis.orientation import detect_rotation, rotate_cw
from culler.api import create_app
from culler.io.thumbs import ensure_rotated, rotate_image, rotated_path, write_cache
from culler.scoring.recover import assess, stops_under

AUTH = {"X-Culler-Token": "t"}


# ---------------------------------------------------------------- rotation helpers
def test_rotate_cw_and_rotate_image_agree():
    a = np.arange(24, dtype=np.uint8).reshape(2, 4, 3)
    for deg in (0, 90, 180, 270):
        assert np.array_equal(rotate_cw(a, deg), np.asarray(rotate_image(Image.fromarray(a), deg)))
    turned = rotate_cw(a, 90)
    assert turned.shape == (4, 2, 3)
    assert np.array_equal(turned[0, -1], a[0, 0])  # the top-left corner ends up top-right
    assert np.array_equal(rotate_cw(rotate_cw(a, 90), 270), a)


def test_rotated_cache_files(tmp_path):
    img = Image.new("RGB", (800, 600), (9, 9, 9))
    write_cache(tmp_path, "abc123", img, 256)
    assert rotated_path(tmp_path, "thumb", "abc123", 0).name == "abc123.jpg"
    turned = ensure_rotated(tmp_path, "preview", "abc123", 90)
    assert turned.name == "abc123-r90.jpg"
    with Image.open(turned) as t:
        assert t.size == (600, 800)
    assert ensure_rotated(tmp_path, "preview", "missing", 90) is None


def test_no_faces_means_no_auto_rotation(scene):
    assert detect_rotation(scene, NullBackend()) == 0


@pytest.fixture(scope="module")
def portrait():
    """A real face photo (scikit-image's bundled sample), enlarged. Skipped if unavailable."""
    data = pytest.importorskip("skimage.data")
    import cv2

    return cv2.resize(data.astronaut(), (1200, 1200), interpolation=cv2.INTER_CUBIC)


@pytest.fixture(scope="module")
def detector(tmp_path_factory):
    from culler.config import Settings

    backend = build_face_backend(Settings(data_dir=tmp_path_factory.mktemp("d")))
    if backend.name == "none":
        pytest.skip("face model not installed (run scripts/fetch_models.sh)")
    return backend


@pytest.mark.parametrize("sideways_by", [90, 180, 270])
def test_sideways_face_photo_is_turned_upright(portrait, detector, sideways_by):
    assert detect_rotation(portrait, detector) == 0  # already upright: leave it alone
    sideways = rotate_cw(portrait, sideways_by)
    fix = detect_rotation(sideways, detector)
    assert fix == (360 - sideways_by) % 360
    assert np.array_equal(rotate_cw(sideways, fix), portrait)


# ---------------------------------------------------------------- recoverability
def _a(**kw):
    return {"exposure_mean": 120.0, "clip_high_pct": 0.0, "clip_low_pct": 0.0, "face_clip_high_pct": None, **kw}


def test_nothing_to_fix():
    r = assess(_a(), ["sharp", "well_exposed"], is_raw=True, iso=400)
    assert (r.score, r.label, r.note, r.has_problem) == (1.0, "Nothing to fix", "", False)


def test_stops_under_scale():
    assert stops_under(118) == 0 and stops_under(200) == 0
    assert 2.0 < stops_under(60) < 2.3 and 4.0 < stops_under(30) < 4.6


def test_underexposure_raw_beats_jpeg_and_high_iso_hurts():
    codes = ["underexposed", "sharp"]
    raw = assess(_a(exposure_mean=55), codes, True, 400)
    jpg = assess(_a(exposure_mean=55), codes, False, 400)
    noisy = assess(_a(exposure_mean=55), codes, True, 6400)
    assert raw.score > jpg.score and raw.score > noisy.score
    assert raw.label in ("Easy fix", "Fixable") and "stops under" in raw.note and "RAW" in raw.note
    assert "ISO 6400" in noisy.note
    very_dark = assess(_a(exposure_mean=14), codes, False, 3200)
    assert very_dark.label == "Not fixable" and "more than a JPEG can recover" in very_dark.note
    dark_jpg, dark_raw = assess(_a(exposure_mean=35), codes, False, 200), assess(_a(exposure_mean=35), codes, True, 200)
    assert dark_jpg.label == "Not fixable" and dark_raw.label == "Hard to fix"


def test_blown_highlights_depend_on_how_much_and_where():
    little = assess(_a(clip_high_pct=3.0), ["highlights_clipped"], True, 100)
    lots = assess(_a(clip_high_pct=40.0), ["overexposed"], True, 100)
    face = assess(_a(clip_high_pct=4.0, face_clip_high_pct=30.0), ["face_blown"], False, 100)
    assert little.label == "Easy fix" and lots.label == "Not fixable" and face.label == "Not fixable"
    assert "main face" in face.note and "JPEG are gone" in face.note
    bright_not_clipped = assess(_a(exposure_mean=215, clip_high_pct=0.2), ["overexposed"], True, 100)
    assert bright_not_clipped.label == "Easy fix"


def test_blur_and_closed_eyes_cannot_be_fixed():
    for code in ("camera_shake", "out_of_focus", "missed_focus", "eyes_closed", "blank_frame"):
        r = assess(_a(), [code], True, 100)
        assert r.label == "Not fixable" and r.note, code
    soft = assess(_a(), ["soft_focus"], True, 100)
    assert soft.label == "Fixable" and "Sharpening" in soft.note
    # the worst problem decides: a fixable exposure does not rescue a blurred frame
    both = assess(_a(exposure_mean=60), ["out_of_focus", "underexposed"], True, 100)
    assert both.label == "Not fixable" and both.note.startswith("Blur")


# ---------------------------------------------------------------- end to end
@pytest.fixture
def scanned(engine, shoot):
    folder, truth = shoot
    shoot_id = engine.repo.add_shoot(str(folder))
    assert engine.scan(shoot_id, inline=True).stage == "done"
    return shoot_id, folder, truth


def test_every_scored_photo_gets_a_recoverability_estimate(engine, scanned):
    shoot_id, _, truth = scanned
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    by_defect = {}
    for p in truth:
        by_defect.setdefault(p.defect, []).append(rows[p.file])
    assert all(r["recover_label"] == "Not fixable" for d in ("blur", "shake", "black") for r in by_defect[d])
    assert all(r["recover_score"] < 1 and "stops under" in r["recover_note"] for r in by_defect["dark"])
    clean = [r for r in by_defect["none"] if r["label"] == "KEEP"]
    assert clean and all(r["recover_label"] == "Nothing to fix" for r in clean)


def test_manual_rotation_and_full_size_image(engine, scanned):
    shoot_id, folder, _ = scanned
    with TestClient(create_app(engine, token="t")) as client:
        photo = next(p for p in client.get(f"/shoots/{shoot_id}/photos", headers=AUTH).json()["photos"] if p["status"] == "done")
        pid, w, h = photo["id"], photo["width"], photo["height"]
        assert photo["rotation"] == 0 and w > h
        original = (folder / photo["name"]).read_bytes()

        # unrotated JPEG: the full-size image is the original file itself
        full = client.get(f"/photos/{pid}/full", headers=AUTH)
        assert full.status_code == 200 and full.content == original

        assert client.post(f"/photos/{pid}/rotate", json={"degrees": 90}, headers=AUTH).json() == {"photo_id": pid, "rotation": 90}
        after = next(p for p in client.get(f"/shoots/{shoot_id}/photos", headers=AUTH).json()["photos"] if p["id"] == pid)
        assert (after["rotation"], after["width"], after["height"]) == (90, h, w)
        assert after["label"] is not None  # re-analyzed and re-scored
        import io
        for kind in ("thumb", "preview", "full"):
            img = Image.open(io.BytesIO(client.get(f"/photos/{pid}/{kind}", headers=AUTH).content))
            assert img.height > img.width, kind
        assert (folder / photo["name"]).read_bytes() == original  # the original is untouched

        # three more quarter turns bring it back; a rescan keeps a rotation set by hand
        client.post(f"/photos/{pid}/rotate", json={"degrees": -90}, headers=AUTH)
        assert client.post(f"/photos/{pid}/rotate", json={"degrees": 180}, headers=AUTH).json()["rotation"] == 180
        engine.repo.conn().execute("UPDATE analysis SET analyzer_version = 0 WHERE photo_id = ?", (pid,))
        engine.repo.conn().commit()
        assert engine.scan(shoot_id, inline=True).stage == "done"
        assert engine.repo.get_photo(pid)["rotation"] == 180 and engine.repo.get_photo(pid)["rotation_source"] == "user"

        assert client.post(f"/photos/{pid}/rotate", json={"degrees": 45}, headers=AUTH).status_code == 422
        assert client.post("/photos/99999/rotate", json={"degrees": 90}, headers=AUTH).status_code == 404
        assert client.get("/photos/99999/full", headers=AUTH).status_code == 404
        fixable = client.get(f"/shoots/{shoot_id}/photos", params={"filter": "fixable"}, headers=AUTH).json()["photos"]
        assert all(0.5 <= p["recover_score"] < 1 for p in fixable)


def test_sideways_portrait_is_auto_rotated_in_a_scan(engine, portrait, detector, tmp_path):
    folder = tmp_path / "faces"
    folder.mkdir()
    Image.fromarray(portrait).save(folder / "upright.jpg", quality=92)
    Image.fromarray(rotate_cw(portrait, 270)).save(folder / "sideways.jpg", quality=92)
    shoot_id = engine.repo.add_shoot(str(folder))
    assert engine.scan(shoot_id, inline=True).stage == "done"
    rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
    assert rows["upright.jpg"]["rotation"] == 0
    assert rows["sideways.jpg"]["rotation"] == 90
    assert engine.repo.get_photo(rows["sideways.jpg"]["id"])["rotation_source"] == "auto"
    # the face was measured on the turned image, so its box sits where the upright photo's does
    a = engine.repo.photo_detail(rows["upright.jpg"]["id"])["faces"][0]["box_rel"]
    b = engine.repo.photo_detail(rows["sideways.jpg"]["id"])["faces"][0]["box_rel"]
    assert np.allclose(a, b, atol=0.03)


def test_eyes_are_measured_on_a_real_face(portrait, detector):
    """Closed-eye detection end to end on a real portrait (eyes open). Needs the landmark model."""
    if getattr(detector, "eyes_problem", "missing"):
        pytest.skip(f"landmark model not available: {getattr(detector, 'eyes_problem', None)}")
    faces = detector.detect(portrait)
    assert len(faces) == 1 and detector.name == "yunet+landmarks"
    face = faces[0]
    assert face.eyes_closed is False and face.eye_open is not None and face.eye_open > 0.4
    # the same face with the eye region painted over reads as not-open or unmeasured, never as open
    x, y, w, h = (int(v) for v in face.box)
    covered = portrait.copy()
    covered[y + int(0.25 * h) : y + int(0.5 * h), x : x + w] = covered[y + int(0.6 * h), x + w // 2]
    blocked = detector.detect(covered)
    assert not blocked or blocked[0].eye_open is None or blocked[0].eye_open < face.eye_open
