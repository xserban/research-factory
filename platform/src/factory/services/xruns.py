"""Experiment runs: registration against planned cells and listing (slice 6, plan XP-A; spec rulings
18 to 24).

Invariants:
- A run's configuration, its hash and its cell hash are computed here from the frozen design and
  the cell; an agent states a cell and nothing else. No input carries a configuration map.
- A run is registered only against a frozen design. A planned cell (`planned_cells`) is accepted
  on its split; a confirmatory cell needs the unlock; a cell the design does not plan is accepted
  only on the `dev` split and marked exploratory (post hoc, IDEA-17), never on the confirmatory
  split. At most `max_runs` runs are registered per design.
- A re-run is a new `xrn_` for the same cell; nothing is replaced and nothing is dropped.
- Registering is an agent or human act; results enter only through ingestion (a human or a
  runner).
"""

from __future__ import annotations

import json
import re
import secrets
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.extraction.numbers import canonical, parse_printed
from factory.hypotheses.design import (
    access_hash,
    cell_hash,
    cell_in_design,
    config_hash,
    planned_cells,
    run_config,
)
from factory.index.experiments import report_flags
from factory.model.base import StrictModel
from factory.model.experiments import (
    MAX_RESULTS_BYTES,
    CanonicalMetric,
    Cell,
    ExperimentDesign,
    ResultsFile,
    XrunRegistered,
    XrunReported,
)
from factory.services.context import Project
from factory.services.experiments import ExperimentView, experiment_view, make_deviation_event
from factory.services.hypotheses import hypothesis_view
from factory.services.reproduction import evaluate_baselines
from factory.services.xrun_accounting import access_counts, budget_view

XrunState = Literal["planned", "completed", "failed"]


class XrunView(StrictModel):
    run_id: str
    experiment_id: str
    cell: Cell
    cell_hash: str
    access_hash: str | None = None
    """The primary cell this run reads on the confirmatory split; None on another split."""
    config_hash: str
    state: XrunState
    exploratory: bool
    flags: tuple[str, ...]
    event_id: str
    reported_event_id: str | None = None
    gpu_hours: str | None = None
    metrics: dict[str, str] | None = None
    """The canonical value of each metric of a reported run; None while planned. The agent surface
    does not carry it."""


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _flags(row: Any) -> tuple[str, ...]:
    if row.flags_json is None:
        return ()
    return tuple(str(f) for f in json.loads(str(row.flags_json)))


def _state(row: Any) -> XrunState:
    if row.reported_event_id is None:
        return "planned"
    return "completed" if int(row.exit_status) == 0 else "failed"


def _view(row: Any) -> XrunView:
    metrics: dict[str, str] | None = None
    if row.metrics_json is not None:
        metrics = {str(k): str(v) for k, v in json.loads(str(row.metrics_json)).items()}
    return XrunView(
        run_id=str(row.run_id),
        experiment_id=str(row.experiment_id),
        cell=Cell(
            universe=tuple((str(k), str(v)) for k, v in json.loads(str(row.universe_json))),
            seed=int(row.seed),
            arm=str(row.arm),
            split=row.split,
        ),
        cell_hash=str(row.cell_hash),
        access_hash=None if row.access_hash is None else str(row.access_hash),
        config_hash=str(row.config_hash),
        state=_state(row),
        exploratory=bool(row.exploratory),
        flags=_flags(row),
        event_id=str(row.event_id),
        reported_event_id=None if row.reported_event_id is None else str(row.reported_event_id),
        gpu_hours=None if row.gpu_hours is None else str(row.gpu_hours),
        metrics=metrics,
    )


def xrun_view(project: Project, run_id: str) -> XrunView | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT * FROM xruns WHERE run_id = :r"), {"r": run_id}).first()
    return None if row is None else _view(row)


