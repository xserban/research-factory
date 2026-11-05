"""Lifecycle state and retirement of registered miners (M-D, task 1)."""

# ruff: noqa: F811
import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import spec_to_json
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import live_rows
from factory.services.miners import MinerState, miner_state, proposer, retire_miner
from factory.services.mining import mine_next, mine_record, register_miner
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import (
    SESSION_M1,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_row,
    miner_actor,
)

A = PassLabel.A


def test_state_registered_after_registration(
    project: Project, agent: Actor, world: list[str]
) -> None:
    register_miner(project, agent, spec_to_json(method_vision()))
    assert miner_state(project, VISION_NAME, 1) is MinerState.REGISTERED


def test_unregistered_version_refused(project: Project, world: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        miner_state(project, VISION_NAME, 1)
    assert raised.value.issues[0].field == "version"


def test_proposer_is_first_registration(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    spec = spec_to_json(method_vision())
    register_miner(project, agent, spec)
    register_miner(project, human, spec)  # the same spec again writes nothing
    found = proposer(project, VISION_NAME, 1)
    assert (found.kind, found.session) == ("agent", agent.session)


def test_retire_from_any_state(project: Project, agent: Actor, world: list[str]) -> None:
    register_miner(project, agent, spec_to_json(method_vision()))
    retire_miner(project, agent, VISION_NAME, 1, "wrong unit family")
    assert miner_state(project, VISION_NAME, 1) is MinerState.RETIRED
    retire_miner(project, agent, VISION_NAME, 1, "again")  # idempotent


def test_human_retires_and_system_cannot(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    register_miner(project, agent, spec_to_json(method_vision()))
    system = Actor(kind="system", id="platform", user="platform", session=human.session)
    with pytest.raises(FactoryValidationError) as raised:
        retire_miner(project, system, VISION_NAME, 1, "x")
    assert raised.value.issues[0].field == "actor"
    with pytest.raises(FactoryValidationError) as raised:
        retire_miner(project, human, VISION_NAME, 1, "  ")
    assert raised.value.issues[0].field == "reason"
    assert miner_state(project, VISION_NAME, 1) is MinerState.REGISTERED
    retire_miner(project, human, VISION_NAME, 1, "superseded")
    assert miner_state(project, VISION_NAME, 1) is MinerState.RETIRED


def test_retired_miner_refuses_tasks_keeps_rows(
    project: Project, agent: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    worker = miner_actor(SESSION_M1, "claude-opus-5-5")
    batch = mine_next(project, worker, VISION_NAME, 1, A).batch
    assert batch is not None
    mine_record(project, worker, batch.task_id, [mine_row()], finish=True)
    retire_miner(project, agent, VISION_NAME, 1, "retired mid-run")
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, worker, VISION_NAME, 1, A)
    assert raised.value.issues[0].field == "miner"
    assert len(live_rows(project, scope=MinerScope(VISION_NAME))) == 1  # the rows stay


def test_retired_miner_refuses_records(project: Project, agent: Actor, world: list[str]) -> None:
    list_miner(project, agent)
    worker = miner_actor(SESSION_M1, "claude-opus-5-5")
    batch = mine_next(project, worker, VISION_NAME, 1, A).batch
    assert batch is not None
    retire_miner(project, agent, VISION_NAME, 1, "retired mid-task")
    with pytest.raises(FactoryValidationError) as raised:
        mine_record(project, worker, batch.task_id, [mine_row()], finish=True)
    assert raised.value.issues[0].field == "miner"


def test_built_in_cannot_retire(project: Project, agent: Actor, world: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        retire_miner(project, agent, "contribution", 1, "no")
    assert raised.value.issues[0].field == "name"
