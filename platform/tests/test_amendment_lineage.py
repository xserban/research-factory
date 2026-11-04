"""Decisions carry along the protocol lineage (decision 50).

An amendment that changes the protocol id must not drop earlier decisions: only the stale rules
of R-15 re-queue work. New decisions are still made under the current version.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import MetaData

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.index.screening import _agreed_by_work, screening_tables
from factory.model.protocol import (
    CriterionEffect,
    Limit,
    ProtocolSpec,
    ScreeningPlan,
    ScreeningStage,
)
from factory.model.screening import PassLabel, Verdict
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
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening import (
    live_decisions,
    screen_next,
    screen_record,
    stale_screening_decisions,
)
from tests.test_screening_next import SourcesFor, _queued
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
