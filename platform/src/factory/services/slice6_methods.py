"""The methods statement's counts of leads, hypotheses and tests (plan XP-B task 7; spec acceptance
11 and 23; R-52).

Invariants:
- Every figure is computed from the projection: nothing is typed and nothing is a rate derived from
  a label. The counts include every outcome, refuted and inconclusive ones too (R-52), so the
  statement cannot report successes only; a failed direction is counted by the registry.
- None depends on the held-out part of an import or on a screening label. An agent reads the same
  counts except for a confirmatory baseline's verdict before the unlock (`agent_counts`).
- Without any lead, hypothesis, design or registry row the statement has no such paragraph
  (`hypothesis_counts` returns None).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.evaluation import latest_evaluation
from factory.services.hypotheses import list_hypotheses
from factory.services.leads import list_leads
from factory.services.xrun_accounting import baseline_verdicts, hidden_baselines


class HypothesisCounts(StrictModel):
    leads_by_decision: dict[str, int]
    hypotheses_by_state: dict[str, int]
    outcomes: dict[str, int]
    """Latest evaluation of each evaluated hypothesis: supported, refuted, inconclusive; and
    `incomplete` for a hypothesis whose only evaluation is a progress report."""
    flags: dict[str, int]
    """Hypotheses whose latest evaluation carries the flag."""
    deviations_by_kind: dict[str, int]
    test_reuse: int
    baselines_by_verdict: dict[str, int]
    autonomy_agent: int
    """Registered hypotheses whose registration is labelled `autonomy: agent`."""
    registry_rows: int


def _count(values: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in sorted(values):
        out[v] = out.get(v, 0) + 1
    return out


def hypothesis_counts(project: Project) -> HypothesisCounts | None:
    project.index.sync()
    leads = list_leads(project)
    hypotheses = list_hypotheses(project)
    with project.index.connect() as conn:
        experiments = [
            str(e) for e in conn.execute(text("SELECT experiment_id FROM experiments")).scalars()
        ]
        deviations = [
            str(k) for k in conn.execute(text("SELECT kind FROM experiment_deviations")).scalars()
        ]
        reused = conn.execute(
            text("SELECT COUNT(*) FROM xruns WHERE flags_json LIKE '%test-reused%'")
        ).scalar_one()
        rows = conn.execute(text("SELECT COUNT(*) FROM directions")).scalar_one()
    if not (leads or hypotheses or experiments or rows):
        return None
    outcomes: list[str] = []
    flags: list[str] = []
    for v in hypotheses:
        live = latest_evaluation(project, v.hypothesis_id)
        if live is not None:
            outcomes.append(live.payload.outcome)
            flags += list(live.payload.flags)
    verdicts = [verdict for e in experiments for verdict in baseline_verdicts(project, e).values()]
    return HypothesisCounts(
        leads_by_decision=_count([lead.state for lead in leads]),
        hypotheses_by_state=_count([v.state for v in hypotheses]),
        outcomes=_count(outcomes),
        flags=_count(flags),
        deviations_by_kind=_count(deviations),
        test_reuse=int(reused),
        baselines_by_verdict=_count(verdicts),
        autonomy_agent=sum(1 for v in hypotheses if v.autonomy == "agent"),
        registry_rows=int(rows),
    )


def agent_counts(project: Project, counts: HypothesisCounts) -> HypothesisCounts:
    """The counts as an agent reads them: a baseline that reproduces on the confirmatory split
    counts as `resolved`, with its row and acceptance left out, until the unlock (decision 94)."""
    hidden = hidden_baselines(project)
    if not hidden:
        return counts
    with project.index.connect() as conn:
        experiments = [
            str(e) for e in conn.execute(text("SELECT experiment_id FROM experiments")).scalars()
        ]
        rows = {str(d) for d in conn.execute(text("SELECT direction_id FROM directions")).scalars()}
        deviations = [
            (str(e), str(k))
            for e, k in conn.execute(text("SELECT experiment_id, kind FROM experiment_deviations"))
        ]
    verdicts: list[str] = []
    for e in experiments:
        for key, verdict in baseline_verdicts(project, e).items():
            verdicts.append("resolved" if (e, key) in hidden and verdict != "pending" else verdict)
    designs = {e for e, _ in hidden}
    return counts.model_copy(
        update={
            "baselines_by_verdict": _count(verdicts),
            "deviations_by_kind": _count(
                [k for e, k in deviations if not (e in designs and k == "baseline-accepted")]
            ),
            "registry_rows": counts.registry_rows - len(rows & {f"{e}:{k}" for e, k in hidden}),
        }
    )


def _items(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {n}" for k, n in counts.items()) or "none"


def hypotheses_paragraph(c: HypothesisCounts) -> str:
    """Fixed sentences over the counts."""
    return (
        "Hypotheses and tests. "
        f"Leads by decision: {_items(c.leads_by_decision)}. "
        f"Hypotheses by state: {_items(c.hypotheses_by_state)}. "
        f"Outcomes, computed by the registered decision rule: {_items(c.outcomes)}. "
        f"Flags on outcomes: {_items(c.flags)}. "
        f"Design deviations by kind: {_items(c.deviations_by_kind)}. "
        f"Runs that read a confirmatory cell again: {c.test_reuse}. "
        f"Baselines by reproduction: {_items(c.baselines_by_verdict)}. "
        f"Hypotheses registered with autonomy: agent: {c.autonomy_agent}. "
        f"Failed-direction registry rows: {c.registry_rows}."
    )
