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
- Pass independence (decision 37): when `session` is given, a session joined to a title/abstract
  pass and to no full-text pass is refused (field `session`). A session joined to a full-text pass
  reads only the works of the full-text batches of its own pass that it holds or has completed,
  and only the conversion such a batch pins; a session joined to an extraction pass (of either
  scope, evidence or contribution), or holding appraisal tasks, is gated the same way on the
  tasks of its own pass; this rule applies whether or not the session also joined a
  title/abstract pass, so a title/abstract membership never widens the access. Any other work,
  document or conversion is refused on its own field. A session in neither stage, and
  a call without `session` (the researcher's CLI), are not gated. The tool returns only document
  segments, never a verdict or label of either pass.
- Read-only: nothing is written, and the index is only synced, never written.
- Only works promoted at title/abstract (`Outcome.INCLUDED`) are read.
- Every returned page is non-empty when more segments remain, and `next_after` is None exactly
  when no segment follows the page. A page takes at most `limit` segments, and at most `max_chars`
  of text unless it holds a single segment (the first segment is always returned).
- Segment text is cut at 8000 characters in page mode and at 40000 in anchor mode; a cut text is
  flagged `truncated`.
- A missing or damaged Markdown or manifest blob is refused, naming `factory document convert
  --restore`. The message never carries document text.
- Work ids match after NFC normalisation (IDEA-49), as `screen_record` does: a model writes a
  non-Latin name composed where the stored id may be decomposed (a Hangul surname is stored as
  jamo). An id that is not a work but whose NFC form equals that of exactly one work is read as
  that work, and the page carries the stored spelling; the batch and miner membership checks
  compare NFC forms. An id matching no work, or several, is refused as before.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from itertools import islice

from sqlalchemy import text

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.extraction import ScopeKey, scope_from_value
from factory.model.fulltext import ROUTE_ORDER, Quality, Route
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import is_pass_session
from factory.services.context import Project
from factory.services.conversions import (
    Conversion,
    _anchor_or_refuse,
    _find,
    _load,
    _query,
    conversion_manifest,
    resolve_anchor,
)
from factory.services.stages import kinds_for, task_kind

__all__ = [
    "DocumentPage",
    "Segment",
    "conversion_manifest",
    "default_conversion",
    "document_read",
    "resolve_anchor",
]

PAGE_SEGMENT_MAX_CHARS = 8000
ANCHOR_MAX_CHARS = 40000
LIMIT_MIN, LIMIT_MAX = 1, 200
MAX_CHARS_MIN, MAX_CHARS_MAX = 1000, 100000
DEFAULT_LIMIT = 50
DEFAULT_MAX_CHARS = 20000

_CONVERT_HINT = "run `factory document convert` first"


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
    session: str | None = None,
    selected: bool = False,
) -> DocumentPage:
    """One page of a promoted work's conversion, or the single anchor `anchor`.

    Raises `FactoryValidationError` with nothing read beyond the projection if an argument is out
    of range or `anchor` and `after` are both given; if the work is not promoted; if the work,
    document or conversion does not match; if the work has no conversion (naming
    `factory document convert`); or if the conversion's blobs are missing or damaged (naming
    `factory document convert --restore`). An unknown `after` or `anchor` is refused on its field.

    `session` is the caller's session when it is an agent's (see the module invariants); a
    full-text screener that names no document or conversion reads the one its batch pins.

    `selected` reads only the anchors the session's own miner task selected for `work_id` (the
    ids stored in the task; no new text is stored), so a miner can read what it is to mine in a
    few large pages. It is refused without an agent `session`, for a session that holds no miner
    task of the work, and together with `anchor`.
    """
    _check_arguments(limit, max_chars, after, anchor)
    if selected and (session is None or anchor is not None):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "selected", "needs an agent session and cannot be combined with anchor"
                )
            ]
        )
    project.index.sync()
    work_id = _as_stored(project, work_id)
    if session is not None:
        document_id, conversion_id = _gate(project, session, work_id, document_id, conversion_id)
    if work_id not in _promoted(project):
        raise FactoryValidationError(
            [ValidationIssue("work_id", f"{work_id}: not promoted at title/abstract")]
        )
    conversion = _select(project, work_id, document_id, conversion_id)
    manifest = _load(project, conversion)
    anchors = manifest.anchors
    only = (
        _held_selection(project, session, work_id, conversion.conversion_id) if selected else None
    )
    total = sum(
        1 for a in anchors if a.kind is not AnchorKind.CELL and (only is None or a.id in only)
    )

    if anchor is not None:
        target = _anchor_or_refuse(manifest, anchor, conversion.conversion_id)
        segments = [_segment(target, ANCHOR_MAX_CHARS)]
        next_after = None
    else:
        segments, next_after = _page(
            manifest, after, limit, max_chars, conversion.conversion_id, only
        )

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


# --- Work ids (NFC-tolerant, IDEA-49) ---


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _same_work(stored: object, work_id: str) -> bool:
    """Whether a stored work id names `work_id`, comparing NFC forms."""
    return isinstance(stored, str) and _nfc(stored) == _nfc(work_id)


