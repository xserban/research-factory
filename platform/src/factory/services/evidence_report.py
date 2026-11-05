"""The evidence report: groups of comparable final rows, counts, claims and limits (plan E).

A derived read model (ruling 1): `evidence_report` reads the projection through plan D's services,
writes nothing, and is recomputed on every call. `assemble_report` is the pure part: it turns the
gathered `ReportInputs` into an `EvidenceReport`.

Invariants:
- Groups are D's `grouped_rows` groups, one per identical comparability key, listed in
  lexicographic key order with `group_id = "grp_" + sha256(json key)[:12]` (ruling 2). No field
  orders, scores or compares across groups.
- Rows in a group are sorted by (normalised method, work, row key), never by value (ruling 3).
- Counts come from D's `independence_counts`; source flags state single-paper,
  single-independent-source and copied-only groups (ruling 4). Direction follows ruling 5.
- Claims are live pass-A claims, minus stale claims, of works in the extraction population;
  grouped by claim type, unmerged and unranked (ruling 10).
- Every `Limit` is generated from ids, counts and fixed sentences; none carries document text
  (ruling 11). Quotes appear only as the verified quote fields of rows and claims.
- Nothing is final before pass B opens; the report is then `provisional` and says why. It is also
  provisional while a unit is open, stale or queued with a document, or a disagreement is
  unresolved.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from factory.errors import FactoryValidationError
from factory.evidence.pareto import Point, pareto, speed_ratio
from factory.extraction.numbers import canonical, normalise_for, normalise_text, parse_printed
from factory.model.base import StrictModel
from factory.model.extraction import ClaimType, EvidenceType, ReportedIn, Strength
from factory.model.notices import WorkNoticeState
from factory.model.screening import PassLabel
from factory.packs import FieldKind, Pack, ReportSpec, UnitFamily
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ClaimRow,
    extraction_population,
    live_claims,
    live_rows,
    pass_config,
    require_schema,
    stale_claims,
    stale_extractions,
    unit_states,
)
from factory.services.extraction_agreement import (
    NON_COMPARABLE_KEYS,
    AgreementOverall,
    FinalField,
    FinalRow,
    Grouped,
    agreement_overall,
    grouped_rows,
    independence_counts,
    key_value,
)
from factory.services.extraction_audit import (
    ExtractionAuditReport,
    extraction_audit_outstanding,
    extraction_audit_report,
)
from factory.services.notices import work_states
from factory.services.search import get_work

__all__ = [
    "REPORT_VERSION",
    "ClaimEntry",
    "EvidenceReport",
    "EvidenceRow",
    "Excluded",
    "ExpectationResult",
    "FrontierAxis",
    "FrontierPartition",
    "FrontierPoint",
    "GroupCounts",
    "GroupReport",
    "Limit",
    "MethodConflict",
    "Provenance",
    "Quality",
    "ReportInputs",
    "agent_evidence",
    "assemble_report",
    "cost_value",
    "evidence_report",
    "group_direction",
    "group_id",
    "metric_of",
    "numeric_value",
    "plain_decimal",
    "report_inputs",
    "report_spec",
]

REPORT_VERSION = 1
"""Version of the derivation; recorded in every report with the pack and its version."""

DirectionStatus = Literal["declared", "pack-default", "conflict", "unparseable", "unknown"]
ExcludedReason = Literal[
    "unresolved", "stale", "missing-value", "no-final-row", "retracted", "correction-pending"
]


# --- Models ---


class Provenance(StrictModel):
    """One shown cell of a final row and where it came from; `trace_id` is `<row_key>/<field>`."""

    field: str
    value: str | bool
    unit: str | None
    canonical: str | None
    anchor: str | None
    cell: str | None
    quote: str | None
    reported_in: ReportedIn
    copy_marker: bool
    reproduced: bool
    cited_work: str | None
    extraction_id: str
    trace_id: str


class EvidenceRow(StrictModel):
    row_key: str
    work_id: str
    title: str
    document_id: str
    conversion_id: str
    status: Literal["agreed", "resolved", "single"]
    independent: bool
    method_name: str | None
    variant: str | None
    is_proposed: bool | None
    value: Provenance
    costs: dict[str, Provenance]
    """Hardware-independent cost cells (`ReportSpec.display_costs`); never a speed field."""
    regime: dict[str, str]
    notice: str | None = None
    """The notice flag of the row's work (`retracted`, `correction-pending`, `concern`), set only
    when a notice labels it (living-C); omitted from the serialised row otherwise."""

    @model_serializer(mode="wrap")
    def _omit_empty_notice(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """A row no notice labels serialises exactly as it did before notices existed."""
        data: dict[str, Any] = handler(self)
        if self.notice is None:
            data.pop("notice", None)
        return data


class Limit(StrictModel):
    """A platform-generated statement of what the corpus does not support. `subject` is an id
    (group, work) or None; `text` is a fixed sentence with ids and counts only."""

    code: str
    text: str
    subject: str | None


class GroupCounts(StrictModel):
    independent: int
    copied: int
    works: int
    independent_works: int


class MethodConflict(StrictModel):
    """Independent rows of one normalised (method, variant) in a group whose values differ;
    listed, never averaged. When `metric` is not a group key, rows are compared only within one
    normalised metric, named in `metric` (None when the metric is a key)."""

    method: str
    variant: str | None
    rows: list[str]
    metric: str | None = None


class FrontierPoint(StrictModel):
    """One independent row plotted on a cost axis; `cost` and `metric` are canonical decimal
    strings, `trace_id` is `<row_key>/value`."""

    row_key: str
    work_id: str
    method_name: str | None
    cost: str
    metric: str
    on_frontier: bool
    dominated_by: str | None
    trace_id: str


class FrontierPartition(StrictModel):
    """Points sharing a value unit (and a resolution, and a normalised metric, when that is not a
    group key); compared only with each other. `metric` is None when the metric is a key."""

    unit: str | None
    resolution: str | None
    points: list[FrontierPoint]
    statement: str | None
    metric: str | None = None


class FrontierAxis(StrictModel):
    """The frontier on one hardware-independent cost axis. `missing` maps `cost-missing`,
    `cost-not-positive` and `value-not-numeric` to the row keys left out for that reason."""

    axis: str
    partitions: list[FrontierPartition]
    missing: dict[str, list[str]]
    statement: str | None = None
    """Set when no independent row reports this cost, so the axis has no partition."""


class GroupReport(StrictModel):
    group_id: str
    key: list[tuple[str, str]]
    rows: list[EvidenceRow]
    counts: GroupCounts
    direction: bool | None
    direction_status: DirectionStatus
    frontiers: list[FrontierAxis] = Field(default_factory=list)
    method_conflicts: list[MethodConflict]
    statements: list[Limit]


class ClaimEntry(StrictModel):
    claim_id: str
    work_id: str
    claim_type: ClaimType
    evidence_type: EvidenceType
    strength: Strength
    """The extracting agent's judgement, not the platform's."""
    statement: str
    anchor: str
    quote: str
    trace_id: str


class Excluded(StrictModel):
    """Rows (or, for `no-final-row`, included works) left out of the report, by reason."""

    reason: ExcludedReason
    count: int
    works: list[str]


class ExpectationResult(StrictModel):
    """A partial key the caller expected (ruling 12) and the groups it matches."""

    expect: dict[str, str]
    group_ids: list[str]


class Quality(StrictModel):
    dual_works: int
    single_extraction_works: int
    agreement_overall: float | None
    audit_n: int
    """Labelled items of the latest audit."""
    audit_error_rate: float | None
    audit_above_ceiling: bool | None
    agreement_rows_aligned: int
    """Aligned dual rows over which `agreement_overall` is computed."""
    agreement_rows_unmatched: int
    """Dual row keys held by one pass only (or twice by one pass); outside the agreement."""


class WithinPaperRatio(StrictModel):
    """How many times faster a proposed row is than a baseline row of the same paper (ruling 7).

    Both rows are in one group; both speed cells are effectively own, share unit and the pack's
    speed context (`ReportSpec.speed_context`); the ratio is a two-place string. `hardware` is
    the normalised text (None when hardware is not a context field); `context` maps every
    context field to the proposed row's printed value (None when absent)."""

    work_id: str
    document_id: str
    field: Literal["throughput", "latency"]
    method: str
    baseline_method: str
    ratio: str
    unit: str | None
    hardware: str | None
    batch_size: str | None
    precision: str | None
    proposed: Provenance
    baseline: Provenance
    context: dict[str, str | None] = Field(default_factory=dict)


