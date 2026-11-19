# ruff: noqa: F401, F811
"""The lead engine MCP tools: read-only, labelled exploratory, refused to a pass session, held-out
identifiers scrubbed, bounded replies."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import lead_engine_reply as bounds
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.model.lead_engine import NOTICE
from factory.services.access import TOOL_PERMISSIONS
from factory.services.context import Project
from tests.extraction_helpers import screened, world
from tests.helpers import open_session
from tests.lead_engine_helpers import engine_world

TOOLS = ("lead_candidates", "lead_queue", "lead_stats")
KNOBS: dict[str, Any] = {"layer": "all", "technique_min_works": 1}


@pytest.mark.anyio
async def test_the_tools_are_listed_and_read_only(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert all(t in names for t in TOOLS)
    assert all(TOOL_PERMISSIONS[t].value == "project:read" for t in TOOLS)


@pytest.mark.anyio
async def test_every_reply_is_labelled_and_the_queue_is_balanced(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    clock: FixedClock,
) -> None:
    engine_world(project, agent, human, world)
    async with open_session(settings, clock) as client:
        cands = await client.call("lead_candidates", project="demo", **KNOBS)
        queue = await client.call("lead_queue", project="demo", top=4, **KNOBS)
        flat = await client.call("lead_queue", project="demo", top=1, balance=False, **KNOBS)
        stats = await client.call("lead_stats", project="demo")
    for out in (cands, queue, flat, stats):
        assert out["ok"] is True, out
        assert out["notice"] == NOTICE and out["data"]["notice"] == NOTICE
    assert cands["data"]["exploratory"] is True and cands["data"]["candidates"]
    first = cands["data"]["candidates"][0]
    assert {t["kind"] for t in first["triggers"]} <= {"item", "work"}
    assert cands["data"]["reply_cap"]["truncated"] is False
    sources = {i["source"] for i in queue["data"]["items"]}
    assert len(sources) > 1 and queue["data"]["parameters"]["balance"] == 1
    assert len(flat["data"]["items"]) == 1 and flat["data"]["parameters"]["balance"] == 0
    assert stats["data"]["recorded"] == 0


@pytest.mark.anyio
async def test_bad_parameters_are_refused_with_the_field_and_the_notice(
    settings: Settings, project: Project, world: list[str], clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        bad = [
            ("lead_candidates", {"sources": ["nope"]}, "sources"),
            ("lead_candidates", {"per_source": 0}, "per_source"),
            ("lead_queue", {"order_by": ["nope"]}, "order_by"),
            ("lead_queue", {"top": 0}, "top"),
            ("lead_queue", {"per_source_top": 0}, "per_source_top"),
            ("lead_queue", {"per_source_top": 2, "balance": False}, "per_source_top"),
        ]
        for tool, args, field in bad:
            out = await client.call(tool, project="demo", **args)
            assert out["ok"] is False and out["errors"][0]["field"] == field, (tool, out)
            assert out["notice"] == NOTICE
        missing = await client.call("lead_stats", project="nosuch")
        assert missing["ok"] is False and missing["notice"] == NOTICE


@pytest.mark.anyio
async def test_a_pass_session_is_refused_with_the_notice(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server.passes_service, "is_pass_session", lambda *a, **k: True)
    async with open_session(settings, clock) as client:
        for tool in TOOLS:
            out = await client.call(tool, project="demo")
            assert out["ok"] is False and out["errors"][0]["field"] == "session", tool
            assert out["notice"] == NOTICE


@pytest.mark.anyio
async def test_held_out_identifiers_are_scrubbed_but_work_ids_are_not_asked_to_be(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordered = engine_world(project, agent, human, world)
    calls: list[bool] = []

    def tokens(_project: Project, include_work_ids: bool = True) -> set[str]:
        calls.append(include_work_ids)
        return {"Lorem"}  # every verbatim quote of the fixture begins so

    monkeypatch.setattr(mcp_server, "_held_out_tokens", tokens)
    async with open_session(settings, clock) as client:
        cands = await client.call("lead_candidates", project="demo", **KNOBS)
        queue = await client.call("lead_queue", project="demo", **KNOBS)
    assert calls and not any(calls)
    for out in (cands, queue):
        assert out["ok"] is True
        text = str(out)
        assert "Lorem" not in text and ordered[0] in text  # quotes scrubbed, work ids kept


def _candidate(n: int, source: str, quotes: int) -> dict[str, Any]:
    return {
        "candidate_id": f"{source}:{n}",
        "source": source,
        "triggers": [{"kind": "work", "ref": f"w{i}"} for i in range(20)],
        "quotes": [{"quote": "q" * 700, "role": "a"} for _ in range(quotes)],
    }


def test_the_reply_is_bounded_and_says_so() -> None:
    entries = [_candidate(i, s, 9) for s in ("a", "b") for i in range(60)]
    out = bounds.bound_candidates({"candidates": entries})
    shown = out["candidates"]
    assert len(shown) == bounds.MAX_CANDIDATES
    assert {c["source"] for c in shown} == {"a", "b"}
    assert all(len(c["quotes"]) == 9 for c in shown)  # a quote per cited row, none dropped
    assert all(len(c["triggers"]) == 20 for c in shown)  # triggers are never cut
    assert all(c["quotes"][0]["quote"].endswith("[cut]") for c in shown)
    assert all(len(q["quote"]) <= bounds.quote_chars(9) + 6 for c in shown for q in c["quotes"])
    cap = out["reply_cap"]
    assert cap["truncated"] is True and cap["shown"] == 40 and cap["of"] == 120
    assert cap["quotes_cut_in_text"] == 40 * 9 and "narrow" in cap["note"]
    assert "every cited row keeps its quote" in cap["note"]
    items = [{"source": "a", "candidate": _candidate(i, "a", 1)} for i in range(50)]
    queue = bounds.bound_queue({"items": items, "leads": []})
    assert len(queue["items"]) == bounds.MAX_QUEUE_ITEMS
    assert queue["reply_cap"]["of"] == 50 and queue["reply_cap"]["truncated"] is True


def _item(n: int, source: str) -> dict[str, Any]:
    return {"source": source, "entry_id": f"{source}:{n}", "candidate": _candidate(n, source, 1)}


def test_a_weak_sources_first_entry_survives_the_queue_cut_and_the_trim_is_named() -> None:
    items = [_item(i, "abc"[i % 3]) for i in range(44)]
    items.append(_item(0, "d"))  # global rank 45
    items += [_item(100 + i, "a") for i in range(5)]
    out = bounds.bound_queue({"items": items, "leads": []})
    ids = [i["entry_id"] for i in out["items"]]
    assert len(ids) == bounds.MAX_QUEUE_ITEMS and "d:0" in ids
    order = [i["entry_id"] for i in items]
    assert ids == [e for e in order if e in set(ids)]  # the global order is kept
    cap = out["reply_cap"]
    assert cap["truncated"] is True and cap["of"] == 50
    assert cap["sources_trimmed"] == ["a", "b", "c"]


def test_freed_slots_go_to_the_other_sources_in_the_global_order() -> None:
    entries = [_item(i, "a") for i in range(40)] + [_item(0, "b"), _item(1, "b")]
    kept = bounds._balanced_cut(entries, 30, lambda e: e["source"])
    assert len(kept) == 30
    assert [e["entry_id"] for e in kept if e["source"] == "b"] == ["b:0", "b:1"]
    assert sum(1 for e in kept if e["source"] == "a") == 28
    # more sources than the limit: the global order decides
    many = [_item(0, f"s{i}") for i in range(10)]
    assert [e["entry_id"] for e in bounds._balanced_cut(many, 3, lambda e: e["source"])] == [
        "s0:0",
        "s1:0",
        "s2:0",
    ]
