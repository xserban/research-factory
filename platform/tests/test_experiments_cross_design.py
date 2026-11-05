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
from factory.model.extraction import ExtractedRowInput
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
from tests.test_finder_gaps import SourcesFor, _method
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


@pytest.mark.parametrize("live", ["says-2", "gone"])
def test_a_changed_evidence_row_does_not_strand_a_frozen_experiment(
    project: Project,
    human: Actor,
    xw: XW,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live: str,
) -> None:
    # re-review 3: the verdict compares with the value frozen with the design. The reviewer's route
    # (an agent correcting the row with `extract_record(supersedes=...)`) needs a live claim on a
    # task of a work whose row is already final, which no sequence of the services gives; so the
    # live evidence is made to disagree directly: it reports 2, or has lost the row, where 1 was
    # frozen. (Disclosed in the decision row; the route is not reproduced.)
    from factory.services import extraction_agreement as agreement

    exp = frozen_design(project, human, xw)
    rk = xw.rows[0]
    view = experiment_view(project, exp)
    assert view is not None and view.baseline_values == {rk: "1"}
    rows = [r for r in agreement.final_rows(project) if r.row_key == rk]
    if live == "says-2":
        field = rows[0].fields["value"].model_copy(update={"value": "2", "canonical": "2"})
        rows = [rows[0].model_copy(update={"fields": {**rows[0].fields, "value": field}})]
    else:
        rows = []
    monkeypatch.setattr(agreement, "final_rows", lambda _p, **_k: rows)
    monkeypatch.setattr(
        "factory.services.reproduction.final_rows", lambda _p, **_k: rows, raising=False
    )
    assert baseline_verdicts(project, exp) == {rk: "pending"}
    before = len(_events(project, "baseline.evaluated"))
    _repro(project, human, tmp_path, exp, rk, {1: "1", 2: "1", 3: "1"})
    assert baseline_verdicts(project, exp) == {rk: "reproduced"}  # against the frozen value
    assert len(_events(project, "baseline.evaluated")) == before + 1


def test_an_agent_cannot_set_the_test_access_limit_by_recording_a_protocol(
    explore_project: Project, human: Actor
) -> None:
    # re-review 4: the same refusal at the other door (`record_protocol`, and the MCP tool on it)
    from factory.model.hypothesis_plan import HypothesisPlan
    from factory.services.hypothesis_gates import effective_plan
    from factory.services.protocol import agent_admission_issues, record_protocol
    from tests.helpers import pilot_protocol_spec, record_pilot_question
    from tests.hypothesis_helpers import OTHER

    project = explore_project
    question = record_pilot_question(project, human)
    plain = pilot_protocol_spec(question, None, reviewer=human.id)
    high = plain.model_copy(update={"hypothesis_plan": HypothesisPlan(test_access_limit=50)})
    with pytest.raises(FactoryValidationError) as err:  # a first record
        record_protocol(project, OTHER, high, ready=False)
    assert _fields(err) == [("hypothesis_plan.test_access_limit", "agent-cannot-raise")]
    record_protocol(project, OTHER, plain, ready=False)
    with pytest.raises(FactoryValidationError) as err:  # a re-recorded draft
        record_protocol(project, OTHER, high, ready=False)
    assert _fields(err) == [("hypothesis_plan.test_access_limit", "agent-cannot-raise")]
    assert effective_plan(project).test_access_limit == 1
    record_protocol(project, human, high, ready=False)  # the researcher may
    assert effective_plan(project).test_access_limit == 50
    assert agent_admission_issues(OTHER, high, high) == []  # an agent may keep or lower it
    lower = plain.model_copy(update={"hypothesis_plan": HypothesisPlan(test_access_limit=2)})
    assert agent_admission_issues(OTHER, high, lower) == []