class EvidenceReport(StrictModel):
    project_protocol_id: str | None
    pack: str | None
    pack_version: int | None
    report_version: int
    comparability_keys: list[str]
    provisional: bool
    groups: list[GroupReport]
    ungrouped: list[EvidenceRow]
    claims: dict[str, list[ClaimEntry]]
    excluded: list[Excluded]
    expectations: list[ExpectationResult]
    quality: Quality
    limits: list[Limit]
    speed_ratios: list[WithinPaperRatio] = Field(default_factory=list)
    """Sorted by (work, field, method, baseline); never inside a group table (ruling 7)."""
    speed_unpaired: dict[str, int] = Field(default_factory=dict)
    """Reason -> count of proposed/baseline speed pairs that were not formed."""


# --- Inputs ---


@dataclass(frozen=True)
class ReportInputs:
    """What the report is computed from, read once from the projection.

    `stale` holds the (work, row key) of live stale rows of included works; `claims` the claims
    to show (already filtered); `blocking` is True while a unit is open, stale, or queued with a
    document to extract from."""

    protocol_id: str | None
    pack: Pack | None
    keys: tuple[str, ...]
    grouped: Grouped
    stale: Sequence[tuple[str, str]]
    population: Sequence[str]
    titles: Mapping[str, str]
    claims: Sequence[ClaimRow]
    pass_b_open: bool
    blocking: bool
    agreement: AgreementOverall
    audit: ExtractionAuditReport | None
    audit_outstanding: bool
    declared_fields: tuple[str, ...] | None = None
    """Field names the protocol's extraction schema declares; a frontier axis must be among them.
    None leaves the pack as the only restriction."""
    notice_states: Mapping[str, WorkNoticeState] = field(default_factory=dict)
    """Read-time notice states of the works with a notice (living-C)."""


def report_inputs(project: Project) -> ReportInputs | None:
    """Gather the inputs; None without a ready protocol, a known extraction schema and a full-text
    plan. Read-only."""
    project.index.sync()
    try:
        protocol, schema, pack = require_schema(project)
        population = extraction_population(project)
    except FactoryValidationError:
        return None
    included = set(population)
    stale_ids = stale_extractions(project)
    stale = sorted(
        {
            (row.work_id, row.row_key)
            for row in live_rows(project)
            if row.extraction_id in stale_ids and row.work_id in included
        }
    )
    blocking = any(
        s.state in ("open", "stale")
        or (s.state == "queued" and default_conversion(project, s.work_id) is not None)
        for s in unit_states(project)
    )
    stale_claim_ids = stale_claims(project)
    claims = [
        c
        for c in live_claims(project, PassLabel.A)
        if c.claim_id not in stale_claim_ids and c.work_id in included
    ]
    grouped = grouped_rows(project)
    shown = {r.work_id for rows in grouped.groups.values() for r in rows}
    shown |= {r.work_id for r in grouped.ungrouped} | included
    titles: dict[str, str] = {}
    for work_id in sorted(shown):
        work = get_work(project, work_id)
        titles[work_id] = "" if work is None else work.title
    return ReportInputs(
        protocol_id=protocol.protocol_id,
        pack=pack,
        keys=tuple(schema.comparability_keys or pack.default_comparability_keys),
        grouped=grouped,
        stale=stale,
        population=population,
        titles=titles,
        claims=claims,
        pass_b_open=pass_config(project, PassLabel.B) is not None,
        blocking=blocking,
        agreement=agreement_overall(project),
        audit=extraction_audit_report(project),
        audit_outstanding=extraction_audit_outstanding(project),
        declared_fields=tuple(schema.fields),
        notice_states=work_states(project),
    )


