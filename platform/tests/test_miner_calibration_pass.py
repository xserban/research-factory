"""The calibration pass on the mine path, with the proposer excluded (M-D, task 4)."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mining.spec import MinerRegime, spec_to_json
from factory.model.extraction import MinerScope
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.extraction import (
    MineBatch,
    live_rows,
    stale_extractions,
    unit_states,
)
from factory.services.extraction_agreement import final_rows
from factory.services.miner_gold import label_miner_calibration
from factory.services.miners import draw_miner_calibration
from factory.services.mining import (
    mine_next,
    mine_record,
    mine_status,
    miner_population,
    register_miner,
)
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.helpers import install_skill, open_session
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_pass,
    mine_row,
    miner_actor,
)

A, B = PassLabel.A, PassLabel.B
SESSION_C = "01JZ9Q3K5M7N8P0R2S4T6V8W1G"
SESSION_D = "01JZ9Q3K5M7N8P0R2S4T6V8W1H"
SCOPE = MinerScope(VISION_NAME)


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


SESSION_P = "01JZ9Q3K5M7N8P0R2S4T6V8W1J"
PROPOSER = miner_actor(SESSION_P, "claude-opus-5-5")


def _setup(project: Project, agent: Actor, human: Actor) -> tuple[str, list[str]]:
    """Register the miner as session P, list it (5 calibration units), draw the sample and label
    every unit."""
    spec = replace(method_vision(), regime=MinerRegime(2, 5, 0.8, 0.9))
    register_miner(project, PROPOSER, spec_to_json(spec))
    list_miner(project, agent, spec)  # registering again changes nothing; it lists the miner
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=11)
    works = [u.work_id for u in drawn.units]
    for work in works:
        label_miner_calibration(
            project, human, drawn.calibration_id, work, [mine_row()], channel=Channel.CLI
        )
    return drawn.calibration_id, works


def _calibrate(project: Project, actor: Actor, *, rows: bool = True) -> list[str]:
    done: list[str] = []
    for _ in range(50):
        batch = mine_next(project, actor, VISION_NAME, 1, A, calibration=True).batch
        if batch is None:
            return done
        assert isinstance(batch, MineBatch)
        mine_record(
            project,
            actor,
            batch.task_id,
            [mine_row()] if rows else [],
            finish=True,
            reason=None if rows else "no result",
        )
        done.append(batch.records[0]["work_id"])
    raise AssertionError("too many tasks")


def test_proposer_is_not_evaluator(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _setup(project, agent, human)
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, PROPOSER, VISION_NAME, 1, A, calibration=True)
    assert raised.value.issues[0].field == "session"
    assert _events(project) == before  # no pass opened, no join, no task claimed
    # the refusal says nothing of which rule applied
    assert "proposer" not in raised.value.issues[0].reason


def test_label_relaying_session_cannot_calibrate(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _setup(project, agent, human)
    relayer = Actor(kind="human", id="obd", user="obd", session=SESSION_D)
    label_miner_calibration(
        project, relayer, cal, works[0], [mine_row("lower")], channel=Channel.MCP
    )
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(
            project, miner_actor(SESSION_D, "claude-opus-5-5"), VISION_NAME, 1, A, calibration=True
        )
    assert raised.value.issues[0].field == "session"
    assert _events(project) == before


def test_production_session_cannot_calibrate_and_back(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _setup(project, agent, human)
    producer = miner_actor(SESSION_M1, "claude-opus-5-5")
    mine_next(project, producer, VISION_NAME, 1, A)  # joins a production pass
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, producer, VISION_NAME, 1, A, calibration=True)
    assert raised.value.issues[0].field == "session"
    judge = miner_actor(SESSION_C, "claude-sonnet-5-5")
    assert _calibrate(project, judge)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, judge, VISION_NAME, 1, A)  # a calibration session does not produce
    assert raised.value.issues[0].field == "session"


def test_calibration_needs_a_drawn_sample_and_is_one_pass(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    judge = miner_actor(SESSION_C, "claude-sonnet-5-5")
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, judge, VISION_NAME, 1, A, calibration=True)
    assert raised.value.issues[0].field == "calibration"
    draw_miner_calibration(project, human, VISION_NAME, 1)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, judge, VISION_NAME, 1, B, calibration=True)
    assert raised.value.issues[0].field == "pass"


def test_calibration_serves_only_drawn_units(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _setup(project, agent, human)
    judge = miner_actor(SESSION_C, "claude-sonnet-5-5")
    batch = mine_next(project, judge, VISION_NAME, 1, A, calibration=True).batch
    assert isinstance(batch, MineBatch) and batch.calibration_id == cal
    mine_record(project, judge, batch.task_id, [mine_row()], finish=True)
    served = [batch.records[0]["work_id"], *_calibrate(project, judge)]
    assert sorted(served) == sorted(works) and len(set(served)) == 5
    assert mine_next(project, judge, VISION_NAME, 1, A, calibration=True).batch is None
    states = unit_states(project, scope=SCOPE, calibration_id=cal)
    assert {s.state for s in states} == {"current"} and len(states) == 5


def test_production_skips_calibration_units_until_scored(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _setup(project, agent, human)
    assert not set(miner_population(project, VISION_NAME)) & set(works)
    producer = miner_actor(SESSION_M1, "claude-opus-5-5")
    mined = mine_pass(project, producer, A, lambda w: [mine_row()])
    assert len(mined) == len(world) - 5 and not set(mined) & set(works)
    assert {s.work_id for s in unit_states(project, scope=SCOPE)}.isdisjoint(works)
    _calibrate(project, miner_actor(SESSION_C, "claude-sonnet-5-5"))
    # after the calibration is scored they stay apart: a calibration unit is never produced
    assert not set(miner_population(project, VISION_NAME)) & set(works)
    assert cal


def test_calibration_rows_separate(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _, works = _setup(project, agent, human)
    producer_a = miner_actor(SESSION_M1, "claude-opus-5-5")
    producer_b = miner_actor(SESSION_M2, "claude-sonnet-5-5")
    mine_pass(project, producer_a, A, lambda w: [mine_row()])
    mine_pass(project, producer_b, B, lambda w: [mine_row()])
    finals = [(f.work_id, f.row_key, f.status) for f in final_rows(project, scope=SCOPE)]
    production = {r.extraction_id for r in live_rows(project, scope=SCOPE)}
    status = mine_status(project)[0]
    _calibrate(project, miner_actor(SESSION_C, "claude-opus-5-5"))
    apart = live_rows(project, scope=SCOPE, calibration=True)
    assert len(apart) == 5 and {r.work_id for r in apart} == set(works)
    # the production run is as it was: rows, final rows, status, staleness
    assert {r.extraction_id for r in live_rows(project, scope=SCOPE)} == production
    assert [(f.work_id, f.row_key, f.status) for f in final_rows(project, scope=SCOPE)] == finals
    after = mine_status(project)[0]
    assert (after.units, after.rows, after.closed) == (status.units, status.rows, status.closed)
    assert not stale_extractions(project, scope=SCOPE)
    # and the production run reads none of the calibration's: calibration reads see only theirs
    assert {r.extraction_id for r in apart}.isdisjoint(production)
    assert live_rows(project, calibration=True) == []  # evidence has no calibration rows


def test_calibration_pass_keeps_its_separate_ledger_when_rerun(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, _ = _setup(project, agent, human)
    judge = miner_actor(SESSION_C, "claude-sonnet-5-5")
    _calibrate(project, judge)
    assert {s.state for s in unit_states(project, scope=SCOPE, calibration_id=cal)} == {"current"}
    assert {s.state for s in unit_states(project, scope=SCOPE)} == {"queued"} or not unit_states(
        project, scope=SCOPE
    )


def test_units_queued_for_production_before_the_draw_are_calibrated_apart(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    spec = replace(method_vision(), regime=MinerRegime(2, 5, 0.8, 0.9))
    register_miner(project, PROPOSER, spec_to_json(spec))
    list_miner(project, agent, spec)
    producer = miner_actor(SESSION_M1, "claude-opus-5-5")
    held = mine_next(project, producer, VISION_NAME, 1, A).batch  # queues every unit, claims one
    assert held is not None
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=2)
    assert held.records[0]["work_id"] not in {u.work_id for u in drawn.units}
    for unit in drawn.units:
        label_miner_calibration(
            project, human, drawn.calibration_id, unit.work_id, [mine_row()], channel=Channel.CLI
        )
    judge = miner_actor(SESSION_C, "claude-sonnet-5-5")
    served = _calibrate(project, judge)
    assert sorted(served) == sorted(u.work_id for u in drawn.units)
    states = unit_states(project, scope=SCOPE, calibration_id=drawn.calibration_id)
    assert {s.state for s in states} == {"current"}


@pytest.mark.anyio
async def test_mcp_mine_next_calibration_flag(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    cal, works = _setup(project, agent, human)
    meta = {"role": "miner", "model": "claude-opus-5-5", "skill": "rf-extract"}

    async def call(session: str) -> dict[str, object]:
        class Ids:
            def __init__(self, _clock: object) -> None: ...

            def ulid(self) -> str:
                return session

        monkeypatch.setattr(mcp_server, "IdGenerator", Ids)
        async with open_session(settings, clock) as client:
            return await client.call(
                "mine_next",
                project="demo",
                miner=VISION_NAME,
                version=1,
                pass_label="A",
                calibration=True,
                **meta,
            )

    before = _events(project)
    refused = await call(SESSION_P)  # the proposer's session
    assert refused["ok"] is False and refused["errors"][0]["field"] == "session"  # type: ignore[index]
    assert _events(project) == before
    served = await call(SESSION_C)
    assert served["ok"] is True, served
    batch = served["data"]["batch"]  # type: ignore[index]
    assert batch["calibration_id"] == cal and batch["records"][0]["work_id"] in works
