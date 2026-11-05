"""The matching and finder MCP tools (slice 6, plan H-B, task 6): read tools, plus a proposal.

No tool decides a contradiction; every tool is refused to a pass session and, before a pass
opens, answers with the same neutral message as the card tools."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.finders import decide_contradiction, find_gaps, propose_contradiction
from factory.services.matching import match
from tests.card_helpers import cw
from tests.contribution_helpers import ext_a
from tests.finder_helpers import MatchWorld, mw
from tests.helpers import install_skill, open_session
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.test_contradictions import CtrWorld, ctrw
from tests.test_mcp_cards import AGENT, SESSION_E, _session

TOOLS = ("match_query", "finder_contradictions", "finder_gaps", "contradiction_propose")


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


@pytest.mark.anyio
async def test_tool_list_has_read_tools_and_one_proposal(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert all(tool in names for tool in TOOLS)
    related = [n for n in names if n.startswith(("match_", "finder_", "contradiction_"))]
    assert sorted(related) == sorted(TOOLS)  # nothing decides, confirms or rejects


@pytest.mark.anyio
async def test_read_tools_return_the_service_models(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mw: MatchWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        matched = await client.call("match_query", project="demo", problem_id=mw.problem)
        paged = await client.call(
            "match_query", project="demo", problem_id=mw.problem, limit=2, transfer_only=False
        )
        gaps = await client.call(
            "finder_gaps", project="demo", rows_axis="card", columns_axis="pr:memory-scaling"
        )
        conflicts = await client.call("finder_contradictions", project="demo")
    assert matched["ok"] is True and matched["data"] == match(project, mw.problem).model_dump(
        mode="json"
    )
    assert len(paged["data"]["rows"]) == 2 and paged["data"]["next_after"] is not None
    assert gaps["ok"] is True
    assert gaps["data"] == find_gaps(
        project, rows_axis="card", columns_axis="pr:memory-scaling"
    ).model_dump(mode="json")
    assert "Not found in this corpus" in gaps["data"]["statement"]
    assert conflicts["ok"] is True and conflicts["data"]["conflicts"] == []
    assert conflicts["data"]["claims"] == []


@pytest.mark.anyio
async def test_confirmed_contradictions_are_appended_under_claims(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    other_session_human: Actor,
    ctrw: CtrWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factory.model.findings import ContradictionInput

    cid, _ = propose_contradiction(
        project, agent, ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note="n")
    )
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        before = await client.call("finder_contradictions", project="demo")
        decide_contradiction(project, other_session_human, cid, "confirm", "yes")
        after = await client.call("finder_contradictions", project="demo")
    assert before["data"]["claims"] == []
    [view] = after["data"]["claims"]
    assert (view["contradiction_id"], view["state"]) == (cid, "confirmed")


@pytest.mark.anyio
async def test_contradiction_propose_writes_an_agent_event_and_takes_no_decision(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ctrw: CtrWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-cards")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        refused = await client.call(
            "contradiction_propose",
            project="demo",
            ref_a=ctrw.claim_x,
            ref_b=ctrw.item,
            note="n",
            decision="confirm",
            **AGENT,
        )
        assert refused["ok"] is False and refused["errors"][0]["field"] == "decision"
        assert _of(project, "contradiction.proposed") == []
        out = await client.call(
            "contradiction_propose",
            project="demo",
            ref_a=ctrw.claim_x,
            ref_b=ctrw.item,
            note="the claim negates the item",
            **AGENT,
        )
        again = await client.call(
            "contradiction_propose",
            project="demo",
            ref_a=ctrw.item,
            ref_b=ctrw.claim_x,
            note="again",
            **AGENT,
        )
    assert out["ok"] is True and out["data"]["contradiction_id"].startswith("ctr_")
    assert out["data"]["written"] is True and again["data"]["written"] is False
    [event] = _of(project, "contradiction.proposed")
    assert event.actor.kind == "agent" and event.input_blob is not None
    assert event.actor.skill is not None and event.actor.skill.startswith("rf-cards@")
    assert _of(project, "contradiction.decided") == []


@pytest.mark.anyio
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mw: MatchWorld,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-cards")
    _session(monkeypatch, ctr_a.session)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("match_query", project="demo", problem_id=mw.problem),
            await client.call("finder_contradictions", project="demo"),
            await client.call(
                "finder_gaps", project="demo", rows_axis="card", columns_axis="pr:memory-scaling"
            ),
            await client.call(
                "contradiction_propose",
                project="demo",
                ref_a="clm_01JZ9Q3K5M7N8P0R2S4T6V8W1A",
                ref_b="clm_01JZ9Q3K5M7N8P0R2S4T6V8W1B",
                note="n",
                **AGENT,
            ),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session"
    assert _of(project, "contradiction.proposed") == []


@pytest.mark.anyio
async def test_tools_are_role_blind_before_a_pass_opens(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-cards")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call(
                "match_query", project="demo", problem_id="pbd_01JZ9Q3K5M7N8P0R2S4T6V8W1C"
            ),
            await client.call("finder_contradictions", project="demo"),
            await client.call(
                "finder_gaps", project="demo", rows_axis="method", columns_axis="task"
            ),
            await client.call(
                "contradiction_propose",
                project="demo",
                ref_a="clm_01JZ9Q3K5M7N8P0R2S4T6V8W1A",
                ref_b="clm_01JZ9Q3K5M7N8P0R2S4T6V8W1B",
                note="n",
                **AGENT,
            ),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"] == [
            {"field": "graph", "reason": "not available yet"}
        ]
