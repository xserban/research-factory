"""`factory miner register|list` and `factory mine status` (M-C, task 7)."""

# ruff: noqa: F811
import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mining.spec import spec_to_json
from factory.model.screening import PassLabel
from factory.services.context import Project
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_pass,
    mine_row,
    miner_actor,
    vision_result,
)

A, B = PassLabel.A, PassLabel.B
runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_register_and_list(settings: Settings, project: Project, tmp_path: Path) -> None:
    path = tmp_path / "miner.json"
    path.write_text(json.dumps(spec_to_json(vision_result())))
    code, out, err = _run(settings.root, "miner", "list")
    assert code == 0 and "no registered miners" in out, err
    code, out, err = _run(settings.root, "miner", "register", str(path))
    assert code == 0 and f"registered {VISION_NAME} version 1" in out, err
    code, out, err = _run(settings.root, "miner", "list")
    assert code == 0 and f"{VISION_NAME} version 1" in out and "by human, not listed" in out, err


def test_register_refuses_a_bad_file_and_writes_nothing(
    settings: Settings, project: Project, tmp_path: Path
) -> None:
    before = len(read_all(project.paths.events_dir, project.catalog))
    missing = tmp_path / "absent.json"
    code, _, err = _run(settings.root, "miner", "register", str(missing))
    assert code == 1 and "cannot read" in err
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(spec_to_json(vision_result(name="ml-benchmark"))))
    code, _, err = _run(settings.root, "miner", "register", str(bad))
    assert code != 0 and "name" in err
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_mine_status_prints_units_and_agreement(
    settings: Settings, project: Project, agent: Actor, world: list[str]
) -> None:
    code, out, _ = _run(settings.root, "mine", "status")
    assert code == 0 and "no listed miners" in out
    list_miner(project, agent, method_vision())
    worked = mine_pass(
        project, miner_actor(SESSION_M1, "claude-opus-5-5"), A, lambda w: [mine_row()]
    )
    mine_pass(project, miner_actor(SESSION_M2, "claude-sonnet-5-5"), B, lambda w: [mine_row()])
    code, out, err = _run(settings.root, "mine", "status")
    assert code == 0, err
    units = 2 * len(worked)
    assert f"{VISION_NAME} version 1: units {units} (closed {units}, open 0, stale 0)" in out
    assert "rows " + str(units) in out and "agreement 1.00" in out
