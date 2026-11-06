"""RIS exports (EndNote, Zotero, publisher "download citation") read line by line.

Invariants:
- A record starts at a `TY  - ` line and ends at `ER  - ` (or the next `TY`, or the end of the
  file); a record with no `TY` line, or whose `TY` is empty, is `malformed`. Ordinals run from 1.
- `record_sha256` is the SHA-256 of the record's lines, normalised to LF and stripped of trailing
  blanks, so line endings do not change it.
- Only allow-listed fields leave this module (title, authors, year, DOI, arXiv id, URL, venue,
  type, abstract, keywords). Notes (`N1`), file links (`L1` to `L4`), ids and every other tag are
  ignored: no note field is stored, and no attachment is read.
- The parser name and version are recorded on the import (`ParsedImport.parser`).
"""

from __future__ import annotations

import re
from pathlib import Path

from factory.imports.attachments import sha256_hex
from factory.imports.model import (
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

PARSER = "ris"
PARSER_VERSION = "1+rf1"

_LINE = re.compile(r"^([A-Z][A-Z0-9])  - ?(.*)$")
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/([\w./-]+?)(?:\.pdf)?$", re.IGNORECASE)
_WS = re.compile(r"\s+")

_TYPES: dict[str, RecordType] = {
    "JOUR": "article",
    "MGZN": "article",
    "NEWS": "article",
    "EJOUR": "article",
    "CONF": "inproceedings",
    "CPAPER": "inproceedings",
    "BOOK": "book",
    "CHAP": "book",
    "EBOOK": "book",
    "THES": "thesis",
    "RPRT": "report",
    "UNPB": "preprint",
    "PPRINT": "preprint",
}
_TITLE = ("TI", "T1")
_AUTHOR = ("AU", "A1")
_VENUE = ("T2", "JO", "JF", "JA", "BT")
_YEAR_TAGS = ("PY", "Y1", "DA")
_ABSTRACT = ("AB", "N2")


def parse_ris(data: bytes, base: Path | None = None) -> ParsedImport:
    """Parse a RIS export. `base` is unused (RIS attachments are not read) and kept so the
    parser has the shape of the other byte parsers."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFormatError("not UTF-8 text") from exc
    blocks = _blocks(text)
    if not blocks:
        raise ImportFormatError("no RIS record (no `TY  - ` line)")
    records = tuple(_record(ordinal, block) for ordinal, block in enumerate(blocks, start=1))
    return ParsedImport(
        format=ImportFormat.RIS, parser=PARSER, parser_version=PARSER_VERSION, records=records
    )


def _blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        match = _LINE.match(line)
        tag = match.group(1) if match else None
        if tag == "TY":
            if current:
                blocks.append(current)
            current = [line]
        elif tag == "ER":
            if current:
                blocks.append(current)
            current = None
        elif current is not None and line:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _record(ordinal: int, block: list[str]) -> ImportRecord:
    digest = sha256_hex("\n".join(block).encode("utf-8"))
    values: dict[str, list[str]] = {}
    last: str | None = None
    for line in block:
        match = _LINE.match(line)
        if match:
            last = match.group(1)
            values.setdefault(last, []).append(match.group(2).strip())
        elif last is not None:  # a continuation line belongs to the tag above
            values[last][-1] = f"{values[last][-1]} {line.strip()}"
    ris_type = (values.get("TY") or [""])[0].upper()
    if not ris_type:
        return ImportRecord(
            ordinal=ordinal, outcome=ParseOutcome.MALFORMED, fields=None, record_sha256=digest
        )
    url = _clean(_first(values, ("UR", "L2")))
    doi = _doi(_first(values, ("DO",)))
    arxiv = _arxiv(url, doi)
    kind = _TYPES.get(ris_type, "other")
    if arxiv and kind == "other":
        kind = "preprint"
    fields, flags = bounded_fields(
        title=_clean(_first(values, _TITLE)),
        authors=[a for tag in _AUTHOR for a in values.get(tag, []) if a],
        year=_year(_first(values, _YEAR_TAGS)),
        doi=doi,
        arxiv=arxiv,
        url=url,
        venue=_clean(_first(values, _VENUE)),
        type=kind,
        abstract=_clean(_first(values, _ABSTRACT)),
        tags=[k for k in values.get("KW", []) if k],
    )
    return ImportRecord(
        ordinal=ordinal,
        outcome=outcome_of(fields),
        fields=fields,
        record_sha256=digest,
        flags=flags,
    )


def _first(values: dict[str, list[str]], tags: tuple[str, ...]) -> str | None:
    for tag in tags:
        if values.get(tag):
            return values[tag][0]
    return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WS.sub(" ", value).strip()
    return cleaned or None


def _doi(value: str | None) -> str | None:
    return normalize_doi(value) if value and value.strip() else None


def _year(value: str | None) -> int | None:
    match = _YEAR.search(value or "")
    return int(match.group(1)) if match else None


def _arxiv(url: str | None, doi: str | None) -> str | None:
    if url and (match := _ARXIV_URL.search(url)):
        return normalize_arxiv(match.group(1))
    return arxiv_id_from_doi(doi) if doi else None