def evidence_report(
    project: Project,
    *,
    expect: Sequence[Mapping[str, str]] = (),
    include_notice_affected: bool = False,
) -> EvidenceReport:
    """The evidence report of the project, recomputed from the projection. Never raises for a
    missing schema: the report is then empty with the limit `no-extraction`. Writes nothing.

    By default the rows of works a notice excludes leave the report (see `assemble_report`);
    `include_notice_affected` is the researcher's wider view and is never offered to an agent."""
    inputs = report_inputs(project)
    if inputs is None:
        return _empty(expect)
    return assemble_report(inputs, expect=expect, include_notice_affected=include_notice_affected)


def agent_evidence(report: EvidenceReport) -> EvidenceReport:
    """The report as an agent outside the passes may read it: no label-derived audit rate or
    ceiling flag (decision 37.14). Any `audit-above-ceiling` limit is dropped, and the fixed limit
    `audit-reported-to-researcher` is present whenever an audit is labelled, whatever the flag, so
    the limits do not reveal it. Counts (`audit_n`) are unchanged; the researcher's view keeps
    the rate."""
    limits = [lim for lim in report.limits if lim.code != "audit-above-ceiling"]
    if report.quality.audit_n > 0:
        limits.append(
            Limit(
                code="audit-reported-to-researcher",
                text="The audit result is reported to the researcher and withheld from the "
                "agent view.",
                subject=None,
            )
        )
    quality = report.quality.model_copy(
        update={"audit_error_rate": None, "audit_above_ceiling": None}
    )
    return report.model_copy(update={"quality": quality, "limits": limits})


# --- Assembly (pure) ---

_NO_EXTRACTION = Limit(
    code="no-extraction", text="No extracted row is final; the report is empty.", subject=None
)
_CLAIMS_NOT_CHECKED = Limit(
    code="claims-not-cross-checked",
    text="Claims are listed as extracted; they are not cross-checked against each other.",
    subject=None,
)


def _empty(expect: Sequence[Mapping[str, str]]) -> EvidenceReport:
    expectations = [ExpectationResult(expect=dict(e), group_ids=[]) for e in expect]
    return EvidenceReport(
        project_protocol_id=None,
        pack=None,
        pack_version=None,
        report_version=REPORT_VERSION,
        comparability_keys=[],
        provisional=True,
        groups=[],
        ungrouped=[],
        claims={},
        excluded=[],
        expectations=expectations,
        quality=Quality(
            dual_works=0,
            single_extraction_works=0,
            agreement_overall=None,
            audit_n=0,
            audit_error_rate=None,
            audit_above_ceiling=None,
            agreement_rows_aligned=0,
            agreement_rows_unmatched=0,
        ),
        limits=[_NO_EXTRACTION, *_expectation_limits(expectations)],
    )


def assemble_report(
    inputs: ReportInputs,
    *,
    expect: Sequence[Mapping[str, str]] = (),
    include_notice_affected: bool = False,
) -> EvidenceReport:
    """The report from `inputs`. Pure and deterministic: the same inputs, in any row order,
    give the same report.

    Notices (living-C, spec ruling 12): the rows, claims and population entries of a work whose
    notice state excludes it (`synthesis = excluded`) leave the report, so it equals the report
    without that work, and an `Excluded` entry `retracted` lists them. The rows of a work with a
    correction pending stay in their groups, labelled, but leave the frontiers; an `Excluded`
    entry `correction-pending` lists them. A row of a labelled work carries its notice flag.
    `include_notice_affected` keeps every row in place and only labels it.
    """
    states = inputs.notice_states
    hidden = (
        frozenset()
        if include_notice_affected
        else frozenset(w for w, s in states.items() if s.synthesis == "excluded")
    )
    skip = (
        frozenset()
        if include_notice_affected
        else frozenset(w for w, s in states.items() if s.flag == "correction-pending")
    )
    removed = _rows_of(inputs, hidden)
    kept = _without_works(inputs, hidden) if hidden else inputs
    report = _assemble(kept, expect, skip)
    report = _labelled(report, states)
    extra: list[Excluded] = []
    gone = sorted({w for w, _ in removed} | (hidden & set(inputs.population)))
    if gone:
        extra.append(Excluded(reason="retracted", count=len(removed) or len(gone), works=gone))
    pending = sorted(
        (r.work_id, r.row_key)
        for rows in [*(g.rows for g in report.groups), report.ungrouped]
        for r in rows
        if r.work_id in skip
    )
    if pending:
        extra.append(
            Excluded(
                reason="correction-pending",
                count=len(pending),
                works=sorted({w for w, _ in pending}),
            )
        )
    if not extra:
        return report
    return report.model_copy(update={"excluded": [*report.excluded, *extra]})


def _rows_of(inputs: ReportInputs, works: frozenset[str]) -> list[tuple[str, str]]:
    """The (work, row key) of every final row of `works`, grouped or not."""
    if not works:
        return []
    rows = [r for members in inputs.grouped.groups.values() for r in members]
    rows += inputs.grouped.ungrouped
    return sorted((r.work_id, r.row_key) for r in rows if r.work_id in works)


def _without_works(inputs: ReportInputs, hidden: frozenset[str]) -> ReportInputs:
    """`inputs` as if the works in `hidden` had no rows, claims or place in the population."""
    groups = {
        key: kept
        for key, members in inputs.grouped.groups.items()
        if (kept := [r for r in members if r.work_id not in hidden])
    }
    grouped = Grouped(
        groups=groups,
        ungrouped=[r for r in inputs.grouped.ungrouped if r.work_id not in hidden],
        unresolved=[d for d in inputs.grouped.unresolved if d.work_id not in hidden],
    )
    return dataclasses.replace(
        inputs,
        grouped=grouped,
        population=[w for w in inputs.population if w not in hidden],
        stale=[(w, k) for w, k in inputs.stale if w not in hidden],
        claims=[c for c in inputs.claims if c.work_id not in hidden],
    )


def _labelled(report: EvidenceReport, states: Mapping[str, WorkNoticeState]) -> EvidenceReport:
    """The report with each row of a flagged work carrying its notice flag."""
    flags = {w: s.flag for w, s in states.items() if s.flag != "none"}
    if not flags:
        return report

    def label(rows: list[EvidenceRow]) -> list[EvidenceRow]:
        return [
            r.model_copy(update={"notice": flags[r.work_id]}) if r.work_id in flags else r
            for r in rows
        ]

    groups = [g.model_copy(update={"rows": label(g.rows)}) for g in report.groups]
    return report.model_copy(update={"groups": groups, "ungrouped": label(report.ungrouped)})


