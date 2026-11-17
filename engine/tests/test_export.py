from __future__ import annotations

import csv
import io

import pytest
from PIL import Image

from culler.export import select_rows
from culler.export.csv_export import COLUMNS, export_csv
from culler.export.folders import copy_photos
from culler.export.xmp import (
    XmpMergeError,
    embed_in_jpeg_bytes,
    export_sidecars,
    merge_packet,
    new_packet,
    rating_and_label,
    sidecar_path,
    write_sidecar,
)

LIGHTROOM_SIDECAR = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   xmp:Rating="2"
   crs:Exposure2012="+0.35"
   crs:Contrast2012="+12">
   <dc:subject xmlns:dc="http://purl.org/dc/elements/1.1/"><rdf:Bag><rdf:li>wedding</rdf:li></rdf:Bag></dc:subject>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


def _row(path, label="KEEP", user_label=None, rating=0, **extra):
    return {"path": str(path), "label": label, "user_label": user_label, "user_rating": rating, "status": "done", **extra}


def test_new_packet_contains_rating_and_label():
    xml = new_packet(4, "Green")
    assert 'xmp:Rating="4"' in xml and 'xmp:Label="Green"' in xml and xml.startswith("<?xpacket begin=")
    assert "Rating" not in new_packet(None, "Red")


def test_merge_keeps_develop_settings_and_keywords():
    merged = merge_packet(LIGHTROOM_SIDECAR, 5, "Green")
    assert 'xmp:Rating="5"' in merged and 'xmp:Label="Green"' in merged
    assert 'crs:Exposure2012="+0.35"' in merged and "<rdf:li>wedding</rdf:li>" in merged
    assert merged.count("xmp:Rating") == 1
    # only the two values differ from the original
    assert merged.replace('xmp:Rating="5"', 'xmp:Rating="2"').replace(' xmp:Label="Green"', "") == LIGHTROOM_SIDECAR


def test_merge_handles_element_form_and_old_prefix():
    element = '<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/"><xmp:Rating>1</xmp:Rating></rdf:Description>'
    assert "<xmp:Rating>3</xmp:Rating>" in merge_packet(element, 3, None)
    old = '<rdf:Description rdf:about="" xmlns:xap="http://ns.adobe.com/xap/1.0/" xap:Rating="1"/>'
    assert 'xap:Rating="4"' in merge_packet(old, 4, None)
    assert 'xap:Label="Red"' in merge_packet(old, None, "Red")
    bare = '<rdf:Description rdf:about=""/>'
    out = merge_packet(bare, 2, None)
    assert 'xmlns:xmp="http://ns.adobe.com/xap/1.0/"' in out and 'xmp:Rating="2"' in out


def test_merge_refuses_unknown_structure():
    with pytest.raises(XmpMergeError):
        merge_packet("<nothing/>", 3, None)


def test_rating_and_label_mapping():
    labels = {"KEEP": "Green", "REVIEW": "Yellow", "REJECT": "Red"}
    assert rating_and_label({"label": "KEEP", "user_rating": 0}, labels, -1) == (None, "Green")
    assert rating_and_label({"label": "KEEP", "user_label": "REJECT", "user_rating": 3}, labels, -1) == (-1, "Red")
    assert rating_and_label({"label": "REJECT", "user_label": "KEEP", "user_rating": 4}, labels, -1) == (4, "Green")
    assert rating_and_label({"label": "REJECT"}, labels, None) == (None, "Red")
    assert rating_and_label({"label": "REVIEW"}, labels, -1) == (None, "Yellow")


def test_sidecar_create_merge_and_idempotent(tmp_path):
    raw = tmp_path / "IMG_0001.CR3"
    raw.write_bytes(b"raw")
    assert sidecar_path(raw).name == "IMG_0001.xmp"
    assert write_sidecar(raw, 3, "Green") == "created"
    assert write_sidecar(raw, 3, "Green") == "unchanged"
    assert write_sidecar(raw, 5, "Green") == "merged"
    assert 'xmp:Rating="5"' in sidecar_path(raw).read_text()
    assert raw.read_bytes() == b"raw"  # the original is never touched
    assert not list(tmp_path.glob("*.tmp"))


