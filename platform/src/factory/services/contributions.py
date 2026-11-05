"""Contribution items: the checks and closing rule on top of plan D's machinery (slice 3b, G2-B).

A thin parameterisation of `services.extraction`: this module supplies the hooks that
`next_unit` and `record_unit` take for `Scope.CONTRIBUTION`, and nothing else records or serves.

Serving (`contribution_next`) attaches the unit's reference list (`UnitReferences`): `current`
(the work's current G1 extraction is pinned to the unit's conversion; its entries are listed, as
metadata only), `none` (no current extraction: `cited_entry` is unavailable) or `other-conversion`
(treated as `none`). Entries linked to, or identifying, a held-out seed's work are masked (R-20).
Reads (`live_items`, `final_items`, `contribution_status`) derive every count from the log's rows;
nothing is typed.

Invariants of the checks (`contribution_check`, applied to each verified item alone):
- `cited_entry = n` needs a current G1 extraction of the work pinned to the unit's conversion and
  an entry `n` in it, else the item is rejected. The marker check is then stored on the row as
  `cited`: `matched`, `mismatch` (flagged, stored) or `absent` (the entry is the agent's
  declaration; flagged, stored).
- `result_row` must be the row key of a live, not stale evidence row of the same work; its values
  are never copied.
- A `not-stated` item carries no anchor, cell or quote on any field; within a unit a live
  `not-stated` of kind K and a live item of kind K contradict, in either order of recording.
- Reasons come from a fixed vocabulary and never contain document text.

Invariants of the closing rule (`contribution_close_check`, applied when a call closes a unit):
`base-idea` and `limitation` are each covered (an item or `not-stated`) and at least one
`addition` is recorded; a unit with no `result` closes only with a reason. A unit with no live
item at all closes with a reason alone (the recorded escape of plan D for a document that states
no contribution).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.lineage.cited import item_evidence, marker_check
from factory.lineage.refs import ReferenceView
from factory.model.base import StrictModel
from factory.model.extraction import (
    CitedEntry,
    ExtractedRowInput,
    ExtractionAuditSampled,
    Scope,
    StoredField,
    UnitReferences,
)
from factory.model.screening import Channel, PassLabel
from factory.model.seed import HeldOut
from factory.services import seeds as seeds_service
from factory.services.context import Project
from factory.services.extraction import (
    DUPLICATE_ITEM,
    ContributionBatch,
    ContributionBatchContent,
    ExtraCheck,
    ExtractBatchContent,
    ExtractionRow,
    ExtractNext,
    ExtractResult,
    ExtraVerdict,
    UnitPin,
    live_rows,
    next_unit,
    record_unit,
    recorded_row,
    scope_population,
    stale_extractions,
    unit_pin,
    unit_states,
)
from factory.services.extraction_agreement import (
    Choice,
    ExtractionAgreement,
    FinalField,
    extraction_agreement,
    final_rows,
    resolve_extraction,
)
from factory.services.extraction_audit import (
    ExtractionAuditReport,
    extraction_audit_record,
    extraction_audit_report,
    extraction_audit_sample,
)
from factory.services.reference_view import briefs, reference_view_of
from factory.services.references import current_extraction
from factory.services.stages import scope_of_kind
from factory.services.tasks import get_task

__all__ = [
    "BASE_NOT_COVERED",
    "CONTRADICTS",
    "CONTRIBUTION_INSTRUCTIONS",
    "DUPLICATE_ITEM",
    "ENTRY_UNKNOWN",
    "LIMITATION_NOT_COVERED",
    "NOT_STATED_QUOTE",
    "NO_ADDITION",
    "NO_REFERENCES",
    "NO_RESULT_NEEDS_REASON",
    "OTHER_CONVERSION",
    "RESULT_ROW_UNKNOWN",
    "ContributionStatus",
    "ItemView",
    "checker_superseding",
    "contribution_agreement",
    "contribution_audit_record",
    "contribution_audit_report",
    "contribution_audit_sample",
    "contribution_check",
    "contribution_close_check",
    "contribution_item",
    "contribution_next",
    "contribution_record",
    "contribution_status",
    "final_items",
    "live_items",
    "mask_batch",
    "resolve_contribution",
]

NO_REFERENCES = "no-reference-extraction"
OTHER_CONVERSION = "reference-extraction-other-conversion"
ENTRY_UNKNOWN = "entry-unknown"
RESULT_ROW_UNKNOWN = "result-row-unknown"
NOT_STATED_QUOTE = "not-stated-has-no-quote"
CONTRADICTS = "contradicts-recorded-item"
BASE_NOT_COVERED = "base-idea-not-covered"
LIMITATION_NOT_COVERED = "limitation-not-covered"
NO_ADDITION = "no-addition"
NO_RESULT_NEEDS_REASON = "no-result-needs-reason"

_KIND = "item_kind"
_ABSENT = "absent_kind"
_NOT_STATED = "not-stated"


def _text(fields: Mapping[str, StoredField], name: str) -> str | None:
    stored = fields.get(name)
    return None if stored is None else str(stored.value)


def _kind_of(fields: Mapping[str, StoredField]) -> str:
    return _text(fields, _KIND) or ""


def _contradiction(
    fields: Mapping[str, StoredField], rows: Sequence[ExtractionRow], skip: Collection[str]
) -> bool:
    """Whether the item contradicts a live row of the unit: a `not-stated` of kind K against an
    item of kind K, or the reverse. Rows in `skip` (superseded in this call) do not count."""
    kind = _kind_of(fields)
    absent = _text(fields, _ABSENT)
    for row in rows:
        if row.extraction_id in skip:
            continue
        other = _kind_of(row.fields)
        if kind == _NOT_STATED and other == absent:
            return True
        if kind != _NOT_STATED and other == _NOT_STATED and _text(row.fields, _ABSENT) == kind:
            return True
    return False


class _Checker:
    """One call's checks. G1 and the evidence row keys are read once per unit (the index does
    not change during the call), so a batch of items reads each once."""

    def __init__(self, skip: Collection[str]) -> None:
        self._skip = frozenset(skip)
        self._views: dict[UnitPin, tuple[str, ReferenceView | None]] = {}
        self._result_rows: dict[str, frozenset[str]] = {}

    def __call__(
        self,
        project: Project,
        pin: UnitPin,
        fields: Mapping[str, StoredField],
        seen: Sequence[ExtractionRow],
    ) -> ExtraVerdict:
        issues: list[ValidationIssue] = []
        kind = _kind_of(fields)
        if kind == _NOT_STATED:
            for name, stored in fields.items():
                if stored.quote is not None or stored.anchor is not None or stored.cell is not None:
                    issues.append(ValidationIssue(f"fields.{name}.quote", NOT_STATED_QUOTE))
        if _contradiction(fields, seen, self._skip):
            issues.append(ValidationIssue(f"fields.{_KIND}.value", CONTRADICTS))
        row = fields.get("result_row")
        if row is not None and str(row.value) not in self._rows_of(project, pin.work_id):
            issues.append(ValidationIssue("fields.result_row.value", RESULT_ROW_UNKNOWN))
        cited, refusal = self._cited(project, pin, fields)
        if refusal is not None:
            issues.append(ValidationIssue("fields.cited_entry.value", refusal))
        return ExtraVerdict(cited=cited, issues=issues)

    def _rows_of(self, project: Project, work_id: str) -> frozenset[str]:
        if work_id not in self._result_rows:
            stale = stale_extractions(project)
            self._result_rows[work_id] = frozenset(
                r.row_key
                for r in live_rows(project, work_id=work_id)
                if r.extraction_id not in stale
            )
        return self._result_rows[work_id]

    def _view(self, project: Project, pin: UnitPin) -> tuple[str, ReferenceView | None]:
        """`("ok", view)`, or the refusal reason and None."""
        if pin not in self._views:
            extraction = current_extraction(project, pin.work_id)
            view = None if extraction is None else reference_view_of(project, extraction)
            if view is None:
                self._views[pin] = (NO_REFERENCES, None)
            elif view.conversion_id != pin.conversion_id:
                self._views[pin] = (OTHER_CONVERSION, None)
            else:
                self._views[pin] = ("ok", view)
        return self._views[pin]

    def _cited(
        self, project: Project, pin: UnitPin, fields: Mapping[str, StoredField]
    ) -> tuple[CitedEntry | None, str | None]:
        given = fields.get("cited_entry")
        if given is None:
            return None, None
        status, view = self._view(project, pin)
        if view is None:
            return None, status
        ordinal = int(given.value)
        if view.entry(ordinal) is None:
            return None, ENTRY_UNKNOWN
        evidence = item_evidence(fields)
        marker = (
            "absent"
            if evidence is None
            else marker_check(evidence[1], evidence[0], ordinal, view.contexts)
        )
        return CitedEntry(
            reference_extraction_id=view.extraction_id, ordinal=ordinal, marker=marker
        ), None


def contribution_check(
    project: Project,
    pin: UnitPin,
    fields: Mapping[str, StoredField],
    seen: Sequence[ExtractionRow],
) -> ExtraVerdict:
    """The `ExtraCheck` of contribution items (rulings 2-4); see the module docstring."""
    return _Checker(frozenset())(project, pin, fields, seen)


def checker_superseding(superseded: Collection[str]) -> ExtraCheck:
    """`contribution_check` for a call that supersedes the rows `superseded`: those rows, still
    live while their corrections are judged, take no part in the contradiction rule."""
    return _Checker(superseded)


def contribution_close_check(
    project: Project, pin: UnitPin, rows: Sequence[ExtractionRow], reason: str | None
) -> list[ValidationIssue]:
    """The `CloseCheck` of contribution units (ruling 5): issues on `finish` and `reason`."""
    del project, pin
    if not rows:
        return []  # plan D already requires the reason of a unit with nothing in it
    stated = {_kind_of(r.fields) for r in rows} - {_NOT_STATED}
    declared = {_text(r.fields, _ABSENT) for r in rows if _kind_of(r.fields) == _NOT_STATED}
    issues: list[ValidationIssue] = []
    if stated & declared:
        issues.append(ValidationIssue("finish", CONTRADICTS))
    if "base-idea" not in stated | declared:
        issues.append(ValidationIssue("finish", BASE_NOT_COVERED))
    if "limitation" not in stated | declared:
        issues.append(ValidationIssue("finish", LIMITATION_NOT_COVERED))
    if "addition" not in stated:
        issues.append(ValidationIssue("finish", NO_ADDITION))
    if "result" not in stated and not (reason or "").strip():
        issues.append(ValidationIssue("reason", NO_RESULT_NEEDS_REASON))
    return issues


# --- Serving ---

CONTRIBUTION_INSTRUCTIONS = (
    "Record the contribution items the pinned document states, reading only that document with "
    "document_read. Give each item its item_kind, and for every text field the verbatim quote "
    "that contains it and its anchor. One item per named predecessor. Never paraphrase a quote "
    "and never infer a base idea; declare not-stated only for an absent base idea or limitation. "
    "The wording rules for telling a base idea from an addition belong to the skill."
)
"""The fixed instructions of a contribution task (the wording rules are the skill's)."""

ITEM_RULES = [
    "one item per named predecessor; a sentence naming several is split into several items "
    "with the same quote",
    "cited_entry names an entry of the reference list, only when the quote's marker or the "
    "entry text identifies it",
    "a not-stated item names absent_kind (base-idea or limitation) and carries no quote or anchor",
    "a result item quotes its metric and value; result_row is the row key of an evidence row "
    "of the same work",
    "a unit closes when base-idea and limitation are each covered by an item or not-stated and "
    "an addition is recorded; a unit with no result item closes only with a reason",
]
"""The pack's conditional rules as the sentences served with each task."""


def _references(
    project: Project, work_id: str, conversion_id: str, held_out: HeldOut
) -> UnitReferences:
    extraction = current_extraction(project, work_id)
    view = None if extraction is None else reference_view_of(project, extraction)
    if view is None:
        return UnitReferences(status="none", extraction_id=None, entries=[])
    if view.conversion_id != conversion_id:
        return UnitReferences(status="other-conversion", extraction_id=None, entries=[])
    return UnitReferences(
        status="current", extraction_id=view.extraction_id, entries=briefs(view, held_out)
    )


def mask_batch(project: Project, batch: ContributionBatch, held_out: HeldOut) -> ContributionBatch:
    """`batch` with the entries of its reference list that touch a held-out seed masked (R-20),
    whatever the list was when the task was created."""
    references = batch.references
    if references.status != "current" or references.extraction_id is None:
        return batch
    view = reference_view_of(project, references.extraction_id)
    if view is None:
        return batch
    masked = references.model_copy(update={"entries": briefs(view, held_out)})
    return batch.model_copy(update={"references": masked})


def contribution_next(project: Project, actor: Actor, label: PassLabel) -> ExtractNext:
    """Serve the next contribution unit of pass `label`: `next_unit` with scope contribution and
    a content hook attaching the unit's reference list and the item rules."""
    held_out = seeds_service.held_out(project)

    def content(proj: Project, base: ExtractBatchContent) -> ExtractBatchContent:
        record = base.records[0]
        return ContributionBatchContent(
            **{**base.model_dump(), "instructions": CONTRIBUTION_INSTRUCTIONS},
            references=_references(proj, record["work_id"], record["conversion_id"], held_out),
            item_rules=list(ITEM_RULES),
        )

    served = next_unit(project, actor, label, scope=Scope.CONTRIBUTION, content=content)
    if isinstance(served.batch, ContributionBatch):
        return served.model_copy(update={"batch": mask_batch(project, served.batch, held_out)})
    return served


def contribution_record(
    project: Project,
    actor: Actor,
    task_id: str,
    items: Sequence[ExtractedRowInput],
    *,
    finish: bool = False,
    reason: str | None = None,
    supersedes: Mapping[int, str] | None = None,
) -> ExtractResult:
    """Record contribution items for a held contribution task, and close the unit on `finish`:
    `record_unit` with the contribution checks, the closing rule and the item duplicate message.
    Refused on `task_id` for a task that is not a contribution task; claims are always empty."""
    task = get_task(project, task_id)
    if task is None or scope_of_kind(task.kind) is not Scope.CONTRIBUTION:
        raise FactoryValidationError(
            [ValidationIssue("task_id", "not a contribution task; evidence uses extract_record")]
        )
    return record_unit(
        project,
        actor,
        task_id,
        items,
        finish=finish,
        reason=reason,
        supersedes=supersedes,
        extra_check=checker_superseding((supersedes or {}).values()),
        close_check=contribution_close_check,
        duplicate_reason=DUPLICATE_ITEM,
    )


# --- Reads ---


class ItemView(StrictModel):
    """A contribution item as the log holds it. `live`: no later row supersedes it; `stale`: its
    document, schema or reference extraction is no longer current. `anchor`/`quote` are the
    item's evidence (ruling 1), None for `not-stated`."""

    extraction_id: str
    work_id: str
    pass_label: PassLabel
    item_kind: str
    absent_kind: str | None
    name: str | None
    statement: str | None
    compared_to: str | None
    cited_entry: int | None
    metric: str | None
    value: str | None
    unit: str | None
    canonical: str | None
    result_row: str | None
    anchor: str | None
    quote: str | None
    document_id: str
    conversion_id: str
    cited: CitedEntry | None
    live: bool
    stale: bool
    event_id: str


def _view(
    fields: Mapping[str, StoredField] | Mapping[str, FinalField],
    row: ExtractionRow,
    *,
    extraction_id: str,
    cited: CitedEntry | None,
    live: bool,
    stale: bool,
) -> ItemView:
    def text_of(name: str) -> str | None:
        f = fields.get(name)
        return None if f is None else str(f.value)

    entry = text_of("cited_entry")
    value = fields.get("value")
    evidence = None
    for name in ("name", "statement", "compared_to"):
        f = fields.get(name)
        if f is not None and f.anchor is not None and f.quote is not None:
            evidence = (f.anchor, f.quote)
            break
    return ItemView(
        extraction_id=extraction_id,
        work_id=row.work_id,
        pass_label=row.pass_label,
        item_kind=text_of(_KIND) or "",
        absent_kind=text_of(_ABSENT),
        name=text_of("name"),
        statement=text_of("statement"),
        compared_to=text_of("compared_to"),
        cited_entry=None if entry is None else int(entry),
        metric=text_of("metric"),
        value=None if value is None else str(value.value),
        unit=None if value is None else value.unit,
        canonical=None if value is None else value.canonical,
        result_row=text_of("result_row"),
        anchor=None if evidence is None else evidence[0],
        quote=None if evidence is None else evidence[1],
        document_id=row.document_id,
        conversion_id=row.conversion_id,
        cited=cited,
        live=live,
        stale=stale,
        event_id=row.event_id,
    )


def _item_of(row: ExtractionRow, *, live: bool, stale: Collection[str]) -> ItemView:
    return _view(
        row.fields,
        row,
        extraction_id=row.extraction_id,
        cited=row.cited,
        live=live,
        stale=row.extraction_id in stale,
    )


def contribution_item(project: Project, extraction_id: str) -> ItemView | None:
    """Any recorded contribution row, live or superseded; None for an unknown id."""
    found = recorded_row(project, extraction_id, scope=Scope.CONTRIBUTION)
    if found is None:
        return None
    row, live = found
    return _item_of(row, live=live, stale=stale_extractions(project, scope=Scope.CONTRIBUTION))


def live_items(
    project: Project,
    *,
    work_id: str | None = None,
    kind: str | None = None,
    include_stale: bool = False,
) -> list[ItemView]:
    """The live items of both passes, by extraction id; stale ones only with `include_stale`."""
    stale = stale_extractions(project, scope=Scope.CONTRIBUTION)
    out = [
        _item_of(r, live=True, stale=stale)
        for r in live_rows(project, work_id=work_id, scope=Scope.CONTRIBUTION)
        if include_stale or r.extraction_id not in stale
    ]
    return [i for i in out if kind is None or i.item_kind == kind]


def final_items(project: Project) -> list[ItemView]:
    """One item per final row of the contribution scope (agreed, resolved, or single), built from
    its final fields; `extraction_id` is that of its `item_kind` field."""
    rows = {r.extraction_id: r for r in live_rows(project, scope=Scope.CONTRIBUTION)}
    stale = stale_extractions(project, scope=Scope.CONTRIBUTION)
    out: list[ItemView] = []
    for final in final_rows(project, scope=Scope.CONTRIBUTION):
        kind = final.fields.get(_KIND)
        if kind is None or kind.extraction_id not in rows:
            continue
        head = rows[kind.extraction_id]
        entry = final.fields.get("cited_entry")
        source = rows.get(entry.extraction_id) if entry is not None else None
        out.append(
            _view(
                final.fields,
                head,
                extraction_id=kind.extraction_id,
                cited=None if source is None else source.cited,
                live=True,
                stale=any(f.extraction_id in stale for f in final.fields.values()),
            )
        )
    return out


class ContributionStatus(StrictModel):
    """Counts computed from the log. `units`: unit state -> count; `items_by_kind` counts final
    rows by `item_kind` (`not-stated` included); `not_stated`: absent kind -> count; `markers`:
    marker state -> count of final items with a cited entry; `no_references`: population works
    without a current G1 extraction; `other_conversion`: works whose current extraction pins
    another conversion than their unit's."""

    units: dict[str, int]
    items_by_kind: dict[str, int]
    not_stated: dict[str, int]
    markers: dict[str, int]
    no_references: list[str]
    other_conversion: list[str]


def contribution_status(project: Project) -> ContributionStatus:
    """The contribution counts. Empty, with no refusal, until the schema is declared."""
    scope = Scope.CONTRIBUTION
    units = Counter(s.state for s in unit_states(project, scope=scope))
    finals = final_items(project)
    try:
        population = scope_population(project, scope)
    except FactoryValidationError:
        population = []
    none: list[str] = []
    other: list[str] = []
    for work_id in population:
        extraction = current_extraction(project, work_id)
        if extraction is None:
            none.append(work_id)
            continue
        view = reference_view_of(project, extraction)
        pin = unit_pin(project, work_id, scope=scope)
        if view is not None and pin is not None and view.conversion_id != pin[1]:
            other.append(work_id)
    return ContributionStatus(
        units=dict(sorted(units.items())),
        items_by_kind=dict(sorted(Counter(i.item_kind for i in finals).items())),
        not_stated=dict(
            sorted(
                Counter(i.absent_kind or "" for i in finals if i.item_kind == _NOT_STATED).items()
            )
        ),
        markers=dict(
            sorted(Counter(i.cited.marker for i in finals if i.cited is not None).items())
        ),
        no_references=none,
        other_conversion=other,
    )


# --- Agreement, resolution and audit (plan D with the scope fixed) ---


def contribution_agreement(project: Project, actor: Actor) -> ExtractionAgreement:
    """`extraction_agreement` for contribution items. In a row disagreement the `value` shown is
    the item's `item_kind`."""
    return extraction_agreement(project, actor, scope=Scope.CONTRIBUTION)


def resolve_contribution(
    project: Project,
    actor: Actor,
    work_id: str,
    row_key: str,
    field: str | None,
    choice: Choice,
    reason: str,
    channel: Channel,
) -> str:
    """`resolve_extraction` for a contribution item; returns the event id."""
    return resolve_extraction(
        project, actor, work_id, row_key, field, choice, reason, channel, scope=Scope.CONTRIBUTION
    )


def contribution_audit_sample(
    project: Project, actor: Actor, *, random_seed: int | None = None
) -> ExtractionAuditSampled:
    """`extraction_audit_sample` over the agreed contribution values (`not-stated` items and
    `cited_entry` values included)."""
    return extraction_audit_sample(
        project, actor, random_seed=random_seed, scope=Scope.CONTRIBUTION
    )


def contribution_audit_record(
    project: Project,
    actor: Actor,
    audit_id: str,
    work_id: str,
    row_key: str,
    field: str,
    correct: bool,
    note: str,
    channel: Channel,
) -> str:
    """`extraction_audit_record` for a sampled contribution value; returns the event id."""
    return extraction_audit_record(
        project, actor, audit_id, work_id, row_key, field, correct, note, channel
    )


def contribution_audit_report(project: Project) -> ExtractionAuditReport | None:
    """The latest contribution audit with its error rate; None when none was drawn."""
    return extraction_audit_report(project, scope=Scope.CONTRIBUTION)