def _assemble(
    inputs: ReportInputs, expect: Sequence[Mapping[str, str]], skip: frozenset[str]
) -> EvidenceReport:
    """The report of `inputs`; the works in `skip` take no part in any frontier."""
    pack = inputs.pack
    if pack is None:
        return _empty(expect)
    spec = _spec(pack)
    keys = [k for k in inputs.keys if k not in NON_COMPARABLE_KEYS]
    missing_value: list[FinalRow] = []

    def keep(rows: Sequence[FinalRow]) -> list[FinalRow]:
        out = []
        for row in rows:
            if spec.value_field in row.fields:
                out.append(row)
            else:
                missing_value.append(row)
        return out

    groups: list[GroupReport] = []
    for key, members in inputs.grouped.groups.items():
        rows = keep(members)
        if rows:
            groups.append(
                _group(list(key), rows, pack, spec, inputs.titles, inputs.declared_fields, skip)
            )
    groups.sort(key=lambda g: g.key)
    ungrouped = _rows(keep(inputs.grouped.ungrouped), spec, inputs.titles, pack)

    finals = {r.work_id for g in groups for r in g.rows} | {r.work_id for r in ungrouped}
    excluded = _excluded(inputs, missing_value, finals)
    expectations = [_expectation(e, groups, pack) for e in expect]
    quality = _quality(inputs)
    provisional = (
        not inputs.pass_b_open
        or inputs.blocking
        or bool(inputs.grouped.unresolved)
        or not (groups or ungrouped)
    )
    limits = _limits(inputs, groups, ungrouped, excluded, expectations, quality, finals)
    ratios, unpaired = _speed(inputs.grouped, spec, pack)
    return EvidenceReport(
        project_protocol_id=inputs.protocol_id,
        pack=pack.name,
        pack_version=pack.version,
        report_version=REPORT_VERSION,
        comparability_keys=keys,
        provisional=provisional,
        groups=groups,
        ungrouped=ungrouped,
        claims=_claims(inputs.claims, set(inputs.population)),
        excluded=excluded,
        expectations=expectations,
        quality=quality,
        limits=limits,
        speed_ratios=ratios,
        speed_unpaired=unpaired,
    )


def report_spec(pack: Pack) -> ReportSpec:
    """The pack's report spec, or an empty one (no costs, no known directions)."""
    return _spec(pack)


def _spec(pack: Pack) -> ReportSpec:
    if pack.report is not None:
        return pack.report
    return ReportSpec(
        value_field="value",
        direction_field="higher_is_better",
        metric_directions={},
        frontier_costs=(),
        speed_fields={},
        speed_context=(),
        proposed_field="is_proposed",
        display_costs=(),
    )


# --- Rows ---


def _provenance(row_key: str, name: str, f: FinalField) -> Provenance:
    return Provenance(
        field=name,
        value=f.value,
        unit=f.unit,
        canonical=f.canonical,
        anchor=f.anchor,
        cell=f.cell,
        quote=f.quote,
        reported_in=f.reported_in,
        copy_marker=f.copy_marker,
        reproduced=f.reproduced,
        cited_work=f.cited_work,
        extraction_id=f.extraction_id,
        trace_id=f"{row_key}/{name}",
    )


def _as_bool(f: FinalField | None) -> bool | None:
    if f is None:
        return None
    if isinstance(f.value, bool):
        return f.value
    text = normalise_text(f.value)
    if text in ("true", "yes", "1"):
        return True
    if text in ("false", "no", "0"):
        return False
    return None


def _text(f: FinalField | None) -> str | None:
    return None if f is None else str(f.value)


def _display(f: FinalField) -> str:
    if isinstance(f.value, bool):
        return "true" if f.value else "false"
    return f"{f.value} {f.unit}" if f.unit else f.value


_REGIME_GROUP = "regime"


def _row(
    row: FinalRow, spec: ReportSpec, titles: Mapping[str, str], pack: Pack | None
) -> EvidenceRow:
    regime_fields = (
        [d.name for d in pack.fields if d.group == _REGIME_GROUP] if pack is not None else []
    )
    return EvidenceRow(
        row_key=row.row_key,
        work_id=row.work_id,
        title=titles.get(row.work_id, ""),
        document_id=row.document_id,
        conversion_id=row.conversion_id,
        status=row.status,
        independent=row.independent,
        method_name=_text(row.fields.get("method_name")),
        variant=_text(row.fields.get("variant")),
        is_proposed=_as_bool(row.fields.get(spec.proposed_field)),
        value=_provenance(row.row_key, spec.value_field, row.fields[spec.value_field]),
        costs={
            name: _provenance(row.row_key, name, row.fields[name])
            for name in spec.display_costs
            if name in row.fields and name not in spec.speed_fields
        },
        regime={name: _display(row.fields[name]) for name in regime_fields if name in row.fields},
    )


def _row_order(row: EvidenceRow) -> tuple[str, str, str]:
    return normalise_text(row.method_name or ""), row.work_id, row.row_key


def _rows(
    rows: Sequence[FinalRow], spec: ReportSpec, titles: Mapping[str, str], pack: Pack | None = None
) -> list[EvidenceRow]:
    return sorted((_row(r, spec, titles, pack) for r in rows), key=_row_order)


# --- Groups ---


