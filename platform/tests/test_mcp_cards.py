# ruff: noqa: F401, F811
"""The card MCP tools (slice 6, plan H-A, task 5): propose and assert only; no tool decides."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import sessions as mcp_sessions
from factory.mcp.server import build_server
from factory.services.cards import create_card
from factory.services.context import Project
from tests.card_helpers import CardWorld, cw
from tests.helpers import install_skill, open_session
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world

SESSION_E = "01JZ9Q3K5M7N8P0R2S4T6V8W1E"
AGENT = {"role": "cards", "model": "claude-opus-5-5", "skill": "rf-cards"}
TOOLS = ("vocabulary_propose", "card_create", "card_assert", "card_view")


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_sessions, "IdGenerator", Ids)


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


def _quote_item(cw: CardWorld, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "property": "pr:attention-kind",
        "value": "linear",
        "basis_kind": "quote",
        "basis": {
            "work_id": cw.source,
            "conversion_id": cw.conversion_id,
            "anchor": "s1.p1",
            "quote": "linear attention",
        },
    }
    item.update(over)
    return item


@pytest.mark.anyio
async def test_tool_list_has_four_card_tools_and_no_decisions(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert all(tool in names for tool in TOOLS)
    banned = ("confirm", "approve", "decide", "merge", "reject", "import")
    related = [n for n in names if n.startswith(("vocabulary_", "card_"))]
    assert sorted(related) == sorted(TOOLS)
    assert not [n for n in related if any(b in n for b in banned)]


@pytest.mark.anyio
async def test_propose_create_assert_view_round_trip(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    cw: CardWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-cards")
    _session(monkeypatch, SESSION_E)
    new = {
        "key": "pr:causal-mask",
        "kind": "bool",
        "match": "equal",
        "applies_to": "both",
        "aliases": ["causal mask"],
    }
    async with open_session(settings, clock) as client:
        proposed = await client.call("vocabulary_propose", project="demo", definition=new, **AGENT)
        assert proposed["ok"] is True and proposed["data"] == {"key": "pr:causal-mask"}
        created = await client.call(
            "card_create",
            project="demo",
            kind="method",
            subject=cw.idea,
            owner="obd",
            **AGENT,
        )
        card = created["data"]["card_id"]
        assert created["ok"] is True and card.startswith("mcd_")
        bad = _quote_item(cw, value="softmax")
        stated = {"status": "stated", **_quote_item(cw)}
        out = await client.call(
            "card_assert",
            project="demo",
            card_id=card,
            items=[_quote_item(cw), bad, stated],
            **AGENT,
        )
        assert out["ok"] is True, out
        assert [a[0] for a in out["data"]["accepted"]] == [0]
        assert [r[0] for r in out["data"]["rejected"]] == [1, 2]
        assert out["data"]["rejected"][1][1][0]["reason"].startswith("Extra inputs")
        seen = await client.call("card_view", project="demo", card_id=card)
        assert seen["ok"] is True
        [a] = seen["data"]["assertions"]
        assert (a["property"], a["value"], a["effective"]) == (
            "pr:attention-kind",
            "linear",
            "stated",
        )
    written = _of(project, "vocabulary.property_proposed", "card.created", "card.asserted")
    mine = [e for e in written if e.actor.id == "cards"]
    assert {e.type for e in mine} == {
        "vocabulary.property_proposed",
        "card.created",
        "card.asserted",
    }
    for event in mine:
        assert event.actor.skill is not None and event.actor.skill.startswith("rf-cards@")
        assert event.input_blob is not None
    # the proposal is unusable until a human approves it
    assert [e.payload["definition"]["key"] for e in _of(project, "vocabulary.property_proposed")][
        -1
    ] == "pr:causal-mask"


@pytest.mark.anyio
async def test_status_argument_is_refused_and_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    cw: CardWorld,
    agent: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-cards")
    card = create_card(project, agent, "method", cw.source, "obd")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        out = await client.call(
            "card_assert",
            project="demo",
            card_id=card,
            items=[_quote_item(cw)],
            status="stated",
            **AGENT,
        )
    assert out["ok"] is False and out["errors"][0]["field"] == "status"
    assert _of(project, "card.asserted") == []


@pytest.mark.anyio
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    cw: CardWorld,
    agent: Actor,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-cards")
    card = create_card(project, agent, "method", cw.source, "obd")
    _session(monkeypatch, ctr_a.session)  # this session read a contribution pass
    before = len(_of(project, "vocabulary.property_proposed", "card.created", "card.asserted"))
    async with open_session(settings, clock) as client:
        outs = [
            await client.call(
                "vocabulary_propose",
                project="demo",
                definition={
                    "key": "pr:other-key",
                    "kind": "bool",
                    "match": "equal",
                    "applies_to": "both",
                },
                **AGENT,
            ),
            await client.call(
                "card_create",
                project="demo",
                kind="method",
                subject=cw.source,
                owner="obd",
                **AGENT,
            ),
            await client.call(
                "card_assert", project="demo", card_id=card, items=[_quote_item(cw)], **AGENT
            ),
            await client.call("card_view", project="demo", card_id=card),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session"
    after = len(_of(project, "vocabulary.property_proposed", "card.created", "card.asserted"))
    assert after == before


@pytest.mark.anyio
async def test_card_tools_are_role_blind_before_a_pass_opens(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-cards")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        out = await client.call(
            "card_create",
            project="demo",
            kind="method",
            subject="rf:smith-2020-a1b2c3d4",
            owner="obd",
            **AGENT,
        )
        viewed = await client.call(
            "card_view", project="demo", card_id="mcd_01JZ9Q3K5M7N8P0R2S4T6V8W1C"
        )
    for res in (out, viewed):
        assert res["ok"] is False and res["errors"] == [
            {"field": "graph", "reason": "not available yet"}
        ]
    assert _of(project, "card.created") == []
