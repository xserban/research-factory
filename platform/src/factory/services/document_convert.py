"""Document conversion: raw retrieved documents to canonical Markdown with an anchor manifest.

`convert_documents` converts the live (not superseded) documents of promoted works, or the named
documents or works. Each document is decided and recorded on its own, so a crash keeps the work
already done.

Invariants:
- Validation is complete before anything is written. A refused request writes nothing.
- Per document, under the write lock: a missing raw blob gives `raw-missing` with no event; a
  missing converter, an unavailable tool or a failed conversion records one
  `document.conversion_failed` event; a successful conversion records one `document.converted`
  event. A document whose converter version already has a conversion gives `unchanged`, with no
  event and no blob.
- Conversion events carry hashes, counts and warnings, never document text. A failure carries the
  exception class name only, never its message.
- The Markdown and manifest bytes go to the project library. The stored Markdown hash equals
  `ConversionResult.markdown_hash`, and the manifest hash is the hash of `manifest.to_json()`.
- A batch continues past a failed document. Each document's events are one `project.record` call.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.document.anchors import AnchorKind
from factory.document.converter import (
    ConversionResult,
    Converter,
    ConverterUnavailable,
    convert,
)
from factory.document.registry import ConverterRegistry
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.document import (
    WARNING_MAX_CHARS,
    WARNINGS_MAX,
    ConversionFailed,
    Converted,
    FailureReason,
)
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project

ConversionStatus = Literal["converted", "unchanged", "failed", "raw-missing"]


class ConversionOutcome(StrictModel):
    """What happened to one document. `conversion_id` is set only for `converted`; `reason` is
    the failure reason for `failed` and None otherwise."""

    document_id: str
    work_id: str
    status: ConversionStatus
    conversion_id: str | None
    reason: str | None


class ConvertSummary(StrictModel):
    """One outcome per document, in event order, and the count of each status."""

    outcomes: list[ConversionOutcome]
    converted: int
    unchanged: int
    failed: int
    raw_missing: int


@dataclass(frozen=True)
class _Doc:
    """A live document as the projection holds it, with what a conversion needs."""

    document_id: str
    work_id: str
    raw_hash: str
    media_type: str


def convert_documents(
    project: Project,
    registry: ConverterRegistry,
    *,
    work_ids: Sequence[str] | None = None,
    document_ids: Sequence[str] | None = None,
) -> ConvertSummary:
    """Convert the documents in scope and record each outcome.

    With neither argument, the scope is the live documents of promoted works. `work_ids` limits
    the scope to the live documents of the named works, which must be promoted. `document_ids`
    limits it to the named documents, which must be live. Both together intersect.

    Raises `FactoryValidationError` (issues on `work_ids` or `document_ids`) with nothing written
    if a named work is not promoted or a named document is unknown or superseded.
    """
    with project.index.exclusive():
        project.index.sync()
        targets = _targets(project, work_ids, document_ids)
    outcomes = [_convert_one(project, registry, doc) for doc in targets]
    return _summary(outcomes)


# --- Scope (validated before any write) ---


def _targets(
    project: Project, work_ids: Sequence[str] | None, document_ids: Sequence[str] | None
) -> list[_Doc]:
    live = _live_documents(project)
    promoted = _promoted(project)
    issues: list[ValidationIssue] = []
    if work_ids is not None:
        issues += [
            ValidationIssue("work_ids", f"{work}: not promoted at title/abstract")
            for work in sorted(set(work_ids))
            if work not in promoted
        ]
    if document_ids is not None:
        known = {doc.document_id for doc in live}
        issues += [
            ValidationIssue("document_ids", f"{doc}: unknown or superseded")
            for doc in sorted(set(document_ids))
            if doc not in known
        ]
    if issues:
        raise FactoryValidationError(issues)

    if work_ids is None and document_ids is None:
        return [doc for doc in live if doc.work_id in promoted]
    selected = live
    if work_ids is not None:
        wanted_works = set(work_ids)
        selected = [doc for doc in selected if doc.work_id in wanted_works]
    if document_ids is not None:
        wanted_docs = set(document_ids)
        selected = [doc for doc in selected if doc.document_id in wanted_docs]
    return selected


def _promoted(project: Project) -> frozenset[str]:
    return frozenset(
        work for work, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _live_documents(project: Project) -> list[_Doc]:
    """Every live document in event order. Requires a synced index."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT document_id, work_id, raw_hash, media_type FROM fulltext_documents "
                    "WHERE superseded_by IS NULL ORDER BY event_id"
                )
            )
            .mappings()
            .all()
        )
    return [
        _Doc(
            document_id=str(row["document_id"]),
            work_id=str(row["work_id"]),
            raw_hash=str(row["raw_hash"]),
            media_type=str(row["media_type"]),
        )
        for row in rows
    ]