def _as_stored(project: Project, work_id: str) -> str:
    """`work_id` spelled as the corpus stores it: itself when it is a work, else the one work
    whose NFC form equals its NFC form, else itself unchanged (and refused later as before)."""
    works = final_outcomes(project).keys()
    if work_id in works:
        return work_id
    matches = [w for w in works if _same_work(w, work_id)]
    return matches[0] if len(matches) == 1 else work_id


# --- The pass-independence gate (decision 37) ---


def _gate(
    project: Project,
    session: str,
    work_id: str,
    document_id: str | None,
    conversion_id: str | None,
) -> tuple[str | None, str | None]:
    """The (document, conversion) to read for `session`, or a refusal. See the module invariants.

    When a work is in several of the session's batches with different pins, the pin of the last
    task by task ID is the default (deterministic)."""
    label = _full_text_pass(project, session)
    kind = None if label is None else task_kind(ScreeningStage.FULL_TEXT, label)
    if label is None:
        extracting = _extraction_pass(project, session)
        kind = None if extracting is None else kinds_for(extracting[0])[extracting[1]]
    if kind is None:
        kind = _appraisal_kind(project, session)
    if kind is None:
        if is_pass_session(project, session, stage=ScreeningStage.TITLE_ABSTRACT):
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "session", "this session has joined a pass and cannot use this tool"
                    )
                ]
            )
        return document_id, conversion_id
    pins = _held_pins(project, session, kind, work_id)
    if not pins:
        raise FactoryValidationError(
            [ValidationIssue("work_id", f"{work_id}: not a record of a batch this session holds")]
        )
    pinned = pins[-1]
    if conversion_id is not None:
        match = next((p for p in pins if p[1] == conversion_id), None)
        if match is None:
            raise FactoryValidationError(
                [ValidationIssue("conversion_id", f"{conversion_id}: not the conversion pinned")]
            )
        pinned = match
    if document_id is not None and document_id != pinned[0]:
        raise FactoryValidationError(
            [ValidationIssue("document_id", f"{document_id}: not the document pinned")]
        )
    return pinned


def _held_selection(
    project: Project, session: str | None, work_id: str, conversion_id: str
) -> frozenset[str]:
    """The anchor ids a miner task held (or completed) by `session` selected for `work_id` at
    `conversion_id`, from the task content (ids only). Refused on `selected` when there is none."""
    extracting = None if session is None else _extraction_pass(project, session)
    if session is None or extracting is None:
        raise FactoryValidationError(
            [ValidationIssue("selected", "this session holds no miner task")]
        )
    kind = kinds_for(extracting[0])[extracting[1]]
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT content_blob FROM tasks WHERE kind = :kind AND claim_session = :s "
                "AND status IN ('claimed', 'completed') ORDER BY task_id DESC"
            ),
            {"kind": kind, "s": session},
        ).all()
    for (blob,) in rows:
        content = project.blobs.get_json(str(blob))
        if not isinstance(content, dict):
            continue
        anchor_ids = content.get("anchors")
        if not isinstance(anchor_ids, list):
            continue
        records = content.get("records")
        for record in records if isinstance(records, list) else []:
            if (
                isinstance(record, dict)
                and _same_work(record.get("work_id"), work_id)
                and record.get("conversion_id") == conversion_id
            ):
                return frozenset(str(a) for a in anchor_ids)
    raise FactoryValidationError(
        [
            ValidationIssue(
                "selected", f"{work_id}: no selection among the miner tasks this session holds"
            )
        ]
    )


def _full_text_pass(project: Project, session: str) -> PassLabel | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT pass_label FROM pass_sessions WHERE session = :s AND stage = :stage"),
            {"s": session, "stage": ScreeningStage.FULL_TEXT.value},
        ).first()
    return None if row is None else PassLabel(str(row[0]))


def _appraisal_kind(project: Project, session: str) -> str | None:
    """The appraisal task kind (`appraise_a` or `appraise_b`) whose task this session claimed, if
    any: such a session reads only the works of the tasks it holds or has completed."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT kind FROM tasks WHERE claim_session = :s AND kind IN "
                "('appraise_a', 'appraise_b') ORDER BY task_id DESC LIMIT 1"
            ),
            {"s": session},
        ).first()
    return None if row is None else str(row[0])


def _extraction_pass(project: Project, session: str) -> tuple[ScopeKey, PassLabel] | None:
    """The (scope, pass) of the extraction pass the session joined, if any."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT scope, pass_label FROM extraction_sessions WHERE session = :s"),
            {"s": session},
        ).first()
    return None if row is None else (scope_from_value(str(row[0])), PassLabel(str(row[1])))