def group_id(key: Sequence[tuple[str, str]]) -> str:
    """`grp_` and the first 12 hex digits of the sha256 of the JSON key pairs (ruling 2)."""
    blob = json.dumps([list(pair) for pair in key])
    return "grp_" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def _group(
    key: list[tuple[str, str]],
    rows: list[FinalRow],
    pack: Pack,
    spec: ReportSpec,
    titles: Mapping[str, str],
    declared: Sequence[str] | None = None,
    frontier_skip: frozenset[str] = frozenset(),
) -> GroupReport:
    gid = group_id(key)
    counts = independence_counts(rows)
    works = {r.work_id for r in rows}
    independent_works = {r.work_id for r in rows if r.independent}
    group_counts = GroupCounts(
        independent=counts.independent,
        copied=counts.copied,
        works=len(works),
        independent_works=len(independent_works),
    )
    direction, status = group_direction(key, rows, pack, spec)
    statements: list[Limit] = []
    if len(works) == 1:
        statements.append(
            Limit(
                code="single-paper", text="All rows of this group come from one work.", subject=gid
            )
        )
    if len(independent_works) <= 1:
        statements.append(
            Limit(
                code="single-independent-source",
                text=f"At most one work reports an own result in this group "
                f"({len(independent_works)}).",
                subject=gid,
            )
        )
    if counts.independent == 0:
        statements.append(
            Limit(
                code="no-independent-results",
                text=f"This group holds only copied results ({counts.copied} rows).",
                subject=gid,
            )
        )
    if status == "conflict":
        statements.append(
            Limit(
                code="direction-conflict",
                text="The declared metric direction is inconsistent; no frontier is computed.",
                subject=gid,
            )
        )
    elif status == "unparseable":
        statements.append(
            Limit(
                code="direction-unparseable",
                text="A declared metric direction is not a boolean; no frontier is computed.",
                subject=gid,
            )
        )
    elif status == "unknown":
        statements.append(
            Limit(
                code="direction-unknown",
                text="The metric direction is neither declared nor known to the pack; "
                "no frontier is computed.",
                subject=gid,
            )
        )
    shown = _rows(rows, spec, titles, pack)
    frontiers: list[FrontierAxis] = []
    if status in ("declared", "pack-default") and direction is not None:
        frontiers = _frontiers(
            [r for r in rows if r.work_id not in frontier_skip],
            pack,
            spec,
            dict(key),
            direction,
            declared,
        )
        for axis in frontiers:
            for part in axis.partitions:
                if part.statement is not None:
                    statements.append(
                        Limit(
                            code="frontier-single-point",
                            text=f"Axis {axis.axis}: {part.statement}",
                            subject=gid,
                        )
                    )
    return GroupReport(
        group_id=gid,
        key=key,
        rows=shown,
        counts=group_counts,
        direction=direction,
        direction_status=status,
        frontiers=frontiers,
        method_conflicts=_conflicts(shown, _metrics_of(rows, pack, dict(key))),
        statements=statements,
    )


def _decimal(f: FinalField) -> Decimal | None:
    """The canonical number of a field, else its printed number; None unless finite."""
    if isinstance(f.value, bool):
        return None
    try:
        d = Decimal(f.canonical) if f.canonical is not None else parse_printed(str(f.value))
    except InvalidOperation:
        return None
    return d if d is not None and d.is_finite() else None


def numeric_value(f: FinalField) -> Decimal | None:
    """The finite canonical (else printed) number of a final field, or None."""
    return _decimal(f)


def cost_value(f: FinalField, family: UnitFamily) -> Decimal | None:
    """A cost field's finite canonical number, or None (as the frontiers read it)."""
    return _cost_decimal(f, family)


def plain_decimal(d: Decimal) -> str:
    """A decimal in plain notation, as the report prints metrics and costs."""
    return _plain(d)


def metric_of(row: FinalRow, pack: Pack) -> str:
    """The row's normalised metric as a group key would hold it; "" when absent."""
    return _metric_of(row, pack)


def _cost_decimal(f: FinalField, family: UnitFamily) -> Decimal | None:
    """A cost's canonical number; without one, the printed number scaled by its unit. None when
    the unit is outside the family's vocabulary or the number is not finite."""
    if f.canonical is not None or isinstance(f.value, bool):
        return _decimal(f)
    printed = parse_printed(str(f.value))
    if printed is None:
        return None
    try:
        d = Decimal(canonical(printed, f.unit, family))
    except (ValueError, InvalidOperation):
        return None
    return d if d.is_finite() else None


# --- Speed ---


def _own(f: FinalField) -> bool:
    return f.reported_in is ReportedIn.OWN and not f.copy_marker


def _context(row: FinalRow, name: str, pack: Pack) -> str | None:
    """A speed-context field's comparable value: by the pack's normaliser when it declares one
    (so 224 and 224x224 are one resolution), else the normalised text; None when absent."""
    f = row.fields.get(name)
    if f is None:
        return None
    definition = pack.field(name)
    if definition is not None and definition.normaliser is not None:
        return key_value(definition, f)
    return normalise_text(str(f.value))


_HARDWARE = "hardware"


