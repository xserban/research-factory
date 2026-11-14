"""Document conversion: raw retrieved documents to canonical Markdown with an anchor manifest.

`convert_documents` converts the live (not superseded) documents of promoted works, or the named
documents or works. Each document is decided and recorded on its own, so a crash keeps the work
already done.

Invariants:
- Validation is complete before anything is written. A refused request writes nothing.
- Per document: an already-converted (converter, version) gives `unchanged`, checked first and
  with no event. So does, unless the command named a converter (`override`), a document whose
  latest conversion this run could not replace: its converter is absent or cannot run here, or
  the latest conversion comes from another converter, which a plain run must not displace.
- A document whose latest conversion is by this converter at another version gives `outdated`,
  with no event, unless `upgrade` is set (IDEA-48): a plain run never re-converts the corpus after
  a version bump. With `upgrade` it is converted, and the old conversion is kept. Then a missing
  raw blob gives `raw-missing`, with no event. Then a missing converter or an unavailable
  tool records one `document.conversion_failed` event. A conversion runs outside the write lock,
  and its result is recorded under the lock after a re-check.
- Conversion events carry hashes, counts and warnings, never document text. A failure carries the
  exception class name only, never its message.
- A raw blob that is missing, corrupt or unreadable is `raw-missing` for that document, with no
  event, and the batch continues.
- The Markdown and manifest bytes go to the project library. The stored Markdown hash equals
  `ConversionResult.markdown_hash`, and the manifest hash is the hash of `manifest.to_json()`.
- A batch continues past a failed document. Each document's events are one `project.record` call.
- `convert_or_restore` is the single entry point of the CLI command: it refuses a scope combined
  with `restore` before anything is read.
- `restore_conversions` regenerates the Markdown and manifest blobs of recorded conversions that
  are missing or corrupt. It writes no event. The regenerated Markdown and manifest must hash to
  the recorded references, or nothing is stored. It runs outside the write lock.
"""

from __future__ import annotations

import hashlib
import json
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
from factory.document.registry import ConverterRegistry, default_converters
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
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
from factory.services.work_ref import resolve_work_ids

ConversionStatus = Literal[
    "converted", "unchanged", "outdated", "failed", "raw-missing", "restored"
]
RestoreReason = Literal["version-unavailable", "hash-differs", "store-error"]
OutdatedReason = Literal["other-converter-version"]
OutcomeReason = FailureReason | RestoreReason | OutdatedReason
"""The reason of a `failed` outcome (a conversion failure, or a restore failure), or of an
`outdated` one (the latest conversion is by another version of this converter; IDEA-48)."""


class ConversionOutcome(StrictModel):
    """What happened to one document. `conversion_id` is set only for `converted`; `reason` is
    the failure reason for `failed`, `other-converter-version` for `outdated`, and None
    otherwise."""

    document_id: str
    work_id: str
    status: ConversionStatus
    conversion_id: str | None
    reason: OutcomeReason | None


class ConvertSummary(StrictModel):
    """One outcome per document, in event order, and the count of each status."""

    outcomes: list[ConversionOutcome]
    converted: int
    unchanged: int
    outdated: int
    failed: int
    raw_missing: int
    restored: int


@dataclass(frozen=True)
class _Record:
    """A recorded conversion with its document's work and media type, as the projection holds it."""

    conversion_id: str
    document_id: str
    work_id: str
    media_type: str
    converter: str
    converter_version: str
    raw_hash: str
    markdown_hash: str
    manifest_hash: str


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
    override: bool = False,
    upgrade: bool = False,
) -> ConvertSummary:
    """Convert the documents in scope and record each outcome.

    With neither argument, the scope is the live documents of promoted works. `work_ids` limits
    the scope to the live documents of the named works, which must be promoted. `document_ids`
    limits it to the named documents, which must be live. Both together intersect.

    Raises `FactoryValidationError` (issues on `work_ids` or `document_ids`) with nothing written
    if a named work is not promoted or a named document is unknown or superseded. `override` says
    the researcher named the converter of `registry`, so it may add a conversion beside another
    converter's; see the module invariants. `upgrade` says the researcher asked to re-convert a
    document whose latest conversion is an older version of this converter (IDEA-48); without it
    such a document is `outdated`.
    """
    with project.index.exclusive():
        project.index.sync()
        if work_ids is not None:
            work_ids = resolve_work_ids(project, work_ids)
        targets = _targets(project, work_ids, document_ids)
    outcomes = [_convert_one(project, registry, doc, override, upgrade) for doc in targets]
    return _summary(outcomes)


