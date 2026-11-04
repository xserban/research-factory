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
  identifiers, never an error. `sniff_identifiers` lives in `factory.imports.pdfs` (slice 3d)
  and is re-exported here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from factory.errors import FactoryValidationError, ValidationIssue
from factory.imports.pdfs import Source as Source
from factory.imports.pdfs import canonical_doi_key
from factory.imports.pdfs import sniff_identifiers as sniff_identifiers
from factory.model.base import StrictModel
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.fulltext import record_supplied_document
from factory.services.search import list_works

_PDF_HEADER = b"%PDF-"
_HEADER_WINDOW = 1024
_MEDIA_TYPE = "application/pdf"
_SOURCE_PREFIX = "file:"
_SOURCE_DIGITS = 12


class ImportReport(StrictModel):
    """Where each file of one import landed. Every list holds file basenames, except `imported`."""

    imported: list[tuple[str, str, str]] = Field(default_factory=list)
    already_imported: list[str] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    not_promoted: list[str] = Field(default_factory=list)
    not_pdf: list[str] = Field(default_factory=list)


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
        keys.add(canonical_doi_key(work.identifiers.doi))
    if work.identifiers.arxiv:
        keys.add(f"arxiv:{normalize_arxiv(work.identifiers.arxiv)}")
    return frozenset(keys)