def _held_pins(project: Project, session: str, kind: str, work_id: str) -> list[tuple[str, str]]:
    """(document, conversion) pinned for `work_id` by tasks of `kind` (a full-text screening or an
    extraction pass) that `session` holds or has completed, in task-ID order."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT content_blob FROM tasks WHERE kind = :kind AND claim_session = :s "
                "AND status IN ('claimed', 'completed') ORDER BY task_id"
            ),
            {"kind": kind, "s": session},
        ).all()
    pins: list[tuple[str, str]] = []
    for (blob,) in rows:
        content = project.blobs.get_json(str(blob))
        records = content.get("records") if isinstance(content, dict) else None
        for record in records if isinstance(records, list) else []:
            if (
                isinstance(record, dict)
                and _same_work(record.get("work_id"), work_id)
                and isinstance(record.get("document_id"), str)
                and isinstance(record.get("conversion_id"), str)
            ):
                pins.append((str(record["document_id"]), str(record["conversion_id"])))
    return pins


# --- Choosing the conversion ---


def _promoted(project: Project) -> frozenset[str]:
    return frozenset(
        work for work, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def promoted_works(project: Project) -> frozenset[str]:
    """The works promoted at title/abstract, whose documents a tool may show. Read-only."""
    project.index.sync()
    return _promoted(project)


def _select(
    project: Project, work_id: str, document_id: str | None, conversion_id: str | None
) -> Conversion:
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

    chosen = _default(project, work_id)
    if chosen is None:
        raise FactoryValidationError(
            [ValidationIssue("work_id", f"{work_id}: has no conversion; {_CONVERT_HINT}")]
        )
    return chosen


def _default(project: Project, work_id: str) -> Conversion | None:
    """The default conversion of a work: the first live document in route order (then document
    event order), at its latest conversion by event order; None when no live document of the work
    has a conversion."""
    live = [c for c in _query(project, "d.work_id = :work", {"work": work_id}) if c.live]
    if not live:
        return None
    preferred = _preferred_document(project, work_id)
    if preferred is not None and any(c.document_id == preferred for c in live):
        return max(
            (c for c in live if c.document_id == preferred),
            key=lambda c: c.conversion_event_id,
        )
    return _automatic(live)


def automatic_default_document(project: Project, work_id: str) -> str | None:
    """The document the automatic route order would serve for the work, ignoring any preference."""
    live = [c for c in _query(project, "d.work_id = :work", {"work": work_id}) if c.live]
    chosen = _automatic(live) if live else None
    return None if chosen is None else chosen.document_id


def _automatic(live: list[Conversion]) -> Conversion:
    first = min(live, key=lambda c: (_route_rank(c.route), c.document_event_id))
    return max(
        (c for c in live if c.document_id == first.document_id),
        key=lambda c: c.conversion_event_id,
    )


@dataclass(frozen=True)
class ConversionRef:
    """A conversion named by its document and its own id."""

    document_id: str
    conversion_id: str


def _preferred_document(project: Project, work_id: str) -> str | None:
    """The document a human prefers for the work (living-C), or None: no preference, or the latest
    act cleared the override by naming the automatic default. Whether the document is live and
    converted is the caller's check, so a lapsed preference falls back to the route order."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT document_id, automatic FROM document_preferences WHERE work_id = :work "
                "ORDER BY event_id DESC LIMIT 1"
            ),
            {"work": work_id},
        ).first()
    if row is None or row[1]:
        return None
    return str(row[0])


def default_conversion(project: Project, work_id: str) -> ConversionRef | None:
    """The conversion `document_read` serves for `work_id` when no document or conversion is named
    (plan 2B2 ruling 5), or None when the work has none. Read-only; the caller syncs the index."""
    chosen = _default(project, work_id)
    return None if chosen is None else ConversionRef(chosen.document_id, chosen.conversion_id)


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


# --- Anchors and pages ---


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
    only: frozenset[str] | None = None,
) -> tuple[list[Segment], str | None]:
    """The segments after `after` (all, if None), and the `next_after` of the page. With `only`,
    just the anchors whose id it holds (a miner's selected anchors)."""
    anchors = manifest.anchors
    if after is None:
        start = -1
    else:
        position = manifest.position(after)
        if position is None:
            raise FactoryValidationError(
                [ValidationIssue("after", f"{after}: not an anchor of {conversion_id}")]
            )
        start = position

    segments: list[Segment] = []
    used = 0
    index = start + 1
    end = len(anchors)
    while index < end:
        anchor = anchors[index]
        index += 1
        if anchor.kind is AnchorKind.CELL or (only is not None and anchor.id not in only):
            continue
        if len(segments) == limit:
            index -= 1
            break
        segment = _segment(anchor, PAGE_SEGMENT_MAX_CHARS)
        if segments and used + len(segment.text) > max_chars:
            index -= 1
            break
        segments.append(segment)
        used += len(segment.text)

    # `index` is the first anchor not consumed; more output exists iff a non-cell one follows.
    more = any(
        a.kind is not AnchorKind.CELL and (only is None or a.id in only)
        for a in islice(anchors, index, end)
    )
    next_after = segments[-1].anchor if segments and more else None
    return segments, next_after
