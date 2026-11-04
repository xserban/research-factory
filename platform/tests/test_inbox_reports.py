"""Supplied links in PRISMA, methods, trace, check and status (slice 4a; acceptance 5, 13)."""

from __future__ import annotations

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.inbox import ResolveStatus
from factory.services.check import check
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.discovery import Route, discovery_report
from factory.services.inbox import withdraw_link
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import prisma_flow
from factory.services.project import project_status
from factory.services.protocol import record_deviation
from factory.services.trace import TraceNode, agent_trace, trace
from tests.helpers import SourcesFor, ready_protocol
from tests.inbox_helpers import Keyed, accept_supplied, capture, link_item, resolve
from tests.test_chase_service import _corpus, _settle


def _codes(project: Project) -> set[str]:
    return {f.code for f in check(project).findings}


def _find(node: TraceNode, kind: str) -> TraceNode | None:
    if node.kind == kind:
        return node
    for child in node.children:
        found = _find(child, kind)
        if found is not None:
            return found
    return None


def _supplied_corpus(
    project: Project, agent: Actor, human: Actor, supplier: Actor, mock_sources: SourcesFor
) -> tuple[str, str]:
    """The settled pilot corpus plus one new supplied work and one link to a searched work
    (`10.1000/p2`), both resolved under a deviation. Returns (supplied work, item id)."""
    protocol_id = _corpus(project, agent, human, mock_sources)
    [new_item, _again] = capture(project, supplier, "10.2000/s1", "10.1000/p2", note="central")
    deviation = record_deviation(project, human, description="Supplied link", reason="Colleague.")
    keyed = Keyed(
        openalex={
            "doi:10.2000/s1": [link_item(1)],
            "doi:10.1000/p2": [link_item(2, doi="10.1000/p2", title="Paper 2")],
        }
    )
    outcomes = resolve(project, supplier, keyed, deviation_id=deviation)
    assert [o.status for o in outcomes] == [ResolveStatus.NEW, ResolveStatus.IN_CORPUS]
    dedup_run(project)
    _settle(project, agent, human, protocol_id)
    work_id = outcomes[0].work_id
    assert work_id is not None
    return work_id, new_item


def test_prisma_supplied_and_database_counts_database(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _supplied_corpus(project, agent, human, other_session_human, mock_sources)
    flow = prisma_flow(project)
    # The new supplied work counts under "supplied"; the link to a searched work under databases.
    assert flow.identified_other["supplied"] == 1
    assert flow.identified_databases == {"openalex": 9}
    identified = sum(flow.identified_databases.values()) + sum(flow.identified_other.values())
    assert identified - flow.duplicates_removed == flow.screened
    assert sum(flow.excluded.values()) + flow.pending + flow.included == flow.screened
    report = discovery_report(project)
    assert report.overlaps == {"database+supplied-human": 1}


def test_methods_paragraph_matches_discovery(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _supplied_corpus(project, agent, human, other_session_human, mock_sources)
    report = methods_report(project)
    links = report.supplied_links
    assert links is not None
    assert links.captured == {"human": 2, "agent": 0}
    assert links.resolved == {"human": 2, "agent": 0}
    discovery = discovery_report(project)
    assert links.included["human"] == discovery.by_first_route[Route.SUPPLIED_HUMAN]["ta-included"]
    assert links.included["human"] == 1
    rendered = render_methods(report)
    assert "Supplied links. Links captured: human 2, agent 0." in rendered
    assert "screeners did not see how a work was found" in rendered
    assert "central" not in rendered


def test_methods_paragraph_absent_without_inbox(explore_project: Project) -> None:
    report = methods_report(explore_project)
    assert report.supplied_links is None
    assert "Supplied links" not in render_methods(report)


def test_trace_reaches_inbox_item(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    work_id, item_id = _supplied_corpus(project, agent, human, other_session_human, mock_sources)
    with project.index.connect() as conn:
        decision = conn.execute(
            text("SELECT decision_id FROM decisions WHERE work_id = :w LIMIT 1"), {"w": work_id}
        ).scalar_one()

    node = _find(trace(project, str(decision)), "inbox_item")
    assert node is not None
    assert (node.id, node.label) == (item_id, "link (doi) captured by human")
    assert node.event_id.startswith("ev_")
    forward = trace(project, item_id, direction="forward")
    assert [c.id for c in forward.children] == [work_id]
    # The agent view never shows the route.
    assert _find(agent_trace(project, work_id), "inbox_item") is None
    assert "supplied" not in agent_trace(project, work_id).model_dump_json()
    # No inbox ref is reported as a broken link.
    assert "broken-link" not in _codes(project)


def test_check_open_after_screening(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    assert "inbox-open-after-screening" not in _codes(project)
    [item_id] = capture(project, other_session_human, "10.2000/s9")
    finding = next(f for f in check(project).findings if f.code == "inbox-open-after-screening")
    assert (finding.refs, finding.severity) == ([item_id], "warning")
    withdraw_link(project, other_session_human, item_id, "not relevant")
    assert "inbox-open-after-screening" not in _codes(project)


def test_check_resolve_failed(explore_project: Project, human: Actor) -> None:
    [item_id] = capture(explore_project, human, "10.2000/s1")
    assert "inbox-resolve-failed" not in _codes(explore_project)
    resolve(explore_project, human, Keyed(fail=True))
    finding = next(f for f in check(explore_project).findings if f.code == "inbox-resolve-failed")
    assert finding.refs == [item_id]
    resolve(explore_project, human, Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}))
    assert "inbox-resolve-failed" not in _codes(explore_project)


def test_check_supplied_without_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    capture(project, human, "10.2000/s1")
    deviation = record_deviation(project, human, description="Supplied link", reason="Colleague.")
    resolve(
        project,
        human,
        Keyed(openalex={"doi:10.2000/s1": [link_item(1)]}),
        deviation_id=deviation,
    )
    finding = next(f for f in check(project).findings if f.code == "supplied-without-plan")
    assert finding.severity == "warning"
    accept_supplied(project, agent, "human")
    assert "supplied-without-plan" not in _codes(project)


def test_status_counts(explore_project: Project, human: Actor) -> None:
    assert project_status(explore_project).inbox.model_dump() == {
        "open": 0,
        "resolved": 0,
        "withdrawn": 0,
    }
    [a, _b, _c] = capture(explore_project, human, "10.2000/s1", "10.2000/s2", "10.2000/s3")
    withdraw_link(explore_project, human, a, "duplicate")
    resolve(explore_project, human, Keyed(openalex={"doi:10.2000/s2": [link_item(2)]}))
    assert project_status(explore_project).inbox.model_dump() == {
        "open": 0,
        "resolved": 2,
        "withdrawn": 1,
    }
