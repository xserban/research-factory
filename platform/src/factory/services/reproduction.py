"""Baseline reproduction verdicts, written by the platform as `system` events (slice 6, plan XP-A
task 6; spec ruling 24).

Invariants:
- A baseline's verdict is written once, when every declared seed has a reported reproduction run
  and the baseline has no verdict yet. A later run, a re-run or a better number never changes it
  (no best-of-n): the first completed run of each seed is used.
- A seed whose runs all failed is left out of the mean and its runs are listed in the event. If
  every seed failed the verdict is `no-runs-completed`, which unlock treats as not reproduced.
- The reported value is the canonical value of the final evidence row `row_key`; the reproduced
  value is the mean of the primary metric (`hypotheses.reproduction`). Nothing here is typed by an
  agent: the verdict is bookkeeping, and the acceptance of a baseline that did not reproduce is a
  human act at the gate `experiments.accept_baseline` (`services.experiments.accept_baseline`).
"""

from __future__ import annotations

from factory.events.envelope import Event
from factory.extraction.numbers import parse_printed
from factory.hypotheses.reproduction import (
    EVALUATOR_VERSION,
    reproduced_value,
    reproduction_verdict,
)
from factory.model.experiments import BaselineEvaluated
from factory.services.context import Project
from factory.services.experiments import ExperimentView, experiment_view
from factory.services.extraction_agreement import FinalRow, final_rows
from factory.services.xrun_accounting import (
    ReproductionRun,
    Verdict,
    baseline_verdicts,
    reproduction_runs,
)

__all__ = ["Verdict", "baseline_verdicts", "evaluate_baselines"]


def _reported(row: FinalRow | None) -> str | None:
    """The canonical reported value of an evidence row's `value` field, if it has a number."""
    field = None if row is None else row.fields.get("value")
    if field is None:
        return None
    if field.canonical is not None:
        return field.canonical
    printed = parse_printed(str(field.value))
    if printed is None:
        return None
    return "0" if printed == 0 else format(printed.normalize(), "f")


def _used_runs(
    seeds: tuple[int, ...], runs: list[ReproductionRun]
) -> tuple[list[ReproductionRun], list[str]] | None:
    """The first completed run of each seed and the runs of seeds that only failed; None while a
    declared seed has no reported run."""
    included: list[ReproductionRun] = []
    excluded: list[str] = []
    for seed in sorted(set(seeds)):
        of_seed = [r for r in runs if r.seed == seed]
        if not of_seed:
            return None
        done = [r for r in of_seed if r.exit_status == 0]
        if done:
            included.append(done[0])
        else:
            excluded.extend(r.run_id for r in of_seed)
    return included, excluded


def _evaluate(project: Project, view: ExperimentView) -> list[Event]:
    pending = {
        k for k, v in baseline_verdicts(project, view.experiment_id).items() if v == "pending"
    }
    if not pending:
        return []
    rows = {r.row_key: r for r in final_rows(project)}
    metric = next(m.name for m in view.design.metrics if m.primary)
    events: list[Event] = []
    for baseline in view.design.baselines:
        if baseline.row_key not in pending:
            continue
        used = _used_runs(
            view.design.seeds, reproduction_runs(project, view.experiment_id, baseline.row_key)
        )
        reported = _reported(rows.get(baseline.row_key))
        if used is None or reported is None:
            continue
        included, excluded = used
        reproduced = reproduced_value([r.metrics[metric] for r in included])
        events.append(
            project.events.make(
                "baseline.evaluated",
                BaselineEvaluated(
                    experiment_id=view.experiment_id,
                    row_key=baseline.row_key,
                    reported=reported,
                    reproduced=reproduced,
                    runs=tuple(r.run_id for r in included),
                    excluded_runs=tuple(excluded),
                    tolerance=baseline.tolerance,
                    tolerance_kind=baseline.tolerance_kind,
                    verdict=reproduction_verdict(
                        reported, reproduced, baseline.tolerance, baseline.tolerance_kind
                    ),
                    evaluator_version=EVALUATOR_VERSION,
                ),
                project.system_actor(),
                refs=[view.experiment_id, baseline.row_key],
            )
        )
    return events


def evaluate_baselines(project: Project, experiment_id: str) -> list[str]:
    """Write the verdict of every baseline that is ready and has none (a `system` act) and return
    the event ids. Called after each ingestion of a reproduction run; safe to call again, it
    writes nothing for a baseline that already has a verdict."""
    with project.index.exclusive():
        project.index.sync()
        view = experiment_view(project, experiment_id)
        if view is None or view.state in ("draft", "superseded"):
            return []
        events = _evaluate(project, view)
        if events:
            project.record(events)
    return [e.id for e in events]