def restore_conversions(project: Project, registry: ConverterRegistry) -> ConvertSummary:
    """Regenerate the missing or corrupt Markdown and manifest of every recorded conversion.

    A conversion with both blobs intact is skipped and has no outcome. Otherwise the registry must
    hold the recorded converter for the document's media type, at the recorded version (else
    `failed` / `version-unavailable`). The raw blob must be readable (else
    `raw-missing`). The conversion is rerun; its Markdown and manifest must hash to the recorded
    references (else `failed` / `hash-differs`, and neither blob is stored). Only then are both
    blobs stored, and the outcome is `restored` with the existing conversion id. No event is
    written: the conversion is already recorded.
    """
    with project.index.exclusive():
        project.index.sync()
        records = _records(project)
    damaged = [record for record in records if not _intact(project, record)]
    return _summary([_restore_one(project, registry, record) for record in damaged])


def convert_or_restore(
    project: Project,
    registry: ConverterRegistry,
    *,
    restore: bool,
    work_ids: Sequence[str] | None = None,
    document_ids: Sequence[str] | None = None,
    override: bool = False,
    upgrade: bool = False,
) -> ConvertSummary:
    """Restore damaged conversions, or convert the documents in scope, as one command.

    `restore` takes no scope: with `work_ids` or `document_ids` it raises `FactoryValidationError`
    on field `restore`, before anything is read or written. Otherwise it is `restore_conversions`
    when `restore` is set and `convert_documents` when it is not.
    """
    if restore and (work_ids or document_ids):
        raise FactoryValidationError([ValidationIssue("restore", "takes no --work or --document")])
    if restore:
        return restore_conversions(project, registry)
    return convert_documents(
        project,
        registry,
        work_ids=work_ids,
        document_ids=document_ids,
        override=override,
        upgrade=upgrade,
    )


def _records(project: Project) -> list[_Record]:
    """Every recorded conversion in event order. Requires a synced index."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT c.conversion_id, c.document_id, d.work_id, d.media_type, c.converter, "
                    "c.converter_version, c.raw_hash, c.markdown_hash, c.manifest_hash "
                    "FROM document_conversions c JOIN fulltext_documents d "
                    "ON d.document_id = c.document_id ORDER BY c.event_id"
                )
            )
            .mappings()
            .all()
        )
    return [
        _Record(
            conversion_id=str(row["conversion_id"]),
            document_id=str(row["document_id"]),
            work_id=str(row["work_id"]),
            media_type=str(row["media_type"]),
            converter=str(row["converter"]),
            converter_version=str(row["converter_version"]),
            raw_hash=str(row["raw_hash"]),
            markdown_hash=str(row["markdown_hash"]),
            manifest_hash=str(row["manifest_hash"]),
        )
        for row in rows
    ]


def _intact(project: Project, record: _Record) -> bool:
    """True when both of the conversion's blobs exist and hash to their references."""
    return _blob_ok(project, record.markdown_hash) and _blob_ok(project, record.manifest_hash)


def _blob_ok(project: Project, ref: str) -> bool:
    if not project.library.exists(ref):
        return False
    try:
        project.library.get(ref)
    except (BlobNotFoundError, BlobIntegrityError, OSError):
        return False
    return True


def _restore_one(
    project: Project, registry: ConverterRegistry, record: _Record
) -> ConversionOutcome:
    """Reconvert one damaged conversion and store its blobs only if they reproduce its hashes."""
    converter = registry.named(record.converter, record.media_type)
    version = _version_or_none(converter) if converter is not None else None
    if converter is None or version != record.converter_version:
        return _restore_outcome(record, "failed", "version-unavailable")
    try:
        raw = project.library.get(record.raw_hash)
    except (BlobNotFoundError, BlobIntegrityError, OSError):
        return _restore_outcome(record, "raw-missing")
    try:
        result = convert(converter, raw, record.media_type)
    except ConverterUnavailable:
        return _restore_outcome(record, "failed", FailureReason.CONVERTER_UNAVAILABLE)
    except Exception:
        return _restore_outcome(record, "failed", FailureReason.CONVERSION_ERROR)
    manifest = result.manifest.to_json()
    if result.markdown_hash != record.markdown_hash or _sha256(manifest) != record.manifest_hash:
        return _restore_outcome(record, "failed", "hash-differs")
    try:
        _store(project, record.markdown_hash, result.markdown.encode("utf-8"))
        _store(project, record.manifest_hash, manifest)
    except (BlobNotFoundError, BlobIntegrityError, OSError):
        # A partial store is safe: the blob that landed is intact, and a rerun restores the other.
        return _restore_outcome(record, "failed", "store-error")
    return _restore_outcome(record, "restored")


