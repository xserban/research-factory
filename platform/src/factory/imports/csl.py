"""CSL JSON exports (Zotero, Better BibTeX, citeproc) read with pydantic models (ruling 18).

Invariants:
- The file is a JSON array of items; anything else raises `ImportFormatError`.
- Ordinals run from 1 in array order. An element that is not an object, or whose allow-listed
  fields have the wrong types, is `malformed`.
- `record_sha256` is the SHA-256 of the item's canonical JSON (sorted keys), so key order and
  whitespace do not change it.
- Only allow-listed fields leave this module; every other key (notes, ids, paths) is ignored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from factory.canonical import canonical_json
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

PARSER = "csl-json"
PARSER_VERSION = "1+rf1"

_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_ARXIV_NUMBER = re.compile(r"(?:arxiv:\s*)?([\w./-]+)", re.IGNORECASE)
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/([\w./-]+?)(?:\.pdf)?$", re.IGNORECASE)
_LIST_SEP = re.compile(r"[,;]")
_WS = re.compile(r"\s+")
_PDF = "application/pdf"

_TYPES: dict[str, RecordType] = {
    "article-journal": "article",
    "article-magazine": "article",
    "article-newspaper": "article",
    "paper-conference": "inproceedings",
    "book": "book",
    "chapter": "book",
    "thesis": "thesis",
    "report": "report",
    "article": "preprint",
    "manuscript": "preprint",
    "posted-content": "preprint",
}


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, strict=True)


class _Name(_Loose):
    family: str | None = None
    given: str | None = None
    literal: str | None = None


class _Date(_Loose):
    date_parts: list[list[int | str]] | None = Field(default=None, alias="date-parts")
    raw: str | None = None
    literal: str | None = None


class _AttachmentRef(_Loose):
    path: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    content_type: str | None = Field(default=None, alias="contentType")


class _Item(_Loose):
    type: str | None = None
    title: str | None = None
    author: list[_Name] = Field(default_factory=list)
    issued: _Date | None = None
    doi: str | None = Field(default=None, alias="DOI")
    url: str | None = Field(default=None, alias="URL")
    container_title: str | None = Field(default=None, alias="container-title")
    abstract: str | None = None
    keyword: str | list[str] | None = None
    number: str | int | None = None
    publisher: str | None = None
    attachments: list[_AttachmentRef] = Field(default_factory=list)


def parse_csl(data: bytes, base: Path | None) -> ParsedImport:
    """Parse a CSL JSON export. `base` is the export's folder, for relative attachment paths."""
    try:
        items = json.loads(data.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ImportFormatError("not JSON") from exc
    if not isinstance(items, list):
        raise ImportFormatError("CSL JSON is an array of items")
    records: list[ImportRecord] = []
    attachment_bytes: dict[str, bytes] = {}
    for ordinal, raw in enumerate(items, start=1):
        digest = sha256_hex(canonical_json(raw))
        try:
            item = _Item.model_validate(raw)
        except ValidationError:
            records.append(
                ImportRecord(
                    ordinal=ordinal,
                    outcome=ParseOutcome.MALFORMED,
                    fields=None,
                    record_sha256=digest,
                )
            )
            continue
        record, content = _record(ordinal, item, digest, base)
        records.append(record)
        if content is not None and record.attachment and record.attachment.content_sha256:
            attachment_bytes[record.attachment.content_sha256] = content
    return ParsedImport(
        format=ImportFormat.CSL,
        parser=PARSER,
        parser_version=PARSER_VERSION,
        records=tuple(records),
        attachment_bytes=attachment_bytes,
    )


def _reject_constant(name: str) -> None:
    raise ValueError(f"not JSON: {name}")


def _record(
    ordinal: int, item: _Item, digest: str, base: Path | None
) -> tuple[ImportRecord, bytes | None]:
    doi = normalize_doi(item.doi) if item.doi and item.doi.strip() else None
    arxiv = _arxiv(item, doi)
    kind = _TYPES.get((item.type or "").casefold(), "other")
    if arxiv and kind in {"other", "report"}:
        kind = "preprint"
    fields, flags = bounded_fields(
        title=_clean(item.title),
        authors=[n for n in (_name(a) for a in item.author) if n],
        year=_year(item.issued),
        doi=doi,
        arxiv=arxiv,
        url=_clean(item.url),
        venue=_clean(item.container_title),
        type=kind,
        abstract=_clean(item.abstract),
        tags=_tags(item.keyword),
    )
    attachment, content = _attachment(item.attachments, base)
    record = ImportRecord(
        ordinal=ordinal,
        outcome=outcome_of(fields),
        fields=fields,
        record_sha256=digest,
        attachment=attachment,
        flags=flags,
    )
    return record, content


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WS.sub(" ", value).strip()
    return cleaned or None


def _name(name: _Name) -> str | None:
    if name.literal:
        return _clean(name.literal)
    family, given = _clean(name.family), _clean(name.given)
    if family and given:
        return f"{family}, {given}"
    return family or given


def _year(issued: _Date | None) -> int | None:
    if issued is None:
        return None
    if issued.date_parts and issued.date_parts[0]:
        first = issued.date_parts[0][0]
        match = _YEAR.search(str(first))
        if match:
            return int(match.group(1))
    match = _YEAR.search(issued.raw or issued.literal or "")
    return int(match.group(1)) if match else None


def _arxiv(item: _Item, doi: str | None) -> str | None:
    """From `number` when the publisher is arXiv, else from the URL, else a DataCite DOI."""
    if (item.publisher or "").strip().casefold() == "arxiv" and item.number is not None:
        match = _ARXIV_NUMBER.fullmatch(str(item.number).strip())
        if match:
            return normalize_arxiv(match.group(1))
    if item.url and (match := _ARXIV_URL.search(item.url.strip())):
        return normalize_arxiv(match.group(1))
    return arxiv_id_from_doi(doi) if doi else None


def _tags(keyword: str | list[str] | None) -> list[str]:
    if keyword is None:
        return []
    parts = keyword if isinstance(keyword, list) else _LIST_SEP.split(keyword)
    return [p for p in parts if p.strip()]


def _attachment(
    refs: list[_AttachmentRef], base: Path | None
) -> tuple[Attachment | None, bytes | None]:
    for ref in refs:
        mime = (ref.mime_type or ref.content_type or "").casefold()
        path = (ref.path or "").strip()
        if path and (mime == _PDF or path.casefold().endswith(".pdf")):
            return read_attachment(path, base)
    return None, None
