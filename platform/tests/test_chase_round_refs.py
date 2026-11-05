"""Chase queries are linked to their round by the ref they carry; the text rule is the fallback."""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection, ChaseRoundStarted
from factory.model.search import QueryKind, QueryPurpose, QueryRegistered, QuerySpec
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.protocol import recorded_round
from factory.services.search import list_works, register_query
from factory.services.trace import trace
from tests.document_helpers import events_of_type
from tests.helpers import SourcesFor, _setup
from tests.screening_helpers import _citing, _corpus, _settle

TEXT = "cited_by:W1|W2"


def _spec(text: str = TEXT) -> QuerySpec:
    return QuerySpec(
        source="openalex", kind=QueryKind.FILTER, text=text, purpose=QueryPurpose.CHASE
    )


def _round(project: Project, actor: Actor, source: str) -> str:
    round_id = project.ids.new("chs")
    payload = ChaseRoundStarted(
        round_id=round_id,
        directions=(ChaseDirection.BACKWARD,),
        from_works=(source,),
        unchasable=(),
        queries=(TEXT,),
    )
    project.record([project.events.make("chase.round_started", payload, actor, refs=(round_id,))])
    return round_id


def _query(project: Project, actor: Actor, *rounds: str) -> str:
    query_id = project.ids.new("qry")
    payload = QueryRegistered(query_id=query_id, spec=_spec(), interface="openalex")
    project.record(
        [project.events.make("query.registered", payload, actor, refs=(query_id, *rounds))]
    )
    return query_id


def test_chase_query_refs_name_round(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    summary = search_chase(
        project, human, [ChaseDirection.FORWARD], sources=mock_sources(openalex=[_citing(900)])
    )
    events = [
        e
        for e in events_of_type(project, "query.registered")
        if e.payload["spec"]["purpose"] == "chase"  # type: ignore[index]
    ]
    assert events and all(e.refs[-1] == summary.round_id for e in events)
    assert recorded_round(project, summary.round_id) == "chase"


def test_identical_texts_link_by_ref(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    source = sorted(w.id for w in list_works(project))[0]
    r1, r2 = _round(project, human, source), _round(project, human, source)
    # Both rounds are recorded before either query: the text rule would give both to r2.
    q1, q2 = _query(project, human, r1), _query(project, human, r2)
    for round_id, query_id in ((r1, q1), (r2, q2)):
        back = trace(project, query_id)
        assert [c.id for c in back.children if c.kind == "chase_round"] == [round_id]
        forward = trace(project, round_id, direction="forward")
        assert [c.id for c in forward.children] == [query_id]


def test_legacy_log_links_by_text(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    source = sorted(w.id for w in list_works(project))[0]
    r1 = _round(project, human, source)
    q1 = _query(project, human)
    r2 = _round(project, human, source)
    q2 = _query(project, human)
    for round_id, query_id in ((r1, q1), (r2, q2)):
        back = trace(project, query_id)
        assert [c.id for c in back.children if c.kind == "chase_round"] == [round_id]


def test_register_query_accepts_chase_round_and_refuses_unknown(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    source = sorted(w.id for w in list_works(project))[0]
    round_id = _round(project, human, source)
    sources = mock_sources(openalex=[])
    assert recorded_round(project, round_id) == "chase"
    assert recorded_round(project, "chs_nope") is None
    assert register_query(project, human, _spec(), sources=sources, round_id=round_id)
    with pytest.raises(FactoryValidationError) as caught:
        register_query(project, human, _spec(), sources=sources, round_id="chs_nope")
    assert [i.field for i in caught.value.issues] == ["round_id"]
