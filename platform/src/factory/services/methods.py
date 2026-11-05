"""The methods statement, generated from events (plan 5b, task 2).

`methods_report` is the only function that computes a figure: each field is read from one service
and no caller can set one. `render_methods` formats the report as Markdown paragraphs and adds no
number of its own. Invariants:

- A figure that is not computed is None and renders as `not computed`, never as zero.
- Held-out seed recall is reported before development recall; development is labelled
  `optimistic` (R-24), since the development seeds shaped the protocol.
- Models and skills are the agent-reported values (decision #38.5), read from the event envelope.
- No seed is named: no seed ID, DOI, arXiv ID or title appears in the render.
"""

from typing import Any

from pydantic import Field
from sqlalchemy import TextClause, text

from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage, SnowballPlan
from factory.model.references import Direction
from factory.references.match import MATCHER_VERSION
from factory.references.parse import PARSER, PARSER_VERSION
from factory.services.agreement import agreement_summary
from factory.services.audit import audit_report
from factory.services.calibration import calibration_status
from factory.services.chase import chase_rounds
from factory.services.context import Project
from factory.services.coverage import (
    Bucket,
    PartCoverage,
    Ratio,
    agent_coverage,
    coverage_report,
    held_out_visible,
    resolved_import_ids,
)
from factory.services.discovery import supplied_only_included
from factory.services.evidence_report import evidence_report
from factory.services.extraction_agreement import agreement_overall
from factory.services.extraction_audit import extraction_audit_report
from factory.services.gate_status import GateStatusRow, notable_rows
from factory.services.prisma import (
    UNCONVERTED,
    PrismaFlow,
    has_full_text_plan,
    prisma_flow,
    search_report,
)
from factory.services.protocol import current_protocol, list_amendments, list_deviations
from factory.services.references import reference_counts
from factory.services.seeds import _rigor_mode, admitted_seed_count, seed_recall
from factory.services.snowball import recorded_rounds

NOT_COMPUTED = "not computed"
NONE_RECORDED = "none recorded"
_SUPPLIERS = ("human", "agent")


class SuppliedLinks(StrictModel):
    """Supplied links by submitter kind (slice 4a): captured, resolved, and included works (last
    declared stage) that came only through supplied links, R-39. The discovery report's
    first-surfaced view is a different figure and is not used here."""

    captured: dict[str, int]
    resolved: dict[str, int]
    included: dict[str, int]


class ImportMethods(StrictModel):
    """Coverage of one resolved library import, by part (slice 3d). Parts carry figures only."""

    import_id: str
    label: str
    parts: list[PartCoverage]
    held_out_withheld: bool = False
    """True in the agent view while no screening pass has been opened."""


class MinerMethods(StrictModel):
    """One registered miner version in the statement (R-52): every version is listed, with the
    state it ended in, so a failed or retired miner stays reported. The score fields are the
    calibration's; an agent view blanks them (they derive from the human gold labels)."""

    name: str
    version: int
    state: str
    proposer_kind: str
    listed: bool
    evidence: bool
    calibration_units: int | None = None
    calibration: str | None = None
    """`passed`, `failed` or `pending`; None while no calibration is drawn. It stays when the
    miner is retired, so a failed and retired version is reported as both."""
    recall: float | None = None
    field_agreement: float | None = None
    precision: float | None = None
    verification_rate: float | None = None


