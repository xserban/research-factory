"""`factory miner add FILE`: validate, register, list and print the page (IDEA-51)."""

# ruff: noqa: F811
import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.reader import read_all
from factory.mining.spec import spec_to_json
from factory.services.context import Project
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.miner_helpers import VISION_NAME, method_vision

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "miner-add.json"
    body = {"spec": spec_to_json(method_vision()), "use": {"dual_extract_sample": 0.5}}
    path.write_text(json.dumps(body))
    return path


def test_add_check_then_add(
    settings: Settings, project: Project, world: list[str], tmp_path: Path
) -> None:
    path = _file(tmp_path)
    before = len(read_all(project.paths.events_dir, project.catalog))
    code, out, err = _run(settings.root, "miner", "add", str(path), "--check")
    assert code == 0 and "would register" in out and "would list" in out, err
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    code, out, err = _run(settings.root, "miner", "add", str(path))
    assert code == 0, err
    assert f"registered {VISION_NAME} version 1" in out and "listed in the protocol" in out
    assert f"miners/{VISION_NAME}.html" in out
    code, out, err = _run(settings.root, "miner", "list")
    assert code == 0 and "listed" in out and "not listed" not in out, err


def test_add_refuses_a_bad_file_and_writes_nothing(
    settings: Settings, project: Project, world: list[str], tmp_path: Path
) -> None:
    before = len(read_all(project.paths.events_dir, project.catalog))
    code, _, err = _run(settings.root, "miner", "add", str(tmp_path / "absent.json"))
    assert code == 1 and "cannot read" in err
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"spec": spec_to_json(method_vision(name="ml-benchmark"))}))
    code, _, err = _run(settings.root, "miner", "add", str(bad))
    assert code != 0 and "name" in err
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
