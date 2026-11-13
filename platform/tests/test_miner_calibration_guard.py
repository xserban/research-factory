"""A production pass needs a passed calibration unless explicitly exploratory (IDEA-69 (3))."""

# ruff: noqa: F811
import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mining.spec import spec_to_json
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import task_content
from factory.services.miners import MinerState, miner_state
from factory.services.mining import mine_next, register_miner
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_calibration_helpers import calibrated_world, run_calibration
from tests.miner_helpers import (
    SESSION_M1,
    VISION_NAME,
    list_miner,
    method_vision,
    miner_actor,
)

A = PassLabel.A
WORKER = miner_actor(SESSION_M1, "claude-opus-5-5")


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def test_unregistered_calibration_refuses_production(
    project: Project, agent: Actor, world: list[str]
) -> None:
    spec = method_vision()
    register_miner(project, agent, spec_to_json(spec))
    list_miner(project, agent, spec)
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, WORKER, VISION_NAME, 1, A)
    issue = raised.value.issues[0]
    assert issue.field == "calibration"
    assert f"{VISION_NAME} version 1" in issue.reason and "exploratory" in issue.reason
    assert _events(project) == before


def test_exploratory_run_serves_and_marks_the_task(
    project: Project, agent: Actor, world: list[str]
) -> None:
    spec = method_vision()
    register_miner(project, agent, spec_to_json(spec))
    list_miner(project, agent, spec)
    batch = mine_next(project, WORKER, VISION_NAME, 1, A, exploratory=True).batch
    assert batch is not None and batch.exploratory is True
    stored = task_content(project, _task(project, batch.task_id))
    assert isinstance(stored, dict) and stored["exploratory"] is True


def _task(project: Project, task_id: str):  # type: ignore[no-untyped-def]
    from factory.services.extraction import get_task

    task = get_task(project, task_id)
    assert task is not None
    return task


def test_passed_calibration_allows_production_unmarked(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED
    batch = mine_next(project, WORKER, VISION_NAME, 1, A).batch
    assert batch is not None and batch.exploratory is False


def test_calibrating_or_unrun_calibration_still_refuses(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)  # drawn and labelled, pass not run
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATING
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, WORKER, VISION_NAME, 1, A)
    assert raised.value.issues[0].field == "calibration"


def test_calibration_pass_cannot_be_exploratory(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, WORKER, VISION_NAME, 1, A, calibration=True, exploratory=True)
    assert raised.value.issues[0].field == "exploratory"
