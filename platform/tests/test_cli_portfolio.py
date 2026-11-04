"""`factory portfolio` and the human list of `factory status`."""

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.services.portfolio import Portfolio
from factory.services.project import init_project
from tests.helpers import SESSION, T0
from tests.portfolio_helpers import SCOPING_SLUG, TA_SLUG

runner = CliRunner()
AS_OF = "2026-11-05T09:00:00+00:00"


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def _two_idle_projects(root: Path) -> None:
    settings = Settings(root=root, user="obd")
    clock = FixedClock(T0)
    init_project(settings, "alpha", "pilot", session=SESSION, clock=clock)
    init_project(settings, "bravo", "exploratory", session=SESSION, clock=clock)


def test_markdown_is_the_default_output(tmp_path: Path) -> None:
    _two_idle_projects(tmp_path)
    result = runner.invoke(app, ["portfolio", "--as-of", AS_OF], env=_env(tmp_path))
    assert result.exit_code == 0
    assert result.stdout.startswith("# Portfolio\n\nAs of 2026-11-05T09:00:00Z. 2 projects.")
    assert "| alpha | pilot | scoping |" in result.stdout
    assert "Nothing is waiting on you." in result.stdout


def test_html_option_writes_the_file_and_refuses_a_directory(tmp_path: Path) -> None:
    _two_idle_projects(tmp_path)
    target = tmp_path / "out.html"
    ok = runner.invoke(
        app, ["portfolio", "--as-of", AS_OF, "--html", str(target)], env=_env(tmp_path)
    )
    assert ok.exit_code == 0
    first = target.read_text(encoding="utf-8")
    assert first.startswith("<!doctype html>") and "<script" not in first
    runner.invoke(app, ["portfolio", "--as-of", AS_OF, "--html", str(target)], env=_env(tmp_path))
    assert target.read_text(encoding="utf-8") == first

    bad = runner.invoke(
        app, ["portfolio", "--as-of", AS_OF, "--html", str(tmp_path)], env=_env(tmp_path)
    )
    assert bad.exit_code == 1
    assert "directory" in bad.stderr


def test_json_parses_into_the_model_and_is_stable(tmp_path: Path) -> None:
    _two_idle_projects(tmp_path)
    args = ["portfolio", "--json", "--as-of", AS_OF]
    first = runner.invoke(app, args, env=_env(tmp_path))
    assert first.exit_code == 0
    built = Portfolio.model_validate_json(first.stdout)
    assert built.generated_at == datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
    assert [row.slug for row in built.projects] == ["alpha", "bravo"]
    assert runner.invoke(app, args, env=_env(tmp_path)).stdout == first.stdout


def test_no_project_is_exit_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["portfolio"], env=_env(tmp_path))
    assert result.exit_code == 2


def test_exit_1_when_no_project_could_be_read(tmp_path: Path) -> None:
    _two_idle_projects(tmp_path)
    for log in tmp_path.glob("projects/*/events/*/*.jsonl"):
        with log.open("a", encoding="utf-8") as handle:
            handle.write("{not json\n")
    result = runner.invoke(app, ["portfolio", "--json", "--as-of", AS_OF], env=_env(tmp_path))
    assert result.exit_code == 1
    assert all(row["error"] for row in json.loads(result.stdout)["projects"])


def test_a_bad_as_of_is_refused(tmp_path: Path) -> None:
    _two_idle_projects(tmp_path)
    result = runner.invoke(app, ["portfolio", "--as-of", "yesterday"], env=_env(tmp_path))
    assert result.exit_code == 2


def test_portfolio_and_status_list_what_waits_on_the_human(portfolio_settings: Settings) -> None:
    env = _env(portfolio_settings.root)
    listed = runner.invoke(app, ["portfolio", "--as-of", AS_OF], env=env)
    assert listed.exit_code == 0
    assert f"### {TA_SLUG}" in listed.stdout
    assert "screening-disagreements (title-abstract)" in listed.stdout
    assert f"| {SCOPING_SLUG} | exploratory | scoping |" in listed.stdout

    status = runner.invoke(app, ["--project", TA_SLUG, "status"], env=env)
    assert status.exit_code == 0
    assert "waiting on you:" in status.stdout
    assert (
        f"factory --project {TA_SLUG} screen disagreements --stage title-abstract" in status.stdout
    )
