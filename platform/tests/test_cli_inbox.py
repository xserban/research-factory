"""`factory inbox` and `factory report discovery` (slice 4a): parse, call a service, print."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.services.context import open_project
from factory.services.discovery import discovery_report
from tests.helpers import SESSION
from tests.inbox_helpers import Keyed, link_item

runner = CliRunner()


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def test_inbox_round_trip(
    tmp_path: Path, settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path)
    assert runner.invoke(app, ["init", "demo", "--mode", "exploratory"], env=env).exit_code == 0
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})
    monkeypatch.setattr("factory.cli.main.default_sources", keyed.sources)

    added = runner.invoke(
        app,
        ["inbox", "add", "10.2000/S1", "2103.14030", "https://x.org/p", "--note", "Ana"],
        env=env,
    )
    assert added.exit_code == 1
    captured = [line.split()[1] for line in added.stdout.splitlines()]
    assert len(captured) == 2 and all(i.startswith("inb_") for i in captured)
    assert "unsupported-link" in added.stderr

    withdrawn = runner.invoke(
        app, ["inbox", "withdraw", captured[1], "--reason", "duplicate"], env=env
    )
    assert withdrawn.exit_code == 0, withdrawn.output

    resolved = runner.invoke(app, ["inbox", "resolve", "--item", captured[0]], env=env)
    assert resolved.exit_code == 0, resolved.output
    assert resolved.stdout.split()[:2] == [captured[0], "new"]

    listed = runner.invoke(app, ["inbox", "list", "--status", "resolved"], env=env)
    assert listed.exit_code == 0
    assert listed.stdout.startswith(f"{captured[0]}  resolved  new  doi:10.2000/s1  human")

    as_json = runner.invoke(app, ["report", "discovery", "--json"], env=env)
    assert as_json.exit_code == 0, as_json.output
    project = open_project(settings, "demo", session=SESSION, clock=clock)
    assert json.loads(as_json.stdout) == discovery_report(project).model_dump(mode="json")
    text = runner.invoke(app, ["report", "discovery"], env=env)
    assert "| supplied-human | 1 | 0 | 0 |" in text.stdout


def test_withdraw_needs_open_item(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "demo", "--mode", "exploratory"], env=env)
    out = runner.invoke(app, ["inbox", "withdraw", "inb_x", "--reason", "x"], env=env)
    assert out.exit_code == 1
    assert "item_id: not an open inbox item" in out.stderr
