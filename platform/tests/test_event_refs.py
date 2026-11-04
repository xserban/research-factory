"""The projected `event_refs` table, and the lookups that read it instead of scanning `LIKE`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.search import QueryKind, QuerySpec
from factory.services.context import Project
from factory.services.protocol import (
    is_snowball_round,
    record_deviation,
    registered_deviation,
    registered_round,
)
from factory.services.search import register_query
from tests.helpers import SourcesFor, ready_protocol


def old_registered_deviation(project: Project, query_id: str) -> str | None:
    """The `LIKE` scan the refs table replaced; kept as the oracle."""
    with project.index.connect() as conn:
        events = conn.execute(
            text("SELECT refs FROM events WHERE type = 'query.registered' AND refs LIKE :pattern"),
            {"pattern": f'%"{query_id}"%'},
        ).all()
        for (refs,) in events:
            for ref in json.loads(str(refs)):
                known = conn.execute(
                    text("SELECT 1 FROM deviations WHERE deviation_id = :d"), {"d": ref}
                ).one_or_none()
                if known is not None:
                    return str(ref)
    return None


def old_registered_round(project: Project, query_id: str) -> str | None:
    """The `LIKE` scan the refs table replaced; kept as the oracle."""
    with project.index.connect() as conn:
        events = conn.execute(
            text("SELECT refs FROM events WHERE type = 'query.registered' AND refs LIKE :pattern"),
            {"pattern": f'%"{query_id}"%'},
        ).all()
    for (refs,) in events:
        for ref in json.loads(str(refs)):
            if str(ref).startswith("snw_") and is_snowball_round(project, str(ref)):
                return str(ref)
    return None


def event_refs(project: Project) -> list[tuple[str, int, str, str]]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT event_id, position, ref, type FROM event_refs ORDER BY event_id, position")
        ).all()
    return [(str(a), int(b), str(c), str(d)) for a, b, c, d in rows]


def snapshot(events_dir: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(events_dir.rglob("*.jsonl"))}


def planned_spec(project: Project) -> QuerySpec:
    return QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")


def test_event_refs_equal_each_events_refs_in_order(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, project.human_actor(), mock_sources)
    project.index.sync()
    events = read_all(project.paths.events_dir, project.catalog)
    expected = [
        (e.id, i, ref, e.type)
        for e in sorted(events, key=lambda e: e.id)
        for i, ref in enumerate(e.refs)
    ]
    assert expected, "the fixture log has events with refs"
    assert event_refs(project) == expected


def test_event_refs_rebuild_is_deterministic(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, project.human_actor(), mock_sources)
    project.index.sync()
    before = event_refs(project)
    project.index.rebuild()
    assert event_refs(project) == before


def test_registered_lookups_match_the_old_scan(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, project.human_actor(), mock_sources)
    sources = mock_sources(openalex=[])
    deviation_id = record_deviation(
        project, agent, description="d", reason="r", affects=("queries",)
    )
    planned = register_query(project, agent, planned_spec(project), sources=sources)
    deviated = register_query(
        project,
        agent,
        QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="transformers"),
        sources=sources,
        deviation_id=deviation_id,
    )
    project.index.sync()
    assert registered_deviation(project, deviated) == deviation_id
    assert registered_deviation(project, planned) is None
    for query_id in (planned, deviated, "qry_missing"):
        assert registered_deviation(project, query_id) == old_registered_deviation(
            project, query_id
        )
        assert registered_round(project, query_id) == old_registered_round(project, query_id)


def test_register_query_unknown_round_writes_nothing(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, project.human_actor(), mock_sources)
    before = snapshot(project.paths.events_dir)
    with pytest.raises(FactoryValidationError) as caught:
        register_query(
            project,
            agent,
            planned_spec(project),
            sources=mock_sources(openalex=[]),
            round_id="snw_nope",
        )
    assert [i.field for i in caught.value.issues] == ["round_id"]
    assert snapshot(project.paths.events_dir) == before


def test_register_query_unknown_deviation_writes_nothing(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, project.human_actor(), mock_sources)
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="transformers")
    before = snapshot(project.paths.events_dir)
    with pytest.raises(FactoryValidationError) as caught:
        register_query(
            project, agent, spec, sources=mock_sources(openalex=[]), deviation_id="dev_other"
        )
    assert [i.field for i in caught.value.issues] == ["deviation_id"]
    assert snapshot(project.paths.events_dir) == before
