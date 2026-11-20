"""`factory tour`: the stage list with progress, one stage card, json; read-only."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.learn.stages import STAGES
from factory.services.context import Project
from tests.cli_helpers import _env

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout


def test_tour_without_a_project_lists_the_stages_with_unknown_progress(tmp_path: Path) -> None:
    code, out = _run(tmp_path, "tour")
    assert code == 0, out
    assert f"{len(STAGES)}. {STAGES[-1].title} [unknown]" in out


def test_tour_with_a_project_shows_its_progress(project: Project) -> None:
    code, out = _run(project.settings.root, "--project", project.paths.slug, "tour")
    assert code == 0, out
    assert f"1. {STAGES[0].title} [not-started]" in out


def test_one_stage_card_and_json(project: Project) -> None:
    root, slug = project.settings.root, project.paths.slug
    code, out = _run(root, "--project", slug, "tour", "--stage", "3")
    assert code == 0, out
    assert STAGES[2].title in out and "done looks like:" in out
    code, out = _run(root, "--project", slug, "tour", "--stage", "3", "--format", "json")
    assert json.loads(out)["id"] == STAGES[2].id
    code, out = _run(root, "--project", slug, "tour", "--format", "json")
    assert [s["id"] for s in json.loads(out)] == [s.id for s in STAGES]


def test_a_stage_out_of_range_is_refused(tmp_path: Path) -> None:
    code, _ = _run(tmp_path, "tour", "--stage", "10")
    assert code != 0
