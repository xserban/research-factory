"""Researcher-supplied import: folder PDFs matched to promoted works (ruling 7; IDEA-56).

`import_folder` takes every `*.pdf` under a folder, in sorted path order. Files are matched to
**canonical** works: every corpus record maps to the primary of the active merge that absorbed it,
and a canonical work carries the identifiers of all its records. A file is matched, in order, by:

1. its filename, when the stem is a work id without `rf:` (the researcher's own naming);
2. the identifiers it carries: its filename first, and only if that yields none, the text of its
   first page (`pypdf`). An identifier is an arXiv id or a DOI, and both resolve through their
   normalised forms, so a DataCite arXiv DOI and a bare arXiv id name the same work;
3. when the file carries no identifier at all, the title of a promoted canonical work found on its
   opening pages (titles of at least `MIN_TITLE_TOKENS` normalised tokens only).

Each file lands in exactly one list of the report:
- `not_pdf`: the bytes carry no PDF header.
- `unmatched`: no canonical work matches.
- `ambiguous`: more than one canonical work does; `candidates` names them.
- `not_promoted`: the one matching canonical work did not pass title/abstract screening.
- `identity_unchecked`: the match came from first-page text (an identifier that may be a
  citation, IDEA-26, when the work's title is not on that page; or a title match) and the
  researcher has not vouched for it. `candidates` names the work; `accept` names the files the
  researcher vouches for. A filename identifier or work id is the researcher's own naming and is
  not checked.
- `already_imported`: the file's bytes already back a document of that work. No event is written.
- `imported`: a document was recorded, with its attempt, as `(file, work, document)`; the work is
  always canonical.

Invariants:
- Nothing is written for a file that is not imported. Imported bytes go to the project library only,
  never to `blobs/`.
- A title match is never imported without the researcher's `accept`. A title counts as found when
  it, or its leading `PREFIX_SHARE` of tokens (at least `MIN_PREFIX_TOKENS`), is on the opening
  pages.
- Two records of one canonical work never make a file ambiguous.
- The actor is the researcher (`project.human_actor()`), and the source version is
  `file:<first 12 hex digits of the sha256>`.
- Identifier sniffing is advisory and reads no more than page 1; the title checks read the first
  `TITLE_PAGES` pages. A reader failure means no identifiers and no title, never an error.
  `sniff_identifiers` lives in `factory.imports.pdfs` (slice 3d) and is re-exported here.
"""

from __future__ import annotations

import hashlib
import io
import math
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field
from pypdf import PdfReader

from factory.errors import FactoryValidationError, ValidationIssue
from factory.imports.pdfs import Source as Source
from factory.imports.pdfs import canonical_doi_key
from factory.imports.pdfs import sniff_identifiers as sniff_identifiers
from factory.model.base import StrictModel
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv, normalize_title
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.fulltext import record_supplied_document
from factory.services.search import list_works

_PDF_HEADER = b"%PDF-"
_HEADER_WINDOW = 1024
_MEDIA_TYPE = "application/pdf"
_SOURCE_PREFIX = "file:"
_SOURCE_DIGITS = 12
_WORK_PREFIX = "rf:"
MIN_TITLE_TOKENS = 4
"""A title shorter than this is too generic to identify a file by its opening pages."""
PREFIX_SHARE = 0.6
MIN_PREFIX_TOKENS = 6
TITLE_PAGES = 2
"""Title checks read this many pages: a cover or copyright page may come before the title."""
"""A cover page may cut a long title: its leading `PREFIX_SHARE` of tokens (at least
`MIN_PREFIX_TOKENS`) found on the page also count as the title."""


class ImportReport(StrictModel):
    """Where each file of one import landed. Every list holds file basenames, except `imported`.

    `candidates` maps an `ambiguous` or `identity_unchecked` file to the canonical works it
    matched, sorted."""

    imported: list[tuple[str, str, str]] = Field(default_factory=list)
    already_imported: list[str] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    not_promoted: list[str] = Field(default_factory=list)
    not_pdf: list[str] = Field(default_factory=list)
    identity_unchecked: list[str] = Field(default_factory=list)
    candidates: dict[str, list[str]] = Field(default_factory=dict)


@dataclass(frozen=True)
class _Corpus:
    """The corpus as canonical works: keys and titles of all records, promotion of the work."""

    canonical: Mapping[str, str]
    """Every record id to its canonical work id (itself when no merge absorbed it)."""
    keys: Mapping[str, frozenset[str]]
    titles: Mapping[str, tuple[str, ...]]
    """Normalised titles of every record of a canonical work."""
    promoted: frozenset[str]

    def by_identifiers(self, identifiers: Collection[str]) -> set[str]:
        wanted = set(identifiers)
        return {work for work, keys in self.keys.items() if keys & wanted}

    def title_on(self, work: str, page: str) -> bool:
        return any(_title_found(title, page) for title in self.titles.get(work, ()))

    def by_title(self, page: str) -> set[str]:
        return {
            work
            for work in self.promoted
            for title in self.titles.get(work, ())
            if len(title.split()) >= MIN_TITLE_TOKENS and _title_found(title, page)
        }