class MethodsReport(StrictModel):
    rigor_mode: str
    method_profile: str | None
    protocol_id: str | None
    amendments: int
    deviations: int
    sources: list[str]
    models: list[str]
    skills: list[str]
    passes: int
    dual_sample: float | None
    kappa: float | None
    kappa_by_criterion: dict[str, float | None]
    calibration_sensitivity: dict[str, float | None]
    audit_false_exclusion_rate: float | None
    audit_n: int
    recall_held_out: float | None
    recall_development: float | None
    recall_held_out_admitted: int = 0
    recall_development_admitted: int = 0
    chase_rounds: int
    admitted_seeds: int
    prisma: PrismaFlow
    full_text_passes: int = 0
    """0 when the protocol declares no full-text plan; the other full-text fields are then empty."""
    full_text_dual_sample: float | None = None
    full_text_kappa_floor: float | None = None
    full_text_audit_fraction: float | None = None
    full_text_audit_minimum: int | None = None
    full_text_kappa: float | None = None
    full_text_sessions: int = 0
    full_text_models: list[str] = Field(default_factory=list)
    extraction_pack: str | None = None
    """`name@version` of the declared extraction pack; None (and the fields below empty) when the
    protocol declares no extraction schema."""
    extraction_fields: list[str] = Field(default_factory=list)
    extraction_passes: int = 0
    """Extraction passes opened."""
    extraction_dual_sample: float | None = None
    extraction_sessions: int = 0
    extraction_models: list[str] = Field(default_factory=list)
    extraction_agreement: float | None = None
    """Overall agreement of the passes; None while units are open or nothing is compared."""
    extraction_audit_n: int = 0
    extraction_error_rate: float | None = None
    evidence_groups: int = 0
    """Evidence-report counts, all 0 (and the lists empty) when no extraction schema is declared."""
    evidence_multi_source_groups: int = 0
    """Groups reported by more than one independent work."""
    evidence_rows: int = 0
    evidence_independent: int = 0
    evidence_copied: int = 0
    evidence_comparability_keys: list[str] = Field(default_factory=list)
    evidence_frontier_costs: list[str] = Field(default_factory=list)
    """Cost axes on which at least one group has a frontier."""
    supplied_links: SuppliedLinks | None = None
    """None when no link was ever captured: the paragraph is then left out."""
    reference_extractions: int = 0
    """Live reference-list extractions (slice 3a); 0, and the fields below empty, when the
    project has neither an extraction nor a snowball round."""
    reference_entries: int = 0
    reference_resolved: int = 0
    reference_unresolved: int = 0
    reference_parser: str | None = None
    """`<parser> <version>` of the reference parser."""
    reference_matcher: str | None = None
    """The reference matcher version."""
    snowball_rounds: dict[str, int] = Field(default_factory=dict)
    """Recorded snowball rounds per direction (`backward`, `forward`)."""
    snowball_rule: str | None = None
    """The declared stopping rule, stated in words; None while no plan is declared."""
    imports: list[ImportMethods] = Field(default_factory=list)
    """Resolved library imports (slice 3d); empty, and no paragraph, without imports."""
    miners: list[MinerMethods] = Field(default_factory=list)
    """Registered miner versions (slice M, M-D); empty, and no paragraph, without any."""
    gate_policy: list[GateStatusRow] = Field(default_factory=list)
    """The decision gates the statement reports (slice M, `GateStatusRow.notable`): empty, and no
    paragraph, while every act was passed by a human under a `human` policy."""