def xrun_list(
    project: Project,
    experiment_id: str,
    *,
    arm: str | None = None,
    split: str | None = None,
) -> list[XrunView]:
    """The runs of a design in registration order, optionally of one arm or one split."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM xruns WHERE experiment_id = :e ORDER BY event_id, run_id"),
            {"e": experiment_id},
        ).all()
    views = [_view(r) for r in rows]
    return [
        v
        for v in views
        if (arm is None or v.cell.arm == arm) and (split is None or v.cell.split == split)
    ]


def _registration_issues(
    project: Project, view: ExperimentView, cell: Cell
) -> tuple[list[ValidationIssue], bool]:
    """The reasons a cell cannot be registered, and whether it is a post hoc (exploratory) one."""
    issues: list[ValidationIssue] = []
    design = view.design
    planned = cell in planned_cells(design)
    if view.state == "draft":
        return [ValidationIssue("experiment_id", "not-frozen")], False
    if view.state == "superseded":
        return [ValidationIssue("experiment_id", "superseded")], False
    if not planned:
        if cell.split == "confirmatory":
            issues.append(ValidationIssue("cell", "not-planned"))
        elif not cell_in_design(design, cell):
            issues.append(ValidationIssue("cell", "not-in-design"))
    elif cell.needs_unlock and view.state != "unlocked":
        issues.append(ValidationIssue("split", "locked"))
    if cell.is_reproduction and cell.split == "confirmatory":
        hypothesis = hypothesis_view(project, view.hypothesis)
        if hypothesis is None or hypothesis.state != "registered":
            # it reads the test split before the unlock: the hypothesis is registered first
            issues.append(ValidationIssue("split", "hypothesis-not-registered"))
    registered = len(xrun_list(project, view.experiment_id))
    if registered >= design.budget.max_runs:
        issues.append(ValidationIssue("experiment_id", "max-runs"))
    return issues, not planned


def register_run(project: Project, actor: Actor, experiment_id: str, cell: Cell) -> str:
    """Register a planned run and return its `xrn_` id. The configuration is computed. Refused,
    with nothing written: an actor that is neither agent nor human (`actor`); an unknown experiment
    (`experiment_id`); a design that is not frozen (`experiment_id`: `not-frozen`); a confirmatory
    cell before the unlock (`split`: `locked`); a cell the design does not plan on the confirmatory
    split (`cell`: `not-planned`) or off the design's multiverse or arms (`cell`: `not-in-design`);
    more than `max_runs` runs (`experiment_id`: `max-runs`). A cell the design does not plan on the
    dev split is accepted and marked exploratory."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human registers a run")
    with project.index.exclusive():
        project.index.sync()
        view = experiment_view(project, experiment_id)
        if view is None:
            raise _refuse("experiment_id", "unknown")
        issues, exploratory = _registration_issues(project, view, cell)
        if issues:
            raise FactoryValidationError(issues)
        config = run_config(view.design, cell)
        run_id = project.ids.new("xrn")
        payload = XrunRegistered(
            run_id=run_id,
            experiment_id=experiment_id,
            e_version=view.e_version,
            cell=cell,
            cell_hash=cell_hash(cell),
            config=config,
            config_hash=config_hash(config),
            exploratory=exploratory,
        )
        blob = (
            project.blobs.put_json(payload.model_dump(mode="json"))
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "xrun.registered", payload, actor, refs=[run_id, experiment_id], input_blob=blob
                )
            ]
        )
    return run_id


# --- Ingestion ----------------------------------------------------------------------------------

RUNNER_RE = r"^[a-z0-9][a-z0-9-]{0,40}$"


def _ingest_actor(project: Project, actor: Actor, runner: str | None) -> Actor:
    """The actor a result is written as: the runner's `system` actor when `runner` names one (the
    operator at the command line must be a human), else a human or a runner `system` actor passed
    in. Never an agent (spec ruling 19: numbers come from machine output)."""
    if runner is not None:
        if re.fullmatch(RUNNER_RE, runner) is None:
            raise _refuse("runner", "lowercase words joined by single hyphens")
        if actor.kind != "human":
            raise _refuse("actor", "human-or-runner-only")
        return Actor(
            kind="system",
            id=f"runner-{runner}",
            user=project.settings.user,
            session=project.session,
        )
    if actor.kind == "human" or (actor.kind == "system" and actor.id.startswith("runner-")):
        return actor
    raise _refuse("actor", "human-or-runner-only")


def _read_results(path: Path) -> tuple[bytes, ResultsFile]:
    try:
        size = path.stat().st_size
    except OSError:
        raise _refuse("path", "unreadable") from None
    if size > MAX_RESULTS_BYTES:
        raise _refuse("path", "too-large")
    try:
        raw = path.read_bytes()
        body = json.loads(raw)
    except (OSError, ValueError):
        raise _refuse("path", "not-json") from None
    try:
        return raw, ResultsFile.model_validate(body)
    except ValidationError as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(".".join(["file", *(str(p) for p in err["loc"])]), str(err["msg"]))
                for err in exc.errors()
            ]
        ) from exc


