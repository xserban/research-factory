"""The intuition MCP tools (slice 3c, plan G3-A, task 7): serve, record and list only.

No tool reviews, supersedes as a human, approves a source or confirms a link; a session that
joined a pass is refused all three; before a screening pass is open the tools are not available.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.services.context import Project
from tests.helpers import SESSION, install_skill, open_session
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world
from tests.test_extraction_next import SESSION_A

SESSION_I = "01JZ9Q3K5M7N8P0R2S4T6V8W1K"
AGENT = {"role": "intuiter", "model": "claude-opus-5-5", "skill": "rf-intuition"}
TOOLS = (
    "intuition_next",
    "interpretation_record",
    "interpretation_list",
    "concept_propose",
    "concept_link",
)


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)


def _layer(project: Project) -> list[Event]:
    return [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type.startswith("interpretation.")
    ]


def _source(iw: IWorld, quote: str = "very long sequences degrade") -> dict[str, Any]:
    return iw.quote(quote=quote)


@pytest.mark.anyio
async def test_tool_list_serves_records_and_lists_but_never_reviews(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert all(name in names for name in TOOLS)
    banned = ("review", "supersede", "approve", "confirm", "decide")
    assert not [n for n in names if "interpretation" in n and any(b in n for b in banned)]
    assert not [n for n in names if n.startswith(("concept", "intuition")) and n not in TOOLS]


@pytest.mark.anyio
async def test_serve_record_and_list_roundtrip(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-intuition")
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        served = await client.call("intuition_next", project="demo", targets=[iw.idea1], **AGENT)
        assert served["ok"] is True, served
        batch = served["data"]["batch"]
        assert batch["target"] == iw.idea1 and batch["items"] and batch["max_chars"] == 600
        recorded = await client.call(
            "interpretation_record",
            project="demo",
            task_id=batch["task_id"],
            target=iw.idea1,
            text="Long sequences are the stated limit of the module.",
            sources=[_source(iw)],
            **AGENT,
        )
        listed = await client.call("interpretation_list", project="demo", target=iw.idea1)
    assert recorded["ok"] is True, recorded
    assert recorded["data"]["interpretation_id"].startswith("int_")
    [event] = _layer(project)
    assert event.actor.skill is not None and event.actor.skill.startswith("rf-intuition@")
    assert event.input_blob is not None and event.payload["author"] == "agent"
    [item] = listed["data"]["items"]
    assert item["class"] == "interpretation" and item["label"] == "interpretation · unreviewed"
    assert listed["data"]["hidden"] == {"wrong": 0, "superseded": 0}


@pytest.mark.anyio
async def test_non_verbatim_quote_is_a_structured_error_and_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-intuition")
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        served = await client.call("intuition_next", project="demo", targets=[iw.idea1], **AGENT)
        out = await client.call(
            "interpretation_record",
            project="demo",
            task_id=served["data"]["batch"]["task_id"],
            target=iw.idea1,
            text="Anything.",
            sources=[_source(iw, "very long sequences improve")],
            **AGENT,
        )
        bad_shape = await client.call(
            "interpretation_record",
            project="demo",
            task_id=served["data"]["batch"]["task_id"],
            target=iw.idea1,
            text="Anything.",
            sources=[{"kind": "web", "role": "supports"}],
            **AGENT,
        )
    assert out["ok"] is False
    assert {"field": "sources.0.quote", "reason": "quote-not-in-anchor"} in out["errors"]
    assert "improve" not in str(out) and "degrade" not in str(out)
    assert bad_shape["ok"] is False and bad_shape["errors"][0]["field"].startswith("interpretation")
    assert _layer(project) == []


@pytest.mark.anyio
async def test_pass_sessions_are_refused_all_three(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-intuition")
    for session in (ctr_a.session, SESSION):  # an extraction session; a screening session
        _session(monkeypatch, session)
        async with open_session(settings, clock) as client:
            outs = [
                await client.call("intuition_next", project="demo", **AGENT),
                await client.call(
                    "interpretation_record",
                    project="demo",
                    task_id="tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
                    target=iw.idea1,
                    text="x",
                    sources=[_source(iw)],
                    **AGENT,
                ),
                await client.call("interpretation_list", project="demo"),
            ]
        for out in outs:
            assert out["ok"] is False and out["errors"][0]["field"] == "session", out
    assert _layer(project) == []


@pytest.mark.anyio
async def test_tools_are_not_available_before_a_screening_pass_opens(
    settings: Settings, project: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The role-blind guard of the graph tools: the same neutral answer for every caller."""
    install_skill(settings, "rf-intuition")
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("intuition_next", project="demo", **AGENT),
            await client.call(
                "interpretation_record",
                project="demo",
                task_id="tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
                target="rf:p1-00000001",
                text="x",
                sources=[{"kind": "citation", "role": "background", "work_id": "rf:p1-00000001"}],
                **AGENT,
            ),
            await client.call("interpretation_list", project="demo"),
        ]
    for out in outs:
        assert out == {"ok": False, "errors": [{"field": "graph", "reason": "not available yet"}]}


@pytest.mark.anyio
async def test_list_labels_every_item_and_filters_states(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factory.model.screening import Channel
    from factory.services.interpretations import record_interpretation, review_interpretation

    first = record_interpretation(project, iw.human, iw.entry(iw.idea1))
    second = record_interpretation(project, iw.human, iw.entry(iw.idea2))
    review_interpretation(project, iw.human, second, "wrong", "no", Channel.CLI)
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        default = await client.call("interpretation_list", project="demo")
        wrong = await client.call("interpretation_list", project="demo", states=["wrong"])
        refused = await client.call("interpretation_list", project="demo", states=["bogus"])
    assert [i["interpretation_id"] for i in default["data"]["items"]] == [first]
    assert default["data"]["hidden"]["wrong"] == 1
    assert all(
        i["class"] == "interpretation" and i["label"].startswith("interpretation · ")
        for i in default["data"]["items"] + wrong["data"]["items"]
    )
    assert [i["review_state"] for i in wrong["data"]["items"]] == ["wrong"]
    assert refused["ok"] is False and refused["errors"][0]["field"] == "states"
