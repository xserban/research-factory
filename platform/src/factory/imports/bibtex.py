"""BibTeX exports (Zotero, JabRef, hand-written) read with `bibtexparser` 1.x (slice 3d ruling 18).

The text is cut into raw records at every `@` that begins a line. `@string` definitions are read
first, so a macro may be used before or after its definition; `@comment` and `@preamble` are
skipped. Each other record is parsed on its own: one that yields no entry is `malformed` (counted,
kept as its hash only), so one bad entry never loses the rest of the file.

Invariants:
- Ordinals run from 1 in file order over every raw record that is not a string, comment or
  preamble declaration.
- `record_sha256` is the SHA-256 of the entry as `bibtexparser` re-serialises it with sorted
  fields (before LaTeX conversion), so it is stable under field order and whitespace. A malformed
  record's hash is that of its stripped raw text.
- Only the allow-listed fields leave this module (`ImportFields`); `file` is read for the first
  PDF attachment, whose path is hashed, never returned.
- `ImportFormatError` only when the bytes are not UTF-8 text with at least one `@` record.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.customization import convert_to_unicode
from bibtexparser.latexenc import latex_to_unicode

from factory.imports.attachments import read_attachment, sha256_hex
from factory.imports.model import (
    Attachment,
    ImportFormat,
    ImportFormatError,
    ImportRecord,
    ParsedImport,
    ParseOutcome,
    RecordType,
    bounded_fields,
    outcome_of,
)
from factory.model.work_ids import arxiv_id_from_doi, normalize_arxiv, normalize_doi

PARSER = "bibtexparser"
PARSER_VERSION = f"{bibtexparser.__version__}+rf1"

_RECORD_START = re.compile(r"(?m)^[ \t]*@")
_DECLARATION = re.compile(r"@\s*([A-Za-z]+)\s*[{(]")
_SKIPPED = frozenset({"comment", "preamble"})
_STRING = "string"
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_JOURNAL_ARXIV = re.compile(r"arxiv:\s*([\w./-]+)", re.IGNORECASE)
_WS = re.compile(r"\s+")
_AUTHOR_SEP = re.compile(r"\s+and\s+", re.IGNORECASE)
_LIST_SEP = re.compile(r"[,;]")
_OTHERS = "others"

_TYPES: dict[str, RecordType] = {
    "article": "article",
    "inproceedings": "inproceedings",
    "conference": "inproceedings",
    "book": "book",
    "inbook": "book",
    "incollection": "book",
    "booklet": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
}
_PREPRINT_TYPES = frozenset({"misc", "unpublished", "online", "preprint", "electronic"})


def parse_bibtex(data: bytes, base: Path | None) -> ParsedImport:
    """Parse a BibTeX export. `base` is the export's folder, for relative attachment paths."""
    text = _decode(data)
    chunks = [c for c in _RECORD_START.split(text)[1:]]
    if not chunks:
        raise ImportFormatError("no BibTeX records")
    parser = _parser()
    declared = [(_declared_type(c), "@" + c) for c in chunks]
    strings = "".join(raw for kind, raw in declared if kind == _STRING)
    if strings:
        parser.parse(strings, partial=True)

    records: list[ImportRecord] = []
    attachment_bytes: dict[str, bytes] = {}
    for kind, raw in declared:
        if kind in _SKIPPED or kind == _STRING:
            continue
        before = len(parser.bib_database.entries)
        try:
            parser.parse(raw, partial=True)
        # pyparsing raises several exception types on damaged input; each means "malformed".
        except Exception:
            del parser.bib_database.entries[before:]
        entries = parser.bib_database.entries[before:]
        if not entries:
            records.append(_malformed(len(records) + 1, raw))
            continue
        for entry in entries:
            record, content = _record(len(records) + 1, entry, base)
            records.append(record)
            if content is not None and record.attachment is not None:
                assert record.attachment.content_sha256 is not None
                attachment_bytes[record.attachment.content_sha256] = content
    return ParsedImport(
        format=ImportFormat.BIBTEX,
        parser=PARSER,
        parser_version=PARSER_VERSION,
        records=tuple(records),
        attachment_bytes=attachment_bytes,
    )


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFormatError("not UTF-8 text") from exc
    if "\x00" in text:
        raise ImportFormatError("binary data, not BibTeX")
    return text


def _parser() -> BibTexParser:
    parser = BibTexParser(
        common_strings=True,
        interpolate_strings=True,
        ignore_nonstandard_types=False,
        homogenize_fields=True,
    )
    parser.expect_multiple_parse = True
    return parser


def _declared_type(chunk: str) -> str | None:
    match = _DECLARATION.match("@" + chunk)
    return match.group(1).casefold() if match else None


def _malformed(ordinal: int, raw: str) -> ImportRecord:
    return ImportRecord(
        ordinal=ordinal,
        outcome=ParseOutcome.MALFORMED,
        fields=None,
        record_sha256=sha256_hex(raw.strip().encode("utf-8")),
    )