def methods_report(project: Project) -> MethodsReport:
    """Every figure of the methods statement, computed from the events as they stand.

    `passes` is 0 and `audit_n` is 0 when there is no protocol or no audit; the other undefined
    figures are None.
    """
    project.index.sync()
    protocol = current_protocol(project)
    plan = None if protocol is None else protocol.spec.screening
    flow = prisma_flow(project)
    agreement = agreement_summary(project)
    audit = audit_report(project)
    recall = seed_recall(project)
    full_text = None if protocol is None else protocol.spec.full_text_screening
    ft_kappa = None
    if full_text is not None and has_full_text_plan(project):
        summary = agreement_summary(project, stage=ScreeningStage.FULL_TEXT)
        ft_kappa = None if summary is None else summary.kappa
    ft_sessions = _full_text_sessions(project)
    schema = None if protocol is None else protocol.spec.extraction_schema
    ex_sessions = [] if schema is None else _extraction_sessions(project)
    ex_audit = None if schema is None else extraction_audit_report(project)
    evidence = None if schema is None else evidence_report(project)
    groups = [] if evidence is None else evidence.groups
    references = _references(project, None if protocol is None else protocol.spec.snowball_plan)
    return MethodsReport(
        rigor_mode=_rigor_mode(project).value,
        method_profile=None if protocol is None else protocol.spec.method_profile.value,
        protocol_id=flow.protocol_id,
        amendments=len(list_amendments(project)),
        deviations=len(list_deviations(project)),
        sources=sorted({row.source for row in search_report(project).rows}),
        models=_agent_values(project, _AGENT_MODELS),
        skills=_agent_values(project, _AGENT_SKILLS),
        passes=0 if plan is None else plan.passes,
        dual_sample=None if plan is None else plan.dual_sample,
        kappa=None if agreement is None else agreement.kappa,
        kappa_by_criterion={} if agreement is None else dict(agreement.kappa_by_criterion),
        calibration_sensitivity={
            label: rates.sensitivity
            for label, rates in calibration_status(project).per_pass.items()
        },
        audit_false_exclusion_rate=None if audit is None else audit.rates.false_exclusion,
        audit_n=0 if audit is None else audit.labelled,
        recall_held_out=recall.held_out,
        recall_development=recall.development,
        recall_held_out_admitted=recall.held_out_admitted,
        recall_development_admitted=recall.development_admitted,
        chase_rounds=len(chase_rounds(project)),
        admitted_seeds=admitted_seed_count(project),
        prisma=flow,
        full_text_passes=0 if full_text is None else full_text.passes,
        full_text_dual_sample=None if full_text is None else full_text.dual_sample,
        full_text_kappa_floor=None if full_text is None else full_text.kappa_floor,
        full_text_audit_fraction=None if full_text is None else full_text.audit_fraction,
        full_text_audit_minimum=None if full_text is None else full_text.audit_minimum,
        full_text_kappa=ft_kappa,
        full_text_sessions=len(ft_sessions),
        full_text_models=sorted({model for _, model in ft_sessions}),
        extraction_pack=None if schema is None else f"{schema.pack}@{schema.pack_version}",
        extraction_fields=[] if schema is None else list(schema.fields),
        extraction_passes=0 if schema is None else _extraction_pass_count(project),
        extraction_dual_sample=None if schema is None else schema.dual_extract_sample,
        extraction_sessions=len(ex_sessions),
        extraction_models=sorted({model for _, model in ex_sessions}),
        extraction_agreement=None if schema is None else agreement_overall(project).overall,
        extraction_audit_n=0 if ex_audit is None else ex_audit.labelled,
        extraction_error_rate=None if ex_audit is None else ex_audit.error_rate,
        evidence_groups=len(groups),
        evidence_multi_source_groups=sum(1 for g in groups if g.counts.independent_works > 1),
        evidence_rows=sum(len(g.rows) for g in groups),
        evidence_independent=sum(g.counts.independent for g in groups),
        evidence_copied=sum(g.counts.copied for g in groups),
        evidence_comparability_keys=[] if evidence is None else list(evidence.comparability_keys),
        evidence_frontier_costs=sorted({a.axis for g in groups for a in g.frontiers}),
        **references,
        supplied_links=_supplied_links(project),
        imports=_imports(project, agent=False),
        gate_policy=notable_rows(project),
        miners=_miners(project),
    )


def _miners(project: Project) -> list[MinerMethods]:
    """Every registered miner version with its state, proposer kind, calibration scores and
    evidence flag (the protocol's)."""
    from factory.services.miner_report import miner_calibration_report
    from factory.services.miners import miner_state
    from factory.services.mining import registered_miners

    protocol = current_protocol(project)
    uses = {} if protocol is None else {(u.name, u.version): u for u in protocol.spec.miners or ()}
    out: list[MinerMethods] = []
    for row in registered_miners(project):
        use = uses.get((row.name, row.version))
        state = miner_state(project, row.name, row.version)
        report = miner_calibration_report(project, row.name, row.version)
        result = None if report is None else report.score
        out.append(
            MinerMethods(
                name=row.name,
                version=row.version,
                state=state.value,
                proposer_kind=row.proposer_kind,
                listed=use is not None,
                evidence=use is not None and use.evidence and state.value != "retired",
                calibration_units=None if report is None else report.units,
                calibration=(
                    None
                    if report is None
                    else "pending"
                    if report.passed is None
                    else "passed"
                    if report.passed
                    else "failed"
                ),
                recall=None if result is None else result.recall,
                field_agreement=None if result is None else result.field_agreement,
                precision=None if result is None else result.precision,
                verification_rate=None if result is None else result.verification_rate,
            )
        )
    return out


def _imports(project: Project, *, agent: bool) -> list[ImportMethods]:
    """The coverage of each resolved import; `agent` applies the agent view (decision 43)."""
    out: list[ImportMethods] = []
    visible = held_out_visible(project)
    for import_id in resolved_import_ids(project):
        report = (
            agent_coverage(project, import_id) if agent else coverage_report(project, import_id)
        )
        parts = [p.model_copy(update={"excluded": []}) for p in report.parts]
        withheld = agent and not visible and report.label == "held-out"
        out.append(
            ImportMethods(
                import_id=import_id, label=report.label, parts=parts, held_out_withheld=withheld
            )
        )
    return out


