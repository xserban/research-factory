"""Shared CLI test helpers: the runner and the environment of a project root."""

from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _env(root: Path) -> dict[str, str | None]:
    # FACTORY_PROJECT is cleared so a developer's shell cannot leak into the test.
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def _cli_env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}
