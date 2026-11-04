"""In-memory unpacking of arXiv e-print archives, with caps and safe names.

Media types (as produced by `factory.sources.fulltext.arxiv`): `application/x-eprint-tar` is a
gzip tar of sources; `application/x-eprint` is a single gzipped file (one .tex). A bare
uncompressed tar or .tex is also accepted.

Invariants:
- Nothing is written to disk here; `unpack_eprint` returns `{relative posix path: bytes}`.
- Member count, per-file size and total size are capped, also for decompression (a gzip bomb
  stops at the cap). A breach raises `EprintError`; its message carries no archive content.
- Names are relative, UTF-8 round-trippable, free of any path component starting with `-` (so a
  member can never be read as a command-line option), and no file name is a directory prefix of
  another (a conflict raises `EprintError`).
- Only regular files are kept. Links, devices and members with an unsafe name (absolute, `..`,
  backslash, NUL, empty) are skipped and counted; the count is returned.
"""

import io
import posixpath
import re
import tarfile
import zlib

from factory.errors import FactoryError

MAX_MEMBERS = 2000
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
_GZIP_MAGIC = b"\x1f\x8b"
_DOCUMENTCLASS = re.compile(r"^[^%\n]*\\documentclass", re.MULTILINE)


class EprintError(FactoryError):
    """The archive breaches a cap or is unreadable. The message never contains archive text."""


def safe_member_name(name: str) -> str | None:
    """The normalised relative POSIX name, or None when the name could escape its directory."""
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return None
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return None
    normal = posixpath.normpath(name)
    parts = normal.split("/")
    if normal == "." or ".." in parts or "" in parts:
        return None
    if any(part.startswith("-") for part in parts):
        return None
    return normal


def _gunzip(data: bytes) -> bytes:
    """Decompress gzip data, refusing output above `MAX_TOTAL_BYTES`."""
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = decoder.decompress(data, MAX_TOTAL_BYTES + 1)
    except zlib.error as exc:
        raise EprintError("gzip data is corrupt") from exc
    if len(out) > MAX_TOTAL_BYTES or decoder.unconsumed_tail:
        raise EprintError("decompressed e-print exceeds the size cap")
    return out


def unpack_eprint(raw: bytes) -> tuple[dict[str, bytes], int]:
    """Unpack an e-print into `({name: bytes}, skipped_member_count)`; see the module invariants."""
    data = _gunzip(raw) if raw[:2] == _GZIP_MAGIC else raw
    if not tarfile.is_tarfile(io.BytesIO(data)):
        if len(data) > MAX_FILE_BYTES:
            raise EprintError("file exceeds the size cap")
        return {"main.tex": data}, 0
    files: dict[str, bytes] = {}
    skipped = 0
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for count, member in enumerate(archive, start=1):
                if count > MAX_MEMBERS:
                    raise EprintError("e-print has too many members")
                name = safe_member_name(member.name)
                if not member.isfile() or name is None:
                    skipped += 1
                    continue
                if member.size > MAX_FILE_BYTES:
                    raise EprintError("member exceeds the size cap")
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise EprintError("e-print exceeds the total size cap")
                handle = archive.extractfile(member)
                if handle is None:
                    skipped += 1
                    continue
                files[name] = handle.read()
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise EprintError("tar archive is corrupt") from exc
    for name in files:
        parent = posixpath.dirname(name)
        while parent:
            if parent in files:
                raise EprintError("e-print member names conflict (file and directory)")
            parent = posixpath.dirname(parent)
    return files, skipped


def find_main_tex(files: dict[str, bytes]) -> str | None:
    """Heuristic choice of the main .tex name (a ranking, not a TeX parse): the file has an
    uncommented `\\documentclass`; `\\begin{document}` preferred, then shallowest, then
    lexicographic. None when no .tex declares a document class."""
    candidates: list[tuple[int, int, str]] = []
    for name, content in files.items():
        if not name.endswith(".tex"):
            continue
        text = content.decode("utf-8", errors="replace")
        if _DOCUMENTCLASS.search(text):
            body = 0 if "\\begin{document}" in text else 1
            candidates.append((body, name.count("/"), name))
    return min(candidates)[2] if candidates else None
