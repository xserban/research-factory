"""Budget, test-access and evidence accounting over the runs of a design (slice 6, plan XP-A;
rulings 9 and 18). Read-only: every figure is computed on read from the `xruns` table, never
stored, never typed.

Invariants:
- GPU-hours used is the sum over reported runs, failed runs included. `max_runs` counts registered
  runs. `over` is true when the hours used exceed the budget.
- The access count of a primary cell is the number of confirmatory reports that carry a metric
  value (a failed run too) for that cell, or for its seed when a baseline reproduces there; every
  primary cell is listed, with 0 when unread.
- A hypothesis has confirmatory evidence when any confirmatory run of a design that names it has
  been reported, a baseline reproduction and a failed run too: they may have read the test split
  (R-52, rulings 12 and 18).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import text

from factory.hypotheses.design import cell_hash, primary_cells
from factory.index.experiments import design_of
from factory.model.base import StrictModel
from factory.services.context import Project


class BudgetView(StrictModel):
    gpu_hours_budget: str
    gpu_hours_used: str
    runs_registered: int
    max_runs: int
    over: bool


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f") if value != 0 else "0"


def budget_view(project: Project, experiment_id: str) -> BudgetView | None:
    project.index.sync()
    with project.index.connect() as conn:
        raw = conn.execute(
            text("SELECT design_json FROM experiments WHERE experiment_id = :e"),
            {"e": experiment_id},
        ).scalar()
        if raw is None:
            return None
        design = design_of(raw)
        hours = conn.execute(
            text("SELECT gpu_hours FROM xruns WHERE experiment_id = :e AND gpu_hours IS NOT NULL"),
            {"e": experiment_id},
        ).scalars()
        used = sum((Decimal(str(h)) for h in hours), Decimal(0))
        registered = conn.execute(
            text("SELECT COUNT(*) FROM xruns WHERE experiment_id = :e"), {"e": experiment_id}
        ).scalar_one()
    return BudgetView(
        gpu_hours_budget=_plain(Decimal(design.budget.gpu_hours)),
        gpu_hours_used=_plain(used),
        runs_registered=int(registered),
        max_runs=design.budget.max_runs,
        over=used > Decimal(design.budget.gpu_hours),
    )


def access_counts(project: Project, experiment_id: str) -> dict[str, int]:
    """Primary cell hash to the number of reports that read it on the confirmatory split: the
    primary runs of that cell and the confirmatory baseline reproductions of its seed. A report
    that carries a metric value counts, a failed run too (ruling 18: it has read the split)."""
    project.index.sync()
    with project.index.connect() as conn:
        raw = conn.execute(
            text("SELECT design_json FROM experiments WHERE experiment_id = :e"),
            {"e": experiment_id},
        ).scalar()
        if raw is None:
            return {}
        counts = {cell_hash(c): 0 for c in primary_cells(design_of(raw))}
        rows = conn.execute(
            text(
                "SELECT access_hash, COUNT(*) FROM xruns WHERE experiment_id = :e "
                "AND access_hash IS NOT NULL "
                "AND reported_event_id IS NOT NULL AND metrics_json IS NOT NULL "
                "AND metrics_json != '{}' "
                "GROUP BY access_hash"
            ),
            {"e": experiment_id},
        ).all()
    for key, count in rows:
        if str(key) in counts:
            counts[str(key)] = int(count)
    return counts


def confirmatory_evidence(project: Project, hypothesis_id: str) -> bool:
    """Whether a confirmatory result exists for a design that names the hypothesis: the provider
    of `services.hypotheses.CONFIRMATORY_SOURCES`."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT 1 FROM xruns x JOIN experiments e ON e.experiment_id = x.experiment_id "
                "WHERE e.hypothesis = :h AND x.split = 'confirmatory' "
                "AND x.reported_event_id IS NOT NULL LIMIT 1"
            ),
            {"h": hypothesis_id},
        ).first()
    return found is not None


Verdict = Literal["reproduced", "not-reproduced", "accepted", "pending"]


def baseline_verdicts(project: Project, experiment_id: str) -> dict[str, Verdict]:
    """The state of each declared baseline: `reproduced` or `not-reproduced` once the platform has
    written its verdict (`no-runs-completed` reads as `not-reproduced`), `accepted` once a human
    accepted a baseline that did not reproduce, else `pending`."""
    project.index.sync()
    with project.index.connect() as conn:
        raw = conn.execute(
            text("SELECT design_json FROM experiments WHERE experiment_id = :e"),
            {"e": experiment_id},
        ).scalar()
        if raw is None:
            return {}
        rows = {
            str(r[0]): (str(r[1]), r[2] is not None)
            for r in conn.execute(
                text(
                    "SELECT row_key, verdict, accepted_event_id FROM baseline_evaluations "
                    "WHERE experiment_id = :e"
                ),
                {"e": experiment_id},
            ).all()
        }
    out: dict[str, Verdict] = {}
    for baseline in design_of(raw).baselines:
        found = rows.get(baseline.row_key)
        if found is None:
            out[baseline.row_key] = "pending"
        elif found[1]:
            out[baseline.row_key] = "accepted"
        else:
            out[baseline.row_key] = "reproduced" if found[0] == "reproduced" else "not-reproduced"
    return out


def baseline_flags(project: Project, experiment_id: str) -> tuple[str, ...]:
    """`baseline-not-reproduced` when a baseline that did not reproduce was accepted (R-122): it
    flags every outcome that depends on the design."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT 1 FROM baseline_evaluations WHERE experiment_id = :e "
                "AND accepted_event_id IS NOT NULL LIMIT 1"
            ),
            {"e": experiment_id},
        ).first()
    return () if found is None else ("baseline-not-reproduced",)


@dataclass(frozen=True)
class ReproductionRun:
    run_id: str
    seed: int
    exit_status: int
    metrics: dict[str, str]


def reproduction_runs(project: Project, experiment_id: str, row_key: str) -> list[ReproductionRun]:
    """The reported, planned (not exploratory) reproduction runs of one baseline, in the order they
    were reported. A seed may have several (a re-run is a new run)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT run_id, seed, exit_status, metrics_json FROM xruns "
                "WHERE experiment_id = :e AND arm = :a AND exploratory = 0 "
                "AND reported_event_id IS NOT NULL ORDER BY reported_event_id"
            ),
            {"e": experiment_id, "a": f"reproduction:{row_key}"},
        ).all()
    return [
        ReproductionRun(
            run_id=str(r[0]),
            seed=int(r[1]),
            exit_status=int(r[2]),
            metrics={}
            if r[3] is None
            else {str(k): str(v) for k, v in json.loads(str(r[3])).items()},
        )
        for r in rows
    ]
