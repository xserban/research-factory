"""Projection of the lineage graph (slice 3b, plan G2-D Task 1).

Events are recorded directly, as the other index tests do. Every entry is invented.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.index.default import PROJECTION_VERSION
from factory.index.index import OMITTED_WHEN_EMPTY
from factory.services.context import Project
from tests.lineage_payloads import IDA, ITEM, REL, REL2, REX, SRC, TGT, decided, idea, stated
from tests.test_references_index import FUZZY, OTHER, REX2, _decide, _extract, _resolve
from tests.test_references_model import CITED, WORK, resolution


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def _record(project: Project, type_: str, payload: Any, actor: Actor | None = None) -> Event:
    model = project.catalog.get(type_).payload.model_validate(payload)
    actor = actor or project.human_actor()
    blob = project.blobs.put_json(payload) if actor.kind == "agent" else None
    event = project.events.make(type_, model, actor, input_blob=blob)
    project.record([event])
    return event


def _edges(project: Project) -> list[tuple[Any, ...]]:
    return _rows(
        project,
        "SELECT edge_id, edge_type, source, target, base_status, basis, live, decision "
        "FROM graph_edges ORDER BY edge_id",
    )


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "65"


def test_new_tables_are_omitted_when_empty() -> None:
    assert {"graph_nodes", "graph_edges"} <= OMITTED_WHEN_EMPTY


def test_resolved_link_becomes_cites_edge(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1, confidence="identifier"), resolution(2, work_id=OTHER)])
    assert _edges(project) == [
        ("cit:" + REX + ":1", "cites", WORK, CITED, "stated", REX + ":1", 1, None),
        ("cit:" + REX + ":2", "cites", WORK, OTHER, "stated", REX + ":2", 1, None),
    ]
    assert _rows(project, "SELECT node_id, node_type FROM graph_nodes ORDER BY node_id") == [
        (n, "paper") for n in sorted([CITED, OTHER, WORK])
    ]


def test_unconfirmed_link_is_not_an_edge(project: Project) -> None:
    _extract(project)
    _resolve(project, [FUZZY])
    assert _edges(project) == []
    assert _rows(project, "SELECT * FROM graph_nodes") == []


def test_cites_follow_link_decisions_and_liveness(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1), FUZZY])
    _decide(project, "propose-confirm", OTHER, None)  # a proposal changes nothing
    assert [e[0] for e in _edges(project)] == ["cit:" + REX + ":1"]
    _decide(project, "confirm", OTHER, "human")
    assert [(e[0], e[4], e[7]) for e in _edges(project)] == [
        ("cit:" + REX + ":1", "stated", None),
        ("cit:" + REX + ":2", "confirmed", "confirm"),
    ]
    _decide(project, "reject", None, "human")
    # the link was never resolved by the matcher, so its rejection leaves no edge at all
    assert [e[0] for e in _edges(project)] == ["cit:" + REX + ":1"]
    _extract(project, REX2, n=1)  # a second extraction of the work: the first one's edges go
    assert [(e[0], e[6]) for e in _edges(project)] == [("cit:" + REX + ":1", 0)]


def test_relation_becomes_edge_and_supersession_clears_live(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", stated(), agent)
    assert _edges(project) == [(REL, "builds-on", SRC, TGT, "stated", ITEM, 1, None)]
    _record(project, "relation.proposed", stated(relation_id=REL2, supersedes=REL), agent)
    assert [(e[0], e[6]) for e in _edges(project)] == [(REL, 0), (REL2, 1)]


def test_decision_folded(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", stated(), agent)
    _record(project, "relation.decided", decided(decision="reject"))
    assert _edges(project)[0][7] == "reject"
    _record(project, "relation.decided", decided(decision="confirm"))
    assert _edges(project)[0][7] == "confirm"
    _record(project, "relation.decided", decided(decision="confirm"), agent)  # not a human
    assert _edges(project)[0][7] == "confirm"


def test_idea_and_members_are_nodes(project: Project, agent: Actor) -> None:
    _record(project, "idea.proposed", idea(), agent)
    _record(project, "relation.proposed", stated(target=IDA, resolved_target=IDA), agent)
    nodes = dict(_rows(project, "SELECT node_id, node_type FROM graph_nodes"))
    assert nodes[IDA] == "idea" and nodes[SRC] == "paper"
    assert all(t == "paper" for n, t in nodes.items() if n != IDA)


def test_chain_runs_both_handlers(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", stated(), agent)
    _extract(project)
    _resolve(project, [resolution(1)])
    assert len(_rows(project, "SELECT * FROM relations")) == 1
    assert len(_rows(project, "SELECT * FROM reference_links")) == 1
    assert len(_edges(project)) == 2


def test_rebuild_identical_graph_tables(project: Project, agent: Actor) -> None:
    _extract(project)
    _resolve(project, [resolution(1), FUZZY])
    _decide(project, "confirm", OTHER, "human")
    _record(project, "idea.proposed", idea(), agent)
    _record(project, "relation.proposed", stated(), agent)
    _record(project, "relation.decided", decided(decision="reject"))
    before = (
        _edges(project),
        _rows(project, "SELECT node_id, node_type, event_id FROM graph_nodes ORDER BY node_id"),
        project.index.state_hash(),
    )
    project.index.rebuild()
    after = (
        _edges(project),
        _rows(project, "SELECT node_id, node_type, event_id FROM graph_nodes ORDER BY node_id"),
        project.index.state_hash(),
    )
    assert before == after


def test_traversal_reads_use_indexes(project: Project) -> None:
    project.index.sync()
    with project.index.connect() as conn:
        for column, index in (
            ("source", "ix_graph_edges_source_type"),
            ("target", "ix_graph_edges_target_type"),
        ):
            plan = " ".join(
                str(row)
                for row in conn.execute(
                    text(
                        "EXPLAIN QUERY PLAN SELECT * FROM graph_edges "
                        f"WHERE {column} = 'x' AND edge_type = 'cites'"
                    )
                ).all()
            )
            assert index in plan


def test_reject_of_a_matcher_resolved_link_keeps_the_edge_marked(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1)])
    payload = {
        "extraction_id": REX,
        "ordinal": 1,
        "decision": "reject",
        "work_id": None,
        "rationale": "invented rationale",
        "quotes": [],
        "confirmed_by": "human",
    }
    _record(project, "reference.resolution_decided", payload)
    assert [(e[0], e[7]) for e in _edges(project)] == [("cit:" + REX + ":1", "reject")]
