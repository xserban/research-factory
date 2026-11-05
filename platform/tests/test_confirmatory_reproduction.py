"""A baseline reproduction on the confirmatory split is a test access (review finding C1).

A reproduction reads the split the hypothesis is tested on. The `dev` split is the default; a
baseline that declares `confirmatory` needs a registered hypothesis at registration, counts as a
read of the matching primary baseline cell, closes the revision of the hypothesis, and does not
show an agent a verdict that would bound the value before the unlock.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.hypotheses.design import cell_hash
from factory.model.experiments import XrunRegistered
from factory.services.context import Project
from factory.services.experiments import experiment_view
from factory.services.extraction_agreement import final_rows
from factory.services.hypotheses import draft_hypothesis, has_confirmatory_evidence
from factory.services.xruns import ingest_results, register_run, xrun_list, xrun_view
from tests.experiment_helpers import (
    XW,
    cell,
    design,
    frozen_design,
    register_with_review,
    results_file,
    xw,
)
from tests.hypothesis_helpers import DRAFTER, HW, gw, hw, make_spec
from tests.test_reproduction import _repro

CONFIRMATORY = {"split": "confirmatory"}


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _confirmatory(w: XW) -> dict[str, object]:
    return {"baselines": [{"row_key": w.rows[0], "tolerance": "0.01", **CONFIRMATORY}]}


def test_the_default_reproduction_split_is_dev(project: Project, xw: XW) -> None:
    assert xw.design().baselines[0].split == "dev"


def test_confirmatory_reproduction_needs_a_registered_hypothesis(
    project: Project, human: Actor, hw: HW
) -> None:
    rk = final_rows(project)[0].row_key
    w = XW(hw.hid, [rk])  # the hypothesis is only drafted
    exp = frozen_design(project, human, w, **_confirmatory(w))
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, exp, cell(f"reproduction:{rk}", split="confirmatory"))
    assert _fields(err) == [("split", "hypothesis-not-registered")]
    # a dev-split reproduction needs no registration
    register_run(project, DRAFTER, exp, cell(f"reproduction:{rk}", split="dev"))


def test_the_projector_ignores_a_confirmatory_reproduction_of_an_unregistered_hypothesis(
    project: Project, human: Actor, hw: HW
) -> None:
    from factory.hypotheses.design import config_hash, run_config

    rk = final_rows(project)[0].row_key
    w = XW(hw.hid, [rk])
    exp = frozen_design(project, human, w, **_confirmatory(w))
    view = experiment_view(project, exp)
    assert view is not None
    forged_cell = cell(f"reproduction:{rk}", split="confirmatory")
    config = run_config(view.design, forged_cell)
    payload = XrunRegistered(
        run_id="xrn_01JZ9Q3K5M7N8P0R2S4T6V8W01",
        experiment_id=exp,
        e_version=view.e_version,
        cell=forged_cell,
        cell_hash=cell_hash(forged_cell),
        config=config,
        config_hash=config_hash(config),
        exploratory=False,
    )
    blob = project.blobs.put_json({})
    project.record([project.events.make("xrun.registered", payload, DRAFTER, input_blob=blob)])
    assert xrun_list(project, exp) == []


def test_a_confirmatory_reproduction_is_a_read_of_the_baseline_cell(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw, **_confirmatory(xw))
    rk = xw.rows[0]
    assert has_confirmatory_evidence(project, xw.hid) is False
    _repro(project, human, tmp_path, exp, rk, {1: "1", 2: "1", 3: "1"}, split="confirmatory")
    view = experiment_view(project, exp)
    assert view is not None
    assert [view.access[cell_hash(cell("baseline", seed=s))] for s in (1, 2, 3)] == [1, 1, 1]
    assert [view.access[cell_hash(cell("treatment", seed=s))] for s in (1, 2, 3)] == [0, 0, 0]
    assert view.deviations == []  # the first read of each cell is the allowance
    assert has_confirmatory_evidence(project, xw.hid) is True  # revision is closed
    with pytest.raises(FactoryValidationError) as err:
        draft_hypothesis(project, DRAFTER, make_spec(lead=None), supersedes=xw.hid)
    assert ("supersedes", "evidence-exists") in _fields(err)


def test_a_second_confirmatory_reproduction_read_is_reuse(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw, **_confirmatory(xw))
    rk = xw.rows[0]
    _repro(project, human, tmp_path, exp, rk, {1: "1", 2: "1", 3: "1"}, split="confirmatory")
    again = _repro(project, human, tmp_path, exp, rk, {1: "1"}, split="confirmatory", tag="b")
    kept = xrun_view(project, again[1])
    assert kept is not None and kept.state == "completed" and kept.flags == ("test-reused",)
    view = experiment_view(project, exp)
    assert view is not None
    assert [(d.kind, d.after_unlock) for d in view.deviations] == [("test-reuse", False)]


def test_a_dev_reproduction_reads_nothing_of_the_test_split(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1", 2: "1", 3: "1"})
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1"}, tag="b")
    view = experiment_view(project, exp)
    assert view is not None and view.deviations == []
    assert all(count == 0 for count in view.access.values())
    assert has_confirmatory_evidence(project, xw.hid) is False