def _store(project: Project, ref: str, data: bytes) -> None:
    """Put `data`, which hashes to `ref`, in the library, replacing a corrupt file at that path.

    `BlobStore.put` keeps an existing file, so a corrupt or unreadable one is removed first. Raises
    `OSError` when the library cannot be written; the caller reports that as `store-error`.
    """
    if project.library.exists(ref):
        try:
            project.library.get(ref)
        except (BlobNotFoundError, BlobIntegrityError, OSError):
            project.library.path(ref).unlink(missing_ok=True)
    project.library.put(data)


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _restore_outcome(
    record: _Record, status: ConversionStatus, reason: OutcomeReason | None = None
) -> ConversionOutcome:
    return ConversionOutcome(
        document_id=record.document_id,
        work_id=record.work_id,
        status=status,
        conversion_id=record.conversion_id if status == "restored" else None,
        reason=reason,
    )


class DocumentStatusEntry(StrictModel):
    """One live document of a promoted work. `converter`, `converter_version`, `conversion_id` and
    `counts` are those of its latest conversion (None when it has none). `latest_failure` is the
    reason of its latest recorded failure, None when it has none."""

    document_id: str
    work_id: str
    converted: bool
    conversion_id: str | None
    converter: str | None
    converter_version: str | None
    counts: dict[str, int] | None
    latest_failure: FailureReason | None


class DocumentStatus(StrictModel):
    """Every live document of a promoted work, in event order, with the count of each state."""

    documents: list[DocumentStatusEntry]
    converted: int
    not_converted: int


def document_status(project: Project) -> DocumentStatus:
    """The conversion state of each live document of a promoted work.

    "Latest" means latest in event order. Read-only: nothing is written, and the index is only
    synced. The library is never read, so a missing blob does not change the status.
    """
    with project.index.exclusive():
        project.index.sync()
    return _status(project)


def unconverted_documents(project: Project) -> int:
    """How many live documents of promoted works have no conversion. Takes no write lock, so a
    status read inside another service's lock can call it."""
    project.index.sync()
    return _status(project).not_converted


def _status(project: Project) -> DocumentStatus:
    promoted = _promoted(project)
    latest = _latest_conversions(project)
    failures = _latest_failures(project)
    entries = []
    for doc in _live_documents(project):
        if doc.work_id not in promoted:
            continue
        row = latest.get(doc.document_id)
        entries.append(
            DocumentStatusEntry(
                document_id=doc.document_id,
                work_id=doc.work_id,
                converted=row is not None,
                conversion_id=None if row is None else row[0],
                converter=None if row is None else row[1],
                converter_version=None if row is None else row[2],
                counts=None if row is None else row[3],
                latest_failure=failures.get(doc.document_id),
            )
        )
    converted = sum(1 for entry in entries if entry.converted)
    return DocumentStatus(
        documents=entries, converted=converted, not_converted=len(entries) - converted
    )


class ConverterCount(StrictModel):
    """How many live documents read through one converter at one version. `chosen` says decision
    49 chose that converter; False means the researcher named it."""

    converter: str
    version: str
    media_type: str
    documents: int
    chosen: bool


def conversion_census(project: Project) -> list[ConverterCount]:
    """The latest conversion of each live document, counted by converter, version and media type
    and sorted by them. Requires a synced index. Reads no blob."""
    latest = _latest_conversions(project)
    counts: Counter[tuple[str, str, str]] = Counter()
    for doc in _live_documents(project):
        row = latest.get(doc.document_id)
        if row is not None:
            counts[(row[1], row[2], doc.media_type)] += 1
    chosen = default_converters().names()
    return [
        ConverterCount(
            converter=converter,
            version=version,
            media_type=media_type,
            documents=n,
            chosen=converter in chosen,
        )
        for (converter, version, media_type), n in sorted(counts.items())
    ]


def _latest_conversions(
    project: Project,
) -> dict[str, tuple[str, str, str, dict[str, int]]]:
    """Per document, the latest conversion's (conversion id, converter, version, counts)."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT conversion_id, document_id, converter, converter_version, counts "
                    "FROM document_conversions ORDER BY event_id"
                )
            )
            .mappings()
            .all()
        )
    latest: dict[str, tuple[str, str, str, dict[str, int]]] = {}
    for row in rows:
        counts = {str(k): int(v) for k, v in json.loads(str(row["counts"])).items()}
        latest[str(row["document_id"])] = (
            str(row["conversion_id"]),
            str(row["converter"]),
            str(row["converter_version"]),
            counts,
        )
    return latest


def _latest_failures(project: Project) -> dict[str, FailureReason]:
    """Per document, the reason of its latest recorded failure, in event order."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text("SELECT document_id, reason FROM document_failures ORDER BY event_id")
            )
            .mappings()
            .all()
        )
    return {str(row["document_id"]): FailureReason(str(row["reason"])) for row in rows}


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


@dataclass(frozen=True)
class _Ready:
    """A document to convert: its converter, the version that converter reports, and raw bytes."""

    converter: Converter
    version: str
    raw: bytes


