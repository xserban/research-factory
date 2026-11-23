"""Benchmark metrics of one study, to compare tiers and autonomy levels (plan C9).

`level_metrics` is read-only and computed from the project's events, its index and its run logs;
it writes nothing and calls no model. Invariants:
- Every figure is computed here, never typed. A figure the project cannot give is None, not zero.
- Held-out seed recall comes only through `methods.agent_methods`, the aggregate the agent reports
  use: it is None (`held_out_withheld`) until a screening pass has been opened. No seed is named.
- Label-derived rates (calibration sensitivity, the screening audit's false-exclusion rate) are
  not read (decision 37.14). The overturn rate is the gate audit's, over its labelled acts.
- Tokens and cost exist only where a run's `log.jsonl` holds them (`cost_source` says which).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field
from sqlalchemy import text

from factory.model.base import StrictModel
from factory.services import run_costs
from factory.services.context import Project
from factory.services.gates import autonomy_counts
from factory.services.methods import agent_methods, methods_report


class GateClosures(StrictModel):
    """Acts recorded at one gate, by autonomy kind (`human`, `audited-agent`, `agent`)."""

    gate_id: str
    by_autonomy: dict[str, int]


class LevelMetrics(StrictModel):
    project: str
    rigor_mode: str
    events: int
    events_by_family: dict[str, int]
    """Event counts by the first segment of the event type (`search`, `screening`, ...)."""
    first_event_at: str | None
    last_event_at: str | None
    elapsed_seconds: float | None
    """Last minus first event timestamp: the span the log records, not working time."""
    runner_runs: int
    runner_runs_complete: int
    cost_source: str
    """Where cost figures come from (the run costs report's `cost_source`)."""
    reported_cost_usd: float | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    included: int
    """Works included at the last declared screening stage, from the PRISMA flow."""
    recall_development: float | None
    recall_held_out: float | None
    """None while withheld; see the module invariants."""
    held_out_withheld: bool
    screening_kappa: float | None
    extraction_agreement: float | None
    gates_closed: dict[str, int] = Field(default_factory=dict)
    """Totals over all gates, by autonomy kind."""
    gates: list[GateClosures] = Field(default_factory=list)
    """Only gates with at least one act."""
    audited_acts: int = 0
    """Gate-audit acts with a human label."""
    overturned_acts: int = 0
    overturn_rate: float | None = None
    """Overturned over labelled gate-audit acts; None when none is labelled."""
    unavailable: list[str] = Field(default_factory=list)
    """Names of the figures that are None because the project holds nothing to compute them."""


def _family(event_type: str) -> str:
    return event_type.split(".", 1)[0]


def _timeline(project: Project) -> tuple[int, dict[str, int], str | None, str | None]:
    with project.index.connect() as conn:
        types = conn.execute(text("SELECT type, COUNT(*) FROM events GROUP BY type")).all()
        span = conn.execute(text("SELECT MIN(ts), MAX(ts) FROM events")).one()
    families: dict[str, int] = {}
    for event_type, count in types:
        key = _family(str(event_type))
        families[key] = families.get(key, 0) + int(count)
    first = None if span[0] is None else str(span[0])
    last = None if span[1] is None else str(span[1])
    return sum(families.values()), dict(sorted(families.items())), first, last


def _seconds(first: str | None, last: str | None) -> float | None:
    if first is None or last is None:
        return None
    return (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds()


def _gates(project: Project) -> tuple[dict[str, int], list[GateClosures]]:
    from factory.services.modules.default import default_modules  # the registry imports services

    totals: dict[str, int] = {}
    rows: list[GateClosures] = []
    for gate in default_modules().gates():
        counts = {level.value: n for level, n in autonomy_counts(project, gate.gate_id).items()}
        if not sum(counts.values()):
            continue
        rows.append(GateClosures(gate_id=gate.gate_id, by_autonomy=counts))
        for kind, n in counts.items():
            totals[kind] = totals.get(kind, 0) + n
    return totals, rows


def _overturn(project: Project) -> tuple[int, int]:
    """Labelled and overturned acts of every gate audit (latest label of each act)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT COUNT(correct), COALESCE(SUM(CASE WHEN correct = 0 THEN 1 ELSE 0 END), 0) "
                "FROM gate_audit_items"
            )
        ).one()
    return int(row[0]), int(row[1])


def level_metrics(project: Project) -> LevelMetrics:
    """The metrics of `project` (read-only; syncs the index like every read)."""
    project.index.sync()
    report, _ = agent_methods(project, methods_report(project))
    events, families, first, last = _timeline(project)
    runs = run_costs.runs_with_logs(project)
    costs = run_costs.cost_report(project, runs=runs)
    totals, gate_rows = _gates(project)
    labelled, overturned = _overturn(project)
    withheld = report.recall_held_out is None and report.recall_held_out_admitted is None
    metrics = LevelMetrics(
        project=project.paths.slug,
        rigor_mode=report.rigor_mode,
        events=events,
        events_by_family=families,
        first_event_at=first,
        last_event_at=last,
        elapsed_seconds=_seconds(first, last),
        runner_runs=len(runs),
        runner_runs_complete=sum(1 for cost, _ in runs if cost.complete),
        cost_source=costs.cost_source,
        reported_cost_usd=costs.total_reported_cost_usd,
        input_tokens=sum(log.input_tokens for _, log in runs),
        output_tokens=sum(log.output_tokens for _, log in runs),
        cache_read_tokens=sum(log.cache_read_tokens for _, log in runs),
        cache_write_tokens=sum(log.cache_write_tokens for _, log in runs),
        included=report.prisma.included,
        recall_development=report.recall_development,
        recall_held_out=report.recall_held_out,
        held_out_withheld=withheld,
        screening_kappa=report.kappa,
        extraction_agreement=report.extraction_agreement,
        gates_closed=totals,
        gates=gate_rows,
        audited_acts=labelled,
        overturned_acts=overturned,
        overturn_rate=None if labelled == 0 else overturned / labelled,
    )
    figures = {
        "recall_development": metrics.recall_development,
        "recall_held_out": metrics.recall_held_out,
        "screening_kappa": metrics.screening_kappa,
        "extraction_agreement": metrics.extraction_agreement,
        "reported_cost_usd": metrics.reported_cost_usd,
        "overturn_rate": metrics.overturn_rate,
        "elapsed_seconds": metrics.elapsed_seconds,
    }
    return metrics.model_copy(update={"unavailable": [k for k, v in figures.items() if v is None]})


def render_table(metrics: LevelMetrics) -> str:
    """The metrics as plain `name  value` lines; a missing figure prints `-`."""

    def fmt(value: object) -> str:
        return (
            "-" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))
        )

    rows: list[tuple[str, object]] = [
        ("project", metrics.project),
        ("rigor mode", metrics.rigor_mode),
        ("events", metrics.events),
        ("elapsed seconds", metrics.elapsed_seconds),
        ("runner runs", metrics.runner_runs),
        ("runner runs complete", metrics.runner_runs_complete),
        ("cost source", metrics.cost_source),
        ("reported cost usd", metrics.reported_cost_usd),
        ("input tokens", metrics.input_tokens),
        ("output tokens", metrics.output_tokens),
        ("included works", metrics.included),
        ("development seed recall", metrics.recall_development),
        (
            "held-out seed recall",
            "withheld" if metrics.held_out_withheld else metrics.recall_held_out,
        ),
        ("screening kappa", metrics.screening_kappa),
        ("extraction agreement", metrics.extraction_agreement),
        ("gate acts audited", metrics.audited_acts),
        ("gate acts overturned", metrics.overturned_acts),
        ("overturn rate", metrics.overturn_rate),
    ]
    lines = [f"{name:<26}{fmt(value)}" for name, value in rows]
    for kind in sorted(metrics.gates_closed):
        lines.append(f"{'gates closed ' + kind:<26}{metrics.gates_closed[kind]}")
    for family, count in metrics.events_by_family.items():
        lines.append(f"{'events ' + family:<26}{count}")
    return "\n".join(lines)
