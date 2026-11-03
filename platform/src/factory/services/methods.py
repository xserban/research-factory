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

from sqlalchemy import TextClause, text

from factory.model.base import StrictModel
from factory.services.agreement import agreement_summary
from factory.services.audit import audit_report
from factory.services.calibration import calibration_status
from factory.services.chase import chase_rounds
from factory.services.context import Project
from factory.services.prisma import PrismaFlow, prisma_flow, search_report
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
    )


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


def render_methods(report: MethodsReport) -> str:
    """The methods statement as Markdown paragraphs, separated by blank lines, in the order:
    search, deduplication, screening and automation, agreement and audit, seed recall, deviations.
    """
    paragraphs = [
        _search(report),
        _deduplication(report),
        _screening(report),
        _agreement_and_audit(report),
        _seed_recall(report),
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
    excluded = sum(flow.excluded.values())
    breakdown = ", ".join(f"{criterion} ({n})" for criterion, n in flow.excluded.items())
    provisional = " The flow is provisional." if flow.provisional else ""
    return (
        f"Screening of {flow.screened} works: {flow.included} included, {excluded} excluded, "
        f"{flow.pending} pending.{provisional} Exclusions by criterion: "
        f"{breakdown or NONE_RECORDED}. "
        "Screening decisions were made by Claude models (as reported by the agent: "
        f"{_list(report.models)}) following the skills {_list(report.skills)}; "
        "the platform made no model calls."
    )


def _agreement_and_audit(report: MethodsReport) -> str:
    per_criterion = ", ".join(f"{c} {_fmt(k)}" for c, k in report.kappa_by_criterion.items())
    sensitivity = ", ".join(f"{p} {_fmt(s)}" for p, s in report.calibration_sensitivity.items())
    passes = NOT_COMPUTED if report.passes == 0 else str(report.passes)
    rate = _fmt(report.audit_false_exclusion_rate)
    audit = (
        f"Audit false-exclusion rate: {rate} over {report.audit_n} labelled works."
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


def _seed_recall(report: MethodsReport) -> str:
    return (
        f"Seed recall. Held-out seed recall: {_fmt(report.recall_held_out)}. "
        f"Development seed recall: {_fmt(report.recall_development)} (optimistic: the development "
        "seeds informed the protocol and the screening instructions). "
        f"Seeds admitted by lookup: {report.admitted_seeds}."
    )


def _deviations(report: MethodsReport) -> str:
    return (
        f"Deviations. Protocol amendments recorded: {report.amendments}. "
        f"Deviations recorded: {report.deviations}."
    )