def _convert_one(
    project: Project, registry: ConverterRegistry, doc: _Doc, override: bool, upgrade: bool
) -> ConversionOutcome:
    """Decide under the write lock, convert outside it, then re-check and record under it again.

    A concurrent identical conversion that lands during the unlocked conversion makes this one
    `unchanged`, so the same key never gets two conversion events.
    """
    with project.index.exclusive():
        project.index.sync()
        decided = _decide(project, registry, doc, override, upgrade)
    if isinstance(decided, ConversionOutcome):
        return decided

    result: ConversionResult | None = None
    failure: tuple[FailureReason, str | None] = (FailureReason.CONVERSION_ERROR, None)
    try:
        result = convert(decided.converter, decided.raw, doc.media_type)
    except ConverterUnavailable:
        failure = (FailureReason.CONVERTER_UNAVAILABLE, None)
    except Exception as exc:
        failure = (FailureReason.CONVERSION_ERROR, type(exc).__name__)

    with project.index.exclusive():
        project.index.sync()
        if _converted_before(project, doc.document_id, decided.converter, decided.version):
            return _outcome(doc, "unchanged")
        if result is None:
            reason, error_class = failure
            return _failed(project, doc, decided.converter.name, reason, error_class)
        return _converted(project, doc, result)


def _decide(
    project: Project,
    registry: ConverterRegistry,
    doc: _Doc,
    override: bool,
    upgrade: bool,
) -> ConversionOutcome | _Ready:
    """Under the lock, the document's outcome if nothing needs converting, else what to convert.

    Order: already converted at this converter and version gives `unchanged`, as does a converted
    document this run may not or cannot replace (the module invariants); a latest conversion by
    this converter at another version gives `outdated` unless `upgrade` is set (IDEA-48); a missing
    raw blob gives `raw-missing` (no event, even when there is no converter or it is unavailable);
    then the no-converter and converter-unavailable failures are recorded.
    """
    converter = registry.for_media_type(doc.media_type)
    version = _version_or_none(converter) if converter is not None else None
    if (
        converter is not None
        and version is not None
        and _converted_before(project, doc.document_id, converter, version)
    ):
        return _outcome(doc, "unchanged")
    latest = _latest_converter(project, doc.document_id)
    if (
        not override
        and latest is not None
        and (converter is None or version is None or latest != converter.name)
    ):
        return _outcome(doc, "unchanged")
    if not upgrade and converter is not None and version is not None and latest == converter.name:
        return _outcome(doc, "outdated", reason="other-converter-version")
    if not project.library.exists(doc.raw_hash):
        return _outcome(doc, "raw-missing")
    if converter is None:
        return _failed(project, doc, None, FailureReason.NO_CONVERTER, None)
    if version is None:
        return _failed(project, doc, converter.name, FailureReason.CONVERTER_UNAVAILABLE, None)
    try:
        raw = project.library.get(doc.raw_hash)
    except (BlobNotFoundError, BlobIntegrityError, OSError):
        return _outcome(doc, "raw-missing")
    return _Ready(converter, version, raw)


def _version_or_none(converter: Converter) -> str | None:
    """The converter's version, or None if its tool is unavailable."""
    try:
        return converter.version()
    except ConverterUnavailable:
        return None


def _latest_converter(project: Project, document_id: str) -> str | None:
    """The converter of the document's latest conversion, or None when it has none."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT converter FROM document_conversions WHERE document_id = :doc "
                "ORDER BY event_id DESC LIMIT 1"
            ),
            {"doc": document_id},
        ).first()
    return None if row is None else str(row[0])


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
    """Store the Markdown and manifest, then record the conversion. A storage failure is an
    outcome with no event, so the document is retried by a later run."""
    markdown = result.markdown.encode("utf-8")
    if _sha256(markdown) != result.markdown_hash:
        raise AssertionError("library hash of the Markdown differs from the conversion's hash")
    manifest = result.manifest.to_json()
    manifest_ref = _sha256(manifest)
    try:
        _store(project, result.markdown_hash, markdown)
        _store(project, manifest_ref, manifest)
    except (BlobNotFoundError, BlobIntegrityError, OSError):
        return ConversionOutcome(
            document_id=doc.document_id,
            work_id=doc.work_id,
            status="failed",
            conversion_id=None,
            reason="store-error",
        )
    markdown_ref = result.markdown_hash

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
    with project.writing():
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
    with project.writing():
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
        reason=reason,
    )


def _outcome(
    doc: _Doc, status: ConversionStatus, *, reason: OutcomeReason | None = None
) -> ConversionOutcome:
    return ConversionOutcome(
        document_id=doc.document_id,
        work_id=doc.work_id,
        status=status,
        conversion_id=None,
        reason=reason,
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
        outdated=counts["outdated"],
        failed=counts["failed"],
        raw_missing=counts["raw-missing"],
        restored=counts["restored"],
    )
