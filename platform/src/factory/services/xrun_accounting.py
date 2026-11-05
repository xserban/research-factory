"""Budget, test-access and evidence accounting over the runs of a design (slice 6, plan XP-A;
rulings 9 and 18). Read-only: every figure is computed on read from the `xruns` table, never
stored, never typed.

Invariants:
- GPU-hours used is the sum over reported runs, failed runs included. `max_runs` counts registered
  runs. `over` is true when the hours used exceed the budget.
- The access count of a primary cell is the number of completed (exit status 0) confirmatory runs
  of that exact cell; every primary cell is listed, with 0 when unread. Baseline reproductions are
  not test accesses.
- A hypothesis has confirmatory evidence when any confirmatory, non-reproduction run of a design
  that names it has been reported, failed runs included: a run that failed may still have read the
  test split (R-52, ruling 12).
"""

from __future__ import annotations

from decimal import Decimal

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
    """Primary cell hash to the number of completed confirmatory runs of that cell."""
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
                "SELECT cell_hash, COUNT(*) FROM xruns WHERE experiment_id = :e "
                "AND split = 'confirmatory' AND arm NOT LIKE 'reproduction:%' "
                "AND reported_event_id IS NOT NULL AND exit_status = 0 GROUP BY cell_hash"
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
                "AND x.arm NOT LIKE 'reproduction:%' AND x.reported_event_id IS NOT NULL LIMIT 1"
            ),
            {"h": hypothesis_id},
        ).first()
    return found is not None
