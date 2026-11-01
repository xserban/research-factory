import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.protocol import PressElement, PressFinding
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.protocol import current_protocol, press_review
from factory.services.question import current_question
from factory.services.search import register_query, run_query
from factory.services.seeds import add_seeds, split_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import (
    FAKE_PAGES,
    SESSION,
    FakeSource,
    openalex_item,
    ready_protocol,
    record_pilot_question,
)

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
        "question: none\n"
        "protocol: none\n"
        "seeds: 0 positive (not split), 0 negative, 0 unresolved\n"
        "tasks: open 0 / claimed 0 / expired 0 / completed 0\n"
        "works: 0 (records 0, merges 0)\n"
        "searches: 0 runs (complete 0 / partial 0 / failed 0 / interrupted 0)\n"
    )


def test_status_shows_works_searches_and_shortfalls(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, user="obd")
    clock = FixedClock(datetime(2026, 10, 31, 12, 0, tzinfo=UTC))
    project = init_project(settings, "demo", "exploratory", session=SESSION, clock=clock)
    # The fake source reports 5 records and delivers 3: the shortfall must be shown.
    sources: dict[str, SourceFactory] = {
        "fake": SourceFactory(FakeSource.kinds, lambda _s, _c: FakeSource(FAKE_PAGES, reported=5))
    }
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


# --- Question, seeds, protocol: the human CLI (held-out roles are shown here only) ---


def _cli_env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def _seed_one(project: Project, agent: Actor, sources: Any, n: int, kind: SeedKind) -> None:
    spec = SeedSpec(kind=kind, cite=f"Paper {n}", doi=f"10.1000/p{n}")
    item = openalex_item(
        title=f"Paper {n}",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )
    add_seeds(project, agent, [spec], sources=sources(openalex=[item]))


def test_seeds_cli_shows_held_out_roles(
    project: Project, agent: Actor, mock_sources: Any, settings: Settings
) -> None:
    record_pilot_question(project, agent)
    for n in (1, 2, 3):
        _seed_one(project, agent, mock_sources, n, SeedKind.POSITIVE)
    _seed_one(project, agent, mock_sources, 9, SeedKind.NEGATIVE)
    drawn = split_seeds(project, random_seed=7)

    result = runner.invoke(app, ["seeds"], env=_cli_env(settings.root))
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["id", "kind", "role", "resolution", "check"]
    for held in drawn.held_out:
        [row] = [line for line in lines if line.startswith(held)]
        assert "held-out" in row
    for dev in drawn.development:
        [row] = [line for line in lines if line.startswith(dev)]
        assert "development" in row
    negative = next(line for line in lines if line.startswith("NEG01"))
    assert negative.split()[2] == "unsplit"


def test_seeds_split_and_explain_cli(
    project: Project, agent: Actor, mock_sources: Any, settings: Settings
) -> None:
    record_pilot_question(project, agent)
    for n in (1, 2, 3):
        _seed_one(project, agent, mock_sources, n, SeedKind.POSITIVE)
    env = _cli_env(settings.root)

    split = runner.invoke(app, ["seeds", "split", "--random-seed", "7"], env=env)
    assert split.exit_code == 0, split.stderr
    assert split.stdout == "split drawn with random seed 7\n"
    again = runner.invoke(app, ["seeds", "split"], env=env)
    assert again.exit_code == 1
    assert "already drawn" in again.stderr

    explain = runner.invoke(
        app,
        ["seeds", "explain", "SEED01", "--route", "citation-chase", "--reason", "Not indexed."],
        env=env,
    )
    assert explain.exit_code == 0, explain.stderr
    assert explain.stdout == "explained SEED01 (citation-chase)\n"


def test_confirm_press_cli(
    project: Project, agent: Actor, human: Actor, mock_sources: Any, settings: Settings
) -> None:
    protocol_id = ready_protocol(project, agent, human, mock_sources, press=False)
    finding = PressFinding(
        element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor"
    )
    review_id = press_review(project, agent, protocol_id, (finding,))
    env = _cli_env(settings.root)

    wrong_count = runner.invoke(
        app, ["protocol", "confirm-press", review_id, "--response", "a", "--response", "b"], env=env
    )
    assert wrong_count.exit_code == 1
    assert "responses" in wrong_count.stderr

    confirmed = runner.invoke(
        app, ["protocol", "confirm-press", review_id, "--response", "Accepted."], env=env
    )
    assert confirmed.exit_code == 0, confirmed.stderr
    assert confirmed.stdout == f"confirmed {review_id}\n"
    protocol = current_protocol(project)
    assert protocol is not None and protocol.press == "confirmed"


def test_status_shows_question_protocol_and_seeds(
    project: Project, agent: Actor, human: Actor, mock_sources: Any, settings: Settings
) -> None:
    env = _cli_env(settings.root)
    empty = runner.invoke(app, ["status"], env=env).stdout.splitlines()
    assert "question: none" in empty
    assert "protocol: none" in empty
    assert "seeds: 0 positive (not split), 0 negative, 0 unresolved" in empty

    protocol_id = ready_protocol(project, agent, human, mock_sources)
    question = current_question(project)
    assert question is not None
    lines = runner.invoke(app, ["status"], env=env).stdout.splitlines()
    assert f"question: {question.question_id}" in lines
    assert f"protocol: {protocol_id} (ready, PRESS confirmed)" in lines
    assert "seeds: 3 positive (split drawn), 0 negative, 0 unresolved" in lines
