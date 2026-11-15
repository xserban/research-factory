"""A session may join one pass label of several miners (decision 129); everything else stays
refused. One `extraction.pass_joined` event per join; it carries `calibration` (default False)."""

# ruff: noqa: F811
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import MinerRegime, spec_to_json
from factory.model.screening import Channel, PassLabel
from factory.services import resume
from factory.services.context import Project
from factory.services.document_read import document_read
from factory.services.extraction import (
    MineBatch,
    join_extraction_pass,
    session_scope,
)
from factory.services.miner_gold import label_miner_calibration
from factory.services.miners import draw_miner_calibration
from factory.services.mining import mine_next, mine_record, register_miner
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import (
    VISION_NAME,
    declare_exploratory,
    list_miner,
    method_vision,
    mine_exploratory,
    mine_pass,
    mine_row,
    miner_actor,
)

A, B = PassLabel.A, PassLabel.B
OTHER = "m-vision-two"
S1 = "01JZ9Q3K5M7N8P0R2S4T6V8W2A"
S2 = "01JZ9Q3K5M7N8P0R2S4T6V8W2B"
S3 = "01JZ9Q3K5M7N8P0R2S4T6V8W2C"
SP = "01JZ9Q3K5M7N8P0R2S4T6V8W2D"
OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"


def _two(project: Project, agent: Actor) -> None:
    list_miner(project, agent, method_vision())
    list_miner(project, agent, replace(method_vision(), name=OTHER))


def _joins(project: Project, session: str) -> list[tuple[str, str]]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT scope, pass_label FROM extraction_sessions WHERE session = :s "
                "ORDER BY scope"
            ),
            {"s": session},
        ).all()
    return [(str(s), str(p)) for s, p in rows]


def _refused(raised: pytest.ExceptionInfo[FactoryValidationError], field: str) -> None:
    assert raised.value.issues[0].field == field


