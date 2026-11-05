"""The benchmark ledger: reported against reproduced results, and own results, beside the evidence
report (slice 6, plan XP-B, spec ruling 25; R-125). Not slice 5's credit `ledger`.

Invariants:
- Read-only and recomputed on every call. It reads the evidence report and the projection of
  baseline verdicts and evaluations; it writes nothing and changes nothing the report holds.
- Reported and reproduced values are separate columns of a row (`reported`, `reproduced`); a
  reproduction never becomes a row of the evidence report.
- Own results (a computed evaluation's outcome, mean and interval) sit in `own_results` of the
  group whose key holds every condition of the hypothesis; they never enter a group's rows,
  frontiers or counts. A hypothesis with no condition appears in every group.
- A row's reproduction is read from the latest design that declares the row as a baseline:
  `reproduced`; `not-reproduced` (or `no-runs-completed`); `accepted` when a human accepted a
  baseline that did not reproduce (the deviation is on the design); `none` otherwise.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.evaluation import latest_evaluation
from factory.services.evidence_report import agent_evidence, evidence_report

Reproduction = Literal["reproduced", "not-reproduced", "accepted", "none"]


class LedgerRow(StrictModel):
    row_key: str
    work_id: str
    method_name: str | None
    reported: str
    reproduction: Reproduction
    reproduced: str | None
    experiment_id: str | None
    trace_id: str


class OwnResult(StrictModel):
    hypothesis_id: str
    experiment_id: str | None
    outcome: str
    mean: str | None
    ci_low: str | None
    ci_high: str | None
    n: int
    flags: tuple[str, ...]


class LedgerGroup(StrictModel):
    group_id: str
    key: list[tuple[str, str]]
    rows: list[LedgerRow]
    own_results: list[OwnResult]


def _reproductions(project: Project) -> dict[str, tuple[str, str, str | None, bool]]:
    """Row key to (experiment, verdict, reproduced value, accepted) of its latest design."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT b.row_key, b.experiment_id, b.verdict, b.reproduced, "
                "b.accepted_event_id IS NOT NULL FROM baseline_evaluations b "
                "JOIN experiments e ON e.experiment_id = b.experiment_id "
                "ORDER BY e.event_id"
            )
        ).all()
    return {
        str(r[0]): (str(r[1]), str(r[2]), None if r[3] is None else str(r[3]), bool(r[4]))
        for r in rows
    }


def _own_results(project: Project) -> list[tuple[dict[str, str], OwnResult]]:
    with project.index.connect() as conn:
        hypotheses = conn.execute(
            text("SELECT DISTINCT hypothesis_id FROM hypothesis_evaluations ORDER BY 1")
        ).scalars()
        ids = [str(h) for h in hypotheses]
    out: list[tuple[dict[str, str], OwnResult]] = []
    from factory.services.hypotheses import hypothesis_view

    for hid in ids:
        live = latest_evaluation(project, hid)
        view = hypothesis_view(project, hid)
        if live is None or view is None:
            continue
        p = live.payload
        out.append(
            (
                dict(view.spec.conditions),
                OwnResult(
                    hypothesis_id=hid,
                    experiment_id=p.experiment_id,
                    outcome=p.outcome,
                    mean=p.mean,
                    ci_low=p.ci_low,
                    ci_high=p.ci_high,
                    n=p.n,
                    flags=p.flags,
                ),
            )
        )
    return out


def ledger(
    project: Project, *, group_id: str | None = None, agent: bool = False
) -> list[LedgerGroup]:
    """The groups of the evidence report with reported and reproduced values and own results, in
    the report's order; one group when `group_id` names it (unknown: `group_id`: `unknown`). With
    `agent` the evidence report is read through its agent variant."""
    project.index.sync()
    report = evidence_report(project)
    if agent:
        report = agent_evidence(report)
    groups = report.groups
    if group_id is not None:
        groups = [g for g in groups if g.group_id == group_id]
        if not groups:
            raise FactoryValidationError([ValidationIssue("group_id", "unknown")])
    reproductions = _reproductions(project)
    own = _own_results(project)
    out: list[LedgerGroup] = []
    for group in groups:
        key = set(group.key)
        rows: list[LedgerRow] = []
        for row in group.rows:
            found = reproductions.get(row.row_key)
            reproduction: Reproduction = "none"
            if found is not None:
                _, verdict, _, accepted = found
                reproduction = (
                    "reproduced"
                    if verdict == "reproduced"
                    else "accepted"
                    if accepted
                    else "not-reproduced"
                )
            rows.append(
                LedgerRow(
                    row_key=row.row_key,
                    work_id=row.work_id,
                    method_name=row.method_name,
                    reported=row.value.canonical
                    if row.value.canonical is not None
                    else str(row.value.value),
                    reproduction=reproduction,
                    reproduced=None if found is None else found[2],
                    experiment_id=None if found is None else found[0],
                    trace_id=row.value.trace_id,
                )
            )
        out.append(
            LedgerGroup(
                group_id=group.group_id,
                key=list(group.key),
                rows=rows,
                own_results=[r for cond, r in own if set(cond.items()) <= key],
            )
        )
    return out