# --- One document (under the write lock, so the decision and its record cannot interleave) ---


def _convert_one(project: Project, registry: ConverterRegistry, doc: _Doc) -> ConversionOutcome:
    with project.index.exclusive():
        project.index.sync()
        if not project.library.exists(doc.raw_hash):
            return _outcome(doc, "raw-missing")
        converter = registry.for_media_type(doc.media_type)
        if converter is None:
            return _failed(project, doc, None, FailureReason.NO_CONVERTER, None)
        try:
            version = converter.version()
        except ConverterUnavailable:
            return _failed(project, doc, converter.name, FailureReason.CONVERTER_UNAVAILABLE, None)
        if _converted_before(project, doc.document_id, converter, version):
            return _outcome(doc, "unchanged")
        raw = project.library.get(doc.raw_hash)
        try:
            result = convert(converter, raw, doc.media_type)
        except ConverterUnavailable:
            return _failed(project, doc, converter.name, FailureReason.CONVERTER_UNAVAILABLE, None)
        except Exception as exc:
            return _failed(
                project, doc, converter.name, FailureReason.CONVERSION_ERROR, type(exc).__name__
            )
        return _converted(project, doc, result)


def _converted_before(
    project: Project, document_id: str, converter: Converter, version: str
) -> bool:
    """True if this document already has a conversion by this converter at this version."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM document_conversions WHERE document_id = :doc "
                "AND converter = :converter AND converter_version = :version"
            ),
            {"doc": document_id, "converter": converter.name, "version": version},
        ).first()
    return row is not None


def _converted(project: Project, doc: _Doc, result: ConversionResult) -> ConversionOutcome:
    markdown_ref = project.library.put(result.markdown.encode("utf-8"))
    if markdown_ref != result.markdown_hash:
        raise AssertionError("library hash of the Markdown differs from the conversion's hash")
    manifest_bytes = result.manifest.to_json()
    manifest_ref = project.library.put(manifest_bytes)
    if manifest_ref != f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}":
        raise AssertionError("library hash of the manifest differs from its bytes")

    counts = {kind.value: 0 for kind in AnchorKind}
    for anchor in result.manifest.anchors:
        counts[anchor.kind.value] += 1
    conversion_id = project.ids.new("cnv")
    payload = Converted(
        conversion_id=conversion_id,
        document_id=doc.document_id,
        converter=result.converter,
        converter_version=result.converter_version,
        raw_hash=doc.raw_hash,
        markdown_hash=markdown_ref,
        manifest_hash=manifest_ref,
        counts=counts,
        warnings=_warnings(result.warnings),
    )
    event = project.events.make(
        "document.converted",
        payload,
        project.human_actor(),
        refs=(doc.document_id, conversion_id),
    )
    project.record([event])
    return ConversionOutcome(
        document_id=doc.document_id,
        work_id=doc.work_id,
        status="converted",
        conversion_id=conversion_id,
        reason=None,
    )


def _failed(
    project: Project,
    doc: _Doc,
    converter: str | None,
    reason: FailureReason,
    error_class: str | None,
) -> ConversionOutcome:
    payload = ConversionFailed(
        document_id=doc.document_id,
        converter=converter,
        reason=reason,
        error_class=error_class,
    )
    event = project.events.make(
        "document.conversion_failed",
        payload,
        project.human_actor(),
        refs=(doc.document_id,),
    )
    project.record([event])
    return ConversionOutcome(
        document_id=doc.document_id,
        work_id=doc.work_id,
        status="failed",
        conversion_id=None,
        reason=reason.value,
    )


def _outcome(doc: _Doc, status: ConversionStatus) -> ConversionOutcome:
    return ConversionOutcome(
        document_id=doc.document_id,
        work_id=doc.work_id,
        status=status,
        conversion_id=None,
        reason=None,
    )


def _warnings(raw: Sequence[str]) -> list[str]:
    """The converter's warnings, each capped in length, blank ones dropped, at most the limit."""
    capped = [warning[:WARNING_MAX_CHARS] for warning in raw]
    return [warning for warning in capped if warning.strip()][:WARNINGS_MAX]


def _summary(outcomes: list[ConversionOutcome]) -> ConvertSummary:
    counts = Counter(outcome.status for outcome in outcomes)
    return ConvertSummary(
        outcomes=outcomes,
        converted=counts["converted"],
        unchanged=counts["unchanged"],
        failed=counts["failed"],
        raw_missing=counts["raw-missing"],
    )
