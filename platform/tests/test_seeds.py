from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.project import project_status
from factory.services.search import get_work, list_works, register_query, run_query
from factory.services.seeds import (
    _spec_issues,
    add_seeds,
    admit_seed,
    explain_seed_miss,
    seed_check,
)
from factory.sources.registry import SourceFactory
from tests.helpers import arxiv_atom, openalex_item

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _openalex_item(openalex_id: str = "W1", doi: str | None = "10.1000/xyz") -> dict[str, Any]:
    return openalex_item(
        title="Linear attention",
        author="Ada Zhou",
        published="2023-01-01",
        openalex_id=openalex_id,
        doi=doi,
    )


def _positive(**ids: str) -> SeedSpec:
    return SeedSpec(kind=SeedKind.POSITIVE, cite="Zhou 2023", **ids)


def _requested(http_log: list[httpx.Request]) -> list[str]:
    return [unquote(str(request.url)) for request in http_log]


def test_seed_ids_are_assigned_per_kind(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    sources = mock_sources()
    specs = [
        _positive(doi="10.1000/a"),
        SeedSpec(kind=SeedKind.NEGATIVE, cite="Li 2020", arxiv="2001.00001"),
        _positive(openalex="W5"),
    ]
    result = add_seeds(project, agent, specs, sources=sources)
    assert [outcome.seed_id for outcome in result.written] == ["SEED01", "NEG01", "SEED02"]
    assert result.rejected == []


def test_arxiv_seed_resolves_via_id_list_probe_query(
    project: Project, agent: Actor, mock_sources: SourcesFor, http_log: list[httpx.Request]
) -> None:
    sources = mock_sources(arxiv=arxiv_atom([("2301.01234v2", "Linear attention", 2023, "Ada")]))
    result = add_seeds(project, agent, [_positive(arxiv="2301.01234v2")], sources=sources)
    [outcome] = result.written
    assert outcome.reason is None and outcome.work_id is not None
    assert any("id_list=2301.01234" in url for url in _requested(http_log))
    [work] = list_works(project, include_probe=True)
    assert work.id == outcome.work_id
    assert work.provenance[0].query_id is not None


def test_doi_seed_resolves_via_openalex_filter(
    project: Project, agent: Actor, mock_sources: SourcesFor, http_log: list[httpx.Request]
) -> None:
    sources = mock_sources(openalex=[_openalex_item(doi="10.1000/xyz")])
    result = add_seeds(project, agent, [_positive(doi="10.1000/xyz")], sources=sources)
    [outcome] = result.written
    assert outcome.work_id is not None and outcome.reason is None
    assert any("doi:10.1000/xyz" in url for url in _requested(http_log))


def test_datacite_doi_uses_arxiv_route(
    project: Project, agent: Actor, mock_sources: SourcesFor, http_log: list[httpx.Request]
) -> None:
    sources = mock_sources(arxiv=arxiv_atom([("2301.01234v1", "Linear attention", 2023, "Ada")]))
    result = add_seeds(
        project, agent, [_positive(doi="10.48550/arXiv.2301.01234")], sources=sources
    )
    assert result.written[0].work_id is not None
    [url] = _requested(http_log)
    assert "id_list=2301.01234" in url
    assert "doi:" not in url


def test_unresolvable_seed_is_recorded_with_reason(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    result = add_seeds(project, agent, [_positive(openalex="W999")], sources=mock_sources())
    [outcome] = result.written
    assert outcome.seed_id == "SEED01"
    assert outcome.work_id is None
    assert outcome.reason == "not found in openalex"


def test_seed_without_identifier_rejected_others_written(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    bare = SeedSpec.model_construct(
        kind=SeedKind.POSITIVE, cite="Nobody", doi=None, arxiv=None, openalex=None, why=""
    )
    sources = mock_sources(openalex=[_openalex_item()])
    result = add_seeds(
        project,
        agent,
        [_positive(doi="10.1000/xyz"), bare, _positive(openalex="W9")],
        sources=sources,
    )
    assert [item.index for item in result.rejected] == [1]
    assert result.rejected[0].issues[0].field == "identifier"
    assert [outcome.seed_id for outcome in result.written] == ["SEED01", "SEED02"]


def test_spec_requires_an_identifier() -> None:
    with pytest.raises(ValidationError):
        SeedSpec(kind=SeedKind.POSITIVE, cite="Nobody")


def test_duplicate_seed_in_another_form_is_rejected(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    sources = mock_sources()
    first = add_seeds(project, agent, [_positive(arxiv="2301.01234v2")], sources=sources)
    assert first.written[0].seed_id == "SEED01"
    result = add_seeds(
        project,
        agent,
        [_positive(doi="https://doi.org/10.48550/arXiv.2301.01234")],
        sources=sources,
    )
    assert result.written == []
    [item] = result.rejected
    assert item.issues[0].field == "arxiv"
    assert item.issues[0].reason == "duplicate of SEED01"


def test_spec_issues_compute_identity_keys_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = SeedSpec.identity_keys

    def spy(self: SeedSpec) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(SeedSpec, "identity_keys", spy)
    assert _spec_issues(_positive(arxiv="2301.01234"), []) == []
    assert calls == 1


def test_duplicate_openalex_id_across_forms_is_rejected(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    sources = mock_sources()
    add_seeds(project, agent, [_positive(openalex="W42")], sources=sources)
    result = add_seeds(
        project, agent, [_positive(openalex="https://openalex.org/w42")], sources=sources
    )
    assert result.rejected[0].issues[0].field == "openalex"
    assert result.rejected[0].issues[0].reason == "duplicate of SEED01"


def test_probe_records_stay_out_of_the_corpus(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    sources = mock_sources(openalex=[_openalex_item()])
    add_seeds(project, agent, [_positive(doi="10.1000/xyz")], sources=sources)
    assert list_works(project) == []
    assert len(list_works(project, include_probe=True)) == 1
    assert dedup_run(project).works == 0
    status = project_status(project)
    assert (status.works, status.records) == (0, 0)
    [work] = list_works(project, include_probe=True)
    assert get_work(project, work.id) is not None


def test_agent_seed_events_keep_their_input(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    sources = mock_sources(openalex=[_openalex_item()])
    add_seeds(project, agent, [_positive(doi="10.1000/xyz")], sources=sources)
    events = read_all(project.paths.events_dir, project.catalog)
    seed_events = [e for e in events if e.type.startswith("seed.")]
    assert [e.type for e in seed_events] == ["seed.added", "seed.resolved"]
    assert all(e.input_blob is not None for e in seed_events)


def test_seed_rebuild_equals_incremental(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    sources = mock_sources(openalex=[_openalex_item()])
    add_seeds(
        project,
        agent,
        [_positive(doi="10.1000/xyz"), _positive(openalex="W404")],
        sources=sources,
    )
    before = project.index.state_hash()
    assert project.index.rebuild() == before


# --- Seed admission: an explained miss looked up by its identifier (plan 5a, task 4) ---


def _admission_seed(project: Project, human: Actor, mock_sources: SourcesFor, n: int) -> str:
    """A positive seed whose DOI no search finds, explained as a seed-admission miss."""
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
    [outcome] = add_seeds(project, human, [spec], sources=mock_sources()).written
    explain_seed_miss(
        project, human, outcome.seed_id, "not indexed", ProvenanceMethod.SEED_ADMISSION
    )
    return outcome.seed_id


def _events_of(project: Project, event_type: str) -> list[Any]:
    events = read_all(project.paths.events_dir, project.catalog)
    return [event for event in events if event.type == event_type]


def _admitted_events(project: Project) -> list[Any]:
    return _events_of(project, "seed.admitted")


def _openalex_for(n: int) -> dict[str, Any]:
    return openalex_item(
        title=f"Paper {n}",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )


def test_admission_requires_seed_admission_route(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 9", doi="10.1000/p9")
    [outcome] = add_seeds(explore_project, human, [spec], sources=mock_sources()).written
    explain_seed_miss(explore_project, human, outcome.seed_id, "why", ProvenanceMethod.HAND_SEARCH)
    sources = mock_sources(openalex=[_openalex_for(9)])
    with pytest.raises(FactoryValidationError) as caught:
        admit_seed(explore_project, human, outcome.seed_id, sources=sources)
    assert [issue.field for issue in caught.value.issues] == ["seed_id"]
    assert outcome.seed_id not in str(caught.value)
    assert _admitted_events(explore_project) == []


def test_admission_refuses_agent_actor(
    explore_project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    seed_id = _admission_seed(explore_project, human, mock_sources, 9)
    with pytest.raises(FactoryValidationError) as caught:
        admit_seed(explore_project, agent, seed_id, sources=mock_sources())
    [issue] = caught.value.issues
    assert (issue.field, issue.reason) == ("actor", "seed admission is a human act")
    assert _admitted_events(explore_project) == []


def test_admitted_work_has_seed_admission_provenance_and_checks_retrieved(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    seed_id = _admission_seed(explore_project, human, mock_sources, 9)
    admitted = admit_seed(
        explore_project, human, seed_id, sources=mock_sources(openalex=[_openalex_for(9)])
    )
    assert admitted.work_id is not None
    [check] = seed_check(explore_project)
    assert (check.seed_id, check.status, check.matched_work) == (
        seed_id,
        "retrieved",
        admitted.work_id,
    )
    [work] = list_works(explore_project)
    assert work.id == admitted.work_id
    assert [prov.method for prov in work.provenance] == [ProvenanceMethod.SEED_ADMISSION]


def test_admission_not_found_is_recorded(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    seed_id = _admission_seed(explore_project, human, mock_sources, 9)
    admitted = admit_seed(explore_project, human, seed_id, sources=mock_sources())
    assert admitted.work_id is None
    [check] = seed_check(explore_project)
    assert (check.seed_id, check.status) == (seed_id, "explained")
    [event] = _admitted_events(explore_project)
    assert event.actor.kind == "human"
    assert event.payload["work_id"] is None


def test_admission_twice_refused(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    seed_id = _admission_seed(explore_project, human, mock_sources, 9)
    admit_seed(explore_project, human, seed_id, sources=mock_sources())
    queries_before = _events_of(explore_project, "query.registered")
    with pytest.raises(FactoryValidationError) as caught:
        admit_seed(explore_project, human, seed_id, sources=mock_sources())
    assert seed_id not in str(caught.value)
    assert len(_admitted_events(explore_project)) == 1
    queries_after = _events_of(explore_project, "query.registered")
    assert len(queries_after) == len(queries_before)


def test_admission_refused_when_seed_already_retrieved(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    seed_id = _admission_seed(explore_project, human, mock_sources, 9)
    corpus = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    sources = mock_sources(openalex=[_openalex_for(9)])
    query_id = register_query(explore_project, human, corpus, sources=sources)
    run_query(explore_project, query_id, sources=sources)
    with pytest.raises(FactoryValidationError) as caught:
        admit_seed(explore_project, human, seed_id, sources=sources)
    assert [issue.field for issue in caught.value.issues] == ["seed_id"]
    assert seed_id not in str(caught.value)
    assert _admitted_events(explore_project) == []
