"""Write ratings and colour labels as XMP so Lightroom, Bridge and Capture One can read them.

Two facts about Lightroom Classic shape this module:

* Pick/reject **flags are not part of XMP**. Lightroom keeps them only in its catalog,
  so no outside app can set them. Decisions therefore travel as a colour label
  (Green = keep, Yellow = review, Red = reject) plus the star rating. In Lightroom,
  filter by the Red label and press X once to flag them all.
* Lightroom reads ``.xmp`` **sidecars only for RAW files**. For JPEG/HEIC/PNG the
  metadata has to be inside the file, and originals are never modified here, so those
  get their rating embedded only in *copies* (see ``folders.py``).

An existing sidecar is merged, never replaced: only ``xmp:Rating`` and ``xmp:Label``
are touched and every other byte (develop settings, keywords) is preserved.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from ..config import RAW_EXTS
from . import KEEP, REJECT, REVIEW, effective_label

XMP_NS = "http://ns.adobe.com/xap/1.0/"
DEFAULT_LABELS = {KEEP: "Green", REVIEW: "Yellow", REJECT: "Red"}

_TEMPLATE = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Culler {version}">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"{attrs}/>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""


class XmpMergeError(Exception):
    """The existing XMP could not be understood well enough to edit it safely."""


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def new_packet(rating: int | None, label: str | None) -> str:
    attrs = ""
    if rating is not None:
        attrs += f'\n    xmp:Rating="{int(rating)}"'
    if label:
        attrs += f'\n    xmp:Label="{_escape(label)}"'
    return _TEMPLATE.format(version=__version__, attrs=attrs)


def _set_property(xml: str, name: str, value: str) -> str:
    """Set ``xmp:<name>`` in an XMP packet, whether it is stored as an attribute or an element."""
    value = _escape(value)
    for prefix in ("xmp", "xap"):
        attr = re.compile(rf'(\b{prefix}:{name}\s*=\s*)(["\'])(.*?)\2', re.S)
        if attr.search(xml):
            return attr.sub(lambda m: f"{m.group(1)}{m.group(2)}{value}{m.group(2)}", xml, count=1)
        elem = re.compile(rf"(<{prefix}:{name}\b[^>]*>)(.*?)(</{prefix}:{name}>)", re.S)
        if elem.search(xml):
            return elem.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", xml, count=1)
    # Not present: add it as an attribute on the first rdf:Description.
    desc = re.search(r"<rdf:Description\b", xml)
    if desc is None:
        raise XmpMergeError("no rdf:Description element")
    insert = f' xmp:{name}="{value}"'
    if f'"{XMP_NS}"' not in xml and f"'{XMP_NS}'" not in xml:
        insert = f' xmlns:xmp="{XMP_NS}"' + insert
    elif not re.search(r"xmlns:xmp\s*=", xml):
        # The namespace is bound to another prefix (old files use "xap"): reuse it.
        bound = re.search(rf"xmlns:(\w+)\s*=\s*[\"']{re.escape(XMP_NS)}[\"']", xml)
        if bound is None:
            raise XmpMergeError("XMP namespace is declared in an unexpected way")
        insert = f' {bound.group(1)}:{name}="{value}"'
    return xml[: desc.end()] + insert + xml[desc.end() :]


def merge_packet(existing: str, rating: int | None, label: str | None) -> str:
    """Return ``existing`` with rating and/or label set and everything else untouched."""
    out = existing
    if rating is not None:
        out = _set_property(out, "Rating", str(int(rating)))
    if label:
        out = _set_property(out, "Label", label)
    return out


def sidecar_path(photo_path: str | os.PathLike) -> Path:
    """Adobe's convention: ``IMG_1234.CR3`` -> ``IMG_1234.xmp`` next to it."""
    return Path(photo_path).with_suffix(".xmp")


def write_sidecar(photo_path: str | os.PathLike, rating: int | None, label: str | None) -> str:
    """Create or merge the sidecar. Returns ``created`` | ``merged`` | ``unchanged``."""
    path = sidecar_path(photo_path)
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="strict")
        new = merge_packet(old, rating, label)
        if new == old:
            return "unchanged"
        action = "merged"
    else:
        new, action = new_packet(rating, label), "created"
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, path)
    return action


def rating_and_label(row: dict, labels: dict[str, str], reject_rating: int | None) -> tuple[int | None, str | None]:
    """What to write for one photo: stars the photographer gave, and a colour for the decision."""
    decision = effective_label(row)
    stars = int(row.get("user_rating") or 0)
    rating: int | None = stars if stars > 0 else None
    if decision == REJECT and reject_rating is not None:
        rating = reject_rating  # -1 is "Reject" in Bridge and Photo Mechanic
    return rating, labels.get(decision) if decision else None


@dataclass
class XmpReport:
    created: int = 0
    merged: int = 0
    unchanged: int = 0
    skipped_not_raw: int = 0
    skipped_missing: int = 0
    failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["written"] = self.created + self.merged
        return d


def export_sidecars(
    rows: list[dict],
    labels: dict[str, str] | None = None,
    reject_rating: int | None = -1,
    include_non_raw: bool = False,
) -> XmpReport:
    """Write a sidecar next to each RAW photo in ``rows`` (rows come from ``Repo.grid``)."""
    labels = labels or DEFAULT_LABELS
    report = XmpReport()
    for row in rows:
        path = Path(row["path"])
        if not include_non_raw and path.suffix.lower() not in RAW_EXTS:
            report.skipped_not_raw += 1
            continue
        if not path.exists():
            report.skipped_missing += 1
            continue
        rating, label = rating_and_label(row, labels, reject_rating)
        if rating is None and label is None:
            report.unchanged += 1
            continue
        try:
            action = write_sidecar(path, rating, label)
            setattr(report, action, getattr(report, action) + 1)
        except (XmpMergeError, UnicodeDecodeError, OSError) as exc:
            report.failed.append(f"{path.name}: {exc}")
    return report


# ----------------------------------------------------------------------------- JPEG embedding
_XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"


def embed_in_jpeg_bytes(data: bytes, rating: int | None, label: str | None) -> bytes:
    """Return JPEG bytes with rating/label written into its XMP block.

    Only for copies. The image data itself is passed through untouched (no re-encode).
    """
    if data[:2] != b"\xff\xd8":
        raise XmpMergeError("not a JPEG")
    pos, insert_at, existing = 2, 2, None
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE):  # APPn or COM only; stop at the first other segment
            break
        length = int.from_bytes(data[pos + 2 : pos + 4], "big")
        payload = data[pos + 4 : pos + 2 + length]
        if marker == 0xE1 and payload.startswith(_XMP_HEADER):
            existing = (pos, pos + 2 + length, payload[len(_XMP_HEADER) :])
        elif marker == 0xE0 or (marker == 0xE1 and payload.startswith(b"Exif\x00")):
            insert_at = pos + 2 + length  # keep JFIF and EXIF first
        pos += 2 + length

    if existing is not None:
        start, end, packet = existing
        xml = merge_packet(packet.decode("utf-8"), rating, label)
    else:
        start = end = insert_at
        xml = new_packet(rating, label)
    body = _XMP_HEADER + xml.encode("utf-8")
    if len(body) + 2 > 0xFFFF:
        raise XmpMergeError("XMP block too large for one JPEG segment")
    segment = b"\xff\xe1" + (len(body) + 2).to_bytes(2, "big") + body
    return data[:start] + segment + data[end:]
