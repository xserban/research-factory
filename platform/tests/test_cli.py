import json
import re
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.model.search import QueryKind, QuerySpec
from factory.services.project import init_project
from factory.services.search import register_query, run_query
from factory.sources.registry import SourceFactory
from tests.helpers import FAKE_PAGES, SESSION, FakeSource

runner = CliRunner()


def _env(root: Path) -> dict[str, str | None]:
    # FACTORY_PROJECT is cleared so a developer's shell cannot leak into the test.
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def test_init_status_rebuild(tmp_path: Path) -> None:
    env = _env(tmp_path)
    init = runner.invoke(app, ["init", "demo", "--mode", "pilot"], env=env)
    assert init.exit_code == 0
    assert init.stdout == "initialised demo (pilot)\n"

    status = runner.invoke(app, ["status", "--json"], env=env)
    assert status.exit_code == 0
    st = json.loads(status.stdout)
    assert st["slug"] == "demo" and st["events_total"] == 1

    out = runner.invoke(app, ["rebuild"], env=env)
    assert out.exit_code == 0
    assert re.fullmatch(r"state sha256:[0-9a-f]{64}\n", out.stdout)


def test_rebuild_output_is_stable(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "demo"], env=env)
    first = runner.invoke(app, ["rebuild"], env=env)
    second = runner.invoke(app, ["rebuild"], env=env)
    assert first.exit_code == 0 and second.exit_code == 0
    assert first.stdout == second.stdout


def test_init_invalid_slug_exit_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "Bad"], env=_env(tmp_path))
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "slug:" in result.stderr
    assert not (tmp_path / "projects").exists()


def test_invalid_user_exit_1(tmp_path: Path) -> None:
    env = {"FACTORY_ROOT": str(tmp_path), "FACTORY_USER": "Bad User", "FACTORY_PROJECT": None}
    result = runner.invoke(app, ["init", "demo"], env=env)
    assert result.exit_code == 1
    assert "user:" in result.stderr


def test_ambiguous_project_exit_2(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "a"], env=env)
    runner.invoke(app, ["init", "b"], env=env)
    result = runner.invoke(app, ["status"], env=env)
    assert result.exit_code == 2
    assert result.stderr.strip() == "several projects: a, b; pass --project"


def test_no_project_exit_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["rebuild"], env=_env(tmp_path))
    assert result.exit_code == 2
    assert result.stderr.strip() == "no project; run factory init"


def test_explicit_project_option(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "a"], env=env)
    runner.invoke(app, ["init", "b"], env=env)
    result = runner.invoke(app, ["--project", "b", "status", "--json"], env=env)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["slug"] == "b"


def test_unknown_explicit_project_exit_1(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "a"], env=env)
    result = runner.invoke(app, ["--project", "ghost", "status"], env=env)
    assert result.exit_code == 1
    assert result.stderr.strip() == "unknown project: ghost"


def test_status_human_output(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "demo", "--mode", "systematic"], env=env)
    result = runner.invoke(app, ["status"], env=env)
    assert result.exit_code == 0
    assert result.stdout == (
        "project: demo\n"
        "rigor mode: systematic\n"
        "events: 1\n"
        "tasks: open 0 / claimed 0 / expired 0 / completed 0\n"
        "works: 0 (records 0, merges 0)\n"
        "searches: 0 runs (complete 0 / partial 0 / failed 0 / interrupted 0)\n"
    )


def test_status_shows_works_searches_and_shortfalls(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, user="obd")
    clock = FixedClock(datetime(2026, 10, 31, 12, 0, tzinfo=UTC))
    project = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    # The fake source reports 5 records and delivers 3: the shortfall must be shown.
    sources: dict[str, SourceFactory] = {"fake": lambda _s, _c: FakeSource(FAKE_PAGES, reported=5)}
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="attention")
    query_id = register_query(project, project.human_actor(), spec, sources=sources)
    summary = run_query(project, query_id, sources=sources)

    result = runner.invoke(app, ["status"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert result.stdout.splitlines()[-3:] == [
        "works: 3 (records 3, merges 0)",
        "searches: 1 runs (complete 1 / partial 0 / failed 0 / interrupted 0)",
        f"shortfall: {summary.run_id} fake 3/5 \u2014 2 of 5 reported not delivered",
    ]


def test_serve_is_registered(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--help"], env=_env(tmp_path))
    assert result.exit_code == 0
    for command in ("init", "rebuild", "status", "serve"):
        assert command in result.stdout