def test_export_sidecars_only_for_raw_and_preserves_existing(tmp_path):
    raw, jpg, gone = tmp_path / "a.nef", tmp_path / "b.jpg", tmp_path / "c.cr3"
    raw.write_bytes(b"raw")
    jpg.write_bytes(b"jpg")
    sidecar_path(raw).write_text(LIGHTROOM_SIDECAR)
    report = export_sidecars([_row(raw, "KEEP", rating=4), _row(jpg, "KEEP"), _row(gone, "REJECT")])
    assert (report.merged, report.created, report.skipped_not_raw, report.skipped_missing) == (1, 0, 1, 1)
    text = sidecar_path(raw).read_text()
    assert 'xmp:Rating="4"' in text and 'xmp:Label="Green"' in text and "crs:Contrast2012" in text
    assert not sidecar_path(jpg).exists() or sidecar_path(jpg) == sidecar_path(raw)


def test_embed_in_jpeg_copy_keeps_pixels_identical(tmp_path):
    src = tmp_path / "p.jpg"
    Image.new("RGB", (64, 48), (200, 30, 90)).save(src, "JPEG", quality=92)
    original = src.read_bytes()
    out = embed_in_jpeg_bytes(original, 4, "Green")
    with Image.open(io.BytesIO(out)) as a, Image.open(io.BytesIO(original)) as b:
        assert a.tobytes() == b.tobytes()
        xmp = a.info.get("xmp")
    assert xmp is not None and b'xmp:Rating="4"' in xmp and b'xmp:Label="Green"' in xmp
    # embedding again updates the block in place instead of adding a second one
    again = embed_in_jpeg_bytes(out, 2, "Red")
    assert again.count(b"http://ns.adobe.com/xap/1.0/\x00") == 1 and b'xmp:Rating="2"' in again
    with pytest.raises(XmpMergeError):
        embed_in_jpeg_bytes(b"PNG....", 1, None)


def test_copy_photos_copies_never_moves(tmp_path):
    src_dir, dest = tmp_path / "shoot", tmp_path / "picks"
    src_dir.mkdir()
    jpg, raw = src_dir / "a.jpg", src_dir / "b.cr3"
    Image.new("RGB", (64, 48), (1, 2, 3)).save(jpg, "JPEG")
    raw.write_bytes(b"rawdata")
    before = jpg.read_bytes()
    rows = [_row(jpg, "KEEP", user_label="KEEP", rating=5), _row(raw, "KEEP"), _row(src_dir / "missing.jpg")]
    report = copy_photos(rows, dest)
    assert (report.copied, report.skipped_missing, report.ratings_embedded) == (2, 1, 1)
    assert jpg.read_bytes() == before and raw.exists()
    assert b'xmp:Rating="5"' in (dest / "a.jpg").read_bytes()
    assert (dest / "b.cr3").read_bytes() == b"rawdata" and 'xmp:Label="Green"' in (dest / "b.xmp").read_text()
    # running it again copies nothing new
    again = copy_photos(rows[1:2], dest)
    assert (again.copied, again.already_there) == (0, 1)
    # a different file with the same name gets a new name instead of overwriting
    other = tmp_path / "other"
    other.mkdir()
    (other / "b.cr3").write_bytes(b"different")
    copy_photos([_row(other / "b.cr3", "KEEP")], dest)
    assert (dest / "b.cr3").read_bytes() == b"rawdata" and (dest / "b-2.cr3").read_bytes() == b"different"


def test_select_rows():
    rows = [
        {"id": 1, "label": "KEEP", "user_label": None, "user_rating": 0},
        {"id": 2, "label": "REJECT", "user_label": "KEEP", "user_rating": 0},
        {"id": 3, "label": "KEEP", "user_label": "REJECT", "user_rating": 0},
        {"id": 4, "label": "REVIEW", "user_label": None, "user_rating": 3},
    ]
    ids = lambda sel: [r["id"] for r in select_rows(rows, sel)]  # noqa: E731
    assert ids("picked") == [2] and ids("keep") == [1, 2] and ids("decided") == [2, 3, 4] and ids("all") == [1, 2, 3, 4]
    with pytest.raises(ValueError):
        select_rows(rows, "nope")


def test_csv_export(tmp_path):
    rows = [{"path": "/x/a.jpg", "name": "a.jpg", "label": "KEEP", "confidence": 0.8123, "reason_primary": "Sharp",
             "final_score": 0.71234, "user_label": None, "user_rating": 0, "status": "done", "burst_id": None}]
    path = export_csv(rows, tmp_path / "out" / "cull.csv")
    with open(path, newline="") as fh:
        records = list(csv.DictReader(fh))
    assert list(records[0].keys()) == list(COLUMNS)
    assert records[0]["decision"] == "KEEP" and records[0]["ai_confidence"] == "0.81" and records[0]["score"] == "0.712"
