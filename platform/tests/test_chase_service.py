"""Citation chase rounds: refusals, the round record, runs, resumption and provenance (plan 5a)."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.chase import CHASE_CHUNK, ChaseDirection
from factory.model.screening import Channel, PassLabel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod
from factory.services.calibration import calibration_items, label_calibration
from factory.services.chase import (
    chase_queries,
    chase_rounds,
    chase_sources,
    search_chase,
)
from factory.services.context import Project
from factory.services.screening import open_pass
from factory.services.search import get_work, list_works, register_query, run_query
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from factory.sources.registry import SourceFactory
from tests.helpers import _setup, openalex_item
from tests.test_screening_next import _decide, _draw

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _of_type(project: Project, name: str) -> list[Event]:
    return [e for e in _events(project) if e.type == name]


def _citing(n: int) -> dict[str, Any]:
    return openalex_item(
        title=f"Citing {n}",
        author="Cai Wu",
        published="2024-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/c{n}",
    )


def _corpus(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    extra: Sequence[dict[str, Any]] = (),
) -> str:
    """A ready pilot protocol, its seeded corpus, the calibration set and both passes opened.

    `extra` records are added to the corpus through the planned query before the draw.
    """
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    if extra:
        spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
        query_id = register_query(project, human, spec, sources=mock_sources(openalex=list(extra)))
        run_query(project, query_id, sources=mock_sources(openalex=list(extra)))
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    return protocol_id


def _settle(
    project: Project,
    agent: Actor,
    human: Actor,
    protocol_id: str,
    *,
    verdict: str = "include",
    leave: str | None = None,
) -> None:
    """Decide every corpus work the same way in both passes, and label every calibration work.

    `leave` names one ordinary work to leave undecided.
    """
    calibration = set(calibration_items(project))
    criterion = "EX01" if verdict == "exclude" else None
    for work in sorted(w.id for w in list_works(project)):
        if work == leave:
            continue
        if work in calibration:
            label_calibration(project, human, work, verdict, criterion, Channel.CLI)
            continue
        _decide(project, agent, work, "A", "screening", verdict, criterion, protocol_id)
        _decide(project, agent, work, "B", "screening", verdict, criterion, protocol_id)


def _ordinary(project: Project) -> list[str]:
    calibration = set(calibration_items(project))
    return sorted(w.id for w in list_works(project) if w.id not in calibration)


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
