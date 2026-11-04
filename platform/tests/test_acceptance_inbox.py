"""Slice 4a acceptance criteria 1-13 on a synthetic pilot-shaped fixture.

The fixture is the settled pilot corpus with three supplied links: one new to the corpus, one
already found by the database search, and one also found by a citation-chase round (a snowball
round needs reference extraction; the chase is the supplementary route the fixture can run
offline, and the discovery record tells the two apart by round reference, see
`test_discovery.test_chase_and_snowball_told_apart_by_round_ref`).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.index.chase import considered_works
from factory.model.chase import ChaseDirection
from factory.model.inbox import ResolveStatus
from factory.model.protocol import protocol_version
from factory.model.screening import Channel, PassLabel
from factory.model.search import QueryKind, QuerySpec
from factory.model.work import ProvenanceMethod
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.dedup import canonical_works, dedup_run
from factory.services.discovery import Route, discovery, discovery_report
from factory.services.inbox import LinkInput, add_links, resolve_links, withdraw_link
from factory.services.prisma import prisma_flow
from factory.services.protocol import current_protocol, record_deviation
from factory.services.screening import join_pass, open_pass, screen_next
from factory.services.search import get_work, register_query, run_query
from factory.services.seeds import seed_check, seed_recall
from factory.services.tasks import complete_task
from factory.services.trace import trace
from tests.helpers import SourcesFor, _setup, pilot_protocol_spec, ready_protocol
from tests.inbox_helpers import (
    KNOWLEDGE,
    Keyed,
    accept_supplied,
    capture,
    link_item,
    raising_sources,
    resolve,
)
from tests.test_chase_service import _citing, _corpus, _settle
from tests.test_extraction_schema import PINNED_P_ID
from tests.test_inbox_screening import NOTE, _n, _search, _seeded, _supply_seed
from tests.test_screening_next import _draw


def _events(project: Project, type_: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == type_]


@dataclass(frozen=True)
class Scenario:
    new_work: str
    in_corpus_item: str
    chased_work: str


def _scenario(
    project: Project, agent: Actor, human: Actor, supplier: Actor, mock_sources: SourcesFor
) -> Scenario:
    protocol_id = _corpus(project, agent, human, mock_sources)
    items = capture(project, supplier, "10.2000/s1", "10.1000/p2", "10.1000/c901", note=NOTE)
    deviation = record_deviation(project, human, description="Supplied links", reason="Ana.")
    keyed = Keyed(
        openalex={
            "doi:10.2000/s1": [link_item(1)],
            "doi:10.1000/p2": [link_item(2, doi="10.1000/p2", title="Paper 2")],
            "doi:10.1000/c901": [_citing(901)],
        }
    )
    outcomes = resolve(project, supplier, keyed, deviation_id=deviation)
    assert [o.status for o in outcomes] == [
        ResolveStatus.NEW,
        ResolveStatus.IN_CORPUS,
        ResolveStatus.NEW,
    ]
    dedup_run(project)
    _settle(project, agent, human, protocol_id)
    search_chase(
        project, human, [ChaseDirection.BACKWARD], sources=mock_sources(openalex=[_citing(901)])
    )
    dedup_run(project)
    new_work, chased = outcomes[0].work_id, outcomes[2].work_id
    assert new_work is not None and chased is not None
    return Scenario(new_work=new_work, in_corpus_item=items[1], chased_work=chased)


def test_ac1_capture_validation(project: Project, human: Actor, agent: Actor) -> None:
    links = [
        LinkInput("https://arxiv.org/abs/2103.14030v2"),
        LinkInput("https://doi.org/10.2000/s1"),
        LinkInput("https://example.org/paper"),
    ]
    result = add_links(project, human, links, Channel.CLI)
    assert len(result.written) == 2
    assert result.rejected[0].index == 2
    assert result.rejected[0].issues[0].reason == "unsupported-link"
    assert len(_events(project, "inbox.link_added")) == 2
    agent_result = add_links(project, agent, [LinkInput("10.2000/s2")], Channel.MCP)
    assert agent_result.written == []
    assert len(_events(project, "inbox.link_added")) == 2


def test_ac2_offline_capture_without_protocol(project: Project, human: Actor) -> None:
    assert current_protocol(project) is None
    [item_id] = capture(project, human, "10.2000/s1")
    assert item_id.startswith("inb_")
    assert _events(project, "query.registered") == []


def test_ac3_gate(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    [human_item] = capture(project, human, "10.2000/s1")
    [outcome] = resolve(project, human, Keyed())
    assert "query" in {i.field for i in outcome.issues}
    assert _events(project, "inbox.link_resolved") == []

    accept_supplied(project, agent, "human")
    [agent_item] = capture(project, agent, "10.2000/s2", basis=KNOWLEDGE)
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)], "doi:10.2000/s2": [link_item(2)]})
    outcomes = {o.item_id: o for o in resolve(project, human, keyed)}
    assert outcomes[human_item].status is ResolveStatus.NEW
    assert outcomes[agent_item].status is None and outcomes[agent_item].issues


def test_ac3_exploratory_ungated(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, "10.2000/s1")
    [free] = resolve(explore_project, human, Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}))
    assert free.status is ResolveStatus.NEW


def test_ac4_provenance_and_unchanged_p_ids(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, "10.2000/s1")
    [outcome] = resolve(explore_project, human, Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}))
    work = get_work(explore_project, outcome.work_id or "")
    assert work is not None
    assert [p.method for p in work.provenance] == [ProvenanceMethod.SUPPLIED]
    assert all(explore_project.blobs.exists(p.raw_blob) for p in work.provenance)
    assert protocol_version(pilot_protocol_spec("Q@aaaaaaaa", "prb_1")) == PINNED_P_ID


def test_ac5_in_corpus_link(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _scenario(project, agent, human, other_session_human, mock_sources)
    flow = prisma_flow(project)
    assert flow.identified_databases == {"openalex": 9}
    [paper2] = [w for w in canonical_works(project) if w.identifiers.doi == "10.1000/p2"]
    record = next(r for r in discovery(project) if r.work_id == paper2.id)
    assert record.routes == (Route.DATABASE, Route.SUPPLIED_HUMAN)
    assert record.first_route is Route.DATABASE


def test_ac6_capture_precedes_search(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    capture(explore_project, human, "10.2000/s1")
    sources = mock_sources(openalex=[link_item(1)])
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="linked")
    query_id = register_query(explore_project, human, query, sources=sources)
    run_query(explore_project, query_id, sources=sources)
    resolve(explore_project, human, Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}))
    [record] = discovery(explore_project)
    assert record.routes == (Route.DATABASE, Route.SUPPLIED_HUMAN)
    assert record.first_route is Route.SUPPLIED_HUMAN


def test_ac7_screening_blindness(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    capture(project, other_session_human, "10.2000/s1", note=NOTE)
    deviation = record_deviation(project, human, description="Supplied link", reason="Ana.")
    [outcome] = resolve(
        project,
        other_session_human,
        Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}),
        deviation_id=deviation,
    )
    _draw(project)
    seen: dict[str, set[str]] = {}
    for _ in range(30):
        result = screen_next(project, agent, PassLabel.A)
        if result.batch is None:
            break
        dumped = result.batch.model_dump_json()
        assert NOTE not in dumped and "supplied" not in dumped and "inb_" not in dumped
        seen.update({str(r["work_id"]): set(r) for r in result.batch.records})
        complete_task(project, agent, result.batch.task_id)
    supplied = seen.pop(outcome.work_id or "")
    assert all(keys == supplied for keys in seen.values())


def test_ac8_pass_b_extension(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5)
    _draw(project)
    open_pass(project, agent, PassLabel.B)
    capture(project, other_session_human, "10.2000/s1")
    deviation = record_deviation(project, human, description="Supplied link", reason="Ana.")
    [outcome] = resolve(
        project,
        other_session_human,
        Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}),
        deviation_id=deviation,
    )
    screen_next(project, agent, PassLabel.B)
    with project.index.connect() as conn:
        assert outcome.work_id in considered_works(conn)


def test_ac9_proposer_is_not_evaluator(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    capture(project, agent, "10.2000/s1", basis=KNOWLEDGE)
    with pytest.raises(FactoryValidationError):
        join_pass(project, agent, PassLabel.A)
    join_pass(project, agent_other, PassLabel.A)
    with pytest.raises(FactoryValidationError):
        add_links(project, agent_other, [LinkInput("10.2000/s2", basis=KNOWLEDGE)], Channel.MCP)
    with pytest.raises(FactoryValidationError):
        resolve_links(project, agent_other, sources=raising_sources())


def test_ac10_supplied_held_out_seed_is_a_miss(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    held_out, development = _seeded(explore_project, human, mock_sources)
    _search(explore_project, human, mock_sources, *(_n(s) for s in development))
    before = seed_recall(explore_project).held_out
    _supply_seed(explore_project, human, _n(held_out))
    check = next(c for c in seed_check(explore_project) if c.seed_id == held_out)
    assert check.status == "supplied"
    assert seed_recall(explore_project).held_out == before == 0.0


def test_ac11_discovery_sums_and_rebuild(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    scenario = _scenario(project, agent, human, other_session_human, mock_sources)
    report = discovery_report(project)
    flow = prisma_flow(project)
    assert report.totals["identified"] == flow.screened
    assert report.totals["ta-included"] == flow.included
    for level in report.levels:
        assert sum(c[level] for c in report.by_first_route.values()) == report.totals[level]
        assert sum(c[level] for c in report.by_first_actor.values()) == report.totals[level]
    chased = next(r for r in discovery(project) if r.work_id == scenario.chased_work)
    assert chased.routes == (Route.CHASE_BACKWARD, Route.SUPPLIED_HUMAN)
    assert chased.first_route is Route.SUPPLIED_HUMAN
    before = report.model_dump_json()
    project.index.rebuild()
    assert discovery_report(project).model_dump_json() == before


def test_ac12_withdrawal(explore_project: Project, human: Actor) -> None:
    [item_id] = capture(explore_project, human, "10.2000/s1")
    withdraw_link(explore_project, human, item_id, "wrong paper")
    assert len(_events(explore_project, "inbox.link_withdrawn")) == 1
    assert resolve(explore_project, human, Keyed()) == []
    [other] = capture(explore_project, human, "10.2000/s2")
    resolve(explore_project, human, Keyed(openalex={"doi:10.2000/s2": [link_item(2)]}))
    with pytest.raises(FactoryValidationError):
        withdraw_link(explore_project, human, other, "too late")
    assert len(_events(explore_project, "inbox.link_withdrawn")) == 1


def test_ac13_trace_reaches_item_and_actor(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    scenario = _scenario(project, agent, human, other_session_human, mock_sources)
    with project.index.connect() as conn:
        decision = conn.execute(
            text("SELECT decision_id FROM decisions WHERE work_id = :w LIMIT 1"),
            {"w": scenario.new_work},
        ).scalar_one()
    stack = [trace(project, str(decision))]
    found = None
    while stack:
        node = stack.pop()
        if node.kind == "inbox_item":
            found = node
            break
        stack.extend(node.children)
    assert found is not None
    assert found.label == "link (doi) captured by human"
    [added] = [e for e in _events(project, "inbox.link_added") if e.payload["item_id"] == found.id]
    assert found.event_id == added.id and added.actor.kind == "human"
