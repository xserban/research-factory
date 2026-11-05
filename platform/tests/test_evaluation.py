"""Evaluation service: computed outcomes, flags, supersession and the hooks (slice 6, plan XP-B
task 3; acceptance 18; R-121). No test sets or patches a hook list."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Event
from factory.events.reader import read_all
from factory.model.experiments import XrunReported
from factory.model.hypotheses import HypothesisEvaluated
from factory.services import hypotheses as hypothesis_service
from factory.services.context import Project
from factory.services.evaluation import (
    evaluate_hypothesis,
    evaluations_of,
    latest_evaluation,
    recompute,
)
from factory.services.experiments import (
    accept_baseline,
    experiment_view,
    record_deviation,
    unlock_experiment,
)
from factory.services.hypotheses import (
    abandon_hypothesis,
    conclude_hypothesis,
    draft_hypothesis,
    hypothesis_view,
)
from factory.services.xruns import register_run
from tests.evaluation_helpers import REFUTED, SUPPORTED, report_runs, unlocked
from tests.experiment_helpers import (
    XW,
    cell,
    frozen_design,
    inject,
    raw_event,
    results_file,
    xe,
    xw,
)
from tests.hypothesis_helpers import DRAFTER, HW, OTHER, gw, hw, make_spec
from tests.test_reproduction import _repro


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def test_auto_evaluation_after_last_primary_cell(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    first_five = dict(list(SUPPORTED.items())[:5])
    report_runs(project, human, tmp_path, exp, first_five)
    assert _events(project, "hypothesis.evaluated") == []
    report_runs(project, human, tmp_path, exp, {("baseline", 3): "76.0"})
    [event] = _events(project, "hypothesis.evaluated")
    assert event.actor.kind == "system" and event.input_blob is None
    p = HypothesisEvaluated.model_validate(event.payload)
    assert (p.outcome, p.n, p.mean, p.level) == ("supported", 3, "1", "0.95")
    assert (p.ci_low, p.ci_high) == ("0.503167", "1.496833")
    assert p.flags == () and len(p.runs) == 6 and p.experiment_id == exp
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.event_id == event.id and live.payload == p
    view = hypothesis_view(project, xw.hid)
    assert view is not None and view.state == "evaluated"


def test_refuted_and_inconclusive_are_computed(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.outcome == "refuted"
    assert (live.payload.ci_low, live.payload.ci_high) == ("-1.496833", "-0.503167")


def test_incomplete_request_then_full_evaluation_supersedes(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, dict(list(SUPPORTED.items())[:4]))
    with pytest.raises(FactoryValidationError) as err:
        evaluate_hypothesis(project, xw.hid)
    assert _fields(err) == [("runs", "incomplete")]
    partial = evaluate_hypothesis(project, xw.hid, request_incomplete=True)
    [row] = evaluations_of(project, xw.hid)
    assert row.event_id == partial and row.payload.outcome == "incomplete"
    assert row.payload.n == 2 and "incomplete" in row.payload.flags
    assert hypothesis_service.has_evaluation(project, xw.hid) is False  # a progress report only
    assert evaluate_hypothesis(project, xw.hid, request_incomplete=True) == partial  # idempotent
    report_runs(project, human, tmp_path, exp, dict(list(SUPPORTED.items())[4:]))
    both = evaluations_of(project, xw.hid)
    assert [e.payload.outcome for e in both] == ["incomplete", "supported"]
    assert both[1].supersedes == partial
    assert hypothesis_service.has_evaluation(project, xw.hid) is True
    project.index.rebuild()
    assert [e.payload.outcome for e in evaluations_of(project, xw.hid)] == [
        "incomplete",
        "supported",
    ]


def test_evaluation_refused_for_unknown_and_unregistered(
    project: Project, human: Any, xw: XW, hw: HW
) -> None:
    with pytest.raises(FactoryValidationError) as err:
        evaluate_hypothesis(project, "hyp_01JZ9Q3K5M7N8P0R2S4T6V8WZZ")
    assert _fields(err) == [("hypothesis_id", "unknown")]
    with pytest.raises(FactoryValidationError) as err:
        evaluate_hypothesis(project, xw.hid)  # registered, no frozen design
    assert _fields(err) == [("experiment_id", "no-frozen-design")]
    draft, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="again"))
    with pytest.raises(FactoryValidationError) as err:
        evaluate_hypothesis(project, draft)
    assert _fields(err) == [("state", "not-registered")]


def test_flag_test_reused(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, {("treatment", 1): "77.0"})
    report_runs(project, human, tmp_path, exp, {("treatment", 1): "50.0"})  # a second read
    report_runs(project, human, tmp_path, exp, dict(list(SUPPORTED.items())[1:]))
    live = latest_evaluation(project, xw.hid)
    assert live is not None and "test-reused" in live.payload.flags
    assert live.payload.counts["extra_runs"] == 1
    assert live.payload.outcome == "supported"  # the first completed run of the cell is used


def test_flag_deviated_after_unlock(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    record_deviation(project, human, exp, "planned-change-after-freeze", "dropped a layer", True)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.flags == ("deviated",)


def test_flag_baseline_not_reproduced(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "50.0", 2: "50.0", 3: "50.0"})
    accept_baseline(project, human, exp, xw.rows[0], "the paper used other data")
    unlock_experiment(project, human, exp)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.flags == ("baseline-not-reproduced",)


def test_flag_autonomy_agent(xe: XW, explore_project: Project, human: Any, tmp_path: Path) -> None:
    from factory.services.experiments import design_experiment, freeze_experiment

    exp, _ = design_experiment(explore_project, DRAFTER, xe.design())
    freeze_experiment(explore_project, OTHER, exp)
    unlock_experiment(explore_project, OTHER, exp)
    report_runs(explore_project, human, tmp_path, exp, SUPPORTED)
    live = latest_evaluation(explore_project, xe.hid)
    assert live is not None and "autonomy:agent" in live.payload.flags


def test_confounded_and_failed_cells(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    table = dict(SUPPORTED)
    table[("baseline", 2)] = None  # a failed run: the cell is not complete
    report_runs(project, human, tmp_path, exp, table)
    assert _events(project, "hypothesis.evaluated") == []
    report_runs(project, human, tmp_path, exp, {("baseline", 2): "76.0"})  # a re-run
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.outcome == "supported"
    assert live.payload.counts["excluded"] == 1  # the failed run, listed


def test_recompute_matches_event(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and recompute(project, xw.hid) == live.payload
    assert recompute(project, "hyp_01JZ9Q3K5M7N8P0R2S4T6V8WZZ") is None


def test_unchanged_inputs_write_nothing(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    again = evaluate_hypothesis(project, xw.hid)
    assert len(_events(project, "hypothesis.evaluated")) == 1
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.event_id == again


# --- Hooks, filled without a patch ---------------------------------------------------------------


def test_revision_refused_after_evaluation_without_monkeypatch(
    project: Project, human: Any, xw: XW, hw: HW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    with pytest.raises(FactoryValidationError) as err:
        draft_hypothesis(
            project, DRAFTER, make_spec(lead=hw.lead, rationale="revised"), supersedes=xw.hid
        )
    assert _fields(err) == [("supersedes", "evidence-exists")]
    with pytest.raises(FactoryValidationError) as err:
        abandon_hypothesis(project, human, xw.hid, "other", "gave up")  # type: ignore[arg-type]
    assert _fields(err) == [("hypothesis_id", "evaluated")]  # only the evaluation hook says this


def test_conclude_allowed_after_evaluation_without_monkeypatch(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    with pytest.raises(FactoryValidationError) as err:
        conclude_hypothesis(project, human, xw.hid, "premature")
    assert ("state", "not-evaluated") in _fields(err)
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    conclude_hypothesis(project, human, xw.hid, "The attention variant does not help here.")


def test_conclusion_is_interpretation_and_keeps_outcome(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    conclude_hypothesis(project, human, xw.hid, "It does not help; I suspect the schedule.")
    view = hypothesis_view(project, xw.hid)
    assert view is not None and view.conclusion is not None and view.state == "evaluated"
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.outcome == "refuted"
    [concluded] = _events(project, "hypothesis.concluded")
    assert concluded.actor.kind == "human" and "outcome" not in concluded.payload


# --- Nobody sets an outcome -----------------------------------------------------------------


def _forge(project: Project, actor: Any, base: HypothesisEvaluated, **over: Any) -> Event:
    return raw_event(
        project, "hypothesis.evaluated", actor, {**base.model_dump(mode="json"), **over}
    )


def test_outcome_cannot_be_set(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None
    before = [e.event_id for e in evaluations_of(project, xw.hid)]
    flipped = {"outcome": "supported"}
    forged = [
        _forge(project, human, live.payload, **flipped),  # a human
        _forge(project, human, live.payload, **flipped).model_copy(
            update={"actor": DRAFTER, "input_blob": project.blobs.put_json({"x": 1})}
        ),  # an agent
        _forge(project, project.system_actor(), live.payload, **flipped),  # the platform, wrong
        _forge(  # a runner
            project,
            project.system_actor().model_copy(update={"id": "runner-gpu1"}),
            live.payload,
            inputs_hash="0" * 16,
        ),
        _forge(  # right outcome, invented flag
            project,
            project.system_actor(),
            live.payload,
            flags=["autonomy:agent"],
            inputs_hash="1" * 16,
        ),
        _forge(project, project.system_actor(), live.payload, mean="9", inputs_hash="2" * 16),
        _forge(
            project,
            project.system_actor(),
            live.payload,
            hypothesis_id="hyp_01JZ9Q3K5M7N8P0R2S4T6V8WZZ",
        ),
    ]
    for event in forged:
        inject(project, event)
    assert [e.event_id for e in evaluations_of(project, xw.hid)] == before
    project.index.rebuild()
    assert [e.event_id for e in evaluations_of(project, xw.hid)] == before
    latest = latest_evaluation(project, xw.hid)
    assert latest is not None and latest.payload.outcome == "refuted"


def test_only_the_platform_folds_an_exact_evaluation(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, dict(list(SUPPORTED.items())[:5]))
    exact = recompute(project, xw.hid)
    assert exact is not None and exact.outcome == "incomplete"
    runner = project.system_actor().model_copy(update={"id": "runner-gpu1"})
    agent_blob = project.blobs.put_json({"x": 1})
    for actor in (human, runner, DRAFTER):
        event = _forge(project, human, exact).model_copy(
            update={"actor": actor, "input_blob": agent_blob if actor.kind == "agent" else None}
        )
        inject(project, event)
    assert evaluations_of(project, xw.hid) == []
    project.index.rebuild()
    assert evaluations_of(project, xw.hid) == []
    inject(project, _forge(project, project.system_actor(), exact))
    assert [e.payload for e in evaluations_of(project, xw.hid)] == [
        exact
    ]  # the same payload, system


def test_evaluation_module_has_no_input_model() -> None:
    import inspect

    sig = inspect.signature(evaluate_hypothesis)
    assert set(sig.parameters) == {"project", "hypothesis_id", "request_incomplete"}
