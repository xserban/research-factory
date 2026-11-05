# ruff: noqa: F401, F811
"""The `graph_*` MCP tools (plan G2-D, task 5): reads only, refused to pass sessions."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.services import lineage as lineage_service
from factory.services.context import Project
from factory.services.lineage import graph_export
from tests.helpers import open_session
from tests.lineage_graph_helpers import stand_in_basis, write_fixture
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world
from tests.test_mcp_lineage import _session

P9, P1, P5 = "rf:p9-00000009", "rf:p1-00000001", "rf:p5-00000005"


@pytest.fixture
def gp_closed(project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch) -> Project:
    """The fixture graph, no screening pass opened yet."""
    stand_in_basis(monkeypatch)
    write_fixture(project, agent)
    return project


@pytest.fixture
def gp(gp_closed: Project) -> Project:
    """The same, after a screening pass has opened (`held_out_visible`)."""
    with gp_closed.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO passes (stage, pass_label, framing, criterion_order, random_seed) "
                "VALUES ('title-abstract', 'A', 'f', '[]', 1)"
            )
        )
        conn.commit()
    return gp_closed


@pytest.mark.anyio
async def test_refused_until_a_pass_opens(
    settings: Settings, gp_closed: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("graph_status", project="demo"),
            await client.call("graph_query", project="demo", query="ancestors", node=P9),
            await client.call("graph_export", project="demo"),
        ]
    assert all(o["ok"] is False for o in outs)
    messages = {(e["field"], e["reason"]) for o in outs for e in o["errors"]}
    assert len(messages) == 1  # one neutral message, the same for every tool
    reason = next(iter(messages))[1]
    assert "held" not in reason.lower() and "seed" not in reason.lower()


@pytest.mark.anyio
async def test_status_query_and_export(settings: Settings, gp: Project, clock: FixedClock) -> None:
    async with open_session(settings, clock) as client:
        status = await client.call("graph_status", project="demo")
        path = await client.call("graph_query", project="demo", query="path", node=P9, target=P1)
        wide = await client.call(
            "graph_query", project="demo", query="ancestors", node=P9, include_inferred=True
        )
        export = await client.call("graph_export", project="demo", format="json")
        dot = await client.call(
            "graph_export", project="demo", format="dot", query="ancestors", node=P9
        )
    assert status["ok"] is True and status["data"]["nodes"]["idea"] == 2
    assert [n["id"] for n in path["data"]["nodes"]] == [P9, P5, "rf:p3-00000003", P1]
    assert wide["data"]["filter"]["include_inferred"] is True
    assert export["ok"] is True and export["data"] == graph_export(gp, "json")
    assert dot["data"].startswith("digraph lineage {")


@pytest.mark.anyio
async def test_unknown_query_and_bad_arguments_are_structured_errors(
    settings: Settings, gp: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        bad = await client.call("graph_query", project="demo", query="bogus", node=P9)
        missing = await client.call("graph_query", project="demo", query="ancestors")
        fmt = await client.call("graph_export", project="demo", format="svg")
        unknown = await client.call("graph_query", project="demo", query="ancestors", node="rf:x-0")
    assert bad == {"ok": False, "errors": [{"field": "query", "reason": "unknown query"}]}
    assert missing["errors"] == [{"field": "node", "reason": "required"}]
    assert fmt["ok"] is False and fmt["errors"][0]["field"] == "format"
    assert unknown["ok"] is False and unknown["errors"][0]["field"] == "node"


@pytest.mark.anyio
async def test_export_above_the_cap_is_refused(
    settings: Settings, gp: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lineage_service, "MCP_EXPORT_MAX_EDGES", 3)
    async with open_session(settings, clock) as client:
        whole = await client.call("graph_export", project="demo")
        query = await client.call(
            "graph_export", project="demo", query="ancestors", node=P9, depth=8
        )
    assert whole["errors"] == [{"field": "query", "reason": "too large; use a query or the CLI"}]
    assert query["ok"] is True  # a query's subgraph is bounded and not capped


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
        outs = [
            await client.call("graph_status", project="demo"),
            await client.call("graph_query", project="demo", query="ancestors", node=lin.source),
            await client.call("graph_export", project="demo"),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session"


@pytest.mark.anyio
async def test_output_is_scrubbed_without_hiding_work_ids(
    settings: Settings, gp: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 37.9: only seed ids and stated identifiers are stripped; works stay ordinary."""
    calls: list[bool] = []
    real = mcp_server._held_out_tokens

    def spy(project: Project, include_work_ids: bool = True) -> set[str]:
        calls.append(include_work_ids)
        return real(project, include_work_ids)

    monkeypatch.setattr(mcp_server, "_held_out_tokens", spy)
    async with open_session(settings, clock) as client:
        out = await client.call("graph_query", project="demo", query="ancestors", node=P9)
        await client.call("graph_status", project="demo")
        await client.call("graph_export", project="demo")
    assert calls and not any(calls)
    assert P5 in {n["id"] for n in out["data"]["nodes"]}