def _references(project: Project, plan: SnowballPlan | None) -> dict[str, Any]:
    """The reference and snowballing fields of the report; none while neither stage has run."""
    counts = reference_counts(project)
    rounds = recorded_rounds(project)
    if not counts.extractions and not rounds:
        return {}
    return {
        "reference_extractions": counts.extractions,
        "reference_entries": counts.entries,
        "reference_resolved": counts.resolved,
        "reference_unresolved": counts.unresolved,
        "reference_parser": f"{PARSER} {PARSER_VERSION}",
        "reference_matcher": MATCHER_VERSION,
        "snowball_rounds": {
            d.value: sum(1 for r in rounds if r.direction is d)
            for d in (Direction.BACKWARD, Direction.FORWARD)
        },
        "snowball_rule": None if plan is None else _rule(plan),
    }


def _rule(plan: SnowballPlan) -> str:
    stop = (
        "stop when a round yields no newly included work"
        if plan.stop_when_no_new_included
        else "no stop on an empty round"
    )
    return (
        f"at most {plan.max_backward_rounds} backward and {plan.max_forward_rounds} forward "
        f"round(s); {stop}"
    )


def _supplied_links(project: Project) -> SuppliedLinks | None:
    """Captured and resolved items by submitter kind, and included works that came only through
    supplied links (R-39; `discovery.supplied_only_included`). None when no link was captured."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT actor_kind, status, COUNT(*) FROM inbox_items GROUP BY 1, 2")
        ).all()
    if not rows:
        return None
    captured = dict.fromkeys(_SUPPLIERS, 0)
    resolved = dict.fromkeys(_SUPPLIERS, 0)
    for kind, status, count in rows:
        captured[str(kind)] += int(count)
        if status == "resolved":
            resolved[str(kind)] += int(count)
    included = supplied_only_included(project)
    return SuppliedLinks(captured=captured, resolved=resolved, included=included)


def _extraction_sessions(project: Project) -> list[tuple[str, str]]:
    """(session, model) of every session bound to an evidence extraction pass (the methods
    report describes the evidence table; contribution passes are not counted)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT session, model FROM extraction_sessions WHERE scope = 'evidence' "
                "ORDER BY session"
            )
        ).all()
    return [(str(session), str(model)) for session, model in rows]


def _extraction_pass_count(project: Project) -> int:
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM extraction_passes WHERE scope = 'evidence'")
            ).scalar_one()
        )


