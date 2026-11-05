"""Run registration against planned cells (slice 6, plan XP-A task 3)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.hypotheses.design import cell_hash, config_hash, planned_cells, run_config
from factory.model.experiments import Cell, XrunRegistered
from factory.services.context import Project
from factory.services.experiments import design_experiment, experiment_view
from factory.services.xruns import register_run, xrun_list, xrun_view
from tests.experiment_helpers import XW, cell, frozen_design, xe, xw
from tests.hypothesis_helpers import DRAFTER, HW, OTHER, gw, hw


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def test_register_requires_frozen_design(project: Project, human: Actor, xw: XW) -> None:
    exp, _ = design_experiment(project, DRAFTER, xw.design())
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, exp, cell(split="dev", arm="baseline"))
    assert _fields(err) == [("experiment_id", "not-frozen")]
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, "exp_01JZ9Q3K5M7N8P0R2S4T6V8W99", cell())
    assert _fields(err) == [("experiment_id", "unknown")]
    assert _events(project, "xrun.registered") == []


def test_config_computed_by_platform(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw)
    with pytest.raises(ValidationError):  # the input model has no configuration field
        Cell.model_validate(
            {**cell(split="dev").model_dump(mode="json"), "config": {"attention": "linear"}}
        )
    run = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    view = experiment_view(project, exp)
    assert view is not None
    [event] = _events(project, "xrun.registered")
    assert event.payload["config"] == run_config(view.design, cell("ablation:no-norm", split="dev"))
    assert event.payload["config_hash"] == config_hash(event.payload["config"])  # type: ignore[arg-type]
    listed = xrun_list(project, exp)
    assert [(r.run_id, r.state, r.exploratory) for r in listed] == [(run, "planned", False)]
    assert listed[0].cell_hash == cell_hash(cell("ablation:no-norm", split="dev"))


def test_agent_may_register_planned_run(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw)
    planned = cell("reproduction:" + xw.rows[0], split="dev")
    assert planned in planned_cells(experiment_view(project, exp).design)  # type: ignore[union-attr]
    run = register_run(project, OTHER, exp, planned)  # reproduction runs precede the unlock
    [event] = _events(project, "xrun.registered")
    assert event.actor.kind == "agent" and event.input_blob is not None
    assert event.payload["run_id"] == run and event.payload["exploratory"] is False


def test_confirmatory_primary_cell_needs_the_unlock(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw)
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, human, exp, cell("treatment", split="confirmatory"))
    assert _fields(err) == [("split", "locked")]
    assert xrun_list(project, exp) == []


def test_unplanned_dev_cell_is_exploratory(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw)
    run = register_run(project, DRAFTER, exp, cell("treatment", seed=99, split="dev"))
    view = xrun_view(project, run)
    assert view is not None and view.exploratory is True
    off_design = Cell(universe=(("resolution", "512"),), seed=1, arm="treatment", split="dev")
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, exp, off_design)
    assert _fields(err) == [("cell", "not-in-design")]
    unknown_arm = cell("ablation:ghost", split="dev")
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, exp, unknown_arm)
    assert _fields(err) == [("cell", "not-in-design")]


def test_unplanned_confirmatory_cell_refused(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw)
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, exp, cell("treatment", seed=99, split="confirmatory"))
    assert _fields(err) == [("cell", "not-planned")]
    with pytest.raises(FactoryValidationError) as err:  # an ablation is planned on dev only
        register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="confirmatory"))
    assert _fields(err) == [("cell", "not-planned")]


def test_max_runs_refused(project: Project, human: Actor, xw: XW) -> None:  # acceptance 16
    budget = {"gpu_hours": "100", "per_run_gpu_hours": "10", "max_runs": 2}
    exp = frozen_design(project, human, xw, budget=budget)
    for seed in (1, 2):
        register_run(project, DRAFTER, exp, cell("ablation:no-norm", seed=seed, split="dev"))
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, exp, cell("ablation:no-norm", seed=3, split="dev"))
    assert _fields(err) == [("experiment_id", "max-runs")]
    assert len(xrun_list(project, exp)) == 2


def test_rerun_of_a_cell_is_a_new_run(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw)
    one = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    two = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    assert one != two
    listed = xrun_list(project, exp, arm="ablation:no-norm", split="dev")
    assert [r.run_id for r in listed] == [one, two]
    assert xrun_list(project, exp, arm="baseline") == []


def test_projector_ignores_a_forged_run(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw)
    view = experiment_view(project, exp)
    assert view is not None
    good = cell("ablation:no-norm", split="dev")
    config = run_config(view.design, good)
    base = {
        "run_id": "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W01",
        "experiment_id": exp,
        "e_version": view.e_version,
        "cell": good,
        "cell_hash": cell_hash(good),
        "config": config,
        "config_hash": config_hash(config),
        "exploratory": False,
    }
    forged = [
        {
            **base,
            "config": {**config, "attention": "softmax"},
        },  # configuration not the computed one
        {**base, "run_id": "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W02", "exploratory": True},
        {**base, "run_id": "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W03", "e_version": "E@00000000"},
        {  # a confirmatory cell before the unlock
            **base,
            "run_id": "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W04",
            "cell": cell("treatment"),
            "cell_hash": cell_hash(cell("treatment")),
            "config": run_config(view.design, cell("treatment")),
            "config_hash": config_hash(run_config(view.design, cell("treatment"))),
        },
    ]
    for body in forged:
        payload = XrunRegistered.model_validate(body)
        blob = project.blobs.put_json({})
        project.record(
            [project.events.make("xrun.registered", payload, DRAFTER, refs=[], input_blob=blob)]
        )
    assert xrun_list(project, exp) == []
    assert len(_events(project, "xrun.registered")) == 4
