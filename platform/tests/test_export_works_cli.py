# ruff: noqa: F811, F401
"""`factory export works` (IDEA-87): selection by layer, ids or file; output a directory or zip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.cli.main import app
from factory.config import Settings
from factory.services import work_layers
from factory.services.context import Project
from tests.cli_helpers import _cli_env, runner
from tests.test_export_works import _event_files, two


def test_ids_export_to_a_directory_and_say_what_was_skipped(
    settings: Settings, project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    before = _event_files(project)
    out = tmp_path / "out"
    done = runner.invoke(
        app,
        ["export", "works", "--ids", f"{two[0]},{two[1]}", "--out", str(out)],
        env=_cli_env(settings.root),
    )
    assert done.exit_code == 0, done.stderr + done.stdout
    assert "1 exported, 1 skipped, 0 withheld" in done.stdout
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["selection"] == "ids" and len(manifest["works"]) == 1
    assert _event_files(project) == before


def test_layer_and_file_selections(
    settings: Settings,
    project: Project,
    two: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layer = work_layers.WorkLayer(layer="core", source="moved", scheme_version=1, miner_layer=None)
    monkeypatch.setattr(work_layers, "layers_of", lambda p: {two[0]: layer})
    env = _cli_env(settings.root)
    by_layer = runner.invoke(
        app, ["export", "works", "--layer", "core", "--out", str(tmp_path / "a.zip")], env=env
    )
    assert by_layer.exit_code == 0, by_layer.stderr
    listing = tmp_path / "ids.txt"
    listing.write_text(f"# x\n{two[0]}\n", encoding="utf-8")
    by_file = runner.invoke(
        app, ["export", "works", "--from-file", str(listing), "--out", str(tmp_path / "b")], env=env
    )
    assert by_file.exit_code == 0, by_file.stderr
    assert json.loads((tmp_path / "b" / "manifest.json").read_text())["selection"].startswith(
        "ids from file"
    )


def test_exactly_one_selection_is_required_and_caps_are_errors(
    settings: Settings, project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    env = _cli_env(settings.root)
    none = runner.invoke(app, ["export", "works", "--out", str(tmp_path / "o")], env=env)
    assert none.exit_code == 1 and "selection:" in none.stderr
    both = runner.invoke(
        app,
        ["export", "works", "--layer", "core", "--ids", two[0], "--out", str(tmp_path / "o")],
        env=env,
    )
    assert both.exit_code == 1 and "selection:" in both.stderr
    capped = runner.invoke(
        app,
        [
            "export",
            "works",
            "--ids",
            f"{two[0]},{two[1]}",
            "--max-works",
            "1",
            "--out",
            str(tmp_path / "o"),
        ],
        env=env,
    )
    assert capped.exit_code == 1 and "cap is 1" in capped.stderr
    assert not (tmp_path / "o").exists()


def test_pdfs_flag_is_reported(
    settings: Settings, project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    done = runner.invoke(
        app,
        ["export", "works", "--ids", two[0], "--pdfs", "--out", str(tmp_path / "o")],
        env=_cli_env(settings.root),
    )
    assert done.exit_code == 0, done.stderr
    assert "without a PDF: 1" in done.stdout