def _speed(
    grouped: Grouped, spec: ReportSpec, pack: Pack
) -> tuple[list[WithinPaperRatio], dict[str, int]]:
    """Proposed/baseline speed ratios inside one work and document (ruling 7, decision 52).

    Only effectively own speed cells of rows in the same group (identical comparability key)
    with equal unit and equal `spec.speed_context` values are paired: `hardware`, when it is a
    context field, must be present in both; every other context field must be equal or absent
    in both. Every other proposed/baseline pair is counted under its reason: `key-missing` (a
    row in no group), `group-differs`, `not-own`, `unit-differs`, `hardware-missing`,
    `hardware-differs`, `context-differs`, `value-unusable`. A proposed speed cell with no
    baseline speed cell in its paper counts once as `no-baseline`. Units are compared as text:
    convertible but different units count as `unit-differs`, nothing is scaled. A row with no
    `is_proposed` is ignored. Pairs with the same ruling key collapse when their values are
    equal; when the values differ both are dropped and counted once as `ambiguous`."""
    unpaired: dict[str, int] = {}
    found: dict[tuple[str, ...], WithinPaperRatio] = {}
    values: dict[tuple[str, ...], tuple[Decimal, Decimal]] = {}
    ambiguous: set[tuple[str, ...]] = set()
    context = spec.speed_context

    def skip(reason: str) -> None:
        unpaired[reason] = unpaired.get(reason, 0) + 1

    tagged: list[tuple[str | None, FinalRow]] = [
        (group_id(list(key)), r) for key, members in grouped.groups.items() for r in members
    ]
    tagged += [(None, r) for r in grouped.ungrouped]
    papers: dict[tuple[str, str], list[tuple[str | None, FinalRow]]] = {}
    for gid, row in sorted(tagged, key=lambda t: t[1].row_key):
        papers.setdefault((row.work_id, row.document_id), []).append((gid, row))
    for (work, document), members in sorted(papers.items()):
        proposed = [m for m in members if _as_bool(m[1].fields.get(spec.proposed_field)) is True]
        baselines = [m for m in members if _as_bool(m[1].fields.get(spec.proposed_field)) is False]
        for name, higher in sorted(spec.speed_fields.items()):
            family = UnitFamily.OTHER
            bases = [b for b in baselines if name in b[1].fields]
            for gp, p in (m for m in proposed if name in m[1].fields):
                if not bases:
                    skip("no-baseline")
                    continue
                for gb, b in bases:
                    if gp is None or gb is None:
                        skip("key-missing")
                        continue
                    if gp != gb:
                        skip("group-differs")
                        continue
                    pf, bf = p.fields[name], b.fields[name]
                    if not (_own(pf) and _own(bf)):
                        skip("not-own")
                        continue
                    if normalise_text(pf.unit or "") != normalise_text(bf.unit or ""):
                        skip("unit-differs")
                        continue
                    ctx_p = tuple(_context(p, c, pack) for c in context)
                    ctx_b = tuple(_context(b, c, pack) for c in context)
                    if _HARDWARE in context:
                        at = context.index(_HARDWARE)
                        if not ctx_p[at] or not ctx_b[at]:
                            skip("hardware-missing")
                            continue
                        if ctx_p[at] != ctx_b[at]:
                            skip("hardware-differs")
                            continue
                    if ctx_p != ctx_b:
                        skip("context-differs")
                        continue
                    num_p, num_b = _cost_decimal(pf, family), _cost_decimal(bf, family)
                    value = (
                        speed_ratio(num_p, num_b, higher_is_faster=higher)
                        if num_p is not None and num_b is not None
                        else None
                    )
                    if value is None:
                        skip("value-unusable")
                        continue
                    method = _text(p.fields.get("method_name")) or ""
                    base_method = _text(b.fields.get("method_name")) or ""
                    ident = (
                        work,
                        name,
                        normalise_text(method),
                        normalise_text(_text(p.fields.get("variant")) or ""),
                        normalise_text(base_method),
                        normalise_text(_text(b.fields.get("variant")) or ""),
                        gp,
                        *(c or "" for c in ctx_p),
                    )
                    if ident in ambiguous:
                        continue
                    if ident in found:
                        if values[ident] != (num_p, num_b):
                            del found[ident], values[ident]
                            ambiguous.add(ident)
                            skip("ambiguous")
                        continue
                    assert num_p is not None and num_b is not None
                    values[ident] = (num_p, num_b)
                    assert name in ("throughput", "latency")
                    printed = {
                        c: (None if c not in p.fields else str(p.fields[c].value)) for c in context
                    }
                    found[ident] = WithinPaperRatio(
                        work_id=work,
                        document_id=document,
                        field=name,
                        method=method,
                        baseline_method=base_method,
                        ratio=format(value, "f"),
                        unit=pf.unit,
                        hardware=ctx_p[context.index(_HARDWARE)] if _HARDWARE in context else None,
                        batch_size=printed.get("batch_size"),
                        precision=printed.get("precision"),
                        context=printed,
                        proposed=_provenance(p.row_key, name, pf),
                        baseline=_provenance(b.row_key, name, bf),
                    )
    ordered = sorted(
        found.items(),
        key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][4], kv[0][3], kv[0][5], kv[0][6:]),
    )
    return [v for _, v in ordered], dict(sorted(unpaired.items()))


def _plain(d: Decimal) -> str:
    return "0" if d == 0 else format(d.normalize(), "f")


def _frontiers(
    rows: Sequence[FinalRow],
    pack: Pack,
    spec: ReportSpec,
    key: Mapping[str, str],
    higher_is_better: bool,
    declared: Sequence[str] | None = None,
) -> list[FrontierAxis]:
    """One frontier per cost axis of the spec over the group's independent rows (ruling 6),
    partitioned by value unit and, each if not a group key, by normalised metric and by
    resolution (decision 52). Speed fields are never
    axes. An axis whose pack field or schema declaration is
    missing is omitted; one with no plottable point is kept with its missing counts."""
    by_resolution = "input_resolution" not in key
    by_metric = "metric" not in key
    resolution_def = pack.field("input_resolution")
    own = sorted((r for r in rows if r.independent), key=lambda r: r.row_key)
    axes: list[FrontierAxis] = []
    if not own:
        return axes
    for name in spec.frontier_costs:
        if (
            name in spec.speed_fields
            or pack.field(name) is None
            or (declared is not None and name not in declared)
        ):
            continue
        cost_def = pack.field(name)
        assert cost_def is not None
        cost_family = cost_def.unit_family
        missing: dict[str, list[str]] = {}
        buckets: dict[tuple[str, str, str], list[Point]] = {}
        units: dict[tuple[str, str, str], str | None] = {}
        for row in own:
            value = _decimal(row.fields[spec.value_field])
            if value is None:
                missing.setdefault("value-not-numeric", []).append(row.row_key)
                continue
            field = row.fields.get(name)
            if field is None:
                missing.setdefault("cost-missing", []).append(row.row_key)
                continue
            amount = _cost_decimal(field, cost_family)
            if amount is None:
                missing.setdefault("cost-missing", []).append(row.row_key)
                continue
            if amount <= 0:
                missing.setdefault("cost-not-positive", []).append(row.row_key)
                continue
            unit = row.fields[spec.value_field].unit
            resolution: str | None = None
            if by_resolution and "input_resolution" not in row.fields:
                missing.setdefault("resolution-missing", []).append(row.row_key)
            if by_resolution and "input_resolution" in row.fields:
                res = row.fields["input_resolution"]
                resolution = (
                    key_value(resolution_def, res)
                    if resolution_def is not None
                    else normalise_text(str(res.value))
                )
            bucket = (_metric_of(row, pack) if by_metric else "", unit or "", resolution or "")
            units[bucket] = unit
            method = _text(row.fields.get("method_name"))
            buckets.setdefault(bucket, []).append(
                Point(row.row_key, amount, value, normalise_text(method or ""), row.work_id)
            )
        names = {r.row_key: _text(r.fields.get("method_name")) for r in own}
        partitions = [
            _partition(
                units[b],
                b[2] or None,
                points,
                names,
                higher_is_better=higher_is_better,
                metric=b[0] if by_metric else None,
            )
            for b, points in sorted(buckets.items())
        ]
        statement: str | None = None
        if not buckets and "cost-not-positive" not in missing:
            if len(missing.get("value-not-numeric", [])) == len(own):
                statement = (
                    "No independent row has a numeric metric value; no frontier is computed."
                )
            else:
                statement = f"No independent row reports {name}; no frontier is computed."
        axes.append(
            FrontierAxis(axis=name, partitions=partitions, missing=missing, statement=statement)
        )
    return axes


