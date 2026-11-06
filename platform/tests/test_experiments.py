"""Designing, amending, freezing and deviating (slice 6, plan XP-A task 2)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.hypotheses.design import design_version
from factory.index.default import PROJECTION_VERSION
from factory.model.experiments import ExperimentFrozen
from factory.modules.contract import PolicyKind
from factory.services.context import Project
from factory.services.experiments import (
    amend_experiment,
    design_experiment,
    experiment_view,
    freeze_experiment,
    live_experiment,
    record_deviation,
)
from factory.services.hypotheses import draft_hypothesis
from tests.experiment_helpers import METRIC, XW, design, xe, xw
from tests.hypothesis_helpers import DRAFTER, HW, OTHER, gw, hw, make_spec


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def test_design_is_recorded_with_computed_version(project: Project, human: Actor, xw: XW) -> None:
    d = xw.design()
    exp, version = design_experiment(project, DRAFTER, d)
    assert exp.startswith("exp_") and version == design_version(d)
    view = experiment_view(project, exp)
    assert view is not None and (view.state, view.e_version) == ("draft", version)
    assert view.design == d and view.hypothesis == xw.hid and view.flags == ()
    [event] = _events(project, "experiment.designed")
    assert event.actor.kind == "agent" and event.input_blob is not None  # R-04
    assert live_experiment(project, xw.hid) == view


def test_baseline_conditions_must_match(project: Project, human: Actor, hw: HW) -> None:
    # acceptance 13: the hypothesis conditions name the task; the row is a classification row
    from factory.services.extraction_agreement import final_rows
    from tests.experiment_helpers import register_with_review

    rows = {r.row_key: r.fields["task"].value for r in final_rows(project)}
    detection = next(k for k, v in rows.items() if v == "detection")
    classification = next(k for k, v in rows.items() if v == "classification")
    hid, _ = draft_hypothesis(
        project, DRAFTER, make_spec(lead=hw.lead, conditions={"task": "classification"})
    )
    for key, ok in ((detection, False), (classification, True)):
        body = {"baselines": [{"row_key": key, "tolerance": "0.01"}]}
        d = design(hid, **body)
        if ok:
            design_experiment(project, DRAFTER, d)
        else:
            with pytest.raises(FactoryValidationError) as err:
                design_experiment(project, DRAFTER, d)
            assert _fields(err) == [("baselines.0.row_key", "conditions-differ")]
    unknown = design(hid, baselines=[{"row_key": "rk_000000000000", "tolerance": "0.01"}])
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, unknown)
    assert ("baselines.0.row_key", "not-a-final-row") in _fields(err)


def test_literature_hypothesis_refused(project: Project, human: Actor, hw: HW) -> None:
    literature = make_spec(
        lead=hw.lead,
        kind="literature",
        decision_rule={"rule": "literature-direction", "n_min": 5, "q": "0.8"},
        prediction={"direction": "treatment-better", "margin": "0"},
        test={"kind": "literature", "window_start": "2026-01-01", "sources": []},
    )
    hid, _ = draft_hypothesis(project, DRAFTER, literature)
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, design(hid, baselines=[]))
    assert ("hypothesis", "not-an-experiment") in _fields(err)
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, design("hyp_01JZ9Q3K5M7N8P0R2S4T6V8W99", baselines=[]))
    assert _fields(err) == [("hypothesis", "unknown")]
    assert _events(project, "experiment.designed") == []


def test_primary_metric_must_be_the_hypothesis_metric(project: Project, xw: XW) -> None:
    other = [{"name": "latency", "direction": "lower", "unit_family": "other", "primary": True}]
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, xw.design(metrics=other))
    assert _fields(err) == [("metrics", "not-hypothesis-metric")]


def test_access_limit_cannot_exceed_the_plan(project: Project, xw: XW) -> None:
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, xw.design(test_access_limit=5))
    assert _fields(err) == [("test_access_limit", "above-plan")]


def test_one_live_design_per_hypothesis(project: Project, human: Actor, xw: XW) -> None:
    first, _ = design_experiment(project, DRAFTER, xw.design())
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, xw.design(seeds=[1, 2, 3, 4]))
    assert _fields(err) == [("hypothesis", "design-exists")]
    second, _ = design_experiment(project, DRAFTER, xw.design(seeds=[1, 2, 3, 4]), supersedes=first)
    old = experiment_view(project, first)
    assert old is not None and (old.state, old.superseded_by) == ("superseded", second)
    live = live_experiment(project, xw.hid)
    assert live is not None and live.experiment_id == second
    freeze_experiment(project, human, second)
    with pytest.raises(FactoryValidationError) as err:  # a frozen design is never replaced
        design_experiment(project, DRAFTER, xw.design(seeds=[1, 2, 3, 5]), supersedes=second)
    assert _fields(err) == [("supersedes", "frozen")]
    with pytest.raises(FactoryValidationError) as err:
        design_experiment(project, DRAFTER, xw.design(seeds=[1, 2, 3, 5]), supersedes=first)
    assert _fields(err) == [("supersedes", "already-superseded")]


def test_amend_before_freeze_changes_e_version(project: Project, human: Actor, xw: XW) -> None:
    exp, version = design_experiment(project, DRAFTER, xw.design())
    new = xw.design(seeds=[1, 2, 3, 4])
    event_id = amend_experiment(project, DRAFTER, exp, new, "a fourth seed", False)
    view = experiment_view(project, exp)
    assert view is not None and view.e_version == design_version(new) != version
    assert view.design == new and event_id.startswith("ev_")
    with pytest.raises(FactoryValidationError) as err:
        amend_experiment(project, DRAFTER, exp, xw.design(), "  ", False)
    assert _fields(err) == [("reason", "between 1 and 300 characters")]
    other_hypothesis = new.model_copy(update={"hypothesis": "hyp_01JZ9Q3K5M7N8P0R2S4T6V8W99"})
    with pytest.raises(FactoryValidationError) as err:
        amend_experiment(project, DRAFTER, exp, other_hypothesis, "move it", False)
    assert ("design.hypothesis", "differs") in _fields(err)


def test_frozen_design_only_deviates(project: Project, human: Actor, xw: XW) -> None:
    # Review Focus 2
    exp, version = design_experiment(project, DRAFTER, xw.design())
    with pytest.raises(FactoryValidationError) as err:  # a deviation needs a frozen design
        record_deviation(project, human, exp, "other", "early", False)
    assert _fields(err) == [("experiment_id", "not-frozen")]
    freeze_experiment(project, human, exp)
    with pytest.raises(FactoryValidationError) as err:
        amend_experiment(project, human, exp, xw.design(seeds=[1, 2, 3, 4]), "late", False)
    assert _fields(err) == [("experiment_id", "frozen")]
    view = experiment_view(project, exp)
    assert view is not None and view.e_version == version and view.state == "frozen"
    record_deviation(project, human, exp, "planned-change-after-freeze", "swap the seed", True)
    view = experiment_view(project, exp)
    assert view is not None and view.e_version == version
    [dev] = view.deviations
    assert (dev.kind, dev.semantic, dev.after_unlock) == (
        "planned-change-after-freeze",
        True,
        False,
    )
    assert view.flags == ()  # not deviated: the unlock has not happened


def test_deviations_are_a_human_act_except_the_platform_kinds(
    project: Project, human: Actor, xw: XW
) -> None:
    exp, _ = design_experiment(project, DRAFTER, xw.design())
    freeze_experiment(project, human, exp)
    with pytest.raises(FactoryValidationError) as err:
        record_deviation(project, OTHER, exp, "other", "an agent's deviation", False)
    assert _fields(err) == [("actor", "human-only")]
    with pytest.raises(FactoryValidationError) as err:  # only the platform records its own kinds
        record_deviation(project, human, exp, "test-reuse", "typed by hand", False)
    assert _fields(err) == [("actor", "platform-only")]
    with pytest.raises(FactoryValidationError) as err:
        record_deviation(project, human, exp, "baseline-accepted", "typed by hand", False)
    assert _fields(err) == [("kind", "use-accept-baseline")]
    record_deviation(project, project.system_actor(), exp, "budget-overrun", "over", False)
    view = experiment_view(project, exp)
    assert view is not None and [d.kind for d in view.deviations] == ["budget-overrun"]


def test_pilot_agent_cannot_freeze(project: Project, human: Actor, xw: XW) -> None:
    exp, _ = design_experiment(project, DRAFTER, xw.design())
    with pytest.raises(FactoryValidationError) as err:
        freeze_experiment(project, OTHER, exp)
    assert _fields(err) == [
        ("actor", "gate experiments.freeze_unlock is human: an agent cannot pass it")
    ]
    assert _events(project, "experiment.frozen") == []
    freeze_experiment(project, human, exp)
    [event] = _events(project, "experiment.frozen")
    assert event.payload["policy"] == "human" and event.payload["autonomy"] == "human"
    assert event.payload["test_access_limit"] == 1
    with pytest.raises(FactoryValidationError) as err:
        freeze_experiment(project, human, exp)
    assert _fields(err) == [("experiment_id", "state-frozen")]


def test_exploratory_freeze_needs_a_non_designer_session(explore_project: Project, xe: XW) -> None:
    project = explore_project
    exp, _ = design_experiment(project, DRAFTER, xe.design())
    with pytest.raises(FactoryValidationError) as err:
        freeze_experiment(project, DRAFTER, exp)
    assert _fields(err) == [("session", "the proposer cannot pass gate experiments.freeze_unlock")]
    freeze_experiment(project, OTHER, exp)
    view = experiment_view(project, exp)
    assert view is not None and view.state == "frozen"
    [event] = _events(project, "experiment.frozen")
    assert event.payload["autonomy"] == "agent" and event.input_blob is not None


def test_amending_adds_the_amender_to_the_designers(explore_project: Project, xe: XW) -> None:
    project = explore_project
    exp, _ = design_experiment(project, DRAFTER, xe.design())
    amend_experiment(project, OTHER, exp, xe.design(seeds=[1, 2, 3]), "tune", False)
    with pytest.raises(FactoryValidationError) as err:  # OTHER now co-designed it
        freeze_experiment(project, OTHER, exp)
    assert _fields(err) == [("session", "the proposer cannot pass gate experiments.freeze_unlock")]


# --- The projector refuses what a service would (hand-written events) -----------------------------


def _hand(project: Project, actor: Actor, type_: str, payload: object, ref: str) -> None:
    blob = project.blobs.put_json({}) if actor.kind == "agent" else None
    project.record(
        [project.events.make(type_, payload, actor, refs=[ref], input_blob=blob)]  # type: ignore[arg-type]
    )


def test_projector_ignores_an_agent_freeze_under_a_human_policy(
    project: Project, human: Actor, xw: XW
) -> None:
    exp, version = design_experiment(project, DRAFTER, xw.design())
    forged = ExperimentFrozen(
        experiment_id=exp,
        e_version=version,
        policy=PolicyKind.AGENT,  # not the policy in force (pilot: human)
        autonomy="agent",
        test_access_limit=99,
    )
    _hand(project, OTHER, "experiment.frozen", forged, exp)
    honest = forged.model_copy(update={"policy": PolicyKind.HUMAN})
    _hand(project, OTHER, "experiment.frozen", honest, exp)  # an agent under a human policy
    view = experiment_view(project, exp)
    assert view is not None and view.state == "draft" and view.access_limit is None
    assert len(_events(project, "experiment.frozen")) == 2


def test_projector_ignores_a_stale_version_and_a_frozen_amendment(
    project: Project, human: Actor, xw: XW
) -> None:
    from factory.model.experiments import ExperimentAmended

    exp, version = design_experiment(project, DRAFTER, xw.design())
    freeze_experiment(project, human, exp)
    changed = xw.design(seeds=[1, 2, 3, 4, 5])
    forged = ExperimentAmended(
        experiment_id=exp,
        design=changed,
        e_version=design_version(changed),
        reason="sneak",
        semantic=False,
    )
    _hand(project, DRAFTER, "experiment.amended", forged, exp)
    view = experiment_view(project, exp)
    assert view is not None and view.e_version == version
    assert view.design.seeds == (1, 2, 3)


def test_projector_ignores_a_second_live_design_and_an_agent_deviation(
    project: Project, human: Actor, xw: XW
) -> None:
    from factory.model.experiments import ExperimentDesigned, ExperimentDeviationRecorded

    exp, _ = design_experiment(project, DRAFTER, xw.design())
    rival = xw.design(seeds=[7, 8, 9])
    forged = ExperimentDesigned(
        experiment_id="exp_01JZ9Q3K5M7N8P0R2S4T6V8W77",
        design=rival,
        e_version=design_version(rival),
    )
    _hand(project, DRAFTER, "experiment.designed", forged, forged.experiment_id)
    assert experiment_view(project, forged.experiment_id) is None
    freeze_experiment(project, human, exp)
    lie = ExperimentDeviationRecorded(
        experiment_id=exp, kind="other", text="x", semantic=True, after_unlock=True
    )
    _hand(project, OTHER, "experiment.deviation_recorded", lie, exp)
    view = experiment_view(project, exp)
    assert view is not None and view.deviations == []


def test_rebuild_state_hash_stable(project: Project, human: Actor, xw: XW) -> None:
    exp, _ = design_experiment(project, DRAFTER, xw.design())
    amend_experiment(project, DRAFTER, exp, xw.design(seeds=[1, 2, 3, 4]), "more", False)
    freeze_experiment(project, human, exp)
    record_deviation(project, human, exp, "other", "noted", False)
    before = project.index.state_hash()
    assert project.index.rebuild() == before


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "62"


def test_an_agent_cannot_raise_the_test_access_limit_by_amending_the_protocol(
    project: Project, human: Actor, xw: XW
) -> None:
    # review I2: the allowance is a rule of the protocol; only the researcher relaxes it
    from factory.model.hypothesis_plan import HypothesisPlan
    from factory.services.hypothesis_gates import effective_plan
    from factory.services.protocol import amend_protocol, current_protocol

    current = current_protocol(project)
    assert current is not None
    raised = current.spec.model_copy(
        update={"hypothesis_plan": HypothesisPlan(test_access_limit=50)}
    )
    with pytest.raises(FactoryValidationError) as err:
        amend_protocol(project, OTHER, raised, reason="more reads", semantic=True, effects={})
    assert _fields(err) == [("hypothesis_plan.test_access_limit", "agent-cannot-raise")]
    assert effective_plan(project).test_access_limit == 1
    # the same amendment by the researcher goes through; an agent may lower or keep the limit
    amend_protocol(project, human, raised, reason="more reads", semantic=True, effects={})
    assert effective_plan(project).test_access_limit == 50
    lowered = raised.model_copy(update={"hypothesis_plan": HypothesisPlan(test_access_limit=2)})
    amend_protocol(project, OTHER, lowered, reason="fewer reads", semantic=True, effects={})
    assert effective_plan(project).test_access_limit == 2


def test_projector_recomputes_the_access_limit_of_a_freeze(
    project: Project, human: Actor, xw: XW
) -> None:
    # review I3: the limit is the design's or the plan's at that point of the log, not the payload's
    exp, version = design_experiment(project, DRAFTER, xw.design(baselines=[]))
    forged = ExperimentFrozen(
        experiment_id=exp,
        e_version=version,
        policy=PolicyKind.HUMAN,
        autonomy="human",
        test_access_limit=99,
    )
    project.record([project.events.make("experiment.frozen", forged, human)])
    view = experiment_view(project, exp)
    assert view is not None and view.state == "draft" and view.access_limit is None
    honest = forged.model_copy(update={"test_access_limit": 1})
    project.record([project.events.make("experiment.frozen", honest, human)])
    view = experiment_view(project, exp)
    assert view is not None and (view.state, view.access_limit) == ("frozen", 1)


@pytest.mark.parametrize(
    "type_,payload",
    [
        ("experiment.designed", {}),
        ("experiment.amended", {"experiment_id": "exp_x"}),
        ("experiment.frozen", {"experiment_id": 7}),
        ("experiment.unlocked", {"nonce": None}),
        ("experiment.deviation_recorded", {"kind": "whim"}),
        ("xrun.registered", {"run_id": "xrn_x"}),
        ("xrun.reported", {"run_id": "xrn_x", "metrics": "abc"}),
        ("baseline.evaluated", {"reported": "abc"}),
        ("baseline.accepted", {"experiment_id": ["x"], "row_key": 3}),
    ],
)
def test_a_malformed_event_changes_nothing_and_never_breaks_a_rebuild(
    project: Project, human: Actor, xw: XW, type_: str, payload: dict[str, object]
) -> None:
    # review I5: every handler is total
    from tests.experiment_helpers import experiment_rows, inject, raw_event

    exp, _ = design_experiment(project, DRAFTER, xw.design())
    freeze_experiment(project, human, exp)
    before = experiment_rows(project)
    inject(project, raw_event(project, type_, human, payload))
    project.index.rebuild()
    assert experiment_rows(project) == before


def test_a_baseline_verdict_with_a_non_numeric_value_is_skipped(
    project: Project, human: Actor, xw: XW
) -> None:
    from factory.model.experiments import BaselineEvaluated
    from tests.experiment_helpers import experiment_rows, inject

    exp, _ = design_experiment(project, DRAFTER, xw.design())
    freeze_experiment(project, human, exp)
    row = xw.rows[0]
    bad = BaselineEvaluated.model_construct(
        experiment_id=exp,
        row_key=row,
        reported="abc",
        reproduced="9",
        runs=(),
        excluded_runs=(),
        tolerance="0.01",
        tolerance_kind="relative",
        verdict="reproduced",
        evaluator_version="x",
    )
    before = experiment_rows(project)
    inject(project, project.events.make("baseline.evaluated", bad, project.system_actor()))
    project.index.rebuild()
    assert experiment_rows(project) == before


def test_a_superseding_design_keeps_the_earlier_designers(explore_project: Project) -> None:
    # review I7 (R-51): whoever drafted the first design cannot pass the gate for the second
    project = explore_project
    hid, _ = draft_hypothesis(project, DRAFTER, make_spec(metric=METRIC))
    first, _ = design_experiment(project, DRAFTER, design(hid, baselines=[]))
    second, _ = design_experiment(
        project, OTHER, design(hid, baselines=[], notes="x"), supersedes=first
    )
    with pytest.raises(FactoryValidationError) as err:
        freeze_experiment(project, DRAFTER, second)
    assert _fields(err) == [("session", "the proposer cannot pass gate experiments.freeze_unlock")]
    view = experiment_view(project, second)
    assert view is not None and set(view.designer_sessions) == {DRAFTER.session, OTHER.session}
