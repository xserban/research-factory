"""The concept MCP tools, the batch's concepts and the skill (slice 3c, plan G3-B, task 6).

No tool approves a source, reviews a definition, decides a link, merges or unmerges.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.model.intuition import ConceptInput
from factory.services.concepts import define_concept
from factory.services.context import Project
from factory.services.interpretations import intuition_next
from tests.helpers import SESSION, install_skill, open_session
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world
from tests.test_mcp_intuition import AGENT, SESSION_I, _session

TOOLS = ("concept_propose", "concept_link")
TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}
SKILL_FILE = Path(__file__).resolve().parents[2] / "plugin" / "skills" / "rf-intuition" / "SKILL.md"


def _concept_events(project: Project) -> list[Event]:
    return [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type.startswith("concept.")
    ]


@pytest.mark.anyio
async def test_tool_list_has_the_two_tools_and_no_decision_tool(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert all(name in names for name in TOOLS)
    layer = [n for n in names if n.startswith(("concept", "intuition", "interpretation"))]
    assert sorted(layer) == sorted(
        [
            "concept_propose",
            "concept_link",
            "intuition_next",
            "interpretation_record",
            "interpretation_list",
        ]
    )
    banned = ("approve", "review", "decide", "confirm", "merge")
    assert not [n for n in layer if any(b in n for b in banned) and n != "interpretation_record"]


@pytest.mark.anyio
async def test_propose_and_link_roundtrip(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-intuition")
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        proposed = await client.call(
            "concept_propose",
            project="demo",
            concept_name="softmax attention",
            aliases=["SA"],
            text="The normalised exponential of query-key scores.",
            source=TEXTBOOK,
            **AGENT,
        )
        assert proposed["ok"] is True, proposed
        cid = proposed["data"]["concept_id"]
        assert cid.startswith("cpt_")
        assert proposed["data"]["source_state"] == "proposed"
        assert proposed["data"]["review_state"] == "unreviewed"
        linked = await client.call(
            "concept_link",
            project="demo",
            from_node=iw.source,
            concept_id=cid,
            quote=iw.quote("s1.p2", "Unlike softmax attention"),
            **AGENT,
        )
    assert linked["ok"] is True, linked
    assert linked["data"]["status"] == "stated" and linked["data"]["existing"] is False
    events = _concept_events(project)
    assert [e.type for e in events] == ["concept.defined", "concept.link_proposed"]
    for e in events:
        assert e.actor.skill is not None and e.actor.skill.startswith("rf-intuition@")
        assert e.input_blob is not None


@pytest.mark.anyio
async def test_quote_from_a_non_source_work_is_a_structured_error(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-intuition")
    _session(monkeypatch, SESSION_I)
    source = {"kind": "corpus-paper", "citation": "Another paper", "work_id": iw.other}
    async with open_session(settings, clock) as client:
        out = await client.call(
            "concept_propose",
            project="demo",
            concept_name="softmax attention",
            source=source,
            quotes=[iw.quote()],
            **AGENT,
        )
        bad_shape = await client.call(
            "concept_propose", project="demo", concept_name="x", source={"kind": "blog"}, **AGENT
        )
    assert out["ok"] is False
    assert {"field": "quotes.0.work_id", "reason": "not-source-work"} in out["errors"]
    assert "degrade" not in str(out)
    assert bad_shape["ok"] is False
    assert _concept_events(project) == []


@pytest.mark.anyio
async def test_pass_sessions_and_early_calls_are_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-intuition")
    for session in (ctr_a.session, SESSION):
        _session(monkeypatch, session)
        async with open_session(settings, clock) as client:
            outs = [
                await client.call("concept_propose", project="demo", concept_name="x", **AGENT),
                await client.call(
                    "concept_link",
                    project="demo",
                    from_node=iw.source,
                    concept_id="cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ",
                    note="n",
                    **AGENT,
                ),
            ]
        for out in outs:
            assert out["ok"] is False and out["errors"][0]["field"] == "session", out
    assert _concept_events(project) == []


@pytest.mark.anyio
async def test_tools_are_not_available_before_a_screening_pass_opens(
    settings: Settings, project: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skill(settings, "rf-intuition")
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("concept_propose", project="demo", concept_name="x", **AGENT),
            await client.call(
                "concept_link",
                project="demo",
                from_node="rf:p1-00000001",
                concept_id="cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ",
                note="n",
                **AGENT,
            ),
        ]
    for out in outs:
        assert out == {"ok": False, "errors": [{"field": "graph", "reason": "not available yet"}]}


def test_batch_lists_only_visible_concepts(project: Project, iw: IWorld) -> None:
    shown = define_concept(
        project,
        iw.human,
        ConceptInput.model_validate(
            {"name": "softmax attention", "aliases": ["SA"], "source": TEXTBOOK}
        ),
        approve_source=True,
    )
    define_concept(
        project,
        iw.writer,
        ConceptInput.model_validate({"name": "hidden idea", "source": TEXTBOOK}),
    )
    batch = intuition_next(project, iw.writer, targets=[iw.idea1]).batch
    assert batch is not None
    assert [(c.concept_id, c.name, c.aliases) for c in batch.concepts] == [
        (shown, "softmax attention", ["SA"])
    ]
    assert batch.concepts_total == 1


def test_skill_names_the_tools_and_the_human_steps() -> None:
    text = SKILL_FILE.read_text("utf-8")
    assert "concept_propose" in text and "concept_link" in text
    assert "approved source" in text and "never approve" in text.lower()
