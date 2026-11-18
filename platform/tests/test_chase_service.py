"""Citation chase rounds: refusals, the round record, runs, resumption and provenance (plan 5a)."""

import httpx
import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.chase import CHASE_CHUNK, ChaseDirection
from factory.model.decisions import DecisionLevel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.chase import (
    chase_queries,
    chase_rounds,
    chase_sources,
    search_chase,
)
from factory.services.context import Project
from factory.services.search import get_work, list_works, register_query, run_query
from factory.services.seeds import add_seeds, seed_check
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from factory.sources.registry import SourceFactory
from tests.helpers import SourcesFor, _of_type, bind_ids, openalex_item
from tests.screening_helpers import _citing, _corpus, _events, _ordinary, _settle


def _flaky_openalex() -> dict[str, SourceFactory]:
    """OpenAlex whose first page is good and whose second is not JSON: a PARTIAL, resumable run."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "*":
            page = {
                "meta": {"count": 2, "next_cursor": "c2"},
                "results": [_citing(901)],
            }
            return httpx.Response(200, json=page)
        return httpx.Response(200, text="<html>not json</html>")

    polite = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )
    return {
        "openalex": SourceFactory(
            OpenAlexSource.kinds, lambda s, c: OpenAlexSource(polite, clock=c, mailto=s.mailto)
        )
    }


# --- The pure query builder ---


def test_chase_queries_chunks_and_prefixes() -> None:
    ids = [f"W{n}" for n in range(120, 0, -1)]
    texts = chase_queries((ChaseDirection.BACKWARD, ChaseDirection.FORWARD), ids)

    assert len(texts) == 6
    assert texts[0].startswith("cited_by:") and texts[3].startswith("cites:")
    for text in texts:
        prefix, _, body = text.partition(":")
        assert prefix in {"cited_by", "cites"}
        chunk = body.split("|")
        assert 1 <= len(chunk) <= CHASE_CHUNK
        assert chunk == sorted(chunk)
    assert sum(len(t.partition(":")[2].split("|")) for t in texts[:3]) == 120


def test_chase_queries_follow_direction_order_and_skip_absent_directions() -> None:
    texts = chase_queries((ChaseDirection.FORWARD,), ["W2", "W1"])
    assert texts == ["cites:W1|W2"]
    assert chase_queries((ChaseDirection.BACKWARD,), []) == []


def test_chase_queries_map_direction_to_citation_relation() -> None:
    """BACKWARD names the works the sources cite (`cited_by:`); FORWARD names the works citing
    them (`cites:`). Each direction yields only its own prefix."""
    ids = ["W2", "W1"]
    backward = chase_queries((ChaseDirection.BACKWARD,), ids)
    forward = chase_queries((ChaseDirection.FORWARD,), ids)
    assert backward == ["cited_by:W1|W2"]
    assert forward == ["cites:W1|W2"]
    assert all(text.startswith("cited_by:") for text in backward)
    assert all(text.startswith("cites:") for text in forward)


# --- Refusals write nothing ---


def test_chase_refused_while_pending(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    ordinary = _ordinary(project)
    _settle(project, agent, human, protocol_id, leave=ordinary[0])
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        search_chase(
            project,
            human,
            [ChaseDirection.BACKWARD],
            sources=mock_sources(openalex=[_citing(900)]),
        )

    assert "1 works still pending" in " ".join(i.reason for i in exc.value.issues)
    assert len(_events(project)) == before


def test_chase_within_pending_tolerance_records_the_tolerated_work(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import factory.services.chase as chase_module
    from factory.model.protocol import UnscreenedTolerance

    protocol_id = _corpus(project, agent, human, mock_sources)
    ordinary = _ordinary(project)
    _settle(project, agent, human, protocol_id, leave=ordinary[0])
    monkeypatch.setattr(
        chase_module, "pending_tolerance", lambda _p: UnscreenedTolerance(fewer_than=2)
    )

    summary = search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD],
        sources=mock_sources(openalex=[_citing(900)]),
    )

    assert summary.tolerated_pending == [ordinary[0]]
    [event] = _of_type(project, "chase.round_started")
    assert event.payload["tolerated_pending"] == [ordinary[0]]


def test_chase_without_tolerated_works_omits_the_field(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    search_chase(
        project, human, [ChaseDirection.BACKWARD], sources=mock_sources(openalex=[_citing(900)])
    )

    [event] = _of_type(project, "chase.round_started")
    assert "tolerated_pending" not in event.payload


def test_chase_refused_without_includes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id, verdict="exclude")
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        search_chase(
            project,
            human,
            [ChaseDirection.BACKWARD],
            sources=mock_sources(openalex=[_citing(900)]),
        )

    assert [i.field for i in exc.value.issues] == ["works"]
    assert len(_events(project)) == before


def test_chase_refused_without_direction(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        search_chase(project, human, [], sources=mock_sources(openalex=[]))

    assert [i.field for i in exc.value.issues] == ["directions"]
    assert len(_events(project)) == before


def test_unplanned_chase_query_refused(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    spec = QuerySpec(
        source="openalex",
        kind=QueryKind.FILTER,
        text="cites:W1",
        purpose=QueryPurpose.CHASE,
    )
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        register_query(project, human, spec, sources=mock_sources(openalex=[]))

    assert [i.field for i in exc.value.issues] == ["query"]
    assert len(_events(project)) == before


# --- Sources: chasable and unchasable works ---


def test_unchasable_work_reported_not_queried(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    no_id = openalex_item(
        title="No identifier", author="Ada Zhou", published="2021-01-01", openalex_id="W777"
    )
    no_id.pop("id")
    protocol_id = _corpus(project, agent, human, mock_sources, extra=[no_id])
    _settle(project, agent, human, protocol_id)

    chasable, unchasable = chase_sources(project)
    assert len(unchasable) == 1 and len(chasable) >= 1
    assert chasable == sorted(chasable) and unchasable == sorted(unchasable)

    summary = search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD, ChaseDirection.FORWARD],
        sources=mock_sources(openalex=[_citing(900)]),
    )

    assert summary.unchasable == unchasable
    assert set(summary.from_works) == set(chasable)
    [round_] = chase_rounds(project)
    assert round_.unchasable == tuple(unchasable)
    assert all("W777" not in text for text in round_.queries)


# --- A chase round is recorded, then run ---


def test_chase_records_round_then_runs(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    before = len(_events(project))

    summary = search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD, ChaseDirection.FORWARD],
        sources=mock_sources(openalex=[_citing(900)]),
    )

    new = _events(project)[before:]
    types = [e.type for e in new]
    assert types[0] == "chase.round_started"
    k = len(summary.runs)
    assert k == 2
    assert types[1 : 1 + k] == ["query.registered"] * k
    assert "search.run_started" in types[1 + k :]
    assert summary.new_works == 1
    assert summary.round_id.startswith("chs_")

    [citing_id] = [w.id for w in list_works(project) if w.identifiers.openalex == "W900"]
    citing = get_work(project, citing_id)
    assert citing is not None
    assert citing.provenance and all(
        p.method is ProvenanceMethod.CITATION_CHASE for p in citing.provenance
    )
    assert len(citing.provenance) == 2  # both directions returned it


def test_chase_queries_name_their_round(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    summary = search_chase(
        project, human, [ChaseDirection.FORWARD], sources=mock_sources(openalex=[_citing(900)])
    )
    registered = _of_type(project, "query.registered")
    chase = [e for e in registered if e.payload["spec"]["purpose"] == "chase"]  # type: ignore[index]
    assert chase and all(e.refs[-1] == summary.round_id for e in chase)


def test_chase_from_given_works(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    chasable, _ = chase_sources(project)
    summary = search_chase(
        project,
        human,
        [ChaseDirection.FORWARD],
        sources=mock_sources(openalex=[_citing(900)]),
        from_works=chasable[:2],
    )
    assert summary.from_works == chasable[:2]
    [round_] = chase_rounds(project)
    assert list(round_.from_works) == chasable[:2]
    assert len(round_.queries) == 1 and round_.queries[0].count("|") == 1


def test_chase_refuses_works_outside_the_includes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    chasable, _ = chase_sources(project)
    before = len(_events(project))
    for given in ([*chasable[:1], "rf:z1999-nobody-00000000"], []):
        with pytest.raises(FactoryValidationError) as exc:
            search_chase(
                project,
                human,
                [ChaseDirection.FORWARD],
                sources=mock_sources(openalex=[_citing(900)]),
                from_works=given,
            )
        assert "from_works" in [i.field for i in exc.value.issues]
    assert len(_events(project)) == before


def test_chase_round_is_queryable_as_recorded(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    summary = search_chase(
        project,
        human,
        [ChaseDirection.FORWARD],
        sources=mock_sources(openalex=[_citing(900)]),
    )

    [round_] = chase_rounds(project)
    assert round_.round_id == summary.round_id
    assert round_.directions == (ChaseDirection.FORWARD,)
    assert round_.from_works == tuple(summary.from_works)
    openalex_ids = [
        w.identifiers.openalex for w in list_works(project) if w.id in summary.from_works
    ]
    assert round_.queries == tuple(
        chase_queries((ChaseDirection.FORWARD,), [i for i in openalex_ids if i])
    )


def test_interrupted_chase_run_resumes_within_round(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    summary = search_chase(
        project,
        human,
        [ChaseDirection.FORWARD],
        sources=_flaky_openalex(),
    )

    [partial] = summary.runs
    assert partial.status is RunStatus.PARTIAL
    assert partial.resume_token is not None

    resumed = run_query(
        project,
        partial.query_id,
        sources=mock_sources(openalex=[_citing(901)]),
        resume_run=partial.run_id,
    )

    assert resumed.status is RunStatus.COMPLETE
    assert len(chase_rounds(project)) == 1


def test_agent_round_carries_provenance(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    search_chase(
        project,
        agent,
        [ChaseDirection.BACKWARD],
        sources=mock_sources(openalex=[_citing(900)]),
    )

    [round_event] = _of_type(project, "chase.round_started")
    assert round_event.actor.kind == "agent"
    assert round_event.actor.model == agent.model
    assert round_event.actor.skill == agent.skill
    assert round_event.input_blob is not None
    assert project.blobs.get_json(round_event.input_blob) == {"directions": ["backward"]}


def test_chase_found_seed_counts_as_search_find(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Citing 900", doi="10.1000/c900")
    sources = mock_sources(openalex=[_citing(900)])
    [outcome] = add_seeds(
        project,
        human,
        [spec],
        sources=sources,
        decision_ids=bind_ids(project, human, DecisionLevel.SEEDS),
    ).written
    search_chase(project, human, [ChaseDirection.BACKWARD], sources=sources)

    [check] = [c for c in seed_check(project) if c.seed_id == outcome.seed_id]
    assert (check.status, check.found_by_search) == ("retrieved", True)
