from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from culler.api import create_app

TOKEN = "test-token"
AUTH = {"X-Culler-Token": TOKEN}


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine, token=TOKEN)) as c:
        yield c


def _wait_done(client, shoot_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/shoots/{shoot_id}/progress", params={"stream": "false"}, headers=AUTH).json()
        if not state["running"]:
            return state
        time.sleep(0.1)
    raise AssertionError("scan did not finish")


@pytest.fixture
def scanned(client, shoot):
    folder, truth = shoot
    shoot_id = client.post("/shoots", json={"folder_path": str(folder)}, headers=AUTH).json()["id"]
    client.post(f"/shoots/{shoot_id}/scan", headers=AUTH)
    assert _wait_done(client, shoot_id)["stage"] == "done"
    return shoot_id, folder, truth


def test_health_is_open_everything_else_needs_the_token(client):
    assert client.get("/health").json()["ok"] is True
    assert client.get("/shoots").status_code == 401
    assert client.get("/shoots", headers={"X-Culler-Token": "wrong"}).status_code == 401
    assert client.get("/shoots", headers=AUTH).json() == []
    assert client.get("/shoots", params={"token": TOKEN}).status_code == 200
    assert client.get("/model/status").status_code == 401
    assert client.get("/photos/1/thumb").status_code == 401


def test_add_shoot_validates_folder_and_is_idempotent(client, tmp_path):
    assert client.post("/shoots", json={"folder_path": str(tmp_path / "nope")}, headers=AUTH).status_code == 400
    a = client.post("/shoots", json={"folder_path": str(tmp_path), "name": "Wedding"}, headers=AUTH).json()
    b = client.post("/shoots", json={"folder_path": str(tmp_path)}, headers=AUTH).json()
    assert a["id"] == b["id"] and a["name"] == "Wedding"
    assert client.get("/shoots/9999", headers=AUTH).status_code == 404


def test_scan_then_grid_filters_and_sorting(client, scanned):
    shoot_id, _, truth = scanned
    data = client.get(f"/shoots/{shoot_id}/photos", headers=AUTH).json()
    photos, counts = data["photos"], data["counts"]
    assert len(photos) == len(truth) + 1 and counts["total"] == len(photos)
    assert [p["capture_ts"] for p in photos if p["capture_ts"]] == sorted(p["capture_ts"] for p in photos if p["capture_ts"])
    assert photos[-1]["status"] == "error" and photos[0]["status"] == "done"  # unreadable files sort last
    for name in ("keep", "review", "reject"):
        got = client.get(f"/shoots/{shoot_id}/photos", params={"filter": name}, headers=AUTH).json()["photos"]
        assert len(got) == counts[name] and all(p["label"] == name.upper() for p in got)
    by_score = client.get(f"/shoots/{shoot_id}/photos", params={"sort": "score"}, headers=AUTH).json()["photos"]
    scores = [p["final_score"] for p in by_score if p["final_score"] is not None]
    assert scores == sorted(scores, reverse=True)
    assert client.get(f"/shoots/{shoot_id}/photos", params={"filter": "bogus"}, headers=AUTH).status_code == 400
    assert client.get(f"/shoots/{shoot_id}/photos", params={"sort": "bogus"}, headers=AUTH).status_code == 400
    listed = client.get("/shoots", headers=AUTH).json()[0]
    assert listed["status"] == "ready" and listed["counts"]["total"] == len(photos)


def test_progress_stream_ends_with_done(client, scanned):
    shoot_id, _, _ = scanned
    with client.stream("GET", f"/shoots/{shoot_id}/progress", params={"token": TOKEN}) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    assert events and events[-1]["stage"] == "done" and events[-1]["running"] is False


def test_photo_detail_and_images(client, scanned):
    shoot_id, _, _ = scanned
    photo = next(p for p in client.get(f"/shoots/{shoot_id}/photos", headers=AUTH).json()["photos"] if p["status"] == "done")
    detail = client.get(f"/photos/{photo['id']}", headers=AUTH).json()
    assert detail["name"] == photo["name"] and detail["iso"] and detail["shutter_text"] == "1/250"
    assert detail["reason_codes"] and isinstance(detail["faces"], list)
    for kind in ("thumb", "preview"):
        r = client.get(f"/photos/{photo['id']}/{kind}", params={"token": TOKEN})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
        assert "immutable" in r.headers["cache-control"]
    assert client.get("/photos/99999", headers=AUTH).status_code == 404
    assert client.get("/photos/99999/thumb", headers=AUTH).status_code == 404


def test_decisions_single_batch_and_unflag(client, scanned):
    shoot_id, _, _ = scanned
    photos = [p for p in client.get(f"/shoots/{shoot_id}/photos", headers=AUTH).json()["photos"] if p["status"] == "done"]
    a, b, c = photos[0]["id"], photos[1]["id"], photos[2]["id"]
    assert client.post(f"/photos/{a}/decision", json={"label": "KEEP", "rating": 4}, headers=AUTH).json() == {
        "photo_id": a, "user_label": "KEEP", "user_rating": 4}
    assert client.post(f"/photos/{a}/decision", json={"rating": 2}, headers=AUTH).json()["user_label"] == "KEEP"
    assert client.post(f"/photos/{a}/decision", json={"label": None}, headers=AUTH).json() == {
        "photo_id": a, "user_label": None, "user_rating": 2}
    batch = client.post("/decisions", json={"photo_ids": [b, c], "label": "REJECT", "reason": "duplicate"}, headers=AUTH).json()
    assert [r["user_label"] for r in batch["results"]] == ["REJECT", "REJECT"]
    assert client.post(f"/photos/{a}/decision", json={}, headers=AUTH).status_code == 400
    assert client.post(f"/photos/{a}/decision", json={"label": "MAYBE"}, headers=AUTH).status_code == 422
    assert client.post(f"/photos/{a}/decision", json={"rating": 6}, headers=AUTH).status_code == 422
    assert client.post("/photos/99999/decision", json={"label": "KEEP"}, headers=AUTH).status_code == 404
    picked = client.get(f"/shoots/{shoot_id}/photos", params={"filter": "undecided"}, headers=AUTH).json()["photos"]
    assert b not in [p["id"] for p in picked] and a in [p["id"] for p in picked]


def test_exports(client, scanned, tmp_path):
    shoot_id, folder, truth = scanned
    photos = [p for p in client.get(f"/shoots/{shoot_id}/photos", headers=AUTH).json()["photos"] if p["status"] == "done"]
    client.post("/decisions", json={"photo_ids": [p["id"] for p in photos[:3]], "label": "KEEP"}, headers=AUTH)

    out = client.post(f"/shoots/{shoot_id}/export", json={"kind": "folder", "selection": "picked", "dest": str(tmp_path / "picks")}, headers=AUTH).json()
    assert out["selected"] == 3 and out["copied"] == 3 and len(list((tmp_path / "picks").glob("*.jpg"))) == 3

    out = client.post(f"/shoots/{shoot_id}/export", json={"kind": "csv", "dest": str(tmp_path)}, headers=AUTH).json()
    assert out["rows"] == len(photos) and out["dest"].endswith("-cull.csv")

    # JPEG-only shoot: sidecars are skipped with a count rather than written where Lightroom ignores them
    out = client.post(f"/shoots/{shoot_id}/export", json={"kind": "xmp", "selection": "all"}, headers=AUTH).json()
    assert out["written"] == 0 and out["skipped_not_raw"] == len(photos) and not list(folder.glob("*.xmp"))

    assert client.post(f"/shoots/{shoot_id}/export", json={"kind": "folder"}, headers=AUTH).status_code == 400
    assert client.post(f"/shoots/{shoot_id}/export", json={"kind": "zip"}, headers=AUTH).status_code == 422


def test_teach_queue_model_status_and_finish(client, scanned):
    shoot_id, _, _ = scanned
    ids = client.get(f"/shoots/{shoot_id}/teach", params={"limit": 5}, headers=AUTH).json()["photo_ids"]
    assert 0 < len(ids) <= 5
    status = client.get("/model/status", headers=AUTH).json()
    assert status["ready"] is False and status["needed"] == 300 and status["decisions"] == 0
    assert client.post(f"/shoots/{shoot_id}/finish", headers=AUTH).json()["ok"] is True
    deadline = time.time() + 30
    while time.time() < deadline:
        training = client.get("/model/status", headers=AUTH).json()["training"]
        if not training["running"] and training["last"]:
            break
        time.sleep(0.1)
    assert training["last"]["status"] == "not_enough_data"
    assert client.get(f"/shoots/{shoot_id}", headers=AUTH).json()["finished_at"]
    info = client.get("/info", headers=AUTH).json()
    assert "focus" in info["user_reasons"] and info["version"]


def test_remove_shoot_hides_it_but_keeps_decisions(client, scanned, engine):
    shoot_id, _, _ = scanned
    photo = next(p for p in client.get(f"/shoots/{shoot_id}/photos", headers=AUTH).json()["photos"] if p["status"] == "done")
    client.post(f"/photos/{photo['id']}/decision", json={"label": "KEEP"}, headers=AUTH)
    assert client.delete(f"/shoots/{shoot_id}", headers=AUTH).json() == {"ok": True}
    assert client.get("/shoots", headers=AUTH).json() == []
    assert engine.repo.labeled_count() == 1


# ---------------------------------------------------------------- Finder dialogs and hand-picked photos
def test_select_photos_makes_a_shoot_of_only_those_files(client, shoot, tmp_path):
    folder, truth = shoot
    picked = [str(folder / truth[i].file) for i in (0, 1, 2)]
    notes = tmp_path / "notes.txt"
    notes.write_text("not a photo")
    made = client.post("/shoots", json={"files": picked + [str(notes)]}, headers=AUTH).json()
    assert made["folder_path"] == str(folder.resolve()) and made["skipped"] == 1
    client.post(f"/shoots/{made['id']}/scan", headers=AUTH)
    assert _wait_done(client, made["id"])["stage"] == "done"
    names = lambda: sorted(p["name"] for p in client.get(f"/shoots/{made['id']}/photos", headers=AUTH).json()["photos"])  # noqa: E731
    assert names() == sorted(truth[i].file for i in (0, 1, 2))

    # picking more photos later adds to the same shoot
    again = client.post("/shoots", json={"files": [str(folder / truth[3].file)]}, headers=AUTH).json()
    assert again["id"] == made["id"]
    client.post(f"/shoots/{made['id']}/scan", headers=AUTH)
    _wait_done(client, made["id"])
    assert len(names()) == 4

    # opening the folder itself turns it into the whole folder
    client.post("/shoots", json={"folder_path": str(folder)}, headers=AUTH)
    client.post(f"/shoots/{made['id']}/scan", headers=AUTH)
    _wait_done(client, made["id"])
    assert len(names()) == len(truth) + 1

    assert client.post("/shoots", json={"files": [str(notes)]}, headers=AUTH).status_code == 400
    assert client.post("/shoots", json={}, headers=AUTH).status_code == 400


def test_finder_dialogs(client, monkeypatch):
    from culler import native

    # not on a Mac: the UI is told so and falls back to a typed path
    monkeypatch.setattr(native, "available", lambda: False)
    assert client.post("/dialog/folder", headers=AUTH).status_code == 501
    assert client.post("/dialog/folder").status_code == 401

    calls = []

    class Done:
        def __init__(self, code, out="", err=""):
            self.returncode, self.stdout, self.stderr = code, out, err

    def fake_run(args, **kw):
        calls.append(args)
        script = " ".join(args)
        if "choose folder" in script:
            return Done(0, "/Users/me/Pictures/Smith Wedding/\n")
        return Done(0, "/Users/me/a.CR3\n/Users/me/b c.jpg\n")

    monkeypatch.setattr(native, "available", lambda: True)
    monkeypatch.setattr(native.subprocess, "run", fake_run)
    assert client.post("/dialog/folder", headers=AUTH).json() == {"path": "/Users/me/Pictures/Smith Wedding"}
    assert client.post("/dialog/files", headers=AUTH).json() == {"paths": ["/Users/me/a.CR3", "/Users/me/b c.jpg"]}
    assert calls[0][0] == "osascript" and "multiple selections allowed" in " ".join(calls[1])

    # the user pressed Cancel
    monkeypatch.setattr(native.subprocess, "run", lambda args, **kw: Done(1, "", "execution error: User canceled. (-128)"))
    assert client.post("/dialog/folder", headers=AUTH).json() == {"path": None}
    assert client.post("/dialog/files", headers=AUTH).json() == {"paths": []}
    monkeypatch.setattr(native.subprocess, "run", lambda args, **kw: Done(1, "", "something broke"))
    assert client.post("/dialog/folder", headers=AUTH).status_code == 500