def _record(
    ordinal: int, entry: dict[str, Any], base: Path | None
) -> tuple[ImportRecord, bytes | None]:
    raw = {k: str(v) for k, v in entry.items()}
    converted = cast(dict[str, str], convert_to_unicode(dict(raw)))
    get = _getter(converted)
    doi_raw = get("doi")
    doi = normalize_doi(doi_raw) if doi_raw else None
    arxiv = _arxiv(raw, get, doi)
    authors, truncated = _authors(raw.get("author", ""))
    venue = get("journal") or get("journaltitle") or get("booktitle")
    fields, flags = bounded_fields(
        title=get("title"),
        authors=authors,
        year=_year(get("year") or get("date")),
        doi=doi,
        arxiv=arxiv,
        url=get("url"),
        venue=venue,
        type=_type(raw.get("ENTRYTYPE", ""), arxiv, venue),
        abstract=get("abstract"),
        tags=[t for t in _LIST_SEP.split(get("keyword") or "")],
        truncated_authors=truncated,
    )
    attachment, content = _attachment(raw.get("file"), base)
    record = ImportRecord(
        ordinal=ordinal,
        outcome=outcome_of(fields),
        fields=fields,
        record_sha256=sha256_hex(_serialise(entry).encode("utf-8")),
        attachment=attachment,
        flags=flags,
    )
    return record, content


def _getter(converted: dict[str, str]) -> Callable[[str], str | None]:
    def get(key: str) -> str | None:
        value = converted.get(key)
        return _clean(value) if value else None

    return get


def _clean(value: str) -> str | None:
    cleaned = _WS.sub(" ", value.replace("{", "").replace("}", "")).strip()
    return cleaned or None


def _serialise(entry: dict[str, Any]) -> str:
    database = BibDatabase()
    database.entries = [entry]
    return str(BibTexWriter().write(database))


def _arxiv(raw: dict[str, str], get: Callable[[str], str | None], doi: str | None) -> str | None:
    """arXiv id from `eprint` with an arXiv prefix, an arXiv `journal`, or a DataCite DOI."""
    prefix = (raw.get("archiveprefix") or raw.get("eprinttype") or "").strip().casefold()
    eprint = get("eprint")
    if eprint and prefix == "arxiv":
        return normalize_arxiv(eprint)
    journal = get("journal") or ""
    if journal.casefold().startswith("arxiv") and (match := _JOURNAL_ARXIV.search(journal)):
        return normalize_arxiv(match.group(1))
    return arxiv_id_from_doi(doi) if doi else None


def _authors(raw: str) -> tuple[list[str], bool]:
    """Display names in order; `and others` is dropped and reported as truncation."""
    names: list[str] = []
    truncated = False
    for part in _split_top_level(raw):
        name = _clean(latex_to_unicode(part))
        if not name:
            continue
        if name.casefold() == _OTHERS:
            truncated = True
            continue
        names.append(name)
    return names, truncated


def _split_top_level(raw: str) -> list[str]:
    """Split a BibTeX name list on ` and ` outside braces."""
    parts: list[str] = []
    depth = 0
    start = 0
    position = 0
    while position < len(raw):
        char = raw[position]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(depth - 1, 0)
        elif depth == 0 and (match := _AUTHOR_SEP.match(raw, position)):
            parts.append(raw[start:position])
            start = position = match.end()
            continue
        position += 1
    parts.append(raw[start:])
    return parts


def _year(value: str | None) -> int | None:
    match = _YEAR.search(value or "")
    return int(match.group(1)) if match else None


def _type(entry_type: str, arxiv: str | None, venue: str | None) -> RecordType:
    kind = entry_type.casefold()
    if arxiv and (kind in _PREPRINT_TYPES or (venue or "").casefold().startswith("arxiv")):
        return "preprint"
    return _TYPES.get(kind, "other")


def _attachment(field: str | None, base: Path | None) -> tuple[Attachment | None, bytes | None]:
    """The first PDF of a `file` field (`Description:path:mime;…`, `\\:` escaping a colon)."""
    if not field:
        return None, None
    for item in _split_unescaped(field, ";"):
        parts = _split_unescaped(item, ":")
        if len(parts) >= 3:
            path, mime = ":".join(parts[1:-1]), parts[-1]
        elif len(parts) == 2:
            path, mime = parts[0], parts[1]
        else:
            path, mime = parts[0], ""
        path = _unescape(path).strip()
        is_pdf = mime.strip().casefold() in {"application/pdf", "pdf"}
        if path and (is_pdf or path.casefold().endswith(".pdf")):
            return read_attachment(path, base)
    return None, None


def _split_unescaped(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append("\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == separator:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    parts.append("".join(current))
    return parts


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)
