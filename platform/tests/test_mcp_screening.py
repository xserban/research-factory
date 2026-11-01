"""The screening, calibration and agreement MCP tools: refusals, partial success, scrub (R-20).

Each MCP server is one session, so a screener's calls share one server and client, as a Claude
Code session does. Screening tools withhold held-out seed identifiers but not held-out work ids.
"""

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from mcp import Client
from mcp.types import TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.model.screening import Channel
from factory.services.calibration import calibration_items, calibration_labels, label_calibration
from factory.services.context import Project
from factory.services.seeds import SeedRole, all_seeds
from factory.sources.registry import SourceFactory
from tests.test_screening_next import _draw, _of_type, _setup

AGENT = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


class Session:
    """One MCP server and its client: one session. Every call advances the clock one millisecond."""

    def __init__(self, client: Client, clock: FixedClock) -> None:
        self._client = client
        self._clock = clock

    async def call(self, name: str, **args: Any) -> dict[str, Any]:
        self._clock.advance(timedelta(milliseconds=1))
        result = await self._client.call_tool(name, args)
        block = result.content[0]
        assert isinstance(block, TextContent)
        body: dict[str, Any] = json.loads(block.text)
        return body


@asynccontextmanager
async def open_session(
    settings: Settings, clock: FixedClock, sources: dict[str, SourceFactory] | None = None
) -> AsyncIterator[Session]:
    server = build_server(settings, clock=clock, sources={} if sources is None else sources)
    async with Client(server) as client:
        yield Session(client, clock)


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


def _include(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_id": record["work_id"],
        "verdict": "include",
        "criterion": None,
        "quote": record["title"],
        "rationale": "fits",
    }


def _leaks(text: str, tokens: set[str]) -> list[str]:
    """Tokens that occur in `text` as whole identifiers, case-insensitively."""
    return sorted(
        token
        for token in tokens
        if re.search(rf"(?<![0-9A-Za-z]){re.escape(token)}(?![0-9A-Za-z])", text, re.IGNORECASE)
    )


