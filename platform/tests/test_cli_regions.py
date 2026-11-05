"""The `factory regions` commands (slice 3d, plan Regions-A, task 6)."""

# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from tests.cli_helpers import _env
from tests.region_helpers import RWorld, region_project, screened  # noqa: F401

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _rules(tmp_path: Path) -> Path:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps({"include": [{"kind": "corpus", "outcome": "included", "stage": "full-text"}]})
    )
    return path


def _define(settings: Settings, tmp_path: Path) -> str:
    code, out, err = _run(
        settings.root,
        "regions",
        "define",
        "--name",
        "attention works",
        "--kind",
        "region",
        "--definition",
        "Works on attention.",
        "--rules",
        str(_rules(tmp_path)),
    )
    assert code == 0, err
    return out.split()[-1]


def test_cli_define_and_snapshot(
    settings: Settings, region_project: RWorld, tmp_path: Path
) -> None:
    region = _define(settings, tmp_path)
    assert region.startswith("reg_")
    code, out, err = _run(settings.root, "regions", "snapshot", region)
    assert code == 0, err
    version = out.split()[-1]
    assert version.startswith("R@")
    code, out, _ = _run(settings.root, "regions", "list")
    assert region in out and version in out and f"{len(region_project.included)} work" in out
    code, out, _ = _run(settings.root, "regions", "show", region, "--members", "--limit", "2")
    assert code == 0 and out.count("  work ") == 2
    code, out, _ = _run(settings.root, "regions", "show", version)
    assert "latest" in out and "unreviewed" in out
    code, _, err = _run(settings.root, "regions", "snapshot", "reg_01JZ9Q3K5M7N8P0R2S4T6V8WZZ")
    assert code == 1 and "region-unknown" in err


def test_cli_rules_file_is_validated(
    settings: Settings, region_project: RWorld, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"include": []}')
    code, _, err = _run(
        settings.root, "regions", "define", "--name", "n", "--kind", "region",
        "--definition", "d", "--rules", str(bad),
    )  # fmt: skip
    assert code == 2 and "--rules" in err


def test_cli_review_human_actor(settings: Settings, region_project: RWorld, tmp_path: Path) -> None:
    region = _define(settings, tmp_path)
    _, out, _ = _run(settings.root, "regions", "snapshot", region)
    version = out.split()[-1]
    code, _, _ = _run(settings.root, "regions", "review", version)
    assert code == 2  # one of --reviewed and --wrong
    code, _, err = _run(settings.root, "regions", "review", version, "--wrong")
    assert code == 1 and "note" in err
    code, out, err = _run(settings.root, "regions", "review", version, "--reviewed")
    assert code == 0, err
    with region_project.project.index.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(
            text(
                "SELECT e.actor_kind, r.state, r.self_reviewed FROM region_reviews r "
                "JOIN events e ON e.id = r.event_id"
            )
        ).one()
    assert tuple(row) == ("human", "reviewed", 1)
    _, out, _ = _run(settings.root, "regions", "list")
    assert "reviewed" in out


def test_cli_diff_counts(settings: Settings, region_project: RWorld, tmp_path: Path) -> None:
    region = _define(settings, tmp_path)
    _, out, _ = _run(settings.root, "regions", "snapshot", region)
    first = out.split()[-1]
    code, _, err = _run(settings.root, "regions", "add", region, "rf:added-00000001")
    assert code == 0, err
    removed = region_project.included[0]
    assert _run(settings.root, "regions", "add", region, removed, "--remove")[0] == 0
    _, out, _ = _run(settings.root, "regions", "snapshot", region)
    second = out.split()[-1]
    assert first != second
    code, out, err = _run(settings.root, "regions", "diff", first, second)
    assert code == 0, err
    assert out.splitlines()[0] == "added 1  removed 1"
    assert "+ work rf:added-00000001" in out and f"- work {removed}" in out
    code, _, err = _run(settings.root, "regions", "diff", first, "R@" + "0" * 8)
    assert code == 1 and "version-unknown" in err
