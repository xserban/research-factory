"""Verification of an interpretation's sources, and stale-source detection (slice 3c, G3-A).

Invariants:
- A quote source names a corpus work, a conversion of that work whose document is not superseded
  at write time, an anchor of the conversion and a quote that is verbatim in the anchor's element
  (the slice-2 check, `quote_in_element`). The document is pinned: its id is computed and stored.
- A citation source names a G1 reference entry of a live extraction (stored with the entry's link
  state and resolved work; an `unresolved` entry is accepted and labelled) or a corpus work.
- Verification is all-or-nothing: `stored` is empty when any source has an issue, and every issue
  is reported, located at `<field>[i].<attr>` with a reason from a fixed vocabulary. No reason or
  message carries document text.
- Staleness is never stored: `stale_sources` reads, for the interpretations that are not
  superseded, the quote sources whose document has since been superseded (spec ruling 9).
This module reads the index and the library and writes nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text

from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.intuition import (
    CitationSourceInput,
    QuoteSourceInput,
    SourceInput,
    StoredSource,
)
from factory.services.context import Project
from factory.services.conversions import conversion_manifest, conversion_of
from factory.services.fulltext import document_superseded
from factory.services.reference_view import is_live_reference_extraction, reference_view_of
from factory.services.search import works_by_ids

WORK_UNKNOWN = "work-unknown"
CONVERSION_UNKNOWN = "conversion-unknown"
CONVERSION_UNREADABLE = "conversion-unreadable"
CONVERSION_NOT_OF_WORK = "conversion-not-of-work"
DOCUMENT_SUPERSEDED = "document-superseded"
ANCHOR_UNKNOWN = "anchor-unknown"
QUOTE_NOT_IN_ANCHOR = "quote-not-in-anchor"
EXTRACTION_NOT_LIVE = "extraction-not-live"
ENTRY_UNKNOWN = "entry-unknown"


@dataclass(frozen=True)
class SourceVerdict:
    stored: tuple[StoredSource, ...]
    issues: list[ValidationIssue]


def verify_sources(
    project: Project, sources: Sequence[SourceInput], *, field: str = "sources"
) -> SourceVerdict:
    """Verify every source; all-or-nothing (see the module docstring)."""
    project.index.sync()
    issues: list[ValidationIssue] = []
    stored: list[StoredSource] = []
    for index, source in enumerate(sources):
        where = f"{field}[{index}]"
        if isinstance(source, QuoteSourceInput):
            result = _verify_quote(project, source, where, issues)
        else:
            result = _verify_citation(project, source, where, issues)
        if result is not None:
            stored.append(result)
    if issues:
        return SourceVerdict((), issues)
    return SourceVerdict(tuple(stored), [])


def _is_corpus_work(project: Project, work_id: str) -> bool:
    return bool(works_by_ids(project, [work_id]))


def _verify_quote(
    project: Project, source: QuoteSourceInput, where: str, issues: list[ValidationIssue]
) -> StoredSource | None:
    if not _is_corpus_work(project, source.work_id):
        issues.append(ValidationIssue(f"{where}.work_id", WORK_UNKNOWN))
        return None
    conversion = conversion_of(project, source.conversion_id)
    if conversion is None:
        issues.append(ValidationIssue(f"{where}.conversion_id", CONVERSION_UNKNOWN))
        return None
    if conversion.work_id != source.work_id:
        issues.append(ValidationIssue(f"{where}.conversion_id", CONVERSION_NOT_OF_WORK))
        return None
    if document_superseded(project, conversion.document_id):
        issues.append(ValidationIssue(f"{where}.conversion_id", DOCUMENT_SUPERSEDED))
        return None
    try:
        manifest = conversion_manifest(project, source.conversion_id)
    except FactoryValidationError:
        issues.append(ValidationIssue(f"{where}.conversion_id", CONVERSION_UNREADABLE))
        return None
    anchor = manifest.get(source.anchor)
    if anchor is None:
        issues.append(ValidationIssue(f"{where}.anchor", ANCHOR_UNKNOWN))
        return None
    if not quote_in_element(anchor.text, source.quote):
        issues.append(ValidationIssue(f"{where}.quote", QUOTE_NOT_IN_ANCHOR))
        return None
    return StoredSource(
        kind="quote",
        role=source.role,
        work_id=source.work_id,
        conversion_id=source.conversion_id,
        anchor=source.anchor,
        quote=source.quote,
        document_id=conversion.document_id,
    )


def _verify_citation(
    project: Project, source: CitationSourceInput, where: str, issues: list[ValidationIssue]
) -> StoredSource | None:
    if source.reference is not None:
        extraction_id = source.reference.rpartition(":")[0]
        if not is_live_reference_extraction(project, extraction_id):
            issues.append(ValidationIssue(f"{where}.reference", EXTRACTION_NOT_LIVE))
            return None
        link = entry_link(project, source.reference)
        if link is None:
            issues.append(ValidationIssue(f"{where}.reference", ENTRY_UNKNOWN))
            return None
        return StoredSource(
            kind="citation",
            role=source.role,
            reference=source.reference,
            link_state=link[0],
            resolved_work=link[1],
        )
    assert source.work_id is not None
    if not _is_corpus_work(project, source.work_id):
        issues.append(ValidationIssue(f"{where}.work_id", WORK_UNKNOWN))
        return None
    return StoredSource(kind="citation", role=source.role, work_id=source.work_id)


def entry_link(project: Project, entry_key: str) -> tuple[str, str | None] | None:
    """The link state and resolved work of the reference entry `rex_…:n`; None when the
    extraction or the entry is unknown."""
    extraction_id, _, ordinal = entry_key.rpartition(":")
    view = reference_view_of(project, extraction_id)
    if view is None or not ordinal.isdigit():
        return None
    entry = view.entry(int(ordinal))
    if entry is None:
        return None
    return entry.link_state.value, entry.link_work


def stale_sources(project: Project) -> dict[str, tuple[str, ...]]:
    """Interpretation id -> the documents of its quote sources that have since been superseded,
    for the interpretations that are not themselves superseded. One indexed join."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT i.interpretation_id, s.document_id FROM interpretation_sources s "
                "JOIN interpretations i ON i.interpretation_id = s.interpretation_id "
                "JOIN fulltext_documents d ON d.document_id = s.document_id "
                "WHERE i.superseded_by IS NULL AND d.superseded_by IS NOT NULL "
                "ORDER BY i.interpretation_id, s.document_id"
            )
        ).all()
    out: dict[str, list[str]] = {}
    for interpretation_id, document_id in found:
        out.setdefault(str(interpretation_id), [])
        if str(document_id) not in out[str(interpretation_id)]:
            out[str(interpretation_id)].append(str(document_id))
    return {k: tuple(v) for k, v in out.items()}
