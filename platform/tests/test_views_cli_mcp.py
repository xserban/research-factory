"""`view_onion` and `factory view onion` (slice 7b, plan V-A, task 5).

The tool is an agent path: refused to a session that has joined a pass, refused before a pass opens
(role-blind, one neutral message), the agent variant of every source, and scrubbed of held-out
identifiers without hiding any work. The command is the researcher's: complete.
"""

# ruff: noqa: F811

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.model.views import OnionFilter
from factory.services import onion
from factory.services.context import Project
from factory.services.onion import onion_view
from factory.services.views import to_json
from tests.cli_helpers import _env
from tests.helpers import open_session
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world  # noqa: F401
from tests.onion_helpers import A, B, F, write_graph
from tests.test_mcp_lineage import _session

runner = CliRunner()


@pytest.fixture
def og_closed(project: Project, monkeypatch: pytest.MonkeyPatch) -> Project:
    """The constructed graph, no screening pass opened yet."""
    write_graph(project)
    monkeypatch.setattr(onion, "included_works", lambda _p: list(F))
    return project


@pytest.fixture
def og(og_closed: Project) -> Project:
    """The same, after a screening pass has opened (`held_out_visible`)."""
    with og_closed.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO passes (stage, pass_label, framing, criterion_order, random_seed) "
                "VALUES ('title-abstract', 'A', 'f', '[]', 1)"
            )
        )
        conn.commit()
    return og_closed


@pytest.mark.anyio
async def test_refused_until_a_pass_opens(
    settings: Settings, og_closed: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        out = await client.call("view_onion", project="demo")
    assert out["ok"] is False
    assert out["errors"] == [{"field": "view", "reason": "not available yet"}]


@pytest.mark.anyio
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, ctr_a.session)  # this session read a contribution pass
    async with open_session(settings, clock) as client:
        out = await client.call("view_onion", project="demo")
    assert out["ok"] is False and out["errors"][0]["field"] == "session"


@pytest.mark.anyio
async def test_returns_the_agent_view(settings: Settings, og: Project, clock: FixedClock) -> None:
    async with open_session(settings, clock) as client:
        out = await client.call("view_onion", project="demo", max_ring=1)
    assert out["ok"] is True
    expected = onion_view(og, OnionFilter(max_ring=1), agent=True).model_dump(mode="json")
    assert out["data"] == expected
    assert [r["total"] for r in out["data"]["rings"]] == [3, 4]


@pytest.mark.anyio
async def test_tool_asks_for_the_agent_variant(
    settings: Settings, og: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real = mcp_server.onion_service.onion_view

    def spy(project: Project, flt: OnionFilter, *, agent: bool = False) -> Any:
        seen.append(agent)
        return real(project, flt, agent=agent)

    monkeypatch.setattr(mcp_server.onion_service, "onion_view", spy)
    async with open_session(settings, clock) as client:
        await client.call("view_onion", project="demo")
    assert seen == [True]


@pytest.mark.anyio
async def test_filters_pass_through_and_bad_edge_types_are_structured_errors(
    settings: Settings, og: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        wide = await client.call("view_onion", project="demo", include_inferred=True)
        only = await client.call("view_onion", project="demo", edge_types=["cites"], focus=[A[0]])
        bad = await client.call("view_onion", project="demo", edge_types=["cites", "bogus"])
        outside = await client.call("view_onion", project="demo", focus=[B[4]])
    assert [r["total"] for r in wide["data"]["rings"]] == [3, 5, 4]
    assert [n["work_id"] for n in only["data"]["rings"][0]["nodes"]] == [A[0]]
    assert bad["ok"] is False and bad["errors"][0]["field"] == "edge_types"
    assert outside["ok"] is False and outside["errors"][0]["field"] == "focus"


@pytest.mark.anyio
async def test_output_is_scrubbed_without_hiding_work_ids(
    settings: Settings, og: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 37.9: only seed ids and stated identifiers are stripped; works stay ordinary."""
    calls: list[bool] = []
    real = mcp_server._held_out_tokens

    def spy(project: Project, include_work_ids: bool = True) -> set[str]:
        calls.append(include_work_ids)
        return real(project, include_work_ids)

    monkeypatch.setattr(mcp_server, "_held_out_tokens", spy)
    async with open_session(settings, clock) as client:
        out = await client.call("view_onion", project="demo")
    assert calls and not any(calls)
    assert {n["work_id"] for n in out["data"]["rings"][0]["nodes"]} == set(F)


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_cli_json_equals_the_service(settings: Settings, og_closed: Project) -> None:
    code, out, err = _run(settings.root, "view", "onion", "--format", "json")
    assert code == 0, err
    assert out == to_json(onion_view(og_closed))


def test_cli_options_and_formats(settings: Settings, og_closed: Project) -> None:
    code, md, err = _run(
        settings.root, "view", "onion", "--max-ring", "1", "--edge-type", "cites", "--focus", A[0]
    )
    assert code == 0, err
    assert md.startswith("# Onion view") and "## Ring 1" in md and "## Ring 2" not in md
    code, dot, _ = _run(settings.root, "view", "onion", "--format", "dot")
    assert code == 0 and "layout=twopi" in dot
    code, wide, _ = _run(settings.root, "view", "onion", "--include-inferred", "--format", "json")
    assert code == 0 and '"include_inferred":true' in wide


def test_cli_is_the_researchers_complete_view(settings: Settings, og_closed: Project) -> None:
    """Before any pass has opened, the command still works: the guards belong to the agent path."""
    code, out, err = _run(settings.root, "view", "onion")
    assert code == 0, err
    assert A[0] in out


def test_cli_writes_a_file_and_refuses_bad_input(
    settings: Settings, og_closed: Project, tmp_path: Path
) -> None:
    target = tmp_path / "onion.md"
    code, out, err = _run(settings.root, "view", "onion", "--out", str(target))
    assert code == 0, err
    assert target.read_text().startswith("# Onion view") and str(target) in out
    code, _, err = _run(settings.root, "view", "onion", "--edge-type", "bogus")
    assert code != 0 and "edge_types" in err
    code, _, err = _run(settings.root, "view", "onion", "--format", "svg")
    assert code != 0 and "format" in err
