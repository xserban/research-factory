"""`factory digest` and `factory conclusions` (living-D, task 5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.search import list_works
from factory.services.watch import watch_run
from tests.helpers import SESSION, SourcesFor
from tests.living_helpers import filler, screening_watch_setup
from tests.test_cli import _env
from tests.watch_helpers import ScriptedSource, adapters, by_text

runner = CliRunner()


def _cli(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _digest_events(project: Project) -> list[Any]:
    return [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "digest.generated"
    ]


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    screening_watch_setup(project, agent, human, mock_sources)
    source = ScriptedSource(by_text({"attention": [filler(3)]}))
    assert watch_run(project, sources=adapters(source), trigger="scheduler") is not None
    return project


def test_cli_digest_writes_md_and_json(ready: Project, settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "out"
    code, text, _ = _cli(settings.root, "digest", "--project", "demo")
    assert code == 0 and text.startswith("# Digest") and "Watch study" in text
    code, as_json, _ = _cli(settings.root, "digest", "--project", "demo", "--format", "json")
    assert code == 0 and json.loads(as_json)["projects"][0]["slug"] == "demo"
    code, _, _ = _cli(
        settings.root, "digest", "--project", "demo", "--format", "both", "--out", str(out)
    )
    assert code == 0
    assert (out / "digest.md").read_text().startswith("# Digest")
    assert json.loads((out / "digest.json").read_text())["digest_id"] is None
    assert _digest_events(ready) == []  # without --record nothing is written


def test_cli_digest_record_writes_one_event_per_project(
    ready: Project, settings: Settings, tmp_path: Path, clock: Any
) -> None:
    init_project(settings, "second", "pilot", session=SESSION, clock=clock)
    out = tmp_path / "out"
    code, _, err = _cli(
        settings.root, "digest", "--all", "--record", "--format", "md", "--out", str(out)
    )
    assert code == 0, err
    [event] = _digest_events(ready)
    digest_id = event.payload["digest_id"]
    assert (out / f"{digest_id}.md").read_text().startswith(f"# Digest {digest_id}")
    other = [
        e
        for e in read_all(settings.root / "projects" / "second" / "events", ready.catalog)
        if e.type == "digest.generated"
    ]
    assert [e.payload["digest_id"] for e in other] == [digest_id]
    # The next digest starts where this one ended.
    code, text, _ = _cli(settings.root, "digest", "--project", "demo", "--format", "json")
    assert json.loads(text)["projects"][0]["since_event"] == event.payload["cutoff_event"]
    code, _, err = _cli(settings.root, "digest", "--all", "--project", "demo")
    assert code == 2 and "exclusive" in err


def test_cli_conclusions_register_and_diff(ready: Project, settings: Settings) -> None:
    work = next(w.id for w in list_works(ready))
    code, out, err = _cli(
        settings.root,
        "--project",
        "demo",
        "conclusions",
        "register",
        "--statement",
        "A linear mechanism suffices.",
        "--basis",
        f"work:{work}",
    )
    assert code == 0, err
    cid = out.split()[-1]
    assert cid.startswith("ccl_")
    code, out, _ = _cli(settings.root, "--project", "demo", "conclusions", "status")
    assert code == 0 and cid in out and "A linear mechanism suffices." in out and "new" in out
    code, _, _ = _cli(settings.root, "--project", "demo", "living", "snapshot")
    assert code == 0
    code, out, _ = _cli(settings.root, "--project", "demo", "conclusions", "diff")
    assert code == 0 and f"{cid}  unchanged" in out and "A linear" not in out
    code, _, err = _cli(
        settings.root, "--project", "demo", "conclusions", "diff", "--since", "snp_x"
    )
    assert code == 1 and "since" in err
    code, _, err = _cli(
        settings.root,
        "--project",
        "demo",
        "conclusions",
        "register",
        "--statement",
        "Unfounded.",
        "--basis",
        "work:rf:unknown-deadbeef",
    )
    assert code == 1 and "basis" in err
    code, _, err = _cli(
        settings.root,
        "--project",
        "demo",
        "conclusions",
        "register",
        "--statement",
        "Bad predicate.",
        "--basis",
        f"work:{work}",
        "--predicate",
        '{"kind": "best-in-group"}',
    )
    assert code == 2 and "predicate" in err
    code, _, _ = _cli(
        settings.root, "--project", "demo", "conclusions", "retire", cid, "--reason", "withdrawn"
    )
    assert code == 0
    code, out, _ = _cli(settings.root, "--project", "demo", "conclusions", "status")
    assert cid not in out
