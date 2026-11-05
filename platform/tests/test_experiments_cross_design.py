"""Rules that hold across the designs of a project (re-review of XP-A): reads of one confirmatory
dataset, dev and confirmatory data, a corrected baseline row, and the access limit at its other
doors."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.hypotheses.design import cell_hash
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.experiments import (
    design_experiment,
    experiment_view,
    freeze_experiment,
    unlock_experiment,
    unlock_nonce,
)
from factory.services.extraction import extract_record, live_rows
from factory.services.hypotheses import draft_hypothesis
from factory.services.reproduction import baseline_verdicts
from factory.services.xruns import ingest_results, register_run, xrun_view
from tests.experiment_helpers import (
    XW,
    cell,
    design,
    frozen_design,
    register_with_review,
    results_file,
    xw,
)
from tests.extraction_helpers import SESSION_A, _extractor, _r
from tests.hypothesis_helpers import DRAFTER, HW, gw, hw, make_spec
from tests.test_finder_gaps import _method
from tests.test_reproduction import _repro


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def read(project: Project, human: Actor, tmp_path: Path, exp: str, name: str) -> str:
    nonce = unlock_nonce(project, exp)
    run = register_run(project, DRAFTER, exp, cell("treatment"))
    ingest_results(project, human, results_file(tmp_path, run, nonce=nonce, name=name))
    return run


def test_a_new_design_on_the_same_confirmatory_data_does_not_read_it_at_zero(
    project: Project, human: Actor, xw: XW, hw: HW, tmp_path: Path
) -> None:
    # re-review 1: reads are counted per confirmatory dataset hash, across the project
    first = frozen_design(project, human, xw, baselines=[])
    unlock_experiment(project, human, first)
    read(project, human, tmp_path, first, "a.json")
    hid2, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="second"))
    register_with_review(project, human, hid2)
    second = frozen_design(project, human, XW(hid2, xw.rows), baselines=[])
    unlock_experiment(project, human, second)
    view = experiment_view(project, second)
    assert view is not None and view.deviations == []
    assert view.access[cell_hash(cell("treatment"))] == 1  # design A's read counts here too
    run = read(project, human, tmp_path, second, "b.json")
    kept = xrun_view(project, run)
    assert kept is not None and kept.flags == ("test-reused",)
    view = experiment_view(project, second)
    assert view is not None and [d.kind for d in view.deviations] == ["test-reuse"]
    assert view.access[cell_hash(cell("treatment"))] == 2
    project.index.rebuild()  # the replay gives the same flags
    again = xrun_view(project, run)
    assert again is not None and again.flags == ("test-reused",)
    other_cell = register_run(project, DRAFTER, second, cell("baseline"))
    ingest_results(
        project,
        human,
        results_file(tmp_path, other_cell, nonce=unlock_nonce(project, second), name="c.json"),
    )
    clean = xrun_view(project, other_cell)
    assert clean is not None and clean.flags == ()  # another cell of the data is not a re-read


def test_another_confirmatory_dataset_is_a_fresh_read(
    project: Project, human: Actor, xw: XW, hw: HW, tmp_path: Path
) -> None:
    first = frozen_design(project, human, xw, baselines=[])
    unlock_experiment(project, human, first)
    read(project, human, tmp_path, first, "a.json")
    hid2, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="second"))
    register_with_review(project, human, hid2)
    fresh = [
        {"name": "imagenet-dev", "version": "1", "sha256": "a" * 64, "role": "dev"},
        {"name": "imagenet-test2", "version": "1", "sha256": "c" * 64, "role": "confirmatory"},
    ]
    second = frozen_design(project, human, XW(hid2, xw.rows), baselines=[], datasets=fresh)
    unlock_experiment(project, human, second)
    run = read(project, human, tmp_path, second, "b.json")
    kept = xrun_view(project, run)
    assert kept is not None and kept.flags == ()


def test_dev_data_of_one_design_is_not_confirmatory_data_of_another(
    project: Project, human: Actor, xw: XW, hw: HW
) -> None:
    # re-review 2: the check spans the project (renamed or re-encoded copies cannot be detected)
    design_experiment(project, DRAFTER, xw.design(baselines=[]))
    hid2, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="second"))
    as_dev = [
        {"name": "x-dev", "version": "1", "sha256": "b" * 64, "role": "dev"},  # A's confirmatory
        {"name": "x-test", "version": "1", "sha256": "d" * 64, "role": "confirmatory"},
    ]
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, design(hid2, baselines=[], datasets=as_dev))
    assert _fields(err) == [("datasets.0", "shared-with-another-design")]
    as_test = [
        {"name": "x-dev", "version": "1", "sha256": "e" * 64, "role": "dev"},
        {"name": "x-test", "version": "1", "sha256": "a" * 64, "role": "confirmatory"},  # A's dev
    ]
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, design(hid2, baselines=[], datasets=as_test))
    assert _fields(err) == [("datasets.1", "shared-with-another-design")]
    # the same confirmatory data in two designs is allowed (their reads are counted together)
    same_test = [
        {"name": "x-dev", "version": "1", "sha256": "e" * 64, "role": "dev"},
        {"name": "x-test", "version": "1", "sha256": "b" * 64, "role": "confirmatory"},
    ]
    design_experiment(project, DRAFTER, design(hid2, baselines=[], datasets=same_test))
