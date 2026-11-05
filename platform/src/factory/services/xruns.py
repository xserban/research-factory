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
from typing import Any, Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.hypotheses.design import (
    cell_hash,
    cell_in_design,
    config_hash,
    planned_cells,
    run_config,
)
from factory.model.base import StrictModel
from factory.model.experiments import Cell, XrunRegistered
from factory.services.context import Project
from factory.services.experiments import ExperimentView, experiment_view

XrunState = Literal["planned", "completed", "failed"]


class XrunView(StrictModel):
    run_id: str
    experiment_id: str
    cell: Cell
    cell_hash: str
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
