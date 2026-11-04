"""Discovery record and report (slice 4a ruling 10; Review Focus 4; acceptance 5, 6, 11)."""

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection
from factory.model.inbox import Basis, ResolveStatus
from factory.model.screening import Channel
from factory.model.search import QueryKind, QuerySpec
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.discovery import (
    Route,
    WorkDiscovery,
    _route,
    discovery,
    discovery_report,
)
from factory.services.prisma import prisma_flow
from factory.services.probe import run_probe
from factory.services.protocol import record_deviation
from factory.services.search import register_query, run_query
from tests.helpers import SourcesFor, openalex_item, record_pilot_question
from tests.inbox_helpers import Keyed, capture, link_item, resolve
from tests.test_chase_service import _citing, _corpus, _settle

DOI = "10.1000/x1"


def _item(author: str = "Ada Zhou", openalex_id: str = "W501") -> dict[str, Any]:
    return openalex_item(
        title="A shared paper",
        author=author,
        published="2021-01-01",
        openalex_id=openalex_id,
        doi=DOI,
    )


def _search(
    project: Project, mock_sources: SourcesFor, items: list[dict[str, Any]], actor: Actor | None
) -> None:
    sources = mock_sources(openalex=items)
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="shared")
    query_id = register_query(project, actor or project.human_actor(), query, sources=sources)
    run_query(project, query_id, sources=sources, actor=actor)


def _by_id(project: Project) -> dict[str, WorkDiscovery]:
    return {record.work_id: record for record in discovery(project)}


def test_capture_before_search_surfaces_first(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    project = explore_project
    [item_id] = capture(project, human, DOI)
    _search(project, mock_sources, [_item()], None)
    [outcome] = resolve(project, human, Keyed(openalex={f"doi:{DOI}": [_item()]}))
    assert outcome.status is ResolveStatus.IN_CORPUS

    [record] = discovery(project)
    assert record.routes == (Route.DATABASE, Route.SUPPLIED_HUMAN)
    assert record.first_route is Route.SUPPLIED_HUMAN
    assert record.first_actor_kind == "human"
    report = discovery_report(project)
    assert report.overlaps == {"database+supplied-human": 1}
    assert report.by_first_route == {
        Route.SUPPLIED_HUMAN: {"identified": 1, "ta-included": 0, "in-evidence": 0}
    }
    assert item_id.startswith("inb_")


def test_search_before_capture_surfaces_database(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    project = explore_project
    _search(project, mock_sources, [_item()], human)
    capture(project, human, DOI)
    resolve(project, human, Keyed(openalex={f"doi:{DOI}": [_item()]}))
    [record] = discovery(project)
    assert (record.first_route, record.first_actor_kind) == (Route.DATABASE, "human")


def test_absorbed_work_routes_fold(
    explore_project: Project, human: Actor, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = explore_project
    _search(project, mock_sources, [_item()], None)
    capture(project, agent, DOI, basis=Basis(kind="knowledge"), channel=Channel.MCP)
    other = _item(author="Cy Park", openalex_id="W777")
    [outcome] = resolve(project, human, Keyed(openalex={f"doi:{DOI}": [other]}))
    assert outcome.status is ResolveStatus.IN_CORPUS
    assert len(discovery(project)) == 2  # two stored works before dedup

    dedup_run(project)

    [record] = discovery(project)
    assert record.routes == (Route.DATABASE, Route.SUPPLIED_AGENT_KNOWLEDGE)
    assert (record.first_route, record.first_actor_kind) == (Route.DATABASE, "system")


def test_actor_kind_of_run_start(explore_project: Project, mock_sources: SourcesFor) -> None:
    _search(explore_project, mock_sources, [_item()], None)
    [record] = discovery(explore_project)
    assert (record.first_route, record.first_actor_kind) == (Route.DATABASE, "system")
    assert record.sources == ("openalex",)


def test_probe_runs_never_count(
    explore_project: Project, human: Actor, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = explore_project
    probe = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="shared")
    record_pilot_question(project, agent)
    run_probe(project, agent, [probe], sources=mock_sources(openalex=[_item()]))
    assert discovery(project) == []
    _search(project, mock_sources, [_item()], human)
    [record] = discovery(project)
    assert record.routes == (Route.DATABASE,)


def test_chase_route_and_direction(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    dedup_run(project)
    search_chase(
        project, human, [ChaseDirection.BACKWARD], sources=mock_sources(openalex=[_citing(901)])
    )
    chased = [r for r in discovery(project) if r.first_route is Route.CHASE_BACKWARD]
    assert len(chased) == 1
    assert chased[0].first_actor_kind == "human"


def test_chase_and_snowball_told_apart_by_round_ref() -> None:
    snowball = {
        "snw_B": ("backward", None, "agent"),
        "snw_F": ("forward", "chs_F", "human"),
    }
    common: dict[str, Any] = {
        "snowball": snowball,
        "delegated": {"chs_F": "snw_F"},
        "chase_actor": {"chs_C": "human", "chs_F": "human"},
        "items": {},
    }

    def route(refs: list[str], text: str = "cited_by:W1") -> tuple[Route, str]:
        s = _route("citation-chase", "openalex", text, refs, "ev_1", "system", **common)
        return s.route, s.actor_kind

    assert route(["qry_1", "P@1", "snw_B"], "snowball-round") == (Route.SNOWBALL_BACKWARD, "agent")
    assert route(["qry_1", "P@1", "chs_F"], "cites:W1") == (Route.SNOWBALL_FORWARD, "human")
    assert route(["qry_1", "P@1", "chs_C"], "cites:W1") == (Route.CHASE_FORWARD, "human")
    assert route(["qry_1", "P@1", "chs_C"]) == (Route.CHASE_BACKWARD, "human")
    assert route(["qry_1"]) == (Route.CHASE_BACKWARD, "system")


def test_columns_sum_to_totals(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    capture(project, other_session_human, "10.2000/s1")
    deviation = record_deviation(project, human, description="Supplied link", reason="Colleague.")
    resolve(
        project,
        other_session_human,
        Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}),
        deviation_id=deviation,
    )
    _settle(project, agent, human, protocol_id)

    report = discovery_report(project)
    flow = prisma_flow(project)

    assert report.levels == ("identified", "ta-included", "in-evidence")
    assert report.totals["identified"] == flow.screened
    assert report.totals["ta-included"] == flow.included
    for level in report.levels:
        assert sum(c[level] for c in report.by_first_route.values()) == report.totals[level]
        assert sum(c[level] for c in report.by_first_actor.values()) == report.totals[level]
    assert report.by_first_route[Route.SUPPLIED_HUMAN]["identified"] == 1


def test_report_is_rebuild_stable(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    project = explore_project
    capture(project, human, DOI)
    _search(project, mock_sources, [_item()], None)
    resolve(project, human, Keyed(openalex={f"doi:{DOI}": [_item()]}))
    before = discovery_report(project).model_dump_json()
    records = discovery(project)
    project.index.rebuild()
    assert discovery_report(project).model_dump_json() == before
    assert discovery(project) == records