def _title_found(title: str, page: str) -> bool:
    """Whether a normalised title, or its leading share of tokens, occurs on a normalised page."""
    if not title or not page:
        return False
    if title in page:
        return True
    tokens = title.split()
    size = max(MIN_PREFIX_TOKENS, math.ceil(PREFIX_SHARE * len(tokens)))
    return len(tokens) > size and " ".join(tokens[:size]) in page


def import_folder(project: Project, folder: Path, *, accept: Collection[str] = ()) -> ImportReport:
    """Import every PDF under `folder` that matches exactly one promoted canonical work.

    `accept` holds file names the researcher vouches for, listed earlier as `identity_unchecked`.
    Raises `FactoryValidationError` with nothing written if `folder` is not a directory.
    """
    if not folder.is_dir():
        raise FactoryValidationError([ValidationIssue("folder", "not a directory")])
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    report = ImportReport()
    with project.index.exclusive():
        project.index.sync()
        corpus = _corpus(project, list_works(project))

    for path in files:
        _import_file(project, path, corpus, set(accept), report)
    return report


def _corpus(project: Project, works: list[Work]) -> _Corpus:
    primary_of = {
        absorbed: merge.primary for merge in active_merges(project) for absorbed in merge.absorbed
    }
    canonical = {work.id: primary_of.get(work.id, work.id) for work in works}
    keys: dict[str, set[str]] = defaultdict(set)
    titles: dict[str, list[str]] = defaultdict(list)
    for work in works:
        keys[canonical[work.id]] |= _work_identifiers(work)
        titles[canonical[work.id]].append(normalize_title(work.title))
    promoted = frozenset(
        work
        for work, outcome in final_outcomes(project).items()
        if outcome is Outcome.INCLUDED and canonical.get(work, work) == work
    )
    return _Corpus(
        canonical=canonical,
        keys={work: frozenset(k) for work, k in keys.items()},
        titles={work: tuple(t) for work, t in titles.items()},
        promoted=promoted,
    )


def _import_file(
    project: Project, path: Path, corpus: _Corpus, accept: set[str], report: ImportReport
) -> None:
    """Decide one file's place in the report, and record it if it is imported."""
    name = path.name
    data = path.read_bytes()
    if _PDF_HEADER not in data[:_HEADER_WINDOW]:
        report.not_pdf.append(name)
        return

    named = corpus.canonical.get(_WORK_PREFIX + _stem(name))
    checked = False  # whether the match must be vouched for or title-checked
    title_match = False
    if named is not None:
        matches = {named}
    else:
        identifiers, source = sniff_identifiers(path)
        matches = corpus.by_identifiers(identifiers)
        checked = source == "first-page"
        if not identifiers:
            matches = corpus.by_title(_opening(data))
            checked = title_match = bool(matches)

    if not matches:
        report.unmatched.append(name)
        return
    if len(matches) > 1:
        report.ambiguous.append(name)
        report.candidates[name] = sorted(matches)
        return
    (work_id,) = matches
    if work_id not in corpus.promoted:
        report.not_promoted.append(name)
        return
    if (
        checked
        and name not in accept
        and (title_match or not corpus.title_on(work_id, _opening(data)))
    ):
        report.identity_unchecked.append(name)
        report.candidates[name] = [work_id]
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


def _stem(name: str) -> str:
    return name[: -len(".pdf")] if name.lower().endswith(".pdf") else name


def _opening(data: bytes) -> str:
    """The normalised text of the first `TITLE_PAGES` pages; empty on a reader failure."""
    try:
        pages = PdfReader(io.BytesIO(data)).pages[:TITLE_PAGES]
        text = " ".join(page.extract_text() or "" for page in pages)
    # pypdf raises many exception types on damaged input, and none of them is fatal here.
    except Exception:
        return ""
    return normalize_title(text)


def _work_identifiers(work: Work) -> frozenset[str]:
    """A corpus work's canonical identifiers, in the same form `sniff_identifiers` returns."""
    keys: set[str] = set()
    if work.identifiers.doi:
        keys.add(canonical_doi_key(work.identifiers.doi))
    if work.identifiers.arxiv:
        keys.add(f"arxiv:{normalize_arxiv(work.identifiers.arxiv)}")
    return frozenset(keys)
