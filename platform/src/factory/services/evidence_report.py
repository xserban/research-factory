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

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from factory.errors import FactoryValidationError
from factory.extraction.numbers import normalise_for, normalise_text
from factory.model.base import StrictModel
from factory.model.extraction import ClaimType, EvidenceType, ReportedIn, Strength
from factory.model.screening import PassLabel
from factory.packs import FieldKind, Pack, ReportSpec
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
)
from factory.services.extraction_audit import (
    ExtractionAuditReport,
    extraction_audit_outstanding,
    extraction_audit_report,
)
from factory.services.search import get_work

__all__ = [
    "REPORT_VERSION",
    "ClaimEntry",
    "EvidenceReport",
    "EvidenceRow",
    "Excluded",
    "ExpectationResult",
    "GroupCounts",
    "GroupReport",
    "Limit",
    "MethodConflict",
    "Provenance",
    "Quality",
    "ReportInputs",
    "assemble_report",
    "evidence_report",
    "group_id",
    "report_inputs",
]

REPORT_VERSION = 1
"""Version of the derivation; recorded in every report with the pack and its version."""

DirectionStatus = Literal["declared", "pack-default", "conflict", "unknown"]
ExcludedReason = Literal["unresolved", "stale", "missing-value", "no-final-row"]


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
    listed, never averaged."""

    method: str
    variant: str | None
    rows: list[str]


class GroupReport(StrictModel):
    group_id: str
    key: list[tuple[str, str]]
    rows: list[EvidenceRow]
    counts: GroupCounts
    direction: bool | None
    direction_status: DirectionStatus
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
    )


def evidence_report(
    project: Project, *, expect: Sequence[Mapping[str, str]] = ()
) -> EvidenceReport:
    """The evidence report of the project, recomputed from the projection. Never raises for a
    missing schema: the report is then empty with the limit `no-extraction`. Writes nothing."""
    inputs = report_inputs(project)
    if inputs is None:
        return _empty(expect)
    return assemble_report(inputs, expect=expect)


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
        provisional=False,
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
        ),
        limits=[_NO_EXTRACTION, *_expectation_limits(expectations)],
    )


def assemble_report(
    inputs: ReportInputs, *, expect: Sequence[Mapping[str, str]] = ()
) -> EvidenceReport:
    """The report from `inputs`. Pure and deterministic: the same inputs, in any row order,
    give the same report."""
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
            groups.append(_group(list(key), rows, pack, spec, inputs.titles))
    groups.sort(key=lambda g: g.key)
    ungrouped = _rows(keep(inputs.grouped.ungrouped), spec, inputs.titles, pack)

    finals = {r.work_id for g in groups for r in g.rows} | {r.work_id for r in ungrouped}
    excluded = _excluded(inputs, missing_value, finals)
    expectations = [_expectation(e, groups, pack) for e in expect]
    quality = _quality(inputs)
    provisional = not inputs.pass_b_open or inputs.blocking or bool(inputs.grouped.unresolved)
    limits = _limits(inputs, groups, ungrouped, excluded, expectations, quality, finals)
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
    )


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
    direction, status = _direction(key, rows, pack, spec)
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
    return GroupReport(
        group_id=gid,
        key=key,
        rows=shown,
        counts=group_counts,
        direction=direction,
        direction_status=status,
        method_conflicts=_conflicts(shown),
        statements=statements,
    )


def _direction(
    key: Sequence[tuple[str, str]], rows: Sequence[FinalRow], pack: Pack, spec: ReportSpec
) -> tuple[bool | None, DirectionStatus]:
    """Ruling 5: the rows' declared direction, else the pack default for the normalised metric,
    else unknown; declared values that disagree with each other or the default conflict."""
    declared = {
        d for d in (_as_bool(r.fields.get(spec.direction_field)) for r in rows) if d is not None
    }
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


def _conflicts(rows: Sequence[EvidenceRow]) -> list[MethodConflict]:
    by_method: dict[tuple[str, str], list[EvidenceRow]] = {}
    for row in rows:
        if not row.independent or row.method_name is None:
            continue
        ident = normalise_text(row.method_name), normalise_text(row.variant or "")
        by_method.setdefault(ident, []).append(row)
    out: list[MethodConflict] = []
    for (method, variant), members in sorted(by_method.items()):
        values = {
            (
                r.value.canonical or normalise_text(str(r.value.value)),
                normalise_text(r.value.unit or ""),
            )
            for r in members
        }
        if len(values) > 1:
            out.append(
                MethodConflict(
                    method=method,
                    variant=variant or None,
                    rows=sorted(r.row_key for r in members),
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


def _normalise_key_value(pack: Pack, name: str, value: str) -> str:
    definition = pack.field(name)
    if definition is not None and definition.kind is FieldKind.TEXT:
        return normalise_for(definition, value)
    return normalise_text(value)


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
            if inputs.audit_outstanding:
                out.append(
                    Limit(
                        code="audit-outdated",
                        text="The agreed values changed after the latest audit was sampled.",
                        subject=audit.audit_id,
                    )
                )
            if audit.labelled < audit.sample_size:
                out.append(
                    Limit(
                        code="audit-incomplete",
                        text=f"{audit.sample_size - audit.labelled} of {audit.sample_size} "
                        "audit items are not labelled.",
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
