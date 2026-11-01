"""The question, seed, probe and protocol MCP tools: their outputs and their structured errors.

Every mutating tool is called with an agent's role, model and skill; every refusal is a
structured `ok: false` result naming the field at fault, and writes nothing.
"""

import json
from datetime import timedelta
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.question import current_question
from factory.sources.registry import SourceFactory
from tests.helpers import (
    openalex_item,
    pilot_protocol_spec,
    pilot_question_spec,
    ready_protocol,
    record_pilot_question,
)

AGENT = {"role": "screener-a", "model": "claude-opus-5-5", "skill": "rf-screen"}


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


async def _call(
    settings: Settings,
    clock: FixedClock,
    sources: dict[str, SourceFactory],
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=sources)
    async with Client(server) as client:
        return _body(await client.call_tool(name, args))


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


def _item(n: int) -> dict[str, Any]:
    return openalex_item(
        title=f"Paper {n}",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )


def _positive(n: int) -> dict[str, Any]:
    return {"kind": "positive", "cite": f"Paper {n}", "doi": f"10.1000/p{n}"}


def _event_types(project: Project) -> list[str]:
    return [event.type for event in read_all(project.paths.events_dir, project.catalog)]


@pytest.mark.anyio
async def test_question_record_states_goal_and_records_question(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    spec = pilot_question_spec().model_dump(mode="json")
    body = await _call(
        settings,
        clock,
        {},
        "question_record",
        {"project": "demo", "spec": spec, "raw_goal": "Compare attention on vision", **AGENT},
    )

    assert body["ok"] is True
    assert body["data"]["created"] is True
    assert body["data"]["question_id"].startswith("Q@")
    types = _event_types(project)
    assert types.index("question.goal_stated") < types.index("question.recorded")
    [recorded] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "question.recorded"
    ]
    assert recorded.actor.kind == "agent" and recorded.input_blob is not None


