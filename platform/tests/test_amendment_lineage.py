"""Decisions carry along the protocol lineage (decision 50).

An amendment that changes the protocol id must not drop earlier decisions: only the stale rules
of R-15 re-queue work. New decisions are still made under the current version.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import MetaData

from factory.canonical import population_digest
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.index.screening import _agreed_by_work, screening_tables
from factory.model.protocol import (
    Criterion,
    CriterionEffect,
    Limit,
    ProtocolSpec,
    ScreeningPlan,
    ScreeningStage,
)
from factory.model.screening import PassLabel, ScreeningPhase, Verdict
from factory.services.agreement import (
    agreed_works,
    agreement_summary,
    exclusion_criteria,
    final_outcomes,
    pass_progress,
)
from factory.services.audit import audit_outstanding, audit_sample
from factory.services.calibration import calibration_items, calibration_status
from factory.services.context import Project
from factory.services.prisma import prisma_flow
from factory.services.protocol import amend_protocol, current_protocol, last_criterion_change
from factory.services.screening import (
    _done_keys,
    live_decisions,
    screen_next,
    screen_record,
    stale_screening_decisions,
)
from tests.helpers import _setup
from tests.test_screening_next import (
    SourcesFor,
    _draw,
    _loosen_ex01,
    _pass_calibration_under,
    _queued,
)
from tests.test_screening_record import _batch, _item
from tests.test_stage_services import _loosen, _world

TA = ScreeningStage.TITLE_ABSTRACT
FT = ScreeningStage.FULL_TEXT


def _amend(project: Project, agent: Actor, change: Callable[[ProtocolSpec], ProtocolSpec]) -> str:
    current = current_protocol(project)
    assert current is not None
    amend_protocol(project, agent, change(current.spec), reason="amend", semantic=True, effects={})
    after = current_protocol(project)
    assert after is not None and after.protocol_id != current.protocol_id
    return after.protocol_id


def _limits(spec: ProtocolSpec) -> ProtocolSpec:
    return spec.model_copy(update={"limits": (Limit(field="year", value="2015-2024"),)})


def _screening(spec: ProtocolSpec) -> ProtocolSpec:
    return spec.model_copy(
        update={"screening": spec.screening.model_copy(update={"kappa_floor": 0.6})}
    )


def _full_text(spec: ProtocolSpec) -> ProtocolSpec:
    plan = spec.full_text_screening
    assert isinstance(plan, ScreeningPlan)
    return spec.model_copy(
        update={"full_text_screening": plan.model_copy(update={"kappa_floor": 0.6})}
    )


def _snapshot(project: Project) -> dict[str, Any]:
    flow = prisma_flow(project).model_dump(exclude={"protocol_id"})
    return {
        "flow": flow,
        "outcomes": {s: final_outcomes(project, stage=s) for s in (TA, FT)},
        "progress": {s: pass_progress(project, stage=s) for s in (TA, FT)},
        "agreed": {s: agreed_works(project, stage=s) for s in (TA, FT)},
        "exclusions": {s: exclusion_criteria(project, stage=s) for s in (TA, FT)},
    }


@pytest.mark.parametrize("change", [_limits, _screening, _full_text], ids=lambda f: f.__name__)
def test_non_criterion_amendment_keeps_title_abstract_outcomes(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    change: Callable[[ProtocolSpec], ProtocolSpec],
) -> None:
    _world(project, agent, human, mock_sources)
    before = _snapshot(project)
    assert before["flow"]["pending"] == 0
    assert before["agreed"][TA]  # not vacuous

    _amend(project, agent, change)

    assert _snapshot(project) == before


def test_criterion_amendment_requeues_only_stale_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _world(project, agent, human, mock_sources)
    citing = {
        d.decision_id: d
        for d in live_decisions(project, stage=TA)
        if d.verdict is Verdict.EXCLUDE
        and d.criterion is not None
        and d.criterion.endswith(":EX01")
    }
    assert len(citing) == 3  # gone (A, B) and dis (B)

    new_id = _loosen(project, agent, "EX01")

    assert stale_screening_decisions(project, stage=TA) == set(citing)
    progress = pass_progress(project)
    assert progress["A"].remaining == 1 and progress["B"].remaining == 2
    assert final_outcomes(project)[world.gone].value == "pending"
    assert final_outcomes(project)[world.x].value == "included"
    screen_next(project, agent, PassLabel.A)
    # Pass A queues exactly the one stale ordinary work (the calibration set is queued as well).
    assert _queued(project, new_id) - set(calibration_items(project)) == {world.gone}


def test_clarification_stales_nothing(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    before = _snapshot(project)
    current = current_protocol(project)
    assert current is not None
    criteria = tuple(
        c.model_copy(update={"rule": "exclude it, explicitly"}) if c.id == "EX01" else c
        for c in current.spec.criteria
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"criteria": criteria}),
        reason="clarify",
        semantic=False,
        effects={"EX01": CriterionEffect.CLARIFIED},
    )
    after = current_protocol(project)
    assert after is not None and after.protocol_id != current.protocol_id

    assert stale_screening_decisions(project) == set()
    assert _snapshot(project) == before


def test_per_criterion_kappa_spans_versions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    before = agreement_summary(project)
    assert before is not None and before.kappa_by_criterion.get("EX01") is not None

    _amend(project, agent, _limits)
    _amend(project, agent, _screening)

    after = agreement_summary(project)
    assert after is not None
    assert after.kappa_by_criterion == before.kappa_by_criterion
    assert after.kappa == before.kappa
    assert after.cannot_assess_rate == before.cannot_assess_rate


def test_audit_digest_stable_across_non_criterion_amendment(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    audit_sample(project, human, random_seed=1)
    assert not audit_outstanding(project)

    new_id = _amend(project, agent, _limits)

    assert not audit_outstanding(project)  # the agreed set is unchanged, so the audit stays open
    tables = screening_tables(MetaData())
    for stage in (TA, FT):
        service = {
            w: (a.verdict, ",".join(a.criteria) if a.verdict == "exclude" else None)
            for w, a in agreed_works(project, stage=stage).items()
        }
        with project.index.connect() as conn:
            assert _agreed_by_work(conn, tables, new_id, stage.value) == service
        assert service


def test_calibration_gate_survives_non_criterion_amendment(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    before = calibration_status(project)
    _amend(project, agent, _limits)
    assert calibration_status(project) == before


def test_new_decisions_still_need_current_protocol(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    _amend(project, agent, _limits)

    with pytest.raises(FactoryValidationError) as raised:
        screen_record(project, agent, batch.task_id, [_item(batch.records[0])])
    assert [i.field for i in raised.value.issues] == ["task_id"]


# --- Reverted amendments (A -> B -> A) ---


def test_revert_amendment_keeps_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    before = _snapshot(project)
    original = current_protocol(project)
    assert original is not None

    _amend(project, agent, _limits)
    revert = amend_protocol(
        project, agent, original.spec, reason="revert", semantic=True, effects={}
    )
    assert revert.to_version == original.protocol_id

    assert _snapshot(project) == before
    assert before["flow"]["pending"] == 0
    assert not stale_screening_decisions(project)


def test_revert_of_criterion_amendment_stales_per_rules(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    original = current_protocol(project)
    assert original is not None
    ta = live_decisions(project, stage=TA)
    ex01 = {
        d.decision_id
        for d in ta
        if d.verdict is Verdict.EXCLUDE
        and d.criterion is not None
        and d.criterion.endswith(":EX01")
    }
    includes = {d.decision_id for d in ta if d.verdict is Verdict.INCLUDE}
    assert ex01 and includes

    _loosen(project, agent, "EX01")  # A -> B: stales exclusions citing EX01
    assert stale_screening_decisions(project, stage=TA) == ex01
    amend_protocol(
        project,
        agent,
        original.spec,
        reason="revert",
        semantic=True,
        effects={"EX01": CriterionEffect.TIGHTENED},
    )  # B -> A: tightening stales inclusions

    # Decisions made under A before both amendments are judged by both rules.
    assert stale_screening_decisions(project, stage=TA) == ex01 | includes

    # A decision made under B is judged by B -> A only: an exclusion citing EX01 survives.
    _loosen(project, agent, "EX01")
    current = current_protocol(project)
    assert current is not None
    work = sorted(w for w, o in final_outcomes(project).items() if o.value == "pending")[0]
    under_b = _decide_b(project, agent, work, current.protocol_id)
    amend_protocol(
        project,
        agent,
        original.spec,
        reason="revert",
        semantic=True,
        effects={"EX01": CriterionEffect.TIGHTENED},
    )
    stale = stale_screening_decisions(project, stage=TA)
    assert (
        under_b not in stale
    )  # an exclusion under B: loosening A -> B predates it, tightening spares it


def test_three_amendment_lineage_back_to_the_first_spec_keeps_every_decision(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    before = _snapshot(project)
    decisions = {d.decision_id for d in live_decisions(project, stage=None)}
    original = current_protocol(project)
    assert original is not None and decisions

    _amend(project, agent, _limits)  # A -> B
    _amend(project, agent, _screening)  # B -> C
    amend_protocol(project, agent, original.spec, reason="back", semantic=True, effects={})

    assert {d.decision_id for d in live_decisions(project, stage=None)} == decisions
    assert _snapshot(project) == before
    assert not stale_screening_decisions(project)


def test_lineage_through_a_criterion_change_stales_only_by_the_rules(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    original = current_protocol(project)
    assert original is not None
    ta = live_decisions(project, stage=TA)
    decisions = {d.decision_id for d in live_decisions(project, stage=None)}
    ex01 = {
        d.decision_id
        for d in ta
        if d.verdict is Verdict.EXCLUDE
        and d.criterion is not None
        and d.criterion.endswith(":EX01")
    }
    includes = {d.decision_id for d in ta if d.verdict is Verdict.INCLUDE}

    _loosen(project, agent, "EX01")  # A -> B
    _amend(project, agent, _limits)  # B -> C: no criterion effect
    assert stale_screening_decisions(project, stage=TA) == ex01
    amend_protocol(
        project,
        agent,
        original.spec,
        reason="back",
        semantic=True,
        effects={"EX01": CriterionEffect.TIGHTENED},
    )  # C -> A

    assert {d.decision_id for d in live_decisions(project, stage=None)} == decisions
    assert stale_screening_decisions(project, stage=TA) == ex01 | includes


def _decide_b(project: Project, agent: Actor, work: str, protocol_id: str) -> str:
    from tests.test_stage_services import _decide_at

    return _decide_at(project, agent, TA, work, "A", "exclude", "EX01", protocol_id)


# --- Tightening and an added criterion ---


def test_tightening_requeues_inclusions_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    includes = {d.decision_id for d in live_decisions(project, stage=TA) if d.verdict.promotes}
    current = current_protocol(project)
    assert current is not None
    criteria = tuple(
        c.model_copy(update={"rule": "exclude it, strictly"}) if c.id == "EX01" else c
        for c in current.spec.criteria
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"criteria": criteria}),
        reason="tighten",
        semantic=True,
        effects={"EX01": CriterionEffect.TIGHTENED},
    )

    assert stale_screening_decisions(project, stage=TA) == includes
    assert stale_screening_decisions(project, stage=FT) == set()


def test_added_criterion_requeues_everything_untested(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    everything = {d.decision_id for d in live_decisions(project, stage=TA)}
    current = current_protocol(project)
    assert current is not None
    added = Criterion(
        id="EX06",
        parent="NG03",
        statement="statement EX06",
        rule="exclude it",
        applies_at=TA,
        priority=6,
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"criteria": (*current.spec.criteria, added)}),
        reason="add",
        semantic=True,
        effects={},
    )

    assert stale_screening_decisions(project, stage=TA) == everything
    assert pass_progress(project)["A"].decided == 0


# --- Projector and service agree on the agreed set when decisions are stale ---


def test_audit_digest_ignores_stale_decisions_in_both(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _world(project, agent, human, mock_sources)
    new_id = _loosen(project, agent, "EX01")
    assert stale_screening_decisions(project, stage=TA)

    service = agreed_works(project)
    with project.index.connect() as conn:
        projected = _agreed_by_work(conn, screening_tables(MetaData()), new_id, TA.value)
    assert world.gone not in service and world.gone not in projected
    assert {
        w: (a.verdict, ",".join(a.criteria) if a.verdict == "exclude" else None)
        for w, a in service.items()
    } == projected
    assert population_digest((w, a.verdict) for w, a in service.items()) == population_digest(
        (w, v) for w, (v, _) in projected.items()
    )


# --- Calibration is passed again after a criterion change ---


def _calibrated(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[str, list[str]]:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    _pass_calibration_under(project, agent, human, protocol_id)
    assert calibration_status(project).passed["A"] is True
    return protocol_id, items


def test_calibration_requeued_after_criterion_change(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _, items = _calibrated(project, agent, human, mock_sources)

    _loosen_ex01(project, agent)

    assert calibration_status(project).passed["A"] is False
    batch = screen_next(project, agent, PassLabel.A).batch
    assert batch is not None and batch.phase is ScreeningPhase.CALIBRATION
    assert {str(r["work_id"]) for r in batch.records} <= set(items)


def test_clarification_forces_recalibration_but_limits_do_not(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _, items = _calibrated(project, agent, human, mock_sources)

    _amend(project, agent, _limits)
    assert calibration_status(project).passed["A"] is True  # not a criterion change

    current = current_protocol(project)
    assert current is not None
    criteria = tuple(
        c.model_copy(update={"rule": "exclude it, explicitly"}) if c.id == "EX01" else c
        for c in current.spec.criteria
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"criteria": criteria}),
        reason="clarify",
        semantic=False,
        effects={"EX01": CriterionEffect.CLARIFIED},
    )
    # A clarification is a criterion change: calibration is passed again (slice-1 behaviour).
    assert calibration_status(project).passed["A"] is False
    batch = screen_next(project, agent, PassLabel.A).batch
    assert batch is not None and batch.phase is ScreeningPhase.CALIBRATION
    assert items


# --- The calibration cut is per stage ---


def _declare_full_text_with(
    project: Project, agent: Actor, applies_at: ScreeningStage, *, plan: bool = True
) -> None:
    current = current_protocol(project)
    assert current is not None
    criterion = Criterion(
        id="EX04",
        parent="NG03",
        statement="The full text is outside the question.",
        rule="exclude it",
        applies_at=applies_at,
        priority=4,
    )
    update: dict[str, Any] = {"criteria": (*current.spec.criteria, criterion)}
    if plan:
        update["full_text_screening"] = ScreeningPlan(
            passes=2,
            dual_sample=1.0,
            kappa_floor=0.7,
            calibration_size=3,
            reviewers=current.spec.screening.reviewers,
        )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update=update),
        reason="full text",
        semantic=True,
        effects={},
    )


def test_full_text_only_criterion_leaves_title_abstract_calibration_alone(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _calibrated(project, agent, human, mock_sources)
    done_before = _done_keys(project, PassLabel.A, TA)
    assert last_criterion_change(project, stage=FT) is None

    _declare_full_text_with(project, agent, FT)

    assert calibration_status(project, stage=TA).passed["A"] is True
    assert _done_keys(project, PassLabel.A, TA) == done_before
    assert last_criterion_change(project, stage=TA) is None
    assert last_criterion_change(project, stage=FT) is not None


def test_either_criterion_moves_both_stages(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _calibrated(project, agent, human, mock_sources)

    _declare_full_text_with(project, agent, ScreeningStage.EITHER)

    assert calibration_status(project, stage=TA).passed["A"] is False
    assert last_criterion_change(project, stage=TA) is not None
    assert last_criterion_change(project, stage=FT) == last_criterion_change(project, stage=TA)


def test_title_abstract_criterion_change_does_not_move_the_full_text_cut(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _calibrated(project, agent, human, mock_sources)

    _loosen_ex01(project, agent)

    assert last_criterion_change(project, stage=TA) is not None
    assert last_criterion_change(project, stage=FT) is None