def _canonical_metrics(
    design: ExperimentDesign, results: ResultsFile
) -> tuple[dict[str, CanonicalMetric], list[ValidationIssue]]:
    """The metrics of a file in canonical form, and what is wrong with them: each design metric
    present (unless the run failed) with a printed number and a unit of its family (and equal to
    the design's unit when it names one); none the design does not declare."""
    issues: list[ValidationIssue] = []
    out: dict[str, CanonicalMetric] = {}
    declared = {m.name: m for m in design.metrics}
    for name in sorted(results.metrics):
        if name not in declared:
            issues.append(ValidationIssue(f"metrics.{name}", "undeclared"))
    for name, metric in declared.items():
        got = results.metrics.get(name)
        if got is None:
            if results.exit_status == 0:
                issues.append(ValidationIssue(f"metrics.{name}", "missing"))
            continue
        printed = parse_printed(got.value)
        if printed is None:
            issues.append(ValidationIssue(f"metrics.{name}", "not-a-number"))
            continue
        if metric.unit is not None and (got.unit or "") != metric.unit:
            issues.append(ValidationIssue(f"metrics.{name}", "unit-invalid"))
            continue
        try:
            value = canonical(printed, got.unit, metric.unit_family)
        except ValueError:
            issues.append(ValidationIssue(f"metrics.{name}", "unit-invalid"))
            continue
        out[name] = CanonicalMetric(printed=got.value, unit=got.unit, value=value)
    return out, issues


def ingest_results(project: Project, actor: Actor, path: Path, *, runner: str | None = None) -> str:
    """Ingest a runner's results file for a registered run and return the `xrun.reported` event
    id. The raw bytes are stored as a blob; the metrics are validated against the design and
    stored in canonical form. A failed run (non-zero exit) is recorded and counted; a different
    commit or environment is recorded with the flag `environment-differs` and kept; a second
    confirmatory read of a primary cell beyond the access limit is recorded with the flag
    `test-reused` and a `test-reuse` deviation; hours beyond the budget write one `budget-overrun`
    deviation. Refused, with nothing written: an agent (`actor`); an unreadable, oversized,
    non-JSON or malformed file (`path`, `file.*`); a run that is unknown or already reported (`run`:
    `unknown`, `already-reported`); a metric that is missing, undeclared, not a number or in a unit
    outside its family (`metrics.<name>`); a confirmatory run without the unlock nonce
    (`nonce`: `nonce-mismatch`)."""
    writer = _ingest_actor(project, actor, runner)
    raw, results = _read_results(path)
    with project.index.exclusive():
        project.index.sync()
        run = xrun_view(project, results.run)
        if run is None:
            raise _refuse("run", "unknown")
        if run.reported_event_id is not None:
            raise _refuse("run", "already-reported")
        view = experiment_view(project, run.experiment_id)
        assert view is not None
        metrics, issues = _canonical_metrics(view.design, results)
        if run.cell.needs_unlock:
            from factory.services.experiments import unlock_nonce

            nonce = unlock_nonce(project, run.experiment_id)
            if (
                nonce is None
                or results.nonce is None
                or not secrets.compare_digest(nonce, results.nonce)
            ):
                issues.append(ValidationIssue("nonce", "nonce-mismatch"))
        if issues:
            raise FactoryValidationError(issues)
        before_hours = Decimal(budget_view(project, run.experiment_id).gpu_hours_used)  # type: ignore[union-attr]
        reused = False
        if run.access_hash is not None and metrics:
            counts = access_counts(project, run.experiment_id)
            reused = counts.get(access_hash(run.cell) or "", 0) >= (view.access_limit or 1)
        payload = XrunReported(
            run_id=results.run,
            results_blob=project.blobs.put(raw),
            metrics=metrics,
            gpu_hours=results.compute.gpu_hours,
            exit_status=results.exit_status,
            code_commit=results.code_commit,
            environment=results.environment,
            nonce=results.nonce,
            tracker_run=results.tracker_run,
            artifacts=results.artifacts,
            flags=(),
        )
        flags = report_flags(view.design, payload, reused=reused)
        payload = payload.model_copy(update={"flags": flags})
        events: list[Event] = [
            project.events.make(
                "xrun.reported", payload, writer, refs=[results.run, run.experiment_id]
            )
        ]
        system = project.system_actor()
        if reused:
            events.append(
                make_deviation_event(
                    project,
                    system,
                    view,
                    "test-reuse",
                    f"run {results.run} read the primary cell {run.access_hash} again",
                    False,
                )
            )
        used = before_hours + Decimal(results.compute.gpu_hours)
        already = any(d.kind == "budget-overrun" for d in view.deviations)
        if used > Decimal(view.design.budget.gpu_hours) and not already:
            events.append(
                make_deviation_event(
                    project,
                    system,
                    view,
                    "budget-overrun",
                    f"run {results.run} brought the hours used above the budget",
                    False,
                )
            )
        project.record(events)
        if run.cell.is_reproduction:
            evaluate_baselines(project, run.experiment_id)  # a verdict once every seed is in
        elif run.cell.split == "confirmatory":
            from factory.services.evaluation import auto_evaluate  # it imports this module

            auto_evaluate(project, run.experiment_id)  # once the last primary cell is complete
    return events[0].id