@pytest.mark.anyio
async def test_question_record_refusals_name_the_field_and_write_nothing(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    bad_slot = pilot_question_spec().model_dump(mode="json")
    bad_slot["slots"][0] = {"name": "population"}  # neither value nor open
    body = await _call(
        settings,
        clock,
        {},
        "question_record",
        {"project": "demo", "spec": bad_slot, "raw_goal": "Compare", **AGENT},
    )
    assert "spec.slots.0" in _fields(body)

    no_goal = pilot_question_spec().model_dump(mode="json")
    body = await _call(
        settings, clock, {}, "question_record", {"project": "demo", "spec": no_goal, **AGENT}
    )
    assert _fields(body) == ["raw_goal"]

    thin = pilot_question_spec().model_dump(mode="json")
    thin["non_goals"] = []
    body = await _call(
        settings,
        clock,
        {},
        "question_record",
        {"project": "demo", "spec": thin, "raw_goal": "Compare", **AGENT},
    )
    assert "spec.non_goals" in _fields(body)
    assert "question.recorded" not in _event_types(project)


@pytest.mark.anyio
async def test_seed_add_reports_each_rejection_by_its_index(
    settings: Settings, project: Project, clock: FixedClock, mock_sources: Any, agent: Actor
) -> None:
    record_pilot_question(project, agent)
    sources = dict(mock_sources(openalex=[_item(1)]))
    body = await _call(
        settings,
        clock,
        sources,
        "seed_add",
        {
            "project": "demo",
            "seeds": [_positive(1), {"kind": "positive", "cite": ""}, _positive(1)],
            **AGENT,
        },
    )

    assert body["ok"] is True
    data = body["data"]
    assert [w["seed_id"] for w in data["written"]] == ["SEED01"]
    rejected = {r["index"]: r["issues"] for r in data["rejected"]}
    assert {issue["field"] for issue in rejected[1]} >= {"seeds.1.cite"}
    assert rejected[2] == [{"field": "seeds.2.doi", "reason": "duplicate of SEED01"}]


@pytest.mark.anyio
async def test_seed_list_rejects_a_bad_cursor(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    body = await _call(settings, clock, {}, "seed_list", {"project": "demo", "cursor": "next"})
    assert _fields(body) == ["cursor"]


@pytest.mark.anyio
async def test_probe_run_names_the_bad_query_field(
    settings: Settings, project: Project, clock: FixedClock, mock_sources: Any, agent: Actor
) -> None:
    record_pilot_question(project, agent)
    sources = dict(mock_sources(openalex=[_item(1)]))
    unknown = await _call(
        settings,
        clock,
        sources,
        "probe_run",
        {"project": "demo", "queries": [{"source": "nope", "query": "attention"}], **AGENT},
    )
    assert _fields(unknown) == ["queries.0.source"]

    bad_kind = await _call(
        settings,
        clock,
        sources,
        "probe_run",
        {
            "project": "demo",
            "queries": [{"source": "openalex", "query": "attention", "kind": "bogus"}],
            **AGENT,
        },
    )
    assert _fields(bad_kind) == ["queries.0.kind"]
    assert "query.registered" not in _event_types(project)


@pytest.mark.anyio
async def test_protocol_record_refuses_to_replace_a_ready_protocol(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Actor,
    human: Actor,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_dump(mode="json")
    spec["rationale"] = "A changed wording."  # prose only, still a record attempt
    body = await _call(
        settings,
        clock,
        {},
        "protocol_record",
        {"project": "demo", "spec": spec, "ready": False, **AGENT},
    )
    assert _fields(body) == ["protocol"]


@pytest.mark.anyio
async def test_protocol_press_review_names_the_protocol_and_finding_fields(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Actor,
    human: Actor,
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    finding = {"element": "text-words", "finding": "Add a synonym.", "severity": "minor"}
    unknown = await _call(
        settings,
        clock,
        {},
        "protocol_press_review",
        {"project": "demo", "protocol_id": "P@00000000", "findings": [finding], **AGENT},
    )
    assert _fields(unknown) == ["protocol_id"]

    current = current_protocol(project)
    assert current is not None
    bad = {"element": "bogus", "finding": "x", "severity": "minor"}
    body = await _call(
        settings,
        clock,
        {},
        "protocol_press_review",
        {"project": "demo", "protocol_id": current.protocol_id, "findings": [bad], **AGENT},
    )
    assert _fields(body) == ["findings.0.element"]


@pytest.mark.anyio
async def test_protocol_amend_names_the_effect_and_reason_fields(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Actor,
    human: Actor,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_dump(mode="json")
    bad_effect = await _call(
        settings,
        clock,
        {},
        "protocol_amend",
        {
            "project": "demo",
            "spec": spec,
            "reason": "Reword",
            "semantic": False,
            "effects": {"IN01": "bogus"},
            **AGENT,
        },
    )
    assert _fields(bad_effect) == ["effects.IN01"]

    no_reason = await _call(
        settings,
        clock,
        {},
        "protocol_amend",
        {"project": "demo", "spec": spec, "reason": " ", "semantic": False, "effects": {}, **AGENT},
    )
    assert _fields(no_reason) == ["reason"]


@pytest.mark.anyio
async def test_protocol_deviation_names_the_description_field(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Actor,
    human: Actor,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    body = await _call(
        settings,
        clock,
        {},
        "protocol_deviation",
        {"project": "demo", "description": " ", "reason": "Scope", **AGENT},
    )
    assert _fields(body) == ["description"]


@pytest.mark.anyio
async def test_project_status_tool_reports_question_protocol_and_seed_counts(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Actor,
    human: Actor,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    question = current_question(project)
    assert question is not None
    body = await _call(settings, clock, {}, "project_status", {"project": "demo"})

    assert body["ok"] is True
    data = body["data"]
    assert data["question"] == question.question_id
    assert data["protocol"]["status"] == "ready" and data["protocol"]["press"] == "confirmed"
    assert data["seeds"] == {
        "positive": 3,
        "negative": 0,
        "unresolved": 0,
        "split_drawn": True,
    }


@pytest.mark.anyio
async def test_protocol_record_draft_is_returned_with_its_version(
    settings: Settings, project: Project, clock: FixedClock, agent: Actor
) -> None:
    question_id = record_pilot_question(project, agent)
    spec = pilot_protocol_spec(question_id, probe_id=None).model_dump(mode="json")
    body = await _call(
        settings,
        clock,
        {},
        "protocol_record",
        {"project": "demo", "spec": spec, "ready": False, **AGENT},
    )
    assert body["ok"] is True
    assert body["data"]["protocol_id"].startswith("P@")
    assert body["data"]["status"] == "draft" and body["data"]["created"] is True
