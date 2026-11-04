"""`factory watch run|status|plan`: exit codes, `--all`, `--dry-run` (slice 4b, ruling 5)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.services import watch as watch_service
from factory.services.context import Project
from factory.services.project import init_project
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION, SourcesFor, ready_protocol
from tests.test_cli import _env
from tests.watch_helpers import ScriptedSource, adapters, by_text, record, watch_ready

runner = CliRunner()
A = [record("Alpha methods for sparse graphs", author="Ana Li", year=2021)]
B = [record("Beta bounds on federated drift", author="Bo Chen", year=2022)]


def _cli(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _use(monkeypatch: pytest.MonkeyPatch, source: ScriptedSource) -> None:
    mapping: Mapping[str, SourceFactory] = adapters(source)
    monkeypatch.setattr("factory.cli.main.default_sources", lambda: mapping)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    watch_ready(project, agent, human, mock_sources)
    return project


def test_cli_watch_run_due_exit_codes(
    ready: Project, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, ScriptedSource(by_text({"attention": [A], "transformers": [B]})))
    code, out, _ = _cli(settings.root, "watch", "run", "--project", "demo")
    assert code == 0 and "complete" in out and "2/2 queries complete" in out
    code, out, _ = _cli(settings.root, "watch", "run", "--project", "demo")
    assert code == 0 and out.strip() == "demo: nothing due"
    # Partial: a forced cycle whose source fails.
    _use(monkeypatch, ScriptedSource(lambda _n, _s: "fail"))
    code, out, _ = _cli(settings.root, "watch", "run", "--project", "demo", "--force")
    assert code == 1 and "failed" in out
    starts = [e for e in read_all(ready.paths.events_dir, ready.catalog)]
    assert [e.payload["trigger"] for e in starts if e.type == "watch.cycle_started"] == [
        "scheduler",
        "scheduler",
    ]


def test_cli_watch_exit_2_on_invalid_input(
    project: Project,
    settings: Settings,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_protocol(project, agent, human, mock_sources)  # ready, but no watch_plan
    _use(monkeypatch, ScriptedSource(lambda _n, _s: [[]]))
    before = _count(project)
    code, _, err = _cli(settings.root, "watch", "run", "--project", "demo")
    assert code == 2 and "watch_plan" in err
    code, _, err = _cli(settings.root, "watch", "run", "--all", "--project", "demo")
    assert code == 2 and "exclusive" in err
    assert _count(project) == before


def test_cli_all_continues_after_project_error(
    ready: Project,
    settings: Settings,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = init_project(settings, "alpha", "pilot", session=SESSION, clock=clock)
    watch_ready(other, agent, human, mock_sources)
    bare = init_project(settings, "bare", "exploratory", session=SESSION, clock=clock)
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    _use(monkeypatch, source)
    real = watch_service.watch_run

    def flaky(project: Project, **kwargs: object) -> object:
        if project.paths.slug == "alpha":
            raise RuntimeError("disk on fire")
        return real(project, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("factory.cli.main.watch_service.watch_run", flaky)
    code, out, _ = _cli(settings.root, "watch", "run", "--all", "--json")
    rows = {json.loads(line)["project"]: json.loads(line) for line in out.splitlines()}
    assert code == 1
    assert rows["alpha"]["result"] == "error" and "disk on fire" in rows["alpha"]["error"]
    assert rows["demo"]["result"] == "complete"
    assert rows["bare"]["result"] == "no watch_plan"
    assert _count(bare) == 1  # only project.created


def test_cli_dry_run_writes_nothing(
    ready: Project, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    _use(monkeypatch, source)
    before = _count(ready)
    code, out, _ = _cli(settings.root, "watch", "run", "--project", "demo", "--dry-run")
    assert code == 0 and "would run openalex" in out
    assert _count(ready) == before and source.specs == []


def test_cli_watch_status_and_plan(
    ready: Project, settings: Settings, monkeypatch: pytest.MonkeyPatch, clock: FixedClock
) -> None:
    code, out, _ = _cli(settings.root, "watch", "status", "--project", "demo")
    assert code == 0 and "openalex: full, every 7 d, due now" in out
    code, out, _ = _cli(settings.root, "watch", "status", "--project", "demo", "--json")
    assert code == 0 and json.loads(out)["sources"][0]["source"] == "openalex"
    code, out, _ = _cli(settings.root, "watch", "plan", "--project", "demo")
    assert code == 0 and json.loads(out)["sources"][0]["interval_days"] == 7
    clock.advance(timedelta(days=1))  # silence unused fixture lint without side effects


def test_cli_watch_plan_absent(project: Project, settings: Settings) -> None:
    code, _, err = _cli(settings.root, "watch", "plan", "--project", "demo")
    assert code == 1 and "no watch_plan" in err


def test_living_snapshot_command(ready: Project, tmp_path: Path) -> None:
    code, out, _ = _cli(ready.settings.root, "--project", "demo", "living", "snapshot")
    assert code == 0 and out.startswith("snapshot snp_")
    code, _, err = _cli(ready.settings.root, "--project", "demo", "living", "snapshot")
    assert code == 0, err


def test_living_prisma_update_command(ready: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, ScriptedSource(by_text({"attention": [A], "transformers": [B]})))
    root = ready.settings.root
    assert _cli(root, "watch", "run", "--project", "demo")[0] == 0
    assert _cli(root, "--project", "demo", "living", "snapshot")[0] == 0
    code, out, err = _cli(root, "--project", "demo", "living", "prisma-update", "--json")
    assert code == 0, err
    assert json.loads(out)["screened"] == 0
    code, out, _ = _cli(root, "--project", "demo", "report", "prisma", "--update", "last")
    assert code == 0 and "update flow" in out
    code, _, err = _cli(root, "--project", "demo", "living", "prisma-update", "--since", "snp_x")
    assert code == 1 and "since" in err