@pytest.mark.anyio
async def test_held_out_seed_is_screened_without_being_named(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    for item in _draw(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    held = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held, "the fixture must hold out a positive seed"

    seen: list[dict[str, Any]] = []
    transcript: list[Any] = []
    async with open_session(settings, clock) as screener:
        while True:
            body = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
            transcript.append(body)
            assert body["ok"] is True, body
            batch = body["data"]["batch"]
            if batch is None:
                break
            seen.extend(batch["records"])
            items = [_include(record) for record in batch["records"]]
            written = await screener.call(
                "screen_record", project="demo", task_id=batch["task_id"], items=items, **AGENT
            )
            transcript.append(written)
            assert written["ok"] is True and written["data"]["rejected"] == []

    held_works = {s.work_id for s in held}
    assert held_works <= {record["work_id"] for record in seen}
    tokens = {t for s in held for t in (s.seed_id, s.doi, s.arxiv, s.openalex) if t}
    assert _leaks(json.dumps(transcript), tokens) == []


@pytest.mark.anyio
async def test_screen_tools_require_model_and_skill(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as screener:
        unknown = await screener.call(
            "screen_next",
            project="demo",
            pass_label="A",
            role="screener-a",
            model="claude-sonnet-5-5",
            skill="no-such-skill",
        )
        assert _fields(unknown) == ["skill"]
        no_model = await screener.call(
            "screen_next",
            project="demo",
            pass_label="A",
            role="screener-a",
            model="",
            skill="rf-screen",
        )
        assert _fields(no_model) == ["model"]
        bad_label = await screener.call("screen_next", project="demo", pass_label="C", **AGENT)
        assert _fields(bad_label) == ["pass_label"]
    assert _of_type(project, "screening.pass_opened") == []


@pytest.mark.anyio
async def test_screen_record_partial_success_over_mcp(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    for item in _draw(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    async with open_session(settings, clock) as screener:
        batch = (await screener.call("screen_next", project="demo", pass_label="A", **AGENT))[
            "data"
        ]["batch"]
        records = batch["records"]
        assert len(records) >= 3
        items = [
            _include(records[0]),
            {**_include(records[1]), "quote": "a span that is not in this record"},
            {
                "work_id": records[2]["work_id"],
                "verdict": "exclude",
                "criterion": None,
                "quote": records[2]["title"],
                "rationale": "off topic",
            },
        ]
        body = await screener.call(
            "screen_record", project="demo", task_id=batch["task_id"], items=items, **AGENT
        )
    assert body["ok"] is True
    data = body["data"]
    assert len(data["written"]) == 1
    rejected = {r["index"]: [i["field"] for i in r["issues"]] for r in data["rejected"]}
    assert rejected == {1: ["items.1.quote"], 2: ["items.2"]}


@pytest.mark.anyio
async def test_calibration_label_flow_over_mcp(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as reviewer:
        first = await reviewer.call("calibration_label", project="demo")
        assert first["ok"] is True
        assert first["data"]["labelled"] == 0
        assert first["data"]["drawn"] == len(calibration_items(project)) > 0
        record = first["data"]["record"]
        assert {"work_id", "title", "abstract"} <= set(record)

        written = await reviewer.call(
            "calibration_label", project="demo", work_id=record["work_id"], verdict="include"
        )
        assert written["ok"] is True and isinstance(written["data"]["event_id"], str)

        other = calibration_items(project)[1]
        assert _fields(await reviewer.call("calibration_label", project="demo", work_id=other)) == [
            "verdict"
        ]
        assert _fields(
            await reviewer.call("calibration_label", project="demo", work_id=other, verdict="maybe")
        ) == ["verdict"]
        assert _fields(
            await reviewer.call(
                "calibration_label",
                project="demo",
                work_id=other,
                verdict="exclude",
                criterion="EX09",
            )
        ) == ["criterion"]
        assert _fields(
            await reviewer.call(
                "calibration_label", project="demo", work_id="W-not-drawn", verdict="include"
            )
        ) == ["work_id"]

        labelled = await reviewer.call(
            "calibration_label",
            project="demo",
            work_id=other,
            verdict="exclude",
            criterion="EX01",
        )
        assert labelled["ok"] is True
        counted = await reviewer.call("calibration_label", project="demo")
        assert counted["data"]["labelled"] == 2

    assert calibration_labels(project)[record["work_id"]] == "include"
    [event] = [
        e
        for e in _of_type(project, "calibration.labelled")
        if e.payload["work_id"] == record["work_id"]
    ]
    assert event.payload["channel"] == "mcp" and event.actor.kind == "human"


@pytest.mark.anyio
async def test_agreement_over_mcp_is_refused_until_passes_finish(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as reviewer:
        body = await reviewer.call("screen_agreement", project="demo")
    assert _fields(body) == ["passes"]


@pytest.mark.anyio
async def test_held_out_work_ids_stay_visible_to_screeners(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    """The narrower scrub: a held-out work's id is what the screener records against."""
    _setup(project, agent, human, mock_sources)
    for item in _draw(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    held_works = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT}
    seen: set[str] = set()
    async with open_session(settings, clock) as screener:
        while True:
            batch = (await screener.call("screen_next", project="demo", pass_label="A", **AGENT))[
                "data"
            ]["batch"]
            if batch is None:
                break
            seen.update(record["work_id"] for record in batch["records"])
            await screener.call(
                "screen_record",
                project="demo",
                task_id=batch["task_id"],
                items=[_include(r) for r in batch["records"]],
                **AGENT,
            )
    assert held_works <= seen
    assert all(isinstance(w, str) for w in held_works)
    assert [e.type for e in read_all(project.paths.events_dir, project.catalog)].count(
        "screening.decision_recorded"
    ) == len(seen)
