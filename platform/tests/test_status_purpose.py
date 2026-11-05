"""The STATUS query purpose: identifier lookups that never touch the corpus or PRISMA."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from mcp import Client
from mcp.types import TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.services.agreement import final_outcomes
from factory.services.context import Project
from factory.services.prisma import prisma_flow, search_report
from factory.services.protocol import search_authorization
from factory.services.search import corpus_size, list_works, register_query, search_counts
from factory.services.watch import cycles
from factory.sources.registry import SourceFactory
from tests.helpers import SourcesFor, openalex_item
from tests.status_helpers import StatusStub, in_cycle, noop_hook, status_query_hook
from tests.watch_helpers import watch_ready

STATUS_SPEC = QuerySpec(
    source="openalex",
    kind=QueryKind.ID_LIST,
    text="https://openalex.org/W1",
    purpose=QueryPurpose.STATUS,
)


def _factories(stub: StatusStub) -> dict[str, SourceFactory]:
    return {"openalex": SourceFactory(StatusStub.kinds, lambda _s, _c: stub)}


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    watch_ready(project, agent, human, mock_sources)
    return project


def _state(p: Project) -> tuple[Any, ...]:
    return (
        prisma_flow(p).model_dump(mode="json"),
        corpus_size(p),
        [w.id for w in list_works(p)],
        {k: v.value for k, v in final_outcomes(p).items()},
        search_counts(p).model_dump(mode="json"),
        [r.query_id for r in search_report(p).rows],
    )


def test_status_runs_invisible_to_prisma_and_corpus(ready: Project) -> None:
    in_cycle(ready, noop_hook)
    plain = _state(ready)

    ready.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    runs: list[str] = []
    stub = StatusStub()
    in_cycle(ready, status_query_hook(STATUS_SPEC, runs, _factories(stub), None), records=[])
    assert len(runs) == 1 and stub.specs == [STATUS_SPEC]
    after = _state(ready)
    # The replay returns nothing and the planned queries are reused, so the status query and run
    # leave every count unchanged but the replay's own two planned runs.
    assert after[:4] == plain[:4]
    assert after[4]["queries"] == plain[4]["queries"]
    assert after[4]["runs"] == plain[4]["runs"] + 2
    assert after[5] == plain[5]


def test_status_run_is_not_a_cycle_search_run(ready: Project) -> None:
    runs: list[str] = []
    summary = in_cycle(ready, status_query_hook(STATUS_SPEC, runs, _factories(StatusStub()), None))
    assert runs and runs[0] not in summary.run_ids
    assert summary.counts[0].runs == 2  # the two planned queries only
    [view] = cycles(ready)
    assert view.complete_sources == ("openalex",)


def test_status_query_needs_open_cycle(ready: Project) -> None:
    factories = _factories(StatusStub())
    system = ready.system_actor()
    with pytest.raises(FactoryValidationError) as none:
        register_query(ready, system, STATUS_SPEC, sources=factories)
    assert none.value.issues[0].field == "cycle_id"
    with pytest.raises(FactoryValidationError):
        register_query(ready, system, STATUS_SPEC, sources=factories, cycle_id="wcy_" + "0" * 26)
    summary = in_cycle(ready, noop_hook)  # now a finished cycle
    with pytest.raises(FactoryValidationError) as finished:
        register_query(ready, system, STATUS_SPEC, sources=factories, cycle_id=summary.cycle_id)
    assert finished.value.issues[0].field == "cycle_id"
    assert not any(
        e.type == "query.registered" and e.payload["spec"]["purpose"] == "status"
        for e in read_all(ready.paths.events_dir, ready.catalog)
    )


def test_status_query_kind_is_id_list_or_filter(ready: Project) -> None:
    keyword = STATUS_SPEC.model_copy(update={"kind": QueryKind.KEYWORD})
    fields: list[str] = []

    def hook(project: Project, cycle_id: str, _w: tuple[str, ...]) -> tuple[str, ...]:
        wide = SourceFactory(frozenset(QueryKind), lambda _s, _c: StatusStub())
        with pytest.raises(FactoryValidationError) as err:
            register_query(
                project,
                project.system_actor(),
                keyword,
                sources={"openalex": wide},
                cycle_id=cycle_id,
            )
        fields.extend(i.field for i in err.value.issues)
        return ()

    in_cycle(ready, hook)
    assert "kind" in fields


def test_status_authorised_only_by_its_open_cycle(ready: Project) -> None:
    seen: list[list[str]] = []

    def hook(project: Project, cycle_id: str, _w: tuple[str, ...]) -> tuple[str, ...]:
        seen.append(
            [i.field for i in search_authorization(project, STATUS_SPEC, deviation_id=None)]
        )
        waived = search_authorization(project, STATUS_SPEC, deviation_id=None, cycle_id=cycle_id)
        seen.append([i.field for i in waived])
        return ()

    in_cycle(ready, hook)
    assert seen[0] == ["query"]  # unplanned without a cycle
    assert seen[1] == []


def test_status_run_archives_raw_pages(ready: Project) -> None:
    runs: list[str] = []
    in_cycle(ready, status_query_hook(STATUS_SPEC, runs, _factories(StatusStub()), None))
    events = read_all(ready.paths.events_dir, ready.catalog)
    pages = [
        e for e in events if e.type == "search.page_archived" and e.payload["run_id"] == runs[0]
    ]
    assert len(pages) == 1 and pages[0].payload["raw_blob"]
    done = [e for e in events if e.type == "search.run_finished" and e.payload["run_id"] == runs[0]]
    assert done[0].payload["status"] == "complete"


@pytest.mark.anyio
async def test_agent_cannot_register_status_query(
    settings: Settings, project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    clock.advance(timedelta(milliseconds=1))
    sources = mock_sources(
        openalex=[openalex_item(title="T", author="A B", published="2023-01-05", openalex_id="W1")]
    )
    server = build_server(settings, clock=clock, sources=dict(sources))
    async with Client(server) as client:
        res = await client.call_tool(
            "search_run",
            {
                "project": "demo",
                "source": "openalex",
                "query": "W1",
                "kind": "id_list",
                "purpose": "status",
                "role": "screener-a",
                "model": "claude-opus-5-5",
                "skill": "rf-screen",
            },
        )
    block = res.content[0]
    assert isinstance(block, TextContent)
    body = json.loads(block.text)
    assert body["ok"] is False and body["errors"][0]["field"] == "purpose"
