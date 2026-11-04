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

from pydantic import Field
from sqlalchemy import TextClause, text

from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.services.agreement import agreement_summary
from factory.services.audit import audit_report
from factory.services.calibration import calibration_status
from factory.services.chase import chase_rounds
from factory.services.context import Project
from factory.services.extraction_agreement import agreement_overall
from factory.services.extraction_audit import extraction_audit_report
from factory.services.prisma import (
    UNCONVERTED,
    PrismaFlow,
    has_full_text_plan,
    prisma_flow,
    search_report,
)
from factory.services.protocol import current_protocol, list_amendments, list_deviations
from factory.services.seeds import _rigor_mode, admitted_seed_count, seed_recall

NOT_COMPUTED = "not computed"
NONE_RECORDED = "none recorded"


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
    )


def _extraction_sessions(project: Project) -> list[tuple[str, str]]:
    """(session, model) of every session bound to an extraction pass."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT session, model FROM extraction_sessions ORDER BY session")
        ).all()
    return [(str(session), str(model)) for session, model in rows]


def _extraction_pass_count(project: Project) -> int:
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM extraction_passes")).scalar_one())


def _full_text_sessions(project: Project) -> list[tuple[str, str]]:
    """(session, model) of every session bound to a full-text pass, as the sessions reported."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT session, model FROM pass_sessions WHERE stage = :stage ORDER BY session"),
            {"stage": ScreeningStage.FULL_TEXT.value},
        ).all()
    return [(str(session), str(model)) for session, model in rows]


_AGENT_MODELS = text(
    "SELECT DISTINCT model FROM events WHERE actor_kind = 'agent' AND model IS NOT NULL "
    "ORDER BY model"
)
_AGENT_SKILLS = text(
    "SELECT DISTINCT skill FROM events WHERE actor_kind = 'agent' AND skill IS NOT NULL "
    "ORDER BY skill"
)


def _agent_values(project: Project, statement: TextClause) -> list[str]:
    """Distinct values over the agent events, as the envelope recorded them (the projection)."""
    with project.index.connect() as conn:
        return [str(row[0]) for row in conn.execute(statement).all()]


WITHHELD_RATES = "withheld from the agent view"
WITHHELD_RECALL = "not computed (withheld until screening has started)"
_RATE_FIELDS = frozenset(
    {"calibration_sensitivity", "audit_false_exclusion_rate", "extraction_error_rate"}
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
    return report.model_copy(update=update), frozenset(withheld)


def _screening_started(project: Project) -> bool:
    """Whether any screening pass has been opened."""
    project.index.sync()
    with project.index.connect() as conn:
        return conn.execute(text("SELECT 1 FROM passes LIMIT 1")).first() is not None


def render_methods(report: MethodsReport, *, withheld: frozenset[str] = frozenset()) -> str:
    """The methods statement as Markdown paragraphs, separated by blank lines, in the order:
    search, deduplication, screening and automation, agreement and audit, full-text screening,
    seed recall, deviations.

    `withheld` names the fields an agent view hides; each is rendered as withheld, not as zero.
    """
    paragraphs = [
        _search(report),
        _deduplication(report),
        _screening(report),
        _agreement_and_audit(report, withheld),
        _full_text(report),
        *([] if report.extraction_pack is None else [_extraction(report, withheld)]),
        _seed_recall(report, withheld),
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


def _seed_recall(report: MethodsReport, withheld: frozenset[str]) -> str:
    held_out = WITHHELD_RECALL if "recall_held_out" in withheld else _fmt(report.recall_held_out)
    return (
        f"Seed recall. Held-out seed recall: {held_out}. "
        f"Development seed recall: {_fmt(report.recall_development)} (optimistic: the development "
        "seeds informed the protocol and the screening instructions). "
        f"Seeds admitted by lookup: {report.admitted_seeds}."
    )


def _deviations(report: MethodsReport) -> str:
    return (
        f"Deviations. Protocol amendments recorded: {report.amendments}. "
        f"Deviations recorded: {report.deviations}."
    )
