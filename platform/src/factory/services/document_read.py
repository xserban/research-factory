"""Document reading: the canonical Markdown of a promoted work, paged by anchor (plan 2B2, task 4).

`document_read` returns the non-cell anchors of one conversion in document order, in pages. A
single anchor (cells included) is read with `anchor=`. `conversion_manifest` and `resolve_anchor`
are the entry points that quote checks and later plans use. They apply no INCLUDED gate and no work
scoping, so they must not be exposed through a tool without that gate.

Choosing the conversion (ruling 5): an explicit `conversion_id` wins; else an explicit `document_id`
(its latest conversion); else the first live document with a conversion, in route order
(`ROUTE_ORDER`, then researcher-supplied, ties by event order), and its latest conversion by event
order. An explicit document or conversion may be superseded, so old quotes stay readable.

Invariants:
- Read-only: nothing is written, and the index is only synced, never written.
- Only works promoted at title/abstract (`Outcome.INCLUDED`) are read.
- Every returned page is non-empty when more segments remain, and `next_after` is None exactly
  when no segment follows the page. A page takes at most `limit` segments, and at most `max_chars`
  of text unless it holds a single segment (the first segment is always returned).
- Segment text is cut at 8000 characters in page mode and at 40000 in anchor mode; a cut text is
  flagged `truncated`.
- A missing or damaged Markdown or manifest blob is refused, naming `factory document convert
  --restore`. The message never carries document text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from factory.document.anchors import Anchor, AnchorKind, Manifest, ManifestError
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.model.base import StrictModel
from factory.model.fulltext import ROUTE_ORDER, Quality, Route
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project

PAGE_SEGMENT_MAX_CHARS = 8000
ANCHOR_MAX_CHARS = 40000
LIMIT_MIN, LIMIT_MAX = 1, 200
MAX_CHARS_MIN, MAX_CHARS_MAX = 1000, 100000
DEFAULT_LIMIT = 50
DEFAULT_MAX_CHARS = 20000

_CONVERT_HINT = "run `factory document convert` first"
_RESTORE_HINT = "run `factory document convert --restore` to regenerate it"


class Segment(StrictModel):
    """One readable element: its anchor, kind, parent, text, and whether the text was cut."""

    anchor: str
    kind: AnchorKind
    parent: str | None
    text: str
    truncated: bool


class DocumentPage(StrictModel):
    """One page of a conversion. `next_after` is the last anchor returned, or None when exhausted.
    `total_segments` counts the non-cell anchors of the conversion."""

    work_id: str
    document_id: str
    conversion_id: str
    route: Route
    quality: Quality
    source_version: str
    converter: str
    converter_version: str
    markdown_hash: str
    segments: list[Segment]
    next_after: str | None
    total_segments: int


@dataclass(frozen=True)
class _Conversion:
    """A conversion joined to its document, as the projection holds them."""

    conversion_id: str
    document_id: str
    work_id: str
    route: Route
    quality: Quality
    source_version: str
    converter: str
    converter_version: str
    markdown_hash: str
    manifest_hash: str
    live: bool
    document_event_id: str
    conversion_event_id: str


_SELECT = (
    "SELECT c.conversion_id, c.document_id, d.work_id, d.route, d.quality, d.source_version, "
    "c.converter, c.converter_version, c.markdown_hash, c.manifest_hash, "
    "d.superseded_by, d.event_id AS document_event_id, c.event_id AS conversion_event_id "
    "FROM document_conversions c JOIN fulltext_documents d ON d.document_id = c.document_id"
)


def document_read(
    project: Project,
    *,
    work_id: str,
    document_id: str | None = None,
    conversion_id: str | None = None,
    after: str | None = None,
    anchor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> DocumentPage:
    """One page of a promoted work's conversion, or the single anchor `anchor`.

    Raises `FactoryValidationError` with nothing read beyond the projection if an argument is out
    of range or `anchor` and `after` are both given; if the work is not promoted; if the work,
    document or conversion does not match; if the work has no conversion (naming
    `factory document convert`); or if the conversion's blobs are missing or damaged (naming
    `factory document convert --restore`). An unknown `after` or `anchor` is refused on its field.
    """
    _check_arguments(limit, max_chars, after, anchor)
    project.index.sync()
    if work_id not in _promoted(project):
        raise FactoryValidationError(
            [ValidationIssue("work_id", f"{work_id}: not promoted at title/abstract")]
        )
    conversion = _select(project, work_id, document_id, conversion_id)
    manifest = _load(project, conversion)
    anchors = manifest.anchors
    total = sum(1 for a in anchors if a.kind is not AnchorKind.CELL)

    if anchor is not None:
        target = _anchor_or_refuse(manifest, anchor, conversion.conversion_id)
        segments = [_segment(target, ANCHOR_MAX_CHARS)]
        next_after = None
    else:
        segments, next_after = _page(manifest, after, limit, max_chars, conversion.conversion_id)

    return DocumentPage(
        work_id=conversion.work_id,
        document_id=conversion.document_id,
        conversion_id=conversion.conversion_id,
        route=conversion.route,
        quality=conversion.quality,
        source_version=conversion.source_version,
        converter=conversion.converter,
        converter_version=conversion.converter_version,
        markdown_hash=conversion.markdown_hash,
        segments=segments,
        next_after=next_after,
        total_segments=total,
    )


def conversion_manifest(project: Project, conversion_id: str) -> Manifest:
    """The manifest of one conversion, read from the library and verified by hash.

    Both the Markdown and the manifest blob must be present and hash correctly, as in
    `document_read`. Raises `FactoryValidationError` on field `conversion_id` if the conversion is
    unknown or either blob is missing or damaged (naming `factory document convert --restore`).

    No INCLUDED gate and no work scoping apply: the conversion is found by id alone. Do not expose
    this through a tool without the gate of `document_read`.
    """
    project.index.sync()
    conversion = _find(project, "c.conversion_id = :cid", {"cid": conversion_id})
    if conversion is None:
        raise FactoryValidationError(
            [ValidationIssue("conversion_id", f"{conversion_id}: unknown conversion")]
        )
    return _load(project, conversion)


def resolve_anchor(project: Project, conversion_id: str, anchor_id: str) -> Anchor:
    """The anchor `anchor_id` of one conversion, exactly as its manifest holds it.

    Verifies the blobs as `conversion_manifest` does. Raises `FactoryValidationError` on field
    `conversion_id` if the conversion is unknown or damaged, and on field `anchor` if the conversion
    has no such anchor.

    No INCLUDED gate and no work scoping apply. Do not expose this through a tool without the gate.
    """
    manifest = conversion_manifest(project, conversion_id)
    return _anchor_or_refuse(manifest, anchor_id, conversion_id)


# --- Arguments (validated before anything is read) ---


def _check_arguments(limit: int, max_chars: int, after: str | None, anchor: str | None) -> None:
    issues: list[ValidationIssue] = []
    if not LIMIT_MIN <= limit <= LIMIT_MAX:
        issues.append(ValidationIssue("limit", f"must be between {LIMIT_MIN} and {LIMIT_MAX}"))
    if not MAX_CHARS_MIN <= max_chars <= MAX_CHARS_MAX:
        issues.append(
            ValidationIssue("max_chars", f"must be between {MAX_CHARS_MIN} and {MAX_CHARS_MAX}")
        )
    if anchor is not None and after is not None:
        issues.append(ValidationIssue("after", "cannot be combined with anchor"))
    if issues:
        raise FactoryValidationError(issues)


# --- Choosing the conversion ---


def _promoted(project: Project) -> frozenset[str]:
    return frozenset(
        work for work, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _select(
    project: Project, work_id: str, document_id: str | None, conversion_id: str | None
) -> _Conversion:
    if conversion_id is not None:
        conversion = _find(project, "c.conversion_id = :cid", {"cid": conversion_id})
        if conversion is None:
            raise FactoryValidationError(
                [ValidationIssue("conversion_id", f"{conversion_id}: unknown conversion")]
            )
        if conversion.work_id != work_id:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "conversion_id", f"{conversion_id}: not a conversion of {work_id}"
                    )
                ]
            )
        if document_id is not None and conversion.document_id != document_id:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "conversion_id", f"{conversion_id}: not a conversion of {document_id}"
                    )
                ]
            )
        return conversion

    if document_id is not None:
        owner = _document_work(project, document_id)
        if owner != work_id:
            raise FactoryValidationError(
                [ValidationIssue("document_id", f"{document_id}: not a document of {work_id}")]
            )
        versions = _query(project, "c.document_id = :doc", {"doc": document_id})
        if not versions:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "document_id", f"{document_id}: has no conversion; {_CONVERT_HINT}"
                    )
                ]
            )
        return versions[-1]

    live = [c for c in _query(project, "d.work_id = :work", {"work": work_id}) if c.live]
    if not live:
        raise FactoryValidationError(
            [ValidationIssue("work_id", f"{work_id}: has no conversion; {_CONVERT_HINT}")]
        )
    first = min(live, key=lambda c: (_route_rank(c.route), c.document_event_id))
    return max(
        (c for c in live if c.document_id == first.document_id),
        key=lambda c: c.conversion_event_id,
    )


def _route_rank(route: Route) -> int:
    """Position in the automatic order; researcher-supplied documents come after all of them."""
    return ROUTE_ORDER.index(route) if route in ROUTE_ORDER else len(ROUTE_ORDER)


def _document_work(project: Project, document_id: str) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT work_id FROM fulltext_documents WHERE document_id = :doc"),
            {"doc": document_id},
        ).first()
    return None if row is None else str(row[0])


def _find(project: Project, where: str, params: dict[str, Any]) -> _Conversion | None:
    rows = _query(project, where, params)
    return rows[-1] if rows else None


def _query(project: Project, where: str, params: dict[str, Any]) -> list[_Conversion]:
    """Matching conversions, oldest first by conversion event id."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(f"{_SELECT} WHERE {where} ORDER BY c.event_id"),
                params,
            )
            .mappings()
            .all()
        )
    return [
        _Conversion(
            conversion_id=str(row["conversion_id"]),
            document_id=str(row["document_id"]),
            work_id=str(row["work_id"]),
            route=Route(str(row["route"])),
            quality=Quality(str(row["quality"])),
            source_version=str(row["source_version"]),
            converter=str(row["converter"]),
            converter_version=str(row["converter_version"]),
            markdown_hash=str(row["markdown_hash"]),
            manifest_hash=str(row["manifest_hash"]),
            live=row["superseded_by"] is None,
            document_event_id=str(row["document_event_id"]),
            conversion_event_id=str(row["conversion_event_id"]),
        )
        for row in rows
    ]


