"""Attachment references of an export: a path as written, hashed, and the bytes when readable.

Invariant: the path itself is never returned; only its SHA-256 and the content's SHA-256 are.
A relative path is read against the export's folder (`base`); without a base only an absolute
path can be read. An unreadable or missing file gives `content_sha256 = None`, never an error.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from factory.imports.model import Attachment


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_attachment(path_text: str, base: Path | None) -> tuple[Attachment, bytes | None]:
    """The attachment reference for `path_text`, and its bytes if the file can be read."""
    path_sha = sha256_hex(path_text.encode("utf-8"))
    written = Path(path_text).expanduser()
    candidate: Path | None = written if written.is_absolute() else None
    if candidate is None and base is not None:
        candidate = base / written
    data: bytes | None = None
    if candidate is not None:
        try:
            if candidate.is_file():
                data = candidate.read_bytes()
        except OSError:
            data = None
    content = sha256_hex(data) if data is not None else None
    return Attachment(path_sha256=path_sha, content_sha256=content), data
