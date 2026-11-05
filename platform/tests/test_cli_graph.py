"""The `factory graph` commands (plan G2-D, task 5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.lineage import graph_export
from tests.lineage_graph_helpers import stand_in_basis, write_fixture
from tests.test_cli import _env

runner = CliRunner()
P9, P1 = "rf:p9-00000009", "rf:p1-00000001"


@pytest.fixture
def gp(project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch) -> Project:
    stand_in_basis(monkeypatch)
    write_fixture(project, agent)
    return project


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_build_and_status_print_counts_naming_the_filter(settings: Settings, gp: Project) -> None:
    for command in ("build", "status"):
        code, out, err = _run(settings.root, "graph", command)
        assert code == 0, err
        assert "filter:" in out and "cites" in out and "paper-external" in out


def test_query_path_prints_statuses(settings: Settings, gp: Project) -> None:
    code, out, err = _run(settings.root, "graph", "query", "path", "--node", P9, "--target", P1)
    assert code == 0, err
    assert f"{P9} -> " in out and "stated" in out and "filter:" in out


def test_query_options_and_errors(settings: Settings, gp: Project) -> None:
    code, out, _ = _run(
        settings.root,
        "graph",
        "query",
        "ancestors",
        "--node",
        P9,
        "--depth",
        "1",
        "--include-stale",
    )
    assert code == 0 and "depth 1" in out
    code, _, err = _run(settings.root, "graph", "query", "ancestors")
    assert code != 0 and "node" in err
    code, _, err = _run(settings.root, "graph", "query", "bogus", "--node", P9)
    assert code != 0 and "unknown query" in err


def test_export_equals_the_service_and_writes_a_file(
    settings: Settings, gp: Project, tmp_path: Path
) -> None:
    code, out, err = _run(settings.root, "graph", "export", "--format", "dot")
    assert code == 0, err
    assert out == graph_export(gp, "dot")
    target = tmp_path / "graph.json"
    code, out, err = _run(
        settings.root,
        "graph",
        "export",
        "--format",
        "json",
        "--include-inferred",
        "--out",
        str(target),
    )
    assert code == 0, err
    assert target.read_text().endswith("}\n") and '"include_inferred":true' in target.read_text()
    code, out, err = _run(
        settings.root, "graph", "export", "--query", "ancestors", "--node", P9, "--depth", "8"
    )
    assert code == 0 and P9 in out
    code, _, err = _run(settings.root, "graph", "export", "--format", "svg")
    assert code != 0
