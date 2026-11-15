"""Re-anchor recorded conversions under the current anchoring rules, without the converter.

Canonical Markdown is a fixed point of `anchorise`, which strips every anchor it finds, so the
anchors of a stored conversion can be recomputed from its stored Markdown blob alone. The
converter is not rerun and the raw bytes are not read.

Invariants:
- Nothing recorded is edited. A re-anchored document gets a NEW conversion event whose converter
  version is the old one with the anchoring suffix (`stamp_version`); the old conversion stays,
  and the (document, converter, version) key keeps it distinct. Being the latest in event order,
  the new conversion is the one `document read` and later steps choose, exactly as for a newer
  converter version.
- Soundness is checked per document: anchorising the stored Markdown under the anchoring version
  it was recorded with must reproduce it byte for byte. Otherwise the document is `failed` /
  `hash-differs` and nothing is stored or recorded.
- Only the latest conversion of each live document is considered; one already at the current
  anchoring version, or whose re-anchored version is already recorded, is `unchanged`.
- Each document is recorded on its own (one `project.record` call). Events carry hashes, counts
  and the old warnings, never document text. Raw hash and warnings are copied from the old
  conversion.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text

from factory.document.anchorise import ANCHOR_VERSION, anchorise, split_version, stamp_version
from factory.document.anchors import AnchorKind, parse_manifest
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.model.document import Converted
from factory.services.context import Project
from factory.services.document_convert import (
    ConversionOutcome,
    ConversionStatus,
    ConvertSummary,
    OutcomeReason,
    _live_documents,
    _Record,
    _records,
    _sha256,
    _store,
    _summary,
)


def reanchor_conversions(
    project: Project,
    *,
    converter: str | None = None,
    document_ids: Sequence[str] | None = None,
) -> ConvertSummary:
    """Re-anchor the latest conversion of each live document, as the researcher.

    `converter` limits the scope to documents whose latest conversion is by that converter name;
    `document_ids` to the named documents, which must be live (else `FactoryValidationError` on
    field `document_ids`, nothing written). Statuses: `converted` (a new conversion recorded, its
    id in the outcome), `unchanged`, `failed` (reason `store-error` for a missing or damaged blob,
    `hash-differs` when the soundness check fails).
    """
    with project.index.exclusive():
        project.index.sync()
        live = {doc.document_id for doc in _live_documents(project)}
        if document_ids is not None:
            unknown = sorted(set(document_ids) - live)
            if unknown:
                raise FactoryValidationError(
                    [
                        ValidationIssue("document_ids", f"{d}: unknown or superseded")
                        for d in unknown
                    ]
                )
        records = _records(project)
    wanted = None if document_ids is None else set(document_ids)
    latest: dict[str, _Record] = {}
    versions: dict[tuple[str, str], set[str]] = {}
    for record in records:
        versions.setdefault((record.document_id, record.converter), set()).add(
            record.converter_version
        )
        if record.document_id in live:
            latest[record.document_id] = record
    outcomes = [
        _reanchor_one(project, record, versions[(document_id, record.converter)])
        for document_id, record in latest.items()
        if (converter is None or record.converter == converter)
        and (wanted is None or document_id in wanted)
    ]
    return _summary(outcomes)


def _reanchor_one(project: Project, old: _Record, recorded_versions: set[str]) -> ConversionOutcome:
    base, anchor_version = split_version(old.converter_version)
    new_version = stamp_version(base, ANCHOR_VERSION)
    if anchor_version >= ANCHOR_VERSION or new_version in recorded_versions:
        return _outcome(old, "unchanged")
    try:
        stored = project.library.get(old.markdown_hash).decode("utf-8")
    except (BlobNotFoundError, BlobIntegrityError, OSError, UnicodeDecodeError):
        return _outcome(old, "failed", "store-error")
    if anchorise(stored, version=anchor_version) != stored:
        return _outcome(old, "failed", "hash-differs")
    canonical = anchorise(stored, version=ANCHOR_VERSION)
    manifest = parse_manifest(canonical)
    markdown_bytes = canonical.encode("utf-8")
    markdown_ref = _sha256(markdown_bytes)
    manifest_bytes = manifest.to_json()
    manifest_ref = _sha256(manifest_bytes)
    counts = {kind.value: 0 for kind in AnchorKind}
    for anchor in manifest.anchors:
        counts[anchor.kind.value] += 1
    with project.index.exclusive():
        project.index.sync()
        if _already_recorded(project, old.document_id, old.converter, new_version):
            return _outcome(old, "unchanged")
        try:
            _store(project, markdown_ref, markdown_bytes)
            _store(project, manifest_ref, manifest_bytes)
        except (BlobNotFoundError, BlobIntegrityError, OSError):
            return _outcome(old, "failed", "store-error")
        conversion_id = project.ids.new("cnv")
        payload = Converted(
            conversion_id=conversion_id,
            document_id=old.document_id,
            converter=old.converter,
            converter_version=new_version,
            raw_hash=old.raw_hash,
            markdown_hash=markdown_ref,
            manifest_hash=manifest_ref,
            counts=counts,
            warnings=_old_warnings(project, old.conversion_id),
        )
        with project.writing():
            event = project.events.make(
                "document.converted",
                payload,
                project.human_actor(),
                refs=(old.document_id, conversion_id),
            )
            project.record([event])
    return _outcome(old, "converted", conversion_id=conversion_id)


def _already_recorded(project: Project, document_id: str, converter: str, version: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM document_conversions WHERE document_id = :d "
                "AND converter = :c AND converter_version = :v"
            ),
            {"d": document_id, "c": converter, "v": version},
        ).first()
    return row is not None


def _old_warnings(project: Project, conversion_id: str) -> list[str]:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT warnings FROM document_conversions WHERE conversion_id = :c"),
            {"c": conversion_id},
        ).first()
    return [str(w) for w in json.loads(str(row[0]))] if row is not None else []


def _outcome(
    old: _Record,
    status: ConversionStatus,
    reason: OutcomeReason | None = None,
    *,
    conversion_id: str | None = None,
) -> ConversionOutcome:
    return ConversionOutcome(
        document_id=old.document_id,
        work_id=old.work_id,
        status=status,
        conversion_id=conversion_id,
        reason=reason,
    )