# --- Blobs ---


def _load(project: Project, conversion: _Conversion) -> Manifest:
    """The conversion's manifest, after verifying that its Markdown and manifest blobs exist and
    hash correctly. The one loading path for `document_read`, `conversion_manifest` and
    `resolve_anchor`.

    A missing, mismatching, unreadable or unparseable blob is refused on field `conversion_id`,
    naming the restore command. The exception message is not carried, since it may name a path.
    """
    try:
        project.library.get(conversion.markdown_hash)
        return Manifest.from_json(project.library.get(conversion.manifest_hash))
    except (BlobNotFoundError, BlobIntegrityError, ManifestError, OSError) as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "conversion_id",
                    f"{conversion.conversion_id}: stored Markdown or manifest is missing or "
                    f"damaged; {_RESTORE_HINT}",
                )
            ]
        ) from exc


# --- Anchors and pages ---


def _anchor_or_refuse(manifest: Manifest, anchor_id: str, conversion_id: str) -> Anchor:
    found = manifest.get(anchor_id)
    if found is None:
        raise FactoryValidationError(
            [ValidationIssue("anchor", f"{anchor_id}: not an anchor of {conversion_id}")]
        )
    return found


def _segment(anchor: Anchor, cap: int) -> Segment:
    return Segment(
        anchor=anchor.id,
        kind=anchor.kind,
        parent=anchor.parent,
        text=anchor.text[:cap],
        truncated=len(anchor.text) > cap,
    )


def _page(
    manifest: Manifest,
    after: str | None,
    limit: int,
    max_chars: int,
    conversion_id: str,
) -> tuple[list[Segment], str | None]:
    """The segments after `after` (all, if None), and the `next_after` of the page."""
    anchors = manifest.anchors
    if after is None:
        start = -1
    else:
        position = next((i for i, a in enumerate(anchors) if a.id == after), None)
        if position is None:
            raise FactoryValidationError(
                [ValidationIssue("after", f"{after}: not an anchor of {conversion_id}")]
            )
        start = position
    candidates = [a for a in anchors[start + 1 :] if a.kind is not AnchorKind.CELL]

    segments: list[Segment] = []
    used = 0
    for anchor in candidates:
        if len(segments) == limit:
            break
        segment = _segment(anchor, PAGE_SEGMENT_MAX_CHARS)
        if segments and used + len(segment.text) > max_chars:
            break
        segments.append(segment)
        used += len(segment.text)

    more = len(segments) < len(candidates)
    next_after = segments[-1].anchor if segments and more else None
    return segments, next_after
