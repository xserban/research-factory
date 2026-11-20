"""`factory dedup pairs` and `factory dedup pair`: the human gate `dedup.version_pair` is reachable
from the CLI, listed for reading and decided only by a human (restores IDEA-56 B5)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.services.access import TOOL_PERMISSIONS, Permission
from factory.services.context import Project
from tests.cli_helpers import _env

runner = CliRunner()


def run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_pairs_lists_and_pair_refuses_unknown_works(settings: Settings, project: Project) -> None:
    code, out, err = run(settings.root, "dedup", "pairs")
    assert code == 0, err
    assert "no candidate pairs" in out
    code, _, err = run(
        settings.root, "dedup", "pair", "w_a", "w_b", "same", "--rationale", "same paper"
    )
    assert code == 1 and "unknown work" in err


def test_pair_commands_are_registered_as_gated_acts() -> None:
    assert TOOL_PERMISSIONS["cli:dedup pair"] is Permission.HUMAN_CONFIRM
    assert TOOL_PERMISSIONS["cli:dedup pairs"] is Permission.PROJECT_READ
