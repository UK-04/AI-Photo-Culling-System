"""Fast content fingerprint: xxhash of the first megabyte plus the file size."""

from __future__ import annotations

import os

import xxhash

_CHUNK = 1 << 20


def file_hash(path: str | os.PathLike) -> tuple[str, int]:
    """Return ``(hash, size_in_bytes)``. Reads at most 1 MB, so it is quick on RAW files."""
    size = os.path.getsize(path)
    h = xxhash.xxh3_64()
    with open(path, "rb") as fh:
        h.update(fh.read(_CHUNK))
    h.update(str(size).encode())
    return h.hexdigest(), size
