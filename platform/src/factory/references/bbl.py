"""LaTeX `.bbl` reader and its alignment with a parsed bibliography.

Works on bytes passed in; nothing is extracted to disk. The `.bbl` never creates entries: it only
supplies text from which identifier fields are recovered when entry counts agree.
"""

import gzip
import io
import re
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from factory.references.parse import Bibliography, RefFields, parse_entry_fields

_GZIP_MAGIC = b"\x1f\x8b"
_BIBITEM = "\\bibitem"
_END = re.compile(r"\\end\{thebibliography\}")


@dataclass(frozen=True)
class BblEntry:
    """One `\\bibitem`: its cite key and its text with LaTeX markup reduced to plain text."""

    key: str
    text: str


@dataclass(frozen=True)
class BblAlignment:
    """`fields` has one item per bibliography entry; all `None` unless `status` is `aligned`."""

    status: Literal["absent", "aligned", "count-mismatch"]
    bib_count: int
    bbl_count: int
    fields: tuple[RefFields | None, ...]


def read_bbl(archive: bytes, *, max_bytes: int = 20_000_000) -> list[BblEntry]:
    """Entries of every `*.bbl` in a tar.gz / tar archive, or of a plain (optionally gzipped) bbl.

    Members are read in name order. Returns `[]` when nothing is found, the data is not readable
    or any decompressed size exceeds `max_bytes` (bounded reads; zip bombs are not expanded).
    """
    data = archive
    if len(data) > max_bytes:
        return []
    try:
        if data[:2] == _GZIP_MAGIC:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                data = gz.read(max_bytes + 1)
            if len(data) > max_bytes:
                return []
        texts: list[bytes] = []
        if _is_tar(data):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
                members = sorted(
                    (m for m in tar.getmembers() if m.isfile() and m.name.endswith(".bbl")),
                    key=lambda m: m.name,
                )
                for member in members:
                    handle = tar.extractfile(member)
                    if handle is not None:
                        texts.append(handle.read(member.size))
        else:
            texts.append(data)
    except (OSError, EOFError, tarfile.TarError):
        return []
    entries: list[BblEntry] = []
    for raw in texts:
        entries.extend(_parse(raw.decode("utf-8", errors="replace")))
    return entries


def _is_tar(data: bytes) -> bool:
    try:
        return tarfile.is_tarfile(io.BytesIO(data))
    except (OSError, tarfile.TarError):
        return False


def _close_square(text: str, start: int) -> int | None:
    """Index of the `]` closing the `[` at `start`; brackets inside braces do not count."""
    depth = 0
    brace = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            brace += 1
        elif c == "}":
            brace -= 1
        elif brace == 0 and c == "[":
            depth += 1
        elif brace == 0 and c == "]":
            depth -= 1
            if depth == 0:
                return i
    return None


def _close_brace(text: str, start: int) -> int | None:
    """Index of the `}` closing the `{` at `start`."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _parse(text: str) -> list[BblEntry]:
    text = re.sub(r"(?m)(?:^|(?<=\s))%.*$", "", text)
    end = _END.search(text)
    if end:
        text = text[: end.start()]
    entries: list[BblEntry] = []
    pieces = text.split(_BIBITEM)[1:]
    for piece in pieces:
        i = 0
        while i < len(piece) and piece[i].isspace():
            i += 1
        if i < len(piece) and piece[i] == "[":
            close = _close_square(piece, i)
            if close is None:
                continue
            i = close + 1
            while i < len(piece) and piece[i].isspace():
                i += 1
        if i >= len(piece) or piece[i] != "{":
            continue
        close = _close_brace(piece, i)
        if close is None:
            continue
        key = piece[i + 1 : close].strip()
        entries.append(BblEntry(key, _plain(piece[close + 1 :])))
    return entries


def _plain(body: str) -> str:
    body = re.sub(r"\\href\{([^{}]{0,2000})\}\{([^{}]{0,2000})\}", r"\2 \1", body)
    body = re.sub(r"\\doi\{([^{}]{0,2000})\}", r"doi:\1", body)
    body = re.sub(r"\\url\{([^{}]{0,2000})\}", r"\1", body)
    body = re.sub(r"\\natexlab\{[^{}]{0,200}\}", "", body)
    body = body.replace("\\newblock", " ").replace("~", " ")
    body = re.sub(r"\\([&%_#$])", r"\1", body)
    body = re.sub(r"\\[a-zA-Z]+\*?", " ", body)
    body = body.replace("{", "").replace("}", "")
    return " ".join(body.split())


def align(bib: Bibliography, bbl: Sequence[BblEntry]) -> BblAlignment:
    """Align by order when the counts are equal; otherwise leave the bibliography as it stands."""
    nothing: tuple[RefFields | None, ...] = (None,) * len(bib.entries)
    if not bbl:
        return BblAlignment("absent", len(bib.entries), 0, nothing)
    if len(bbl) != len(bib.entries):
        return BblAlignment("count-mismatch", len(bib.entries), len(bbl), nothing)
    return BblAlignment(
        "aligned",
        len(bib.entries),
        len(bbl),
        tuple(parse_entry_fields(b.text) for b in bbl),
    )
