"""Baseline reproduction verdicts and acceptance (slice 6, plan XP-A task 6)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.hypotheses.reproduction import reproduced_value, reproduction_verdict
from factory.model.experiments import BaselineEvaluated
from factory.services.context import Project
from factory.services.experiments import (
    accept_baseline,
    experiment_view,
    freeze_experiment,
    unlock_experiment,
    unlock_nonce,
)
from factory.services.hypotheses import has_confirmatory_evidence
from factory.services.reproduction import baseline_verdicts, evaluate_baselines
from factory.services.xruns import ingest_results, register_run, xrun_view
from tests.experiment_helpers import (
    XW,
    cell,
    frozen_design,
    results_file,
    xw,
)
from tests.hypothesis_helpers import DRAFTER, HW, OTHER, gw, hw

REPORTED = "1"  # the value of every row of the evidence world of `gw`


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def _repro(
    project: Project,
    human: Actor,
    tmp_path: Path,
    exp: str,
    row_key: str,
    values: dict[int, str | None],
    *,
    tag: str = "",
) -> dict[int, str]:
    """Register and report one reproduction run per seed; `None` is a failed run."""
    runs: dict[int, str] = {}
    for seed, value in values.items():
        run = register_run(project, DRAFTER, exp, cell(f"reproduction:{row_key}", seed=seed))
        path = results_file(
            tmp_path,
            run,
            name=f"r{seed}{tag}.json",
            **(
                {"metrics": {}, "exit_status": 1} if value is None else {"value": value}  # type: ignore[arg-type]
            ),
        )
        ingest_results(project, human, path)
        runs[seed] = run
    return runs


def test_reproduction_world_reports_one(project: Project, xw: XW) -> None:
    # the constant the tests below rely on: the baseline row's canonical reported value
    from factory.services.extraction_agreement import final_rows

    row = next(r for r in final_rows(project) if r.row_key == xw.rows[0])
    assert row.fields["value"].canonical == REPORTED


def test_reproduced_within_tolerance(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:  # acceptance 17
    exp = frozen_design(project, human, xw)
    rk = xw.rows[0]
    assert baseline_verdicts(project, exp) == {rk: "pending"}
    runs = _repro(project, human, tmp_path, exp, rk, {1: "1.00", 2: "1.01", 3: "0.99"})
    assert baseline_verdicts(project, exp) == {rk: "reproduced"}
    [event] = _events(project, "baseline.evaluated")
    payload = BaselineEvaluated.model_validate(event.payload)
    assert (payload.reported, payload.reproduced, payload.verdict) == ("1", "1", "reproduced")
    assert payload.runs == tuple(runs[s] for s in (1, 2, 3)) and payload.excluded_runs == ()
    assert (payload.tolerance, payload.tolerance_kind) == ("0.01", "relative")
    assert payload.evaluator_version == "baseline-eval@1"
    unlock_experiment(project, human, exp)  # resolved: the unlock goes through
    view = experiment_view(project, exp)
    assert view is not None and view.state == "unlocked" and view.flags == ()


def test_verdict_is_system_event(project: Project, human: Actor, xw: XW, tmp_path: Path) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1", 2: "1", 3: "1"})
    [event] = _events(project, "baseline.evaluated")
    assert (event.actor.kind, event.actor.id) == ("system", "factory") and event.input_blob is None
    assert event.refs == (exp, xw.rows[0])


def test_no_verdict_until_every_seed_reported(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1", 2: "1"})
    assert _events(project, "baseline.evaluated") == []
    assert baseline_verdicts(project, exp) == {xw.rows[0]: "pending"}
    _repro(project, human, tmp_path, exp, xw.rows[0], {3: "1"})
    assert len(_events(project, "baseline.evaluated")) == 1


def test_not_reproduced_outside(project: Project, human: Actor, xw: XW, tmp_path: Path) -> None:
    exp = frozen_design(project, human, xw)  # acceptance 17
    rk = xw.rows[0]
    _repro(project, human, tmp_path, exp, rk, {1: "1.2", 2: "1.2", 3: "1.2"})
    assert baseline_verdicts(project, exp) == {rk: "not-reproduced"}
    [event] = _events(project, "baseline.evaluated")
    assert event.payload["verdict"] == "not-reproduced" and event.payload["reproduced"] == "1.2"


def test_tolerance_boundary() -> None:  # Review Focus 5
    assert reproduction_verdict("1", "1.01", "0.01", "absolute") == "reproduced"  # equal
    assert reproduction_verdict("1", "0.99", "0.01", "absolute") == "reproduced"
    assert reproduction_verdict("1", "1.010001", "0.01", "absolute") == "not-reproduced"
    assert reproduction_verdict("100", "99", "0.01", "relative") == "reproduced"
    assert reproduction_verdict("100", "98.999999", "0.01", "relative") == "not-reproduced"
    # a negative-better (lower is better, negative-valued) metric: the tolerance is on |reported|
    assert reproduction_verdict("-5", "-5.5", "0.1", "relative") == "reproduced"
    assert reproduction_verdict("-5", "-4.5", "0.1", "relative") == "reproduced"
    assert reproduction_verdict("-5", "-5.51", "0.1", "relative") == "not-reproduced"
    assert reproduction_verdict("0", "0", "0.1", "relative") == "reproduced"
    assert reproduction_verdict("0", "0.000001", "0.1", "relative") == "not-reproduced"
    assert reproduction_verdict("1", None, "0.1", "relative") == "no-runs-completed"


def test_reproduced_value_is_a_six_place_mean() -> None:
    assert reproduced_value([]) is None
    assert reproduced_value(["1", "2"]) == "1.5"
    assert reproduced_value(["1", "1", "2"]) == "1.333333"
    assert reproduced_value(["0.0000004", "0"]) == "0"
    assert reproduced_value(["-1", "1"]) == "0"
    assert reproduced_value(["76.50"]) == "76.5"


def test_tolerance_boundary_in_a_project(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    body = {
        "baselines": [{"row_key": xw.rows[0], "tolerance": "0.01", "tolerance_kind": "absolute"}]
    }
    exp = frozen_design(project, human, xw, **body)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1.01", 2: "1.01", 3: "1.01"})
    assert baseline_verdicts(project, exp) == {xw.rows[0]: "reproduced"}  # equal to the tolerance


def test_verdict_written_once_no_best_of_n(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    rk = xw.rows[0]
    first = _repro(project, human, tmp_path, exp, rk, {1: "1.2"}, tag="a")
    _repro(project, human, tmp_path, exp, rk, {1: "1.0"}, tag="b")  # a re-run of seed 1, better
    _repro(project, human, tmp_path, exp, rk, {2: "1.2", 3: "1.2"})
    [event] = _events(project, "baseline.evaluated")
    payload = BaselineEvaluated.model_validate(event.payload)
    assert payload.reproduced == "1.2" and payload.runs[0] == first[1]  # the first run of the seed
    assert payload.verdict == "not-reproduced"
    _repro(project, human, tmp_path, exp, rk, {1: "1.0", 2: "1.0", 3: "1.0"}, tag="c")
    assert evaluate_baselines(project, exp) == []
    assert len(_events(project, "baseline.evaluated")) == 1
    assert baseline_verdicts(project, exp) == {rk: "not-reproduced"}


def test_failed_seeds_are_excluded_and_listed(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    runs = _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1", 2: None, 3: "1.01"})
    [event] = _events(project, "baseline.evaluated")
    payload = BaselineEvaluated.model_validate(event.payload)
    assert payload.runs == (runs[1], runs[3]) and payload.excluded_runs == (runs[2],)
    assert (payload.reproduced, payload.verdict) == ("1.005", "reproduced")


def test_every_seed_failed_is_no_runs_completed(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    rk = xw.rows[0]
    _repro(project, human, tmp_path, exp, rk, {1: None, 2: None, 3: None})
    [event] = _events(project, "baseline.evaluated")
    assert event.payload["verdict"] == "no-runs-completed" and event.payload["reproduced"] is None
    assert baseline_verdicts(project, exp) == {rk: "not-reproduced"}
    accept_baseline(project, human, exp, rk, "the reference code does not build any more")
    assert baseline_verdicts(project, exp) == {rk: "accepted"}


def test_unlock_refused_until_resolved(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:  # acceptance 17
    exp = frozen_design(project, human, xw)
    rk = xw.rows[0]
    with pytest.raises(FactoryValidationError) as err:  # nothing run yet
        unlock_experiment(project, human, exp)
    assert _fields(err) == [("baselines", "baseline-unresolved")]
    _repro(project, human, tmp_path, exp, rk, {1: "2", 2: "2", 3: "2"})
    with pytest.raises(FactoryValidationError) as err:  # run, and it did not reproduce
        unlock_experiment(project, human, exp)
    assert _fields(err) == [("baselines", "baseline-unresolved")]
    assert _events(project, "experiment.unlocked") == []


def test_acceptance_writes_deviation_and_unblocks(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    rk = xw.rows[0]
    with pytest.raises(FactoryValidationError) as err:
        accept_baseline(project, human, exp, rk, "no verdict yet")
    assert _fields(err) == [("row_key", "pending")]
    _repro(project, human, tmp_path, exp, rk, {1: "2", 2: "2", 3: "2"})
    with pytest.raises(FactoryValidationError) as err:  # the gate is human in every mode
        accept_baseline(project, OTHER, exp, rk, "an agent's acceptance")
    assert _fields(err) == [
        ("actor", "gate experiments.accept_baseline is human: an agent cannot pass it")
    ]
    with pytest.raises(FactoryValidationError) as err:
        accept_baseline(project, human, exp, "rk_000000000000", "not a baseline")
    assert _fields(err) == [("row_key", "not-a-baseline")]
    with pytest.raises(FactoryValidationError) as err:
        accept_baseline(project, human, exp, rk, "  ")
    assert _fields(err) == [("rationale", "between 1 and 300 characters")]
    event_id = accept_baseline(project, human, exp, rk, "the paper's number used other data")
    assert baseline_verdicts(project, exp) == {rk: "accepted"}
    view = experiment_view(project, exp)
    assert view is not None and view.flags == ("baseline-not-reproduced",)
    [dev] = view.deviations
    assert (dev.kind, dev.semantic, dev.after_unlock) == ("baseline-accepted", False, False)
    [accepted] = _events(project, "baseline.accepted")
    assert accepted.id == event_id and accepted.actor.kind == "human"
    with pytest.raises(FactoryValidationError) as err:
        accept_baseline(project, human, exp, rk, "again")
    assert _fields(err) == [("row_key", "accepted")]
    unlock_experiment(project, human, exp)
    unlocked = experiment_view(project, exp)
    assert unlocked is not None and unlocked.state == "unlocked"
    assert unlocked.flags == ("baseline-not-reproduced",)  # the flag stays on every later outcome


def test_a_reproduced_baseline_needs_no_acceptance(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1", 2: "1", 3: "1"})
    with pytest.raises(FactoryValidationError) as err:
        accept_baseline(project, human, exp, xw.rows[0], "unneeded")
    assert _fields(err) == [("row_key", "reproduced")]


def test_reproduction_runs_precede_the_unlock_without_a_nonce(
    project: Project, human: Actor, hw: HW, tmp_path: Path
) -> None:
    from tests.experiment_helpers import register_with_review

    register_with_review(project, human, hw.hid)
    w = XW(hw.hid, [])
    from factory.services.extraction_agreement import final_rows

    rk = final_rows(project)[0].row_key
    exp = frozen_design(project, human, w, baselines=[{"row_key": rk, "tolerance": "0.01"}])
    _repro(project, human, tmp_path, exp, rk, {1: "1", 2: "1", 3: "1"})
    view = experiment_view(project, exp)
    assert view is not None and view.state == "frozen"
    assert all(count == 0 for count in view.access.values())  # not test accesses
    assert has_confirmatory_evidence(project, hw.hid) is False  # nor evidence
    assert unlock_nonce(project, exp) is None


def test_projector_ignores_a_verdict_the_runs_do_not_give(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    rk = xw.rows[0]
    runs = _repro(project, human, tmp_path, exp, rk, {1: "2", 2: "2"})  # seed 3 still to come
    assert _events(project, "baseline.evaluated") == []
    lie = BaselineEvaluated(
        experiment_id=exp,
        row_key=rk,
        reported="1",
        reproduced="1",  # the runs give 2
        runs=tuple(runs.values()),
        tolerance="0.01",
        tolerance_kind="relative",
        verdict="reproduced",
        evaluator_version="baseline-eval@1",
    )
    project.record([project.events.make("baseline.evaluated", lie, project.system_actor())])
    wrong_verdict = lie.model_copy(update={"reproduced": "2"})  # the mean right, the verdict not
    project.record(
        [project.events.make("baseline.evaluated", wrong_verdict, project.system_actor())]
    )
    by_a_human = wrong_verdict.model_copy(update={"verdict": "not-reproduced"})
    project.record([project.events.make("baseline.evaluated", by_a_human, human)])
    blob = project.blobs.put_json({})
    project.record([project.events.make("baseline.evaluated", by_a_human, OTHER, input_blob=blob)])
    assert len(_events(project, "baseline.evaluated")) == 4
    assert baseline_verdicts(project, exp) == {rk: "pending"}  # none folded
    other_design_run = BaselineEvaluated(
        experiment_id=exp,
        row_key="rk_000000000000",  # not a baseline of the design
        reported="1",
        reproduced="2",
        runs=tuple(runs.values()),
        tolerance="0.01",
        tolerance_kind="relative",
        verdict="not-reproduced",
        evaluator_version="baseline-eval@1",
    )
    project.record(
        [project.events.make("baseline.evaluated", other_design_run, project.system_actor())]
    )
    assert baseline_verdicts(project, exp) == {rk: "pending"}
