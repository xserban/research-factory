"""Smoke tests of `factory feed` (slice 4c, F8): the group parses, calls the service and formats.

The service rules are tested in `test_feed_service.py`; these check the command surface, its exit
codes and that refusals print their issues and write nothing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.services.context import open_project
from factory.services.project import init_project
from tests.helpers import SESSION, T0
from tests.test_feed_index import _record

runner = CliRunner()
SLUG = "alpha"


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def _project(root: Path) -> None:
    settings = Settings(root=root, user="obd")
    init_project(settings, SLUG, "pilot", session=SESSION, clock=FixedClock(T0))


def _fetched_but_not_ranked(root: Path, entry_id: str) -> None:
    """Record one fetched entry and no ranking, so the entry is known but never shown."""
    project = open_project(
        Settings(root=root, user="obd"), SLUG, session=SESSION, clock=FixedClock(T0)
    )
    entries: Any = [{"id": entry_id, "version": "v1", "title": "Fetched paper"}]
    payload = {
        "fetch_id": "fdf_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
        "categories": ["cs.AI"],
        "window_from": "2026-11-10",
        "window_to": "2026-11-11",
        "raw_blobs": [],
        "entries_blob": project.blobs.put_json(entries),
        "count": 1,
        "held_count": 0,
        "complete": True,
    }
    _record(project, "feed.fetched", payload, project.system_actor())


def test_configure_then_status(tmp_path: Path) -> None:
    _project(tmp_path)
    configured = runner.invoke(
        app,
        [
            "feed",
            "configure",
            "--project",
            SLUG,
            "--categories",
            "cs.AI",
            "--categories",
            "cs.LG,cs.MA",
            "--shown",
            "30",
            "--explore",
            "0.1",
        ],
        env=_env(tmp_path),
    )
    assert configured.exit_code == 0, configured.output
    assert "feed configured" in configured.output

    status = runner.invoke(app, ["feed", "status", "--project", SLUG], env=_env(tmp_path))
    assert status.exit_code == 0, status.output
    assert "categories: cs.AI, cs.LG, cs.MA" in status.output
    assert "shown per cycle: 30" in status.output


def test_status_before_configuration_says_so(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(app, ["feed", "status", "--project", SLUG], env=_env(tmp_path))
    assert result.exit_code == 0
    assert "feed not configured" in result.output


def test_invalid_configuration_prints_issues_and_exits_two(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(
        app,
        ["feed", "configure", "--project", SLUG, "--categories", "cs.AI", "--shown", "0"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "shown_per_cycle" in result.output
    assert "feed configured" not in result.output


def test_show_without_ranking_says_why(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(app, ["feed", "show", "--project", SLUG], env=_env(tmp_path))
    assert result.exit_code == 0
    assert "no ranking yet" in result.output


def test_react_to_an_unshown_entry_is_refused(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(
        app,
        ["feed", "react", "--project", SLUG, "2611.01234", "like"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "entry_id: unknown" in result.output
    assert "reacted" not in result.output


def test_react_to_a_fetched_entry_not_in_a_ranking_is_refused(tmp_path: Path) -> None:
    _project(tmp_path)
    _fetched_but_not_ranked(tmp_path, "2611.01234")
    result = runner.invoke(
        app,
        ["feed", "react", "--project", SLUG, "2611.01234", "like"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "entry_id: not-shown" in result.output
    assert "reacted" not in result.output


def test_react_with_an_unknown_reaction_is_refused(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(
        app,
        ["feed", "react", "--project", SLUG, "2611.01234", "love"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "reaction:" in result.output


def test_send_of_an_unshown_entry_is_refused(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(
        app,
        ["feed", "send", "--project", SLUG, "2611.01234"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "entry_id: unknown" in result.output
    assert "sent " not in result.output


def test_send_of_a_fetched_entry_not_in_a_ranking_is_refused(tmp_path: Path) -> None:
    _project(tmp_path)
    _fetched_but_not_ranked(tmp_path, "2611.01234")
    result = runner.invoke(
        app,
        ["feed", "send", "--project", SLUG, "2611.01234"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "entry_id: not-shown" in result.output
    assert "sent " not in result.output


def test_send_with_a_blank_note_is_refused(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(
        app,
        ["feed", "send", "--project", SLUG, "2611.01234", "--note", "   "],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "note:" in result.output


def test_run_refuses_project_and_all_together(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(app, ["feed", "run", "--project", SLUG, "--all"], env=_env(tmp_path))
    assert result.exit_code == 2
    assert "exclusive" in result.output


def test_run_dry_run_of_an_unconfigured_project_exits_two(tmp_path: Path) -> None:
    _project(tmp_path)
    result = runner.invoke(app, ["feed", "run", "--project", SLUG, "--dry-run"], env=_env(tmp_path))
    assert result.exit_code == 2