def _partition(
    unit: str | None,
    resolution: str | None,
    points: Sequence[Point],
    names: Mapping[str, str | None],
    *,
    higher_is_better: bool,
    metric: str | None = None,
) -> FrontierPartition:
    result = pareto(points, higher_is_better=higher_is_better)
    dominators = {p.row_key: q.row_key for p, q in result.dominated}
    on = {p.row_key for p in result.frontier}
    shown = [
        FrontierPoint(
            row_key=p.row_key,
            work_id=p.work_id,
            method_name=names.get(p.row_key),
            cost=_plain(p.cost),
            metric=_plain(p.metric),
            on_frontier=p.row_key in on,
            dominated_by=dominators.get(p.row_key),
            trace_id=f"{p.row_key}/value",
        )
        for p in sorted(points, key=lambda p: (p.cost, p.row_key))
    ]
    statement = (
        "Fewer than two points in this partition; no frontier can be drawn."
        if len(points) < 2
        else None
    )
    return FrontierPartition(
        unit=unit, resolution=resolution, points=shown, statement=statement, metric=metric
    )


def group_direction(
    key: Sequence[tuple[str, str]], rows: Sequence[FinalRow], pack: Pack, spec: ReportSpec
) -> tuple[bool | None, DirectionStatus]:
    """Ruling 5: the rows' declared direction, else the pack default for the normalised metric,
    else unknown; declared values that disagree with each other or the default conflict. A
    declared value that is not a boolean is `unparseable`: never replaced by the default."""
    present = [r.fields[spec.direction_field] for r in rows if spec.direction_field in r.fields]
    parsed = [_as_bool(f) for f in present]
    if any(d is None for d in parsed):
        return None, "unparseable"
    declared = {d for d in parsed if d is not None}
    metrics = dict(key).get("metric")
    if metrics is None:
        definition = pack.field("metric")
        names = {
            normalise_for(definition, str(r.fields["metric"].value))
            if definition is not None
            else normalise_text(str(r.fields["metric"].value))
            for r in rows
            if "metric" in r.fields
        }
        metrics = next(iter(names)) if len(names) == 1 else None
    default = None if metrics is None else spec.metric_directions.get(metrics)
    if len(declared) > 1:
        return None, "conflict"
    if declared:
        (value,) = declared
        if default is not None and default != value:
            return None, "conflict"
        return value, "declared"
    if default is not None:
        return default, "pack-default"
    return None, "unknown"


def _metric_of(row: FinalRow, pack: Pack) -> str:
    """The row's normalised metric, as a group key would hold it; "" when absent."""
    f = row.fields.get("metric")
    return "" if f is None else key_value(pack.field("metric"), f)


def _metrics_of(
    rows: Sequence[FinalRow], pack: Pack, key: Mapping[str, str]
) -> Mapping[str, str] | None:
    """Row key -> normalised metric when the metric is not a group key, else None (one metric)."""
    if "metric" in key:
        return None
    return {r.row_key: _metric_of(r, pack) for r in rows}


def _conflicts(
    rows: Sequence[EvidenceRow], metrics: Mapping[str, str] | None = None
) -> list[MethodConflict]:
    """Ruling: independent rows of one normalised (method, variant) and, when `metrics` is given
    (the metric is not a group key), one normalised metric, whose values differ."""
    by_method: dict[tuple[str, str, str], list[EvidenceRow]] = {}
    for row in rows:
        if not row.independent or row.method_name is None:
            continue
        metric = "" if metrics is None else metrics.get(row.row_key, "")
        ident = metric, normalise_text(row.method_name), normalise_text(row.variant or "")
        by_method.setdefault(ident, []).append(row)
    out: list[MethodConflict] = []
    for (metric, method, variant), members in sorted(
        by_method.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0])
    ):
        values = {(_number_identity(r.value), normalise_text(r.value.unit or "")) for r in members}
        if len(values) > 1:
            out.append(
                MethodConflict(
                    method=method,
                    variant=variant or None,
                    rows=sorted(r.row_key for r in members),
                    metric=None if metrics is None else metric,
                )
            )
    return out


# --- Claims, exclusions, expectations, quality ---


def _claims(claims: Sequence[ClaimRow], included: set[str]) -> dict[str, list[ClaimEntry]]:
    out: dict[str, list[ClaimEntry]] = {t.value: [] for t in ClaimType}
    for c in sorted(claims, key=lambda c: (c.work_id, c.claim_id)):
        if c.work_id not in included:
            continue
        out[c.claim_type.value].append(
            ClaimEntry(
                claim_id=c.claim_id,
                work_id=c.work_id,
                claim_type=c.claim_type,
                evidence_type=c.evidence_type,
                strength=c.strength,
                statement=c.statement,
                anchor=c.anchor,
                quote=c.quote,
                trace_id=c.claim_id,
            )
        )
    return out


def _excluded(
    inputs: ReportInputs, missing_value: Sequence[FinalRow], finals: set[str]
) -> list[Excluded]:
    unresolved = {(d.work_id, d.row_key) for d in inputs.grouped.unresolved}
    stale = set(inputs.stale)
    missing = {(r.work_id, r.row_key) for r in missing_value}
    without = sorted(w for w in inputs.population if w not in finals)
    found: list[tuple[ExcludedReason, int, list[str]]] = [
        ("unresolved", len(unresolved), sorted({w for w, _ in unresolved})),
        ("stale", len(stale), sorted({w for w, _ in stale})),
        ("missing-value", len(missing), sorted({w for w, _ in missing})),
        ("no-final-row", len(without), without),
    ]
    return [Excluded(reason=r, count=n, works=w) for r, n, w in found if n]


