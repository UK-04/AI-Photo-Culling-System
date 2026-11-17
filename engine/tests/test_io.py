from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from PIL import Image

from culler.io.discover import find_photos
from culler.io.exif import format_shutter, parse_capture_time
from culler.io.hashing import file_hash
from culler.io.loader import PhotoLoadError, load_photo
from culler.io.thumbs import cache_path, write_cache
from culler.synth import _exif


def _jpeg(path, size=(800, 600), exif=None, color=(120, 80, 40)):
    img = Image.new("RGB", size, color)
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(path, "JPEG", quality=90, **kwargs)
    return path


def test_discover_skips_hidden_and_pairs_raw_with_jpeg(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / ".hidden").mkdir()
    for name in ["b.jpg", "a.JPG", "notes.txt", "._a.JPG", "sub/c.png", ".hidden/x.jpg", "r1.CR3", "r1.JPG", "r2.nef"]:
        (tmp_path / name).write_bytes(b"x")
    found = find_photos(tmp_path)
    names = [f.path.name for f in found]
    assert names == ["a.JPG", "b.jpg", "r1.CR3", "r2.nef", "c.png"]
    r1 = next(f for f in found if f.path.name == "r1.CR3")
    assert r1.companion is not None and r1.companion.name == "r1.JPG"
    assert all(f.companion is None for f in found if f.path.name != "r1.CR3")


def test_discover_rejects_non_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        find_photos(tmp_path / "nope")


def test_hash_is_stable_and_content_based(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"hello" * 1000)
    b.write_bytes(b"hello" * 1000)
    assert file_hash(a) == file_hash(b)
    b.write_bytes(b"hellp" * 1000)
    assert file_hash(a)[0] != file_hash(b)[0]


def test_capture_time_with_subseconds():
    iso, ts = parse_capture_time("2026:10:03 18:22:01", "250")
    assert iso == "2026-10-03T18:22:01.250"
    _, ts2 = parse_capture_time("2026:10:03 18:22:02", "000")
    assert ts2 - ts == pytest.approx(0.75)
    assert parse_capture_time("garbage") == (None, None)
    assert parse_capture_time(None) == (None, None)


def test_format_shutter():
    assert format_shutter(1 / 250) == "1/250"
    assert format_shutter(2.0) == "2s"
    assert format_shutter(None) is None


def test_load_jpeg_reads_exif_and_downsizes(tmp_path):
    when = datetime(2026, 10, 3, 18, 22, 1, 250000)
    path = _jpeg(tmp_path / "a.jpg", size=(3000, 2000), exif=_exif(when, 800))
    loaded = load_photo(path, max_px=1024)
    assert max(loaded.image.size) == 1024 and loaded.image.mode == "RGB"
    assert (loaded.width, loaded.height) == (3000, 2000)
    assert loaded.exif["captured_at"] == "2026-10-03T18:22:01.250"
    assert loaded.exif["iso"] == 800
    assert loaded.exif["shutter"] == pytest.approx(1 / 250)
    assert loaded.exif["aperture"] == pytest.approx(2.8)
    assert loaded.exif["lens"] == "Synth 50mm F1.8"
    assert loaded.exif["camera"] == "Synth Camera 1"


def test_load_applies_exif_orientation(tmp_path):
    exif = Image.Exif()
    exif[274] = 6  # camera held vertically: stored landscape, shown portrait
    path = _jpeg(tmp_path / "rot.jpg", size=(800, 600), exif=exif)
    loaded = load_photo(path, max_px=2048)
    assert loaded.image.size == (600, 800)
    assert (loaded.width, loaded.height) == (600, 800)


def test_load_without_exif_falls_back_to_file_time(tmp_path):
    loaded = load_photo(_jpeg(tmp_path / "plain.jpg"))
    assert loaded.exif["captured_at"] and loaded.exif["capture_ts"] > 0
    assert loaded.exif.get("time_source") == "file"


def test_load_png_and_heic(tmp_path):
    img = Image.fromarray(np.random.default_rng(0).integers(0, 255, (300, 400, 3), dtype=np.uint8))
    img.save(tmp_path / "a.png")
    assert load_photo(tmp_path / "a.png").image.size == (400, 300)
    img.save(tmp_path / "a.heic", format="HEIF")
    assert load_photo(tmp_path / "a.heic").image.size == (400, 300)


@pytest.mark.parametrize("content", [b"", b"not an image at all", b"\xff\xd8\xff\xe0" + b"\x00" * 50])
def test_corrupt_files_raise_photo_load_error(tmp_path, content):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(content)
    with pytest.raises(PhotoLoadError):
        load_photo(bad)


def test_fake_raw_file_raises_photo_load_error(tmp_path):
    bad = tmp_path / "bad.cr3"
    bad.write_bytes(b"definitely not a raw file" * 10)
    with pytest.raises(PhotoLoadError):
        load_photo(bad)


def test_raw_uses_companion_jpeg(tmp_path):
    raw = tmp_path / "x.cr3"
    raw.write_bytes(b"not decodable")
    jpg = _jpeg(tmp_path / "x.jpg", size=(1200, 800))
    loaded = load_photo(raw, companion=jpg)
    assert loaded.source == "companion" and loaded.image.size == (1200, 800)


def test_thumbnail_cache_written_once(tmp_path):
    img = Image.new("RGB", (2048, 1365), (10, 200, 30))
    thumb, preview = write_cache(tmp_path, "abcdef123456", img, thumb_px=512)
    assert thumb == cache_path(tmp_path, "thumb", "abcdef123456")
    with Image.open(thumb) as t:
        assert max(t.size) == 512
    with Image.open(preview) as p:
        assert p.size == (2048, 1365)
    before = thumb.stat().st_mtime_ns
    write_cache(tmp_path, "abcdef123456", img, thumb_px=512)
    assert thumb.stat().st_mtime_ns == before