def _full_text_sessions(project: Project) -> list[tuple[str, str]]:
    """(session, model) of every session bound to a full-text pass, as the sessions reported."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT session, model FROM pass_sessions WHERE stage = :stage ORDER BY session"),
            {"stage": ScreeningStage.FULL_TEXT.value},
        ).all()
    return [(str(session), str(model)) for session, model in rows]


# The statement describes the evidence pipeline, so the models and skills it names are read from
# events of that pipeline only. A deny-list of the layer's events, not an allow-list of the
# pipeline's: the layer has few event types, the pipeline many and growing, so an allow-list would
# drift with every slice and silently drop a real model. A skill name plays no part (an agent
# declares its own). Layer events: the `interpretation.` and `concept.` event types and the task
# events (`task.*`) of the layer's tasks, which carry the layer task's content as their input; the
# organisation class's are the `label.`, `term.`, `consolidation.` and `region.` types and the
# events of `consolidate` tasks.
_LAYER_EVENTS = (
    "AND e.type NOT LIKE 'interpretation.%' AND e.type NOT LIKE 'concept.%' "
    "AND e.type NOT LIKE 'label.%' AND e.type NOT LIKE 'term.%' "
    "AND e.type NOT LIKE 'consolidation.%' AND e.type NOT LIKE 'region.%' "
    "AND NOT (e.type LIKE 'task.%' AND e.input_blob IN "
    "(SELECT content_blob FROM tasks WHERE kind IN ('intuition', 'consolidate'))) "
)
_AGENT_MODELS = text(
    "SELECT DISTINCT e.model FROM events e WHERE e.actor_kind = 'agent' AND e.model IS NOT NULL "
    + _LAYER_EVENTS
    + "ORDER BY e.model"
)
_AGENT_SKILLS = text(
    "SELECT DISTINCT e.skill FROM events e WHERE e.actor_kind = 'agent' AND e.skill IS NOT NULL "
    + _LAYER_EVENTS
    + "ORDER BY e.skill"
)


def _agent_values(project: Project, statement: TextClause) -> list[str]:
    """Distinct values over the agent events, as the envelope recorded them (the projection)."""
    with project.index.connect() as conn:
        return [str(row[0]) for row in conn.execute(statement).all()]


WITHHELD_RATES = "withheld from the agent view"
WITHHELD_RECALL = "not computed (withheld until screening has started)"
_RATE_FIELDS = frozenset(
    {
        "calibration_sensitivity",
        "audit_false_exclusion_rate",
        "extraction_error_rate",
        "gate_audit",
        "miner_scores",
    }
)


def agent_methods(project: Project, report: MethodsReport) -> tuple[MethodsReport, frozenset[str]]:
    """The report as an agent outside the passes may read it, and the fields it withholds.

    Label-derived rates (calibration sensitivity, the audit false-exclusion rate) are never given
    to an agent (decision 37.14). Held-out recall is withheld until a pass has been opened:
    before then, a per-search recall is a differential oracle for the held-out seeds. Kappa and
    development recall are unchanged. The services stay unrestricted; this is the agent view.
    """
    withheld = set(_RATE_FIELDS)
    update: dict[str, object] = {
        "calibration_sensitivity": {label: None for label in report.calibration_sensitivity},
        "audit_false_exclusion_rate": None,
        "extraction_error_rate": None,
    }
    if not _screening_started(project):
        withheld.add("recall_held_out")
        update["recall_held_out"] = None
        update["recall_held_out_admitted"] = 0
    update["imports"] = _imports(project, agent=True)
    update["gate_policy"] = [row.agent_view() for row in report.gate_policy]
    update["miners"] = [
        m.model_copy(
            update={
                "recall": None,
                "field_agreement": None,
                "precision": None,
                "verification_rate": None,
            }
        )
        for m in report.miners
    ]
    return report.model_copy(update=update), frozenset(withheld)


def _screening_started(project: Project) -> bool:
    """Whether any screening pass has been opened."""
    return held_out_visible(project)


def render_methods(report: MethodsReport, *, withheld: frozenset[str] = frozenset()) -> str:
    """The methods statement as Markdown paragraphs, separated by blank lines, in the order:
    search, deduplication, screening and automation, agreement and audit, full-text screening,
    extraction and evidence (when declared), reference lists and snowballing (when run), seed
    recall, deviations.

    `withheld` names the fields an agent view hides; each is rendered as withheld, not as zero.
    """
    paragraphs = [
        _search(report),
        _deduplication(report),
        _screening(report),
        _agreement_and_audit(report, withheld),
        _full_text(report),
        *([] if report.extraction_pack is None else [_extraction(report, withheld)]),
        *([] if report.extraction_pack is None else [_evidence(report)]),
        *([] if report.reference_parser is None else [_references_paragraph(report)]),
        *[_import_paragraph(i) for i in report.imports],
        _seed_recall(report, withheld),
        *([] if report.supplied_links is None else [_supplied(report.supplied_links)]),
        *([] if not report.miners else [_miners_paragraph(report, withheld)]),
        *([] if not report.gate_policy else [_gate_policy(report, withheld)]),
        _deviations(report),
    ]
    return "\n\n".join(paragraphs) + "\n"


def _fmt(value: float | None) -> str:
    return NOT_COMPUTED if value is None else f"{value:.3f}"


def _list(values: list[str]) -> str:
    return ", ".join(values) if values else NONE_RECORDED


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in counts.items()) or NONE_RECORDED


def _search(report: MethodsReport) -> str:
    flow = report.prisma
    protocol = report.protocol_id or NOT_COMPUTED
    profile = report.method_profile or NOT_COMPUTED
    return (
        f"Search. The protocol {protocol} (method profile {profile}; rigour mode "
        f"{report.rigor_mode}) governed the search of the databases {_list(report.sources)}. "
        f"Records identified from databases: {_counts(flow.identified_databases)}. "
        f"Records identified by other methods: {_counts(flow.identified_other)}. "
        f"Citation-chase rounds: {report.chase_rounds}."
    )


def _references_paragraph(report: MethodsReport) -> str:
    flow = report.prisma
    rounds = report.snowball_rounds
    return (
        f"Reference lists and snowballing. Reference lists were parsed from "
        f"{report.reference_extractions} included work(s) ({report.reference_parser}, matcher "
        f"version {report.reference_matcher}): {report.reference_entries} entries, "
        f"{report.reference_resolved} resolved, {report.reference_unresolved} unresolved. "
        f"Snowball rounds: backward {rounds.get('backward', 0)} (from the documents' reference "
        f"lists), forward {rounds.get('forward', 0)} (from source metadata, as citation "
        f"chasing); stopping rule: {report.snowball_rule or NONE_RECORDED}. Records by "
        f"mechanism: {_counts(flow.identified_other_detail)}."
    )


_PART_ORDER = {"held-out": 0, "development": 1, "unsplit": 2}
_PART_TITLE = {"held-out": "Held-out", "development": "Development", "unsplit": "All"}


def _import_paragraph(entry: ImportMethods) -> str:
    """One paragraph per import, the held-out part first (R-24)."""
    parts = [
        _part_sentence(p, entry.label)
        for p in sorted(entry.parts, key=lambda p: _PART_ORDER[p.part])
    ]
    if entry.held_out_withheld:
        parts.insert(0, "Held-out part: withheld until screening has started.")
    return f"Library import {entry.import_id} ({entry.label}). " + " ".join(parts)


def _ratio_text(name: str, ratio: Ratio | None) -> str:
    if ratio is None:
        return f"{name} {NOT_COMPUTED}"
    return f"{name} {ratio.numerator}/{ratio.denominator} ({ratio.value:.3f})"


def _part_sentence(part: PartCoverage, label: str) -> str:
    c = part.counts
    note = " (optimistic: the library may have shaped the queries)" if label == "optimistic" else ""
    return (
        f"{_PART_TITLE[part.part]} part{note}: {part.resolved} resolved records, "
        f"{c[Bucket.FOUND_DATABASE]} found by database search, "
        f"{c[Bucket.FOUND_SUPPLEMENTARY]} by supplementary routes, "
        f"{c[Bucket.QUERY_MISS]} missed within reach, "
        f"{c[Bucket.OUTSIDE_LIMITS]} outside limits, "
        f"{c[Bucket.NOT_IN_SOURCES]} in no declared source, "
        f"{c[Bucket.SOURCE_UNCHECKED]} with a source unchecked; "
        f"{part.unresolved} unresolved, {part.unconfirmed} unconfirmed; "
        f"{_ratio_text('search sensitivity', part.sensitivity)}, "
        f"{_ratio_text('corpus coverage', part.coverage)}."
    )


def _deduplication(report: MethodsReport) -> str:
    flow = report.prisma
    return (
        f"Deduplication. Duplicate records were removed ({flow.duplicates_removed}), leaving "
        f"{flow.screened} unique works for screening."
    )


def _screening(report: MethodsReport) -> str:
    flow = report.prisma
    breakdown = ", ".join(f"{criterion} ({n})" for criterion, n in flow.excluded.items())
    provisional = " The flow is provisional." if flow.provisional else ""
    return (
        f"Screening of {flow.screened} works: {flow.included} included, "
        f"{flow.excluded_total} excluded, {flow.pending} pending.{provisional} "
        "Exclusions by criterion: "
        f"{breakdown or NONE_RECORDED}. "
        "Screening decisions were made by Claude models (as reported by the agent: "
        f"{_list(report.models)}) following the skills {_list(report.skills)}; "
        "the platform made no model calls."
    )


def _agreement_and_audit(report: MethodsReport, withheld: frozenset[str]) -> str:
    per_criterion = ", ".join(f"{c} {_fmt(k)}" for c, k in report.kappa_by_criterion.items())
    sensitivity = ", ".join(f"{p} {_fmt(s)}" for p, s in report.calibration_sensitivity.items())
    if "calibration_sensitivity" in withheld:
        sensitivity = WITHHELD_RATES
    passes = NOT_COMPUTED if report.passes == 0 else str(report.passes)
    rate = _fmt(report.audit_false_exclusion_rate)
    audit = (
        f"Audit false-exclusion rate: {WITHHELD_RATES}."
        if "audit_false_exclusion_rate" in withheld
        else f"Audit false-exclusion rate: {rate} over {report.audit_n} labelled works."
        if report.audit_n
        else f"Audit false-exclusion rate: {NOT_COMPUTED} (no audit labels)."
    )
    return (
        f"Agreement and audit. Screening passes: {passes}; planned dual-coded share: "
        f"{_fmt(report.dual_sample)}. Agreement between passes (Cohen's kappa): "
        f"{_fmt(report.kappa)}; per-criterion kappa: {per_criterion or NOT_COMPUTED}. "
        f"Calibration sensitivity per pass: {sensitivity or NOT_COMPUTED}. "
        f"{audit}"
    )


def _full_text(report: MethodsReport) -> str:
    if not report.full_text_passes:
        return (
            "Full-text screening. The full-text stage has not run: the protocol declares no "
            "full-text screening plan."
        )
    boxes = report.prisma.full_text
    reasons = ", ".join(f"{reason} ({n})" for reason, n in boxes.not_retrieved_reasons.items())
    excluded = ", ".join(f"{criterion} ({n})" for criterion, n in boxes.excluded.items())
    fraction = _fmt(report.full_text_audit_fraction)
    hint = (
        " Unconverted works need `factory document convert`."
        if boxes.not_retrieved_reasons.get(UNCONVERTED)
        else ""
    )
    state = (
        f"{boxes.assessed} assessed, {boxes.included} included, {boxes.excluded_total} excluded, "
        f"{boxes.pending} pending. Exclusions by criterion: {excluded or NONE_RECORDED}."
        if boxes.stage_run
        else "No full-text decision has been recorded; the stage has not run."
    )
    return (
        f"Full-text screening. Screening passes: {report.full_text_passes}; planned dual-coded "
        f"share: {_fmt(report.full_text_dual_sample)}; kappa floor "
        f"{_fmt(report.full_text_kappa_floor)}; audit fraction {fraction} with a minimum of "
        f"{report.full_text_audit_minimum}. Of {boxes.sought} sought, {boxes.not_retrieved} not "
        f"retrieved (reasons: {reasons or NONE_RECORDED}).{hint} {state} Agreement between passes "
        f"(Cohen's kappa): {_fmt(report.full_text_kappa)}. Full-text sessions: "
        f"{report.full_text_sessions}; models (as reported by the agent): "
        f"{_list(report.full_text_models)}."
    )


def _extraction(report: MethodsReport, withheld: frozenset[str]) -> str:
    rate = _fmt(report.extraction_error_rate)
    audit = (
        f"Extraction audit error rate: {WITHHELD_RATES}."
        if "extraction_error_rate" in withheld
        else f"Extraction audit error rate: {rate} over {report.extraction_audit_n} labelled "
        "values."
        if report.extraction_audit_n
        else f"Extraction audit error rate: {NOT_COMPUTED} (no audit labels)."
    )
    dual = (
        "all works"
        if report.extraction_dual_sample is None
        else _fmt(report.extraction_dual_sample)
    )
    return (
        f"Extraction. Data were extracted with the pack {report.extraction_pack}; declared "
        f"fields: {_list(report.extraction_fields)}. Extraction passes opened: "
        f"{report.extraction_passes}; planned dual-extracted share: "
        f"{dual}. Extraction sessions: {report.extraction_sessions}; models (as reported by the "
        f"agent): {_list(report.extraction_models)}. Overall agreement of the passes: "
        f"{_fmt(report.extraction_agreement)}, over the compared field values of aligned rows "
        f"(unmatched rows are reported separately). {audit} Known limits: the citation-marker "
        "check matches at most five author surnames, so a longer parenthetical citation "
        'without "et al" is not detected as a copy marker; a value inside a cell such as '
        "`79.8 ± 0.2` lets `0.2` match, which agreement and audit catch; `reproduced` is "
        "recorded and not checked. The platform extracted nothing itself."
    )


def _evidence(report: MethodsReport) -> str:
    return (
        f"Evidence. Extracted results form {report.evidence_groups} group(s) by the declared "
        f"comparability keys ({_list(report.evidence_comparability_keys)}); "
        f"{report.evidence_multi_source_groups} group(s) hold results of more than one "
        "independent work. Results are grouped only by these keys and are never ranked across "
        f"groups. The groups hold {report.evidence_rows} row(s): {report.evidence_independent} "
        f"independent and {report.evidence_copied} copied; copied results are flagged and not "
        "counted as independent. Frontiers use params, FLOPs and MACs only "
        f"(computed for: {_list(report.evidence_frontier_costs)}); throughput and latency "
        "appear only as within-paper ratios. Counts are computed from the extraction events."
    )


def _seed_recall(report: MethodsReport, withheld: frozenset[str]) -> str:
    """Recall counts seeds found by search only (decision 54); admitted seeds are listed beside."""
    if "recall_held_out" in withheld:
        held_out = WITHHELD_RECALL
        held_admitted = ""
    else:
        held_out = _fmt(report.recall_held_out)
        held_admitted = f" Held-out seeds admitted, not counted: {report.recall_held_out_admitted}."
    return (
        f"Seed recall. Held-out seed recall: {held_out}. "
        f"Development seed recall: {_fmt(report.recall_development)} (optimistic: the development "
        "seeds informed the protocol and the screening instructions). "
        "Recall counts seeds found by search; a seed a human admitted after an explained miss is "
        f"retrieved but not counted.{held_admitted} "
        f"Development seeds admitted, not counted: {report.recall_development_admitted}. "
        f"Seeds admitted by lookup: {report.admitted_seeds}."
    )


def _supplied(links: SuppliedLinks) -> str:
    return (
        f"Supplied links. Links captured: {_counts(links.captured)}. "
        f"Links resolved: {_counts(links.resolved)}. "
        f"Included works that came only through supplied links: {_counts(links.included)}. "
        "Supplied works were screened under the same protocol, criteria and passes as every "
        "other record; screeners did not see how a work was found."
    )


def _miners_paragraph(report: MethodsReport, withheld: frozenset[str]) -> str:
    """Registered miners: each version, who proposed it, its state and, for the researcher, its
    calibration scores. Failed and retired versions are listed as such (R-52)."""
    parts = [
        "Registered miners. A miner proposed by an agent is exploratory until a calibration "
        "sample, labelled by a human, passes thresholds at or above the platform floors; the "
        "proposer never evaluates it."
    ]
    for m in report.miners:
        text = f"Miner {m.name} version {m.version} (proposed by {m.proposer_kind}): {m.state}"
        if m.state == "retired" and m.calibration in ("passed", "failed"):
            text += f" (calibration {m.calibration})"
        text += "."
        if m.calibration_units is not None:
            if "miner_scores" in withheld:
                text += f" Calibration over {m.calibration_units} unit(s): {WITHHELD_RATES}."
            elif m.recall is None and m.field_agreement is None:
                text += f" Calibration over {m.calibration_units} unit(s): {NOT_COMPUTED}."
            else:
                text += (
                    f" Calibration over {m.calibration_units} unit(s): record recall "
                    f"{_fmt(m.recall)}, field agreement {_fmt(m.field_agreement)}, precision "
                    f"{_fmt(m.precision)}, verification rate {_fmt(m.verification_rate)}."
                )
        text += " Admitted as evidence." if m.evidence else " Not admitted as evidence."
        parts.append(text)
    return " ".join(parts)


def _gate_policy(report: MethodsReport, withheld: frozenset[str]) -> str:
    """Decision gates passed by an agent, or under a protocol policy: who passed what."""
    parts = [
        "Decision gates. A gate is passed by a human, or, where its policy is agent_audit, by an "
        "agent whose acts a human audits on a random sample."
    ]
    for row in report.gate_policy:
        counts = ", ".join(f"{level} {n}" for level, n in row.counts.items())
        text = f"Gate {row.gate_id}: policy {row.policy} (from the {row.source}); acts {counts}."
        if row.audit is None:
            text += " No human audit drawn."
        elif "gate_audit" in withheld or row.audit.labelled is None:
            text += " A human audit was drawn; its figures are " + WITHHELD_RATES + "."
        else:
            text += (
                f" Human audit: {row.audit.sample_size} sampled, {row.audit.labelled} labelled, "
                f"{row.audit.incorrect} incorrect."
            )
        if row.below_policy:
            text += (
                f" {row.below_policy} act(s) were passed by an agent before the policy "
                "became human."
            )
        parts.append(text)
    return " ".join(parts)


def _deviations(report: MethodsReport) -> str:
    return (
        f"Deviations. Protocol amendments recorded: {report.amendments}. "
        f"Deviations recorded: {report.deviations}."
    )
