"""The calibration sample draw of a registered miner (M-D, task 2)."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.calibration import sample_size, thresholds
from factory.mining.spec import MinerRegime
from factory.model.project import RigorMode
from factory.model.screening import PassLabel
from factory.quality.stats import draw_uniform
from factory.services.context import Project
from factory.services.miners import calibration_of, draw_miner_calibration, retire_miner
from factory.services.mining import mine_record, population
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import (
    SESSION_M1,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_exploratory,
    mine_row,
    miner_actor,
)


def _regime(size: int) -> MinerRegime:
    return MinerRegime(2, size, 0.8, 0.9)


@pytest.mark.parametrize(
    ("mode", "declared", "pop", "expected"),
    [
        (RigorMode.EXPLORATORY, 3, 12, 3),
        (RigorMode.PILOT, 3, 12, 5),
        (RigorMode.PILOT, 8, 12, 8),
        (RigorMode.SYSTEMATIC, 3, 12, 10),
        (RigorMode.SYSTEMATIC, 20, 12, 12),
        (RigorMode.PILOT, 3, 4, 4),
    ],
)
def test_size_respects_floor_by_mode(
    mode: RigorMode, declared: int, pop: int, expected: int
) -> None:
    assert sample_size(mode, _regime(declared), pop) == expected


def test_thresholds_are_raised_to_the_floor() -> None:
    low = MinerRegime(2, 10, 0.5, 0.5)
    assert thresholds(RigorMode.PILOT, low) == (0.8, 0.9)
    assert thresholds(RigorMode.SYSTEMATIC, low) == (0.9, 0.95)
    assert thresholds(RigorMode.EXPLORATORY, low) == (0.5, 0.5)
    high = MinerRegime(2, 10, 0.99, 0.99)
    assert thresholds(RigorMode.SYSTEMATIC, high) == (0.99, 0.99)


def test_draw_in_pilot_applies_the_floor(
    project: Project, agent: Actor, human: Actor, world
) -> None:
    list_miner(project, agent, replace(method_vision(), regime=_regime(3)))
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=7)
    assert len(drawn.units) == 5 and drawn.population == len(world)
    stored = calibration_of(project, VISION_NAME, 1)
    assert stored is not None and stored.calibration_id == drawn.calibration_id
    assert tuple(u.work_id for u in stored.units) == tuple(u.work_id for u in drawn.units)


def test_units_exclude_production_mined_units(
    project: Project, agent: Actor, human: Actor, world
) -> None:
    list_miner(project, agent)
    worker = miner_actor(SESSION_M1, "claude-opus-5-5")
    mined = []
    for _ in range(3):
        batch = mine_exploratory(project, worker, VISION_NAME, 1, PassLabel.A).batch
        assert batch is not None
        mine_record(project, worker, batch.task_id, [mine_row()], finish=True)
        mined.append(batch.records[0]["work_id"])
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=1)
    works = {u.work_id for u in drawn.units}
    assert not works & set(mined)
    assert drawn.population == len(world) - 3 and len(drawn.units) == len(world) - 3


def test_seed_reproduces_draw(project: Project, agent: Actor, human: Actor, world) -> None:
    spec = list_miner(project, agent, replace(method_vision(), regime=_regime(6)))
    candidates = list(population(project, spec.selector))
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=99)
    expected = draw_uniform(candidates, 6, 99, key=lambda unit: unit[0])
    assert [(u.work_id, u.conversion_id) for u in drawn.units] == expected
    assert drawn.random_seed == 99


def test_seed_out_of_range_refused(project: Project, agent: Actor, human: Actor, world) -> None:
    list_miner(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=2**32)
    assert raised.value.issues[0].field == "random_seed"
    assert calibration_of(project, VISION_NAME, 1) is None


def test_second_draw_refused(project: Project, agent: Actor, human: Actor, world) -> None:
    list_miner(project, agent)
    draw_miner_calibration(project, human, VISION_NAME, 1)
    with pytest.raises(FactoryValidationError) as raised:
        draw_miner_calibration(project, human, VISION_NAME, 1)
    assert raised.value.issues[0].field == "calibration"


def test_agent_cannot_draw(project: Project, agent: Actor, world) -> None:
    list_miner(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        draw_miner_calibration(project, agent, VISION_NAME, 1)
    assert raised.value.issues[0].field == "actor"
    assert calibration_of(project, VISION_NAME, 1) is None


def test_unlisted_and_retired_miners_refused(
    project: Project, agent: Actor, human: Actor, world
) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        draw_miner_calibration(project, human, VISION_NAME, 1)  # not registered
    assert raised.value.issues[0].field in ("miners", "protocol")
    list_miner(project, agent)
    retire_miner(project, agent, VISION_NAME, 1, "no longer wanted")
    with pytest.raises(FactoryValidationError) as raised:
        draw_miner_calibration(project, human, VISION_NAME, 1)
    assert raised.value.issues[0].field == "miner"


def test_rebuild_determinism(project: Project, agent: Actor, human: Actor, world) -> None:
    list_miner(project, agent)
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=5)
    before = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == before
    stored = calibration_of(project, VISION_NAME, 1)
    assert stored is not None
    assert stored.population_digest == drawn.population_digest
    assert stored.digest == drawn.digest
