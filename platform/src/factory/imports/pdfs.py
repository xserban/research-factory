"""A folder of PDFs read as an import, and the identifier sniffing it shares with plan 2A.

`sniff_identifiers` moved here from `services/fulltext_import.py`, which re-exports it.

Invariants of `parse_pdf_folder`:
- One record per `*.pdf` file under the folder (recursively), in sorted path order.
- `record_sha256` is the file's bytes hash; the attachment is the file itself, known by the hash
  of its path relative to the folder and its content hash.
- Each file is read from disk once; the record hash, identifier sniffing (filename, else page 1)
  and the metadata title all use those bytes. Page-1 text is read in memory and never returned.
- A file without a PDF header is `malformed`, flagged `not-pdf`.
- A junk metadata title is dropped and the record flagged `title-metadata-rejected`.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pypdf
from pypdf import PdfReader

from factory.imports.attachments import sha256_hex
from factory.imports.model import (
    NOT_PDF,
    TITLE_METADATA_REJECTED,
    Attachment,
    ImportFormat,
    ImportFormatError,
    ImportRecord,
    ParsedImport,
    ParseOutcome,
    bounded_fields,
    outcome_of,
)
from factory.model.work_ids import (
    TRAILING_PUNCTUATION,
    arxiv_id_from_doi,
    normalize_arxiv,
    normalize_doi,
    normalize_title,
)

PARSER = "pypdf"
PARSER_VERSION = f"{pypdf.__version__}+rf2"

Source = Literal["filename", "first-page", "none"]

_PDF_HEADER = b"%PDF-"
_HEADER_WINDOW = 1024
_WS = re.compile(r"\s+")
_MIN_TITLE = 8
_HINT_MAX = 200
# What authoring tools leave in the title field: an application stamp, a file name, a placeholder.
_JUNK_TITLE = re.compile(
    r"^(?:microsoft word\b.*|.*\.(?:docx?|tex|pdf|dvi|indd)"
    r"|untitled[\s_-]*\d*|(?:title|document|paper|manuscript)[\s_-]*\d*)$",
    re.IGNORECASE,
)

# A new-style arXiv id, not preceded by a digit or dot, so `10.48550_arXiv.2301.01234` is left to
# the DOI pattern, and the id's version suffix is optional.
_FILE_ARXIV = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", re.IGNORECASE)
_FILE_DOI = re.compile(r"(?<![\w.])10\.\d{4,9}_\S+")
_TEXT_ARXIV = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", re.IGNORECASE)
_TEXT_DOI = re.compile(r"(?<![\w.])10\.\d{4,9}/[^\s\"<>]+")
_ARXIV_KEY = "arxiv:"
_DOI_KEY = "doi:"


def sniff_identifiers(path: Path) -> tuple[set[str], Source]:
    """The normalised identifiers a PDF names, and where they were found.

    Identifiers are `arxiv:<id>` and `doi:<doi>`. A DOI that DataCite minted for an arXiv preprint
    is returned as its `arxiv:` form. The filename is read first; page 1's text is read only if the
    filename yields nothing. A reader failure yields `(set(), "none")`.
    """
    return _sniff(path.name, lambda: PdfReader(path))


def _sniff(name: str, reader: Callable[[], PdfReader]) -> tuple[set[str], Source]:
    """`sniff_identifiers` over a file name and a reader of its bytes, opened only if needed."""
    from_name = _identifiers_in(_FILE_ARXIV, _FILE_DOI, _file_stem(name), underscore=True)
    if from_name:
        return from_name, "filename"
    try:
        text = reader().pages[0].extract_text() or ""
    # pypdf raises many exception types on damaged input, and none of them is fatal here.
    except Exception:
        return set(), "none"
    from_text = _identifiers_in(_TEXT_ARXIV, _TEXT_DOI, text, underscore=False)
    return (from_text, "first-page") if from_text else (set(), "none")


def title_on_first_page(data: bytes, title: str) -> bool:
    """Whether `title`, normalised, occurs in the normalised text of the PDF's first page. The text
    is read in memory and dropped; a reader failure is a failed check."""
    wanted = normalize_title(title)
    if not wanted:
        return False
    try:
        page = PdfReader(io.BytesIO(data)).pages[0].extract_text() or ""
    # pypdf raises many exception types on damaged input, and none of them is fatal here.
    except Exception:
        return False
    return wanted in normalize_title(page)


def canonical_doi_key(doi: str) -> str:
    """`arxiv:<id>` for a DataCite arXiv DOI, else `doi:<doi>`."""
    bridged = arxiv_id_from_doi(doi)
    return f"{_ARXIV_KEY}{bridged}" if bridged else f"{_DOI_KEY}{normalize_doi(doi)}"


def parse_pdf_folder(folder: Path) -> ParsedImport:
    """One import record per PDF under `folder`. Raises `ImportFormatError` if not a directory."""
    if not folder.is_dir():
        raise ImportFormatError("not a directory")
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    records: list[ImportRecord] = []
    attachment_bytes: dict[str, bytes] = {}
    local_paths: dict[int, str] = {}
    for ordinal, path in enumerate(files, start=1):
        data = path.read_bytes()
        local_paths[ordinal] = path.relative_to(folder).as_posix()
        digest = sha256_hex(data)
        if _PDF_HEADER not in data[:_HEADER_WINDOW]:
            records.append(
                ImportRecord(
                    ordinal=ordinal,
                    outcome=ParseOutcome.MALFORMED,
                    fields=None,
                    record_sha256=digest,
                    flags=(NOT_PDF,),
                )
            )
            continue
        records.append(_record(ordinal, path, folder, data, digest))
        attachment_bytes[digest] = data
    return ParsedImport(
        format=ImportFormat.PDFS,
        parser=PARSER,
        parser_version=PARSER_VERSION,
        records=tuple(records),
        attachment_bytes=attachment_bytes,
        local_paths=local_paths,
    )


def _record(ordinal: int, path: Path, folder: Path, data: bytes, digest: str) -> ImportRecord:
    """One PDF's record, from the one read of its bytes (the file is not opened again)."""
    identifiers, _ = _sniff(path.name, lambda: PdfReader(io.BytesIO(data)))
    arxiv = _first(identifiers, _ARXIV_KEY)
    stated = _metadata_title(data)
    title = None if stated is None or is_junk_title(stated) else stated
    fields, flags = bounded_fields(
        title=title,
        authors=[],
        year=None,
        doi=_first(identifiers, _DOI_KEY),
        arxiv=arxiv,
        url=None,
        venue=None,
        type="preprint" if arxiv else "other",
        abstract=None,
        tags=[],
    )
    relative = path.relative_to(folder).as_posix()
    return ImportRecord(
        ordinal=ordinal,
        outcome=outcome_of(fields),
        fields=fields,
        record_sha256=digest,
        attachment=Attachment(
            path_sha256=sha256_hex(relative.encode("utf-8")), content_sha256=digest
        ),
        flags=(*flags, TITLE_METADATA_REJECTED) if stated and title is None else flags,
    )