def _number_identity(p: Provenance) -> str:
    """The canonical value, else the printed number compared numerically ("79.8" == "79.80"),
    else the normalised text."""
    if p.canonical is not None:
        return p.canonical
    printed = parse_printed(str(p.value)) if not isinstance(p.value, bool) else None
    if printed is not None:
        return "0" if printed == 0 else format(printed.normalize(), "f")
    return normalise_text(str(p.value))


def _normalise_key_value(pack: Pack, name: str, value: str) -> str:
    """An expected value normalised as D's `key_value` keys a group (numbers by canonical value,
    text by the pack's normaliser)."""
    definition = pack.field(name)
    canon: str | None = None
    if definition is not None and definition.kind in (FieldKind.NUMBER, FieldKind.INTEGER):
        printed = parse_printed(value)
        if printed is not None:
            try:
                canon = canonical(printed, None, definition.unit_family)
            except ValueError:
                canon = None
    field = FinalField(
        value=value,
        unit=None,
        canonical=canon,
        anchor=None,
        cell=None,
        quote=None,
        reported_in=ReportedIn.OWN,
        copy_marker=False,
        reproduced=False,
        cited_work=None,
        extraction_id="",
    )
    return key_value(definition, field)


def _expectation(
    expect: Mapping[str, str], groups: Sequence[GroupReport], pack: Pack
) -> ExpectationResult:
    wanted = {k: _normalise_key_value(pack, k, v) for k, v in expect.items()}
    ids = sorted(
        g.group_id for g in groups if all(dict(g.key).get(k) == v for k, v in wanted.items())
    )
    return ExpectationResult(expect=dict(expect), group_ids=ids)


def _expectation_limits(expectations: Sequence[ExpectationResult]) -> list[Limit]:
    out = []
    for i, e in enumerate(expectations, start=1):
        if not e.group_ids:
            out.append(
                Limit(
                    code="expectation-empty",
                    text=f"Expectation {i} matches no group.",
                    subject=f"expectation-{i}",
                )
            )
    return out


def _quality(inputs: ReportInputs) -> Quality:
    audit = inputs.audit
    return Quality(
        dual_works=inputs.agreement.dual,
        single_extraction_works=inputs.agreement.single,
        agreement_overall=inputs.agreement.overall,
        audit_n=0 if audit is None else audit.labelled,
        audit_error_rate=None if audit is None else audit.error_rate,
        audit_above_ceiling=None if audit is None else audit.above_ceiling,
        agreement_rows_aligned=inputs.agreement.rows_aligned,
        agreement_rows_unmatched=inputs.agreement.rows_unmatched,
    )


def _limits(
    inputs: ReportInputs,
    groups: Sequence[GroupReport],
    ungrouped: Sequence[EvidenceRow],
    excluded: Sequence[Excluded],
    expectations: Sequence[ExpectationResult],
    quality: Quality,
    finals: set[str],
) -> list[Limit]:
    out: list[Limit] = []
    if not inputs.pass_b_open:
        out.append(
            Limit(
                code="pass-b-not-opened",
                text="Extraction pass B has not opened; no row is final yet.",
                subject=None,
            )
        )
    if inputs.blocking:
        out.append(
            Limit(
                code="units-not-current",
                text="Some extraction units are open, stale or queued; the report is provisional.",
                subject=None,
            )
        )
    if not groups and not ungrouped:
        out.append(_NO_EXTRACTION)
    out.extend(_expectation_limits(expectations))
    if ungrouped:
        out.append(
            Limit(
                code="ungrouped-rows",
                text=f"{len(ungrouped)} rows lack a comparability key and belong to no group.",
                subject=None,
            )
        )
    texts = {
        "unresolved": "{n} rows are excluded: a disagreement between the passes is unresolved.",
        "stale": "{n} rows are excluded: they are stale and await re-extraction.",
        "missing-value": "{n} final rows are excluded: they have no value.",
        "no-final-row": "{n} included works have no final row.",
    }
    for e in excluded:
        code = "no-final-row" if e.reason == "no-final-row" else f"excluded-{e.reason}"
        out.append(Limit(code=code, text=texts[e.reason].format(n=e.count), subject=None))
    if quality.agreement_overall is None:
        out.append(
            Limit(
                code="agreement-not-computed",
                text="Agreement between the passes is not computed yet.",
                subject=None,
            )
        )
    if quality.agreement_rows_unmatched:
        out.append(
            Limit(
                code="agreement-rows-unmatched",
                text=f"{quality.agreement_rows_unmatched} dual rows are held by one pass only and "
                f"are outside the agreement ({quality.agreement_rows_aligned} rows aligned).",
                subject=None,
            )
        )
    if quality.single_extraction_works:
        out.append(
            Limit(
                code="single-extraction",
                text=f"{quality.single_extraction_works} included works were extracted by one "
                "pass only.",
                subject=None,
            )
        )
    audit = inputs.audit
    if finals:
        if audit is None:
            out.append(
                Limit(
                    code="audit-missing",
                    text="No audit of agreed values has been sampled.",
                    subject=None,
                )
            )
        else:
            if inputs.audit_outstanding or audit.outdated:
                out.append(
                    Limit(
                        code="audit-outdated",
                        text="The agreed values changed after the latest audit was sampled."
                        + (
                            f" {audit.outdated} labels are on values that changed and are left "
                            "out of the error rate."
                            if audit.outdated
                            else ""
                        ),
                        subject=audit.audit_id,
                    )
                )
            unlabelled = audit.sample_size - audit.labelled - audit.outdated
            if unlabelled > 0:
                out.append(
                    Limit(
                        code="audit-incomplete",
                        text=f"{unlabelled} of {audit.sample_size} audit items are not labelled.",
                        subject=audit.audit_id,
                    )
                )
            if audit.above_ceiling:
                out.append(
                    Limit(
                        code="audit-above-ceiling",
                        text="The audit error rate is above the ceiling.",
                        subject=audit.audit_id,
                    )
                )
    out.append(_CLAIMS_NOT_CHECKED)
    for g in groups:
        out.extend(g.statements)
    return out
