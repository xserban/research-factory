"""Unlock, nonce, test access and budget (slice 6, plan XP-A task 5)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.hypotheses.design import cell_hash, primary_cells
from factory.model.experiments import ExperimentUnlocked
from factory.model.project import RigorMode
from factory.modules.contract import PolicyKind
from factory.services import hypotheses as hypotheses_service
from factory.services.context import Project
from factory.services.experiments import (
    design_experiment,
    experiment_view,
    freeze_experiment,
    record_deviation,
    unlock_experiment,
    unlock_nonce,
)
from factory.services.hypotheses import draft_hypothesis, has_confirmatory_evidence
from factory.services.xruns import ingest_results, register_run, xrun_list, xrun_view
from tests.experiment_helpers import (
    XW,
    cell,
    design,
    frozen_design,
    register_with_review,
    results_file,
    xe,
    xw,
)
from tests.hypothesis_helpers import DRAFTER, HW, OTHER, gw, hw, make_spec


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def _unlocked(project: Project, human: Actor, w: XW, **over: object) -> tuple[str, str]:
    """A frozen design without baselines (their verdicts are task 6), unlocked by the human."""
    exp = frozen_design(project, human, w, baselines=[], **over)
    unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    assert nonce is not None
    return exp, nonce


def _report(
    project: Project,
    human: Actor,
    tmp_path: Path,
    exp: str,
    nonce: str | None,
    *,
    seed: int = 1,
    arm: str = "treatment",
    name: str = "r.json",
    **over: object,
) -> str:
    run = register_run(project, DRAFTER, exp, cell(arm, seed=seed))
    ingest_results(project, human, results_file(tmp_path, run, nonce=nonce, name=name, **over))  # type: ignore[arg-type]
    return run


def test_unlock_issues_a_nonce_once(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw, baselines=[])
    assert unlock_nonce(project, exp) is None
    event_id = unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    assert nonce is not None and len(nonce) == 32
    view = experiment_view(project, exp)
    assert view is not None and (view.state, view.unlocked_event) == ("unlocked", event_id)
    [event] = _events(project, "experiment.unlocked")
    assert event.payload["nonce"] == nonce and event.payload["policy"] == "human"
    with pytest.raises(FactoryValidationError) as err:
        unlock_experiment(project, human, exp)
    assert _fields(err) == [("experiment_id", "state-unlocked")]
    assert unlock_nonce(project, exp) == nonce  # never reissued


def test_order_enforced(project: Project, human: Actor, xw: XW, tmp_path: Path) -> None:
    # Review Focus 1; acceptance 14
    exp = frozen_design(project, human, xw, baselines=[])
    with pytest.raises(FactoryValidationError) as err:  # a confirmatory run before the unlock
        register_run(project, DRAFTER, exp, cell("treatment"))
    assert _fields(err) == [("split", "locked")]
    unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    run = register_run(project, DRAFTER, exp, cell("treatment"))
    ingest_results(project, human, results_file(tmp_path, run, nonce=nonce))
    done = xrun_view(project, run)
    assert done is not None and done.state == "completed"


def test_unlock_needs_a_frozen_design_and_a_registered_hypothesis(
    project: Project, human: Actor, hw: HW
) -> None:
    exp, _ = design_experiment(project, DRAFTER, design(hw.hid, baselines=[]))
    with pytest.raises(FactoryValidationError) as err:
        unlock_experiment(project, human, exp)
    assert ("experiment_id", "not-frozen") in _fields(err)
    assert ("hypothesis", "hypothesis-not-registered") in _fields(err)
    freeze_experiment(project, human, exp)  # a draft hypothesis may have a frozen design
    with pytest.raises(FactoryValidationError) as err:
        unlock_experiment(project, human, exp)
    assert _fields(err) == [("hypothesis", "hypothesis-not-registered")]
    assert _events(project, "experiment.unlocked") == []
    register_with_review(project, human, hw.hid)
    unlock_experiment(project, human, exp)
    view = experiment_view(project, exp)
    assert view is not None and view.state == "unlocked"


def test_wrong_nonce_refused(project: Project, human: Actor, xw: XW, tmp_path: Path) -> None:
    exp, nonce = _unlocked(project, human, xw)  # acceptance 14
    run = register_run(project, DRAFTER, exp, cell("treatment"))
    for bad in (None, "0" * 32, nonce[::-1]):
        with pytest.raises(FactoryValidationError) as err:
            ingest_results(project, human, results_file(tmp_path, run, nonce=bad))
        assert _fields(err) == [("nonce", "nonce-mismatch")]
    assert _events(project, "xrun.reported") == []
    view = xrun_view(project, run)
    assert view is not None and view.state == "planned"


def test_dev_split_runs_need_no_nonce(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp, _ = _unlocked(project, human, xw)
    run = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    ingest_results(project, human, results_file(tmp_path, run))
    done = xrun_view(project, run)
    assert done is not None and done.state == "completed"


def test_second_access_is_deviation(project: Project, human: Actor, xw: XW, tmp_path: Path) -> None:
    # Review Focus 3; acceptance 14
    exp, nonce = _unlocked(project, human, xw)
    first = _report(project, human, tmp_path, exp, nonce, name="a.json")
    view = experiment_view(project, exp)
    assert view is not None and view.deviations == []
    key = cell_hash(cell("treatment"))
    assert view.access[key] == 1 and view.access[cell_hash(cell("baseline"))] == 0
    second = _report(project, human, tmp_path, exp, nonce, name="b.json", value="80")
    view = experiment_view(project, exp)
    assert view is not None and view.access[key] == 2
    [dev] = view.deviations
    assert (dev.kind, dev.semantic, dev.after_unlock) == ("test-reuse", False, True)
    [event] = [e for e in _events(project, "experiment.deviation_recorded")]
    assert (event.actor.kind, event.actor.id) == ("system", "factory")
    kept = xrun_view(project, second)
    assert kept is not None and kept.state == "completed"  # ingested, never dropped
    assert kept.flags == ("test-reused",) and kept.metrics == {"top-1 accuracy": "80"}
    original = xrun_view(project, first)
    assert original is not None and original.flags == ()
    # the first and second reads are distinct runs of one cell: the evaluation uses the first
    assert [r.run_id for r in xrun_list(project, exp, arm="treatment")] == [first, second]


def test_failed_run_is_not_a_test_access(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp, nonce = _unlocked(project, human, xw)
    _report(project, human, tmp_path, exp, nonce, metrics={}, exit_status=1, name="a.json")
    view = experiment_view(project, exp)
    assert view is not None and view.access[cell_hash(cell("treatment"))] == 0
    _report(project, human, tmp_path, exp, nonce, name="b.json")
    view = experiment_view(project, exp)
    assert view is not None and view.deviations == []  # the failed run did not use the allowance


def test_budget_overrun_writes_one_deviation(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:  # acceptance 16
    budget = {"gpu_hours": "3", "per_run_gpu_hours": "2", "max_runs": 10}
    exp, nonce = _unlocked(project, human, xw, budget=budget)
    _report(project, human, tmp_path, exp, nonce, seed=1, gpu_hours="2", name="a.json")
    view = experiment_view(project, exp)
    assert view is not None and view.budget.over is False and view.deviations == []
    _report(project, human, tmp_path, exp, nonce, seed=2, gpu_hours="2", name="b.json")
    _report(project, human, tmp_path, exp, nonce, seed=3, gpu_hours="2", name="c.json")
    view = experiment_view(project, exp)
    assert view is not None
    assert (view.budget.gpu_hours_used, view.budget.over) == ("6", True)
    assert [d.kind for d in view.deviations] == ["budget-overrun"]  # once, not per run
    [event] = _events(project, "experiment.deviation_recorded")
    assert event.actor.kind == "system"
    assert view.flags == ()  # not semantic: the outcome is not flagged deviated


def test_semantic_deviation_after_unlock_flags_deviated(
    project: Project, human: Actor, xw: XW
) -> None:
    exp, _ = _unlocked(project, human, xw)
    record_deviation(project, human, exp, "environment", "the cluster image changed", False)
    view = experiment_view(project, exp)
    assert view is not None and view.flags == ()
    record_deviation(project, human, exp, "planned-change-after-freeze", "swapped a seed", True)
    view = experiment_view(project, exp)
    assert view is not None and view.flags == ("deviated",)
    assert [d.after_unlock for d in view.deviations] == [True, True]


POSITIVE = {"name": "p", "kind": "positive", "overrides": {"labels": "x"}, "expect": "effect"}
NEGATIVE = {"name": "n", "kind": "negative", "overrides": {"labels": "y"}, "expect": "no-effect"}


@pytest.mark.parametrize("controls", [[], [POSITIVE], [NEGATIVE]])
def test_unlock_requires_both_controls_in_systematic(
    project: Project,
    human: Actor,
    xw: XW,
    monkeypatch: pytest.MonkeyPatch,
    controls: list[dict[str, object]],
) -> None:
    from factory.services import experiments as experiments_service

    monkeypatch.setattr(experiments_service, "project_mode", lambda _p: RigorMode.SYSTEMATIC)
    exp = frozen_design(project, human, xw, baselines=[], controls=controls)
    with pytest.raises(FactoryValidationError) as err:
        unlock_experiment(project, human, exp)
    assert _fields(err) == [("controls", "controls-missing")]
    assert _events(project, "experiment.unlocked") == []


def test_pilot_agent_cannot_unlock(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw, baselines=[])
    with pytest.raises(FactoryValidationError) as err:
        unlock_experiment(project, OTHER, exp)
    assert _fields(err) == [
        ("actor", "gate experiments.freeze_unlock is human: an agent cannot pass it")
    ]
    assert _events(project, "experiment.unlocked") == []


def test_exploratory_unlock_needs_a_non_designer_session(
    explore_project: Project, human: Actor, xe: XW
) -> None:
    project = explore_project
    exp, _ = design_experiment(project, DRAFTER, xe.design())
    freeze_experiment(project, OTHER, exp)
    with pytest.raises(FactoryValidationError) as err:
        unlock_experiment(project, DRAFTER, exp)
    assert _fields(err) == [("session", "the proposer cannot pass gate experiments.freeze_unlock")]
    unlock_experiment(project, OTHER, exp)
    [event] = _events(project, "experiment.unlocked")
    assert event.payload["autonomy"] == "agent" and event.input_blob is not None


def test_projector_ignores_a_forged_unlock(project: Project, human: Actor, xw: XW) -> None:
    exp = frozen_design(project, human, xw, baselines=[])
    view = experiment_view(project, exp)
    assert view is not None
    forged = ExperimentUnlocked(
        experiment_id=exp,
        e_version=view.e_version,
        nonce="1" * 32,
        policy=PolicyKind.HUMAN,
        autonomy="agent",
    )
    blob = project.blobs.put_json({})
    project.record([project.events.make("experiment.unlocked", forged, OTHER, input_blob=blob)])
    agent_policy = forged.model_copy(update={"policy": PolicyKind.AGENT})
    project.record(
        [project.events.make("experiment.unlocked", agent_policy, OTHER, input_blob=blob)]
    )
    assert unlock_nonce(project, exp) is None
    after = experiment_view(project, exp)
    assert after is not None and after.state == "frozen"
    assert len(_events(project, "experiment.unlocked")) == 2


def test_projector_ignores_a_confirmatory_report_without_the_nonce(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    from factory.model.experiments import CanonicalMetric, XrunReported

    exp, nonce = _unlocked(project, human, xw)
    run = register_run(project, DRAFTER, exp, cell("treatment"))
    metric = {"top-1 accuracy": CanonicalMetric(printed="9", unit="%", value="9")}
    base = XrunReported(
        run_id=run,
        results_blob=project.blobs.put(b"{}"),
        metrics=metric,
        gpu_hours="1",
        exit_status=0,
        code_commit="9f2c1ab",
        environment="sha256:lockfile-1",
        nonce="2" * 32,
    )
    project.record([project.events.make("xrun.reported", base, human)])
    done = xrun_view(project, run)
    assert done is not None and done.state == "planned"
    project.record(
        [project.events.make("xrun.reported", base.model_copy(update={"nonce": nonce}), human)]
    )
    done = xrun_view(project, run)
    assert done is not None and done.state == "completed"


def test_has_confirmatory_evidence_true_after_ingest_without_monkeypatch(
    project: Project, human: Actor, hw: HW, tmp_path: Path
) -> None:
    # H-C ruling 6 end to end: the hook list is not patched anywhere in this test
    register_with_review(project, human, hw.hid)
    w = XW(hw.hid, [])
    assert has_confirmatory_evidence(project, hw.hid) is False
    exp, nonce = _unlocked(project, human, w)
    dev = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    ingest_results(project, human, results_file(tmp_path, dev, name="dev.json"))
    assert has_confirmatory_evidence(project, hw.hid) is False  # a dev run is not evidence
    _report(project, human, tmp_path, exp, nonce)
    assert has_confirmatory_evidence(project, hw.hid) is True
    with pytest.raises(FactoryValidationError) as err:
        draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead), supersedes=hw.hid)
    assert _fields(err) == [("supersedes", "evidence-exists")]
    assert hypotheses_service.CONFIRMATORY_SOURCES  # filled from import


def test_has_confirmatory_evidence_blocks_revision(
    project: Project, human: Actor, hw: HW, tmp_path: Path
) -> None:
    # before any confirmatory result a registered hypothesis may still be superseded
    register_with_review(project, human, hw.hid)
    exp, nonce = _unlocked(project, human, XW(hw.hid, []))
    new, _ = draft_hypothesis(
        project,
        DRAFTER,
        make_spec(lead=hw.lead, prediction={"direction": "treatment-better", "margin": "3"}),
        supersedes=hw.hid,
    )
    assert new != hw.hid
    # a failed confirmatory run may still have read the test split: it counts as evidence
    _report(project, human, tmp_path, exp, nonce, metrics={}, exit_status=1)
    assert has_confirmatory_evidence(project, hw.hid) is True
    with pytest.raises(FactoryValidationError) as err:
        draft_hypothesis(
            project,
            DRAFTER,
            make_spec(lead=hw.lead, prediction={"direction": "treatment-better", "margin": "4"}),
            supersedes=hw.hid,
        )
    assert _fields(err) == [("supersedes", "evidence-exists")]