def _first(identifiers: set[str], prefix: str) -> str | None:
    found = sorted(i[len(prefix) :] for i in identifiers if i.startswith(prefix))
    return found[0] if found else None


def is_junk_title(title: str) -> bool:
    """Whether a PDF's metadata title says nothing of the work: too short, without letters, or left
    by an authoring tool. A guess at the true title is never made here."""
    return (
        len(title) < _MIN_TITLE
        or not any(c.isalpha() for c in title)
        or _JUNK_TITLE.match(title) is not None
    )


def first_page_hint(data: bytes) -> str | None:
    """The first non-empty line of page 1, shortened, for the researcher to read. It is never
    stored and never becomes a title (PD-2). A reader failure gives None."""
    try:
        text = PdfReader(io.BytesIO(data)).pages[0].extract_text() or ""
    # pypdf raises many exception types on damaged input, and none of them is fatal here.
    except Exception:
        return None
    line = next((_WS.sub(" ", raw).strip() for raw in text.splitlines() if raw.strip()), "")
    return line[:_HINT_MAX] or None


def _metadata_title(data: bytes) -> str | None:
    try:
        metadata = PdfReader(io.BytesIO(data)).metadata
        title = metadata.title if metadata is not None else None
    # A damaged PDF's metadata is advisory; any reader failure means no title.
    except Exception:
        return None
    if not isinstance(title, str):
        return None
    cleaned = _WS.sub(" ", title).strip()
    return cleaned or None


def _identifiers_in(
    arxiv: re.Pattern[str], doi: re.Pattern[str], text: str, *, underscore: bool
) -> set[str]:
    """Every arXiv id and DOI in `text`, normalised.

    `underscore` says that `_` stands for `/` in a DOI, as it must in a filename. An arXiv id is
    recognised by its pattern in a filename, but only after `arXiv:` in running text, to keep page
    numbers and dates from matching.
    """
    found: set[str] = set()
    for match in arxiv.finditer(text):
        found.add(f"{_ARXIV_KEY}{normalize_arxiv(match.group(1))}")
    for match in doi.finditer(text):
        raw = match.group(0).rstrip(TRAILING_PUNCTUATION)
        found.add(canonical_doi_key(raw.replace("_", "/") if underscore else raw))
    return found


def _file_stem(name: str) -> str:
    return name[: -len(".pdf")] if name.lower().endswith(".pdf") else name