def test_one_session_mines_the_same_pass_of_two_miners(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    actor = miner_actor(S1, OPUS)
    first = mine_pass(project, actor, A, lambda w: [mine_row()])
    second = mine_pass(project, actor, A, lambda w: [mine_row()], name=OTHER)
    assert first and sorted(first) == sorted(second)
    assert _joins(project, S1) == [(VISION_NAME, "A"), (OTHER, "A")]
    assert session_scope(project, S1) is not None


def test_pass_b_of_two_miners_in_one_session(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    actor = miner_actor(S1, OPUS)
    assert mine_pass(project, actor, B, lambda w: [mine_row()])
    assert mine_pass(project, actor, B, lambda w: [mine_row()], name=OTHER)
    assert _joins(project, S1) == [(VISION_NAME, "B"), (OTHER, "B")]


def test_a_task_of_one_miner_is_not_recorded_by_a_session_that_never_joined_it(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    holder = miner_actor(S1, OPUS)
    batch = mine_exploratory(project, holder, VISION_NAME, 1, A).batch
    assert isinstance(batch, MineBatch)
    outsider = miner_actor(S2, SONNET)
    with pytest.raises(FactoryValidationError):
        mine_record(project, outsider, batch.task_id, [mine_row()], finish=True)


def test_pass_a_of_one_miner_then_pass_b_of_another_is_refused(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    actor = miner_actor(S1, OPUS)
    mine_exploratory(project, actor, VISION_NAME, 1, A)
    declare_exploratory(project, OTHER, 1)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, actor, OTHER, 1, B)
    _refused(raised, "pass")
    assert _joins(project, S1) == [(VISION_NAME, "A")]


def test_pass_a_then_pass_b_of_the_same_miner_is_refused(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    actor = miner_actor(S1, OPUS)
    mine_exploratory(project, actor, VISION_NAME, 1, A)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, actor, VISION_NAME, 1, B)
    _refused(raised, "pass")


def test_miner_then_evidence_and_evidence_then_miner_are_refused(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    miner = miner_actor(S1, OPUS)
    mine_exploratory(project, miner, VISION_NAME, 1, A)
    with pytest.raises(FactoryValidationError) as raised:
        join_extraction_pass(project, miner, A)
    _refused(raised, "pass")
    evidence = miner_actor(S2, OPUS)
    join_extraction_pass(project, evidence, A)
    declare_exploratory(project, VISION_NAME, 1)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, evidence, VISION_NAME, 1, A)
    _refused(raised, "pass")
    assert _joins(project, S2) == [("evidence", "A")]


def test_the_model_rule_is_checked_for_each_miner_joined(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    # a sonnet session serves pass B of the first miner only
    mine_exploratory(project, miner_actor(S1, SONNET), VISION_NAME, 1, B)
    both = miner_actor(S2, SONNET)
    mine_exploratory(project, both, OTHER, 1, A)  # pass A of the other miner: allowed
    declare_exploratory(project, VISION_NAME, 1)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, both, VISION_NAME, 1, A)  # but this model serves its pass B
    _refused(raised, "model")
    assert _joins(project, S2) == [(OTHER, "A")]


def _calibration_setup(project: Project, agent: Actor, human: Actor) -> None:
    spec = replace(method_vision(), regime=MinerRegime(2, 5, 0.8, 0.9))
    register_miner(project, miner_actor(SP, OPUS), spec_to_json(spec))
    list_miner(project, agent, spec)
    list_miner(project, agent, replace(method_vision(), name=OTHER))
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=11)
    for unit in drawn.units:
        label_miner_calibration(
            project, human, drawn.calibration_id, unit.work_id, [mine_row()], channel=Channel.CLI
        )


def test_a_calibration_session_joins_nothing_else(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _calibration_setup(project, agent, human)
    judge = miner_actor(S3, SONNET)
    assert mine_next(project, judge, VISION_NAME, 1, A, calibration=True).batch is not None
    declare_exploratory(project, OTHER, 1)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, judge, OTHER, 1, A)
    _refused(raised, "pass")
    assert _joins(project, S3) == [(VISION_NAME, "A")]


def test_nothing_joins_a_calibration_after_a_production_miner(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _calibration_setup(project, agent, human)
    producer = miner_actor(S1, OPUS)
    mine_exploratory(project, producer, OTHER, 1, A)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, producer, VISION_NAME, 1, A, calibration=True)
    _refused(raised, "pass")
    assert _joins(project, S1) == [(OTHER, "A")]


def test_a_calibration_join_that_served_nothing_still_joins_nothing_else(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration_setup(project, agent, human)
    idle = miner_actor(S2, SONNET)
    # the join is written, but no task is claimed (nothing left to claim)
    monkeypatch.setattr("factory.services.extraction.claim_next", lambda *a, **k: None)
    assert mine_next(project, idle, VISION_NAME, 1, A, calibration=True).batch is None
    monkeypatch.undo()
    assert _joins(project, S2) == [(VISION_NAME, "A")]
    declare_exploratory(project, OTHER, 1)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, idle, OTHER, 1, A)
    _refused(raised, "pass")
    assert _joins(project, S2) == [(VISION_NAME, "A")]


def test_resume_lists_each_join(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _two(project, agent)
    actor = miner_actor(S1, OPUS)
    mine_exploratory(project, actor, VISION_NAME, 1, A)
    mine_exploratory(project, actor, OTHER, 1, A)
    monkeypatch.setattr(resume, "pending_work", lambda p: {"mine_a": 3})
    later = project.clock.now() + timedelta(days=2)
    found = [p for p in resume._passes(project, later) if p.session == S1]
    assert sorted(p.scope or "" for p in found) == [VISION_NAME, OTHER]
    assert {p.label for p in found} == {"A"}


def test_selected_reading_unites_the_selections_of_every_miner_joined(
    project: Project, agent: Actor, world: list[str]
) -> None:
    _two(project, agent)
    actor = miner_actor(S1, OPUS)
    first = mine_exploratory(project, actor, VISION_NAME, 1, A).batch
    second = mine_exploratory(project, actor, OTHER, 1, A).batch
    assert isinstance(first, MineBatch) and isinstance(second, MineBatch)
    work = first.records[0]["work_id"]
    page = document_read(project, work_id=work, session=S1, selected=True, limit=100)
    assert page.segments
    assert second.records
