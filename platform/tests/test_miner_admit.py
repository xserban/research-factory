"""`factory miner admit`: the human act that admits a calibrated miner as evidence (M-D)."""

# ruff: noqa: F811
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.miners import admit_miner, retire_miner
from factory.services.protocol import current_protocol
from tests.cli_helpers import _env
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_calibration_helpers import PROPOSER, calibrated_world, run_calibration
from tests.miner_helpers import VISION_NAME

runner = CliRunner()


def _evidence(project: Project) -> bool:
    current = current_protocol(project)
    assert current is not None and current.spec.miners
    return current.spec.miners[0].evidence


def test_a_human_admits_a_calibrated_miner(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    admit_miner(project, human, VISION_NAME)
    assert _evidence(project)
    admit_miner(project, human, VISION_NAME)  # again: nothing changes, nothing is refused


def test_an_agent_cannot_admit(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    for actor in (agent, PROPOSER):
        with pytest.raises(FactoryValidationError) as raised:
            admit_miner(project, actor, VISION_NAME)
        assert raised.value.issues[0].field == "actor"
    assert not _evidence(project)


def test_admission_needs_a_listed_and_calibrated_miner(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    with pytest.raises(FactoryValidationError):
        admit_miner(project, human, VISION_NAME)  # no protocol listing at all
    cal = calibrated_world(project, agent, human)
    with pytest.raises(FactoryValidationError) as raised:
        admit_miner(project, human, VISION_NAME)  # listed, calibrating
    assert raised.value.issues[0].field == "miners.0.evidence"
    with pytest.raises(FactoryValidationError) as raised:
        admit_miner(project, human, "m-not-listed")
    assert raised.value.issues[0].field == "miners"
    run_calibration(project, miss=tuple(cal.works[:2]))  # failed
    with pytest.raises(FactoryValidationError) as raised:
        admit_miner(project, human, VISION_NAME)
    assert raised.value.issues[0].field == "miners.0.evidence"
    assert not _evidence(project)


def test_a_retired_calibrated_miner_cannot_be_admitted(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    retire_miner(project, agent, VISION_NAME, 1, "replaced")
    with pytest.raises(FactoryValidationError):
        admit_miner(project, human, VISION_NAME)
    assert not _evidence(project)


def test_cli_admit(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    root: Path = settings.root
    calibrated_world(project, agent, human)
    code = runner.invoke(app, ["miner", "admit", VISION_NAME], env=_env(root))
    assert code.exit_code == 1 and "miners.0.evidence" in code.stderr  # not calibrated yet
    run_calibration(project)
    code = runner.invoke(app, ["miner", "admit", VISION_NAME], env=_env(root))
    assert code.exit_code == 0 and f"admitted {VISION_NAME}" in code.stdout, code.stderr
    assert _evidence(project)
    code = runner.invoke(app, ["miner", "admit", "m-not-listed"], env=_env(root))
    assert code.exit_code == 1 and "miners" in code.stderr
