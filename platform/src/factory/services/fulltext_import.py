"""Researcher-supplied import: folder PDFs matched to promoted works by identifier (ruling 7).

`import_folder` takes every `*.pdf` under a folder, in sorted path order. A file is matched on the
identifiers it carries: its filename first, and only if that yields none, the text of its first
page (`pypdf`). An identifier is an arXiv id or a DOI, and both resolve to corpus works through
their normalised forms, so a DataCite arXiv DOI and a bare arXiv id name the same work.

Each file lands in exactly one list of the report:
- `not_pdf`: the bytes carry no PDF header.
- `unmatched`: no corpus work carries the file's identifiers.
- `ambiguous`: more than one corpus work does.
- `not_promoted`: the one matching work did not pass title/abstract screening.
- `already_imported`: the file's bytes already back a document of that work. No event is written.
- `imported`: a document was recorded, with its attempt, as `(file, work, document)`.

Invariants:
- Nothing is written for a file that is not imported. Imported bytes go to the project library only,
  never to `blobs/`.
- The actor is the researcher (`project.human_actor()`), and the source version is
  `file:<first 12 hex digits of the sha256>`.
- Identifier sniffing is advisory. It reads no more than page 1, and a reader failure means no
  identifiers, never an error.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import Field
from pypdf import PdfReader

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.work import Work
from factory.model.work_ids import arxiv_id_from_doi, normalize_arxiv, normalize_doi
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.fulltext import record_supplied_document
from factory.services.search import list_works

Source = Literal["filename", "first-page", "none"]

_PDF_HEADER = b"%PDF-"
_HEADER_WINDOW = 1024
_MEDIA_TYPE = "application/pdf"
_SOURCE_PREFIX = "file:"
_SOURCE_DIGITS = 12

# A new-style arXiv id, not preceded by a digit or dot, so `10.48550_arXiv.2301.01234` is left to
# the DOI pattern, and the id's version suffix is optional.
_FILE_ARXIV = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", re.IGNORECASE)
_FILE_DOI = re.compile(r"(?<![\w.])10\.\d{4,9}_\S+")
_TEXT_ARXIV = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", re.IGNORECASE)
_TEXT_DOI = re.compile(r"(?<![\w.])10\.\d{4,9}/[^\s\"<>]+")
_TRAILING_PUNCTUATION = ".,;:)]}"


class ImportReport(StrictModel):
    """Where each file of one import landed. Every list holds file basenames, except `imported`."""

    imported: list[tuple[str, str, str]] = Field(default_factory=list)
    already_imported: list[str] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    not_promoted: list[str] = Field(default_factory=list)
    not_pdf: list[str] = Field(default_factory=list)


def sniff_identifiers(path: Path) -> tuple[set[str], Source]:
    """The normalised identifiers a PDF names, and where they were found.

    Identifiers are `arxiv:<id>` and `doi:<doi>`. A DOI that DataCite minted for an arXiv preprint
    is returned as its `arxiv:` form. The filename is read first; page 1's text is read only if the
    filename yields nothing. A reader failure yields `(set(), "none")`.
    """
    from_name = _identifiers_in(_FILE_ARXIV, _FILE_DOI, _file_stem(path.name), underscore=True)
    if from_name:
        return from_name, "filename"
    try:
        text = PdfReader(path).pages[0].extract_text() or ""
    # pypdf raises many exception types on damaged input, and none of them is fatal here.
    except Exception:
        return set(), "none"
    from_text = _identifiers_in(_TEXT_ARXIV, _TEXT_DOI, text, underscore=False)
    return (from_text, "first-page") if from_text else (set(), "none")


def import_folder(project: Project, folder: Path) -> ImportReport:
    """Import every PDF under `folder` that matches exactly one promoted corpus work.

    Raises `FactoryValidationError` with nothing written if `folder` is not a directory.
    """
    if not folder.is_dir():
        raise FactoryValidationError([ValidationIssue("folder", "not a directory")])
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    report = ImportReport()
    with project.index.exclusive():
        project.index.sync()
        corpus = [(work.id, _work_identifiers(work)) for work in list_works(project)]
        promoted = {
            w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
        }

    for path in files:
        _import_file(project, path, corpus, promoted, report)
    return report


def _import_file(
    project: Project,
    path: Path,
    corpus: list[tuple[str, frozenset[str]]],
    promoted: set[str],
    report: ImportReport,
) -> None:
    """Decide one file's place in the report, and record it if it is imported."""
    name = path.name
    data = path.read_bytes()
    if _PDF_HEADER not in data[:_HEADER_WINDOW]:
        report.not_pdf.append(name)
        return
    identifiers, _ = sniff_identifiers(path)
    matches = [work_id for work_id, keys in corpus if keys & identifiers]
    if not matches:
        report.unmatched.append(name)
        return
    if len(matches) > 1:
        report.ambiguous.append(name)
        return
    work_id = matches[0]
    if work_id not in promoted:
        report.not_promoted.append(name)
        return

    digest = hashlib.sha256(data).hexdigest()
    with project.index.exclusive():
        project.index.sync()
        document_id = record_supplied_document(
            project,
            work_id,
            content=data,
            source_version=f"{_SOURCE_PREFIX}{digest[:_SOURCE_DIGITS]}",
            media_type=_MEDIA_TYPE,
            actor=project.human_actor(),
        )
    if document_id is None:
        report.already_imported.append(name)
    else:
        report.imported.append((name, work_id, document_id))


def _work_identifiers(work: Work) -> frozenset[str]:
    """A corpus work's canonical identifiers, in the same form `sniff_identifiers` returns."""
    keys: set[str] = set()
    if work.identifiers.doi:
        keys.add(_canonical_doi(work.identifiers.doi))
    if work.identifiers.arxiv:
        keys.add(f"arxiv:{normalize_arxiv(work.identifiers.arxiv)}")
    return frozenset(keys)


def _canonical_doi(doi: str) -> str:
    """`arxiv:<id>` for a DataCite arXiv DOI, else `doi:<doi>`."""
    bridged = arxiv_id_from_doi(doi)
    return f"arxiv:{bridged}" if bridged else f"doi:{normalize_doi(doi)}"


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
        found.add(f"arxiv:{normalize_arxiv(match.group(1))}")
    for match in doi.finditer(text):
        raw = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        found.add(_canonical_doi(raw.replace("_", "/") if underscore else raw))
    return found


def _file_stem(name: str) -> str:
    return name[: -len(".pdf")] if name.lower().endswith(".pdf") else name
