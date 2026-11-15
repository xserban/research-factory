from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionLevel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.model.work_ids import arxiv_id_from_doi
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
from tests.helpers import arxiv_atom, bind_ids, openalex_item

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
    result = add_seeds(
        project,
        agent,
        specs,
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    assert [outcome.seed_id for outcome in result.written] == ["SEED01", "NEG01", "SEED02"]
    assert result.rejected == []


def test_arxiv_seed_resolves_via_id_list_probe_query(
    project: Project, agent: Actor, mock_sources: SourcesFor, http_log: list[httpx.Request]
) -> None:
    sources = mock_sources(arxiv=arxiv_atom([("2301.01234v2", "Linear attention", 2023, "Ada")]))
    result = add_seeds(
        project,
        agent,
        [_positive(arxiv="2301.01234v2")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
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
    result = add_seeds(
        project,
        agent,
        [_positive(doi="10.1000/xyz")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    [outcome] = result.written
    assert outcome.work_id is not None and outcome.reason is None
    assert any("doi:10.1000/xyz" in url for url in _requested(http_log))


def test_datacite_doi_uses_arxiv_route(
    project: Project, agent: Actor, mock_sources: SourcesFor, http_log: list[httpx.Request]
) -> None:
    sources = mock_sources(arxiv=arxiv_atom([("2301.01234v1", "Linear attention", 2023, "Ada")]))
    result = add_seeds(
        project,
        agent,
        [_positive(doi="10.48550/arXiv.2301.01234")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    assert result.written[0].work_id is not None
    [url] = _requested(http_log)
    assert "id_list=2301.01234" in url
    assert "doi:" not in url


def test_unresolvable_seed_is_recorded_with_reason(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    result = add_seeds(
        project,
        agent,
        [_positive(openalex="W999")],
        sources=mock_sources(),
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
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
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
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
    first = add_seeds(
        project,
        agent,
        [_positive(arxiv="2301.01234v2")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    assert first.written[0].seed_id == "SEED01"
    result = add_seeds(
        project,
        agent,
        [_positive(doi="https://doi.org/10.48550/arXiv.2301.01234")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
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
    add_seeds(
        project,
        agent,
        [_positive(openalex="W42")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    result = add_seeds(
        project,
        agent,
        [_positive(openalex="https://openalex.org/w42")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    assert result.rejected[0].issues[0].field == "openalex"
    assert result.rejected[0].issues[0].reason == "duplicate of SEED01"


def test_probe_records_stay_out_of_the_corpus(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    sources = mock_sources(openalex=[_openalex_item()])
    add_seeds(
        project,
        agent,
        [_positive(doi="10.1000/xyz")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
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
    add_seeds(
        project,
        agent,
        [_positive(doi="10.1000/xyz")],
        sources=sources,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
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
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    before = project.index.state_hash()
    assert project.index.rebuild() == before


# --- Seed admission: an explained miss looked up by its identifier (plan 5a, task 4) ---


def _admission_seed(project: Project, human: Actor, mock_sources: SourcesFor, n: int) -> str:
    """A positive seed whose DOI no search finds, explained as a seed-admission miss."""
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
    [outcome] = add_seeds(
        project,
        human,
        [spec],
        sources=mock_sources(),
        decision_ids=bind_ids(project, human, DecisionLevel.SEEDS),
    ).written
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
    [outcome] = add_seeds(
        explore_project,
        human,
        [spec],
        sources=mock_sources(),
        decision_ids=bind_ids(explore_project, human, DecisionLevel.SEEDS),
    ).written
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
    assert check.found_by_search is False
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


def test_lookup_source_missing_rejects_item_and_writes_nothing_for_it(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    only_arxiv = {"arxiv": mock_sources()["arxiv"]}
    result = add_seeds(
        project,
        agent,
        [
            _positive(arxiv="2301.01234"),
            _positive(doi="10.1000/xyz"),
            _positive(arxiv="2301.09999"),
        ],
        sources=only_arxiv,
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    assert [item.index for item in result.rejected] == [1]
    assert result.rejected[0].issues[0].field == "source"
    assert [o.seed_id for o in result.written] == ["SEED01", "SEED02"]
    assert len(_events_of(project, "seed.added")) == 2


def test_repeat_explanation_is_refused(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    seed_id = _admission_seed(explore_project, human, mock_sources, 9)
    with pytest.raises(FactoryValidationError) as caught:
        explain_seed_miss(explore_project, human, seed_id, "again", ProvenanceMethod.SEED_ADMISSION)
    assert [issue.field for issue in caught.value.issues] == ["seed_id"]
    assert seed_id not in str(caught.value)
    assert len(_events_of(explore_project, "seed.miss_explained")) == 1


def test_seed_check_equals_the_pairwise_loop(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    specs = [
        _positive(doi="10.1000/p1"),
        _positive(arxiv="2301.01234"),
        _positive(doi="10.48550/arXiv.2302.00002"),
        _positive(doi="10.1000/absent"),
    ]
    add_seeds(
        explore_project,
        human,
        specs,
        sources=mock_sources(),
        decision_ids=bind_ids(explore_project, human, DecisionLevel.SEEDS),
    )
    sources = mock_sources(
        openalex=[_openalex_for(1), _openalex_for(2)],
        arxiv=arxiv_atom(
            [
                ("2301.01234v1", "Linear attention", 2023, "Ada"),
                ("2302.00002v1", "Other", 2023, "Bo"),
            ]
        ),
    )
    for source in ("openalex", "arxiv"):
        spec = QuerySpec(source=source, kind=QueryKind.KEYWORD, text="attention")
        query_id = register_query(explore_project, human, spec, sources=sources)
        run_query(explore_project, query_id, sources=sources)
    corpus = list_works(explore_project)
    assert len(corpus) >= 3

    def arxiv_of(work: Any) -> str | None:
        if work.identifiers.arxiv:
            return str(work.identifiers.arxiv)
        return arxiv_id_from_doi(work.identifiers.doi) if work.identifiers.doi else None

    def oracle(spec: SeedSpec) -> str | None:
        keys = spec.identity_keys()
        for work in corpus:
            if "doi" in keys and work.identifiers.doi == keys["doi"]:
                return str(work.id)
            if "arxiv" in keys and arxiv_of(work) == keys["arxiv"]:
                return str(work.id)
        return None

    checks = seed_check(explore_project)
    assert [c.matched_work for c in checks] == [oracle(s) for s in specs]
    assert sum(c.matched_work is not None for c in checks) >= 2


# --- seeds by PMID (plan pmid-seeds S1)


def test_pmid_only_seed_is_valid_and_normalised() -> None:
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Doe 2020", pmid=" PMID: 31452104 ")
    assert spec.pmid == "31452104"
    assert spec.identity_keys() == {"pmid": "31452104"}
    assert SeedSpec(kind=SeedKind.POSITIVE, cite="x", pmid="pmid:7").pmid == "7"


@pytest.mark.parametrize("bad", ["abc", "12a", "0", "000", "PMID 12", "-5", "1.5", "PMC123"])
def test_bad_pmid_is_refused_at_the_boundary(bad: str) -> None:
    with pytest.raises(ValidationError):
        SeedSpec(kind=SeedKind.POSITIVE, cite="x", doi="10.1000/a", pmid=bad)


def test_pmid_joins_the_other_identity_keys() -> None:
    keys = SeedSpec(kind=SeedKind.POSITIVE, cite="x", doi="10.1000/A", pmid="12").identity_keys()
    assert keys == {"doi": "10.1000/a", "pmid": "12"}


def test_dump_omits_an_absent_pmid_so_old_events_are_unchanged() -> None:
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Zhou 2023", doi="10.1000/xyz")
    dumped = spec.model_dump(mode="json")
    assert "pmid" not in dumped
    assert dumped == {
        "kind": "positive",
        "cite": "Zhou 2023",
        "doi": "10.1000/xyz",
        "arxiv": None,
        "openalex": None,
        "why": "",
    }
    old = SeedSpec.model_validate(dumped)
    assert old == spec and old.model_dump_json() == spec.model_dump_json()
    with_pmid = SeedSpec(kind=SeedKind.POSITIVE, cite="x", pmid="5").model_dump(mode="json")
    assert with_pmid["pmid"] == "5"


def test_pmid_seed_resolves_through_pubmed_id_list() -> None:
    from factory.services.seeds import _lookup_query

    spec = _positive(pmid="31452104")
    query = _lookup_query(spec)
    assert (query.source, query.kind, query.text) == ("pubmed", QueryKind.ID_LIST, "31452104")
    assert _lookup_query(spec, QueryPurpose.SEED).purpose is QueryPurpose.SEED


def test_pmid_is_the_last_route() -> None:
    from factory.services.seeds import _lookup_query

    assert _lookup_query(_positive(pmid="1", arxiv="2301.01234")).source == "arxiv"
    assert _lookup_query(_positive(pmid="1", doi="10.1000/a")).source == "openalex"
    assert _lookup_query(_positive(pmid="1", openalex="W3")).source == "openalex"


def test_duplicate_pmid_is_rejected() -> None:
    existing = [("SEED01", _positive(pmid="31452104"))]
    issues = _spec_issues(_positive(pmid="PMID:31452104"), existing)
    assert [(i.field, i.reason) for i in issues] == [("pmid", "duplicate of SEED01")]


def test_seed_is_matched_to_a_corpus_work_by_pmid() -> None:
    from factory.services.seeds import _matching_work

    keys = _positive(pmid="12").identity_keys()
    position = {"rf:a": 0, "rf:b": 1}
    assert _matching_work(keys, None, {}, {}, {"12": "rf:b"}, position) == "rf:b"
    assert _matching_work(keys, None, {}, {}, {"13": "rf:b"}, position) is None


def test_pmid_leading_zeros_are_stripped() -> None:
    from factory.model.work_ids import normalize_pmid, work_pmid_key

    assert SeedSpec(kind=SeedKind.POSITIVE, cite="x", pmid="PMID: 0031452104").pmid == "31452104"
    assert normalize_pmid("007") == "7"
    assert work_pmid_key("0031452104") == "31452104"
    assert work_pmid_key("PMC1") is None
    assert work_pmid_key(None) is None


def test_blank_pmid_is_tolerated_like_a_blank_doi() -> None:
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="x", doi="10.1000/a", pmid="  ")
    assert spec.pmid is None
    assert "pmid" not in spec.model_dump()
    with pytest.raises(ValueError):
        SeedSpec(kind=SeedKind.POSITIVE, cite="x", pmid="")


def test_work_side_pmid_with_zeros_matches_the_seed_key() -> None:
    from factory.model.work_ids import work_pmid_key
    from factory.services.seeds import _matching_work

    key = work_pmid_key("0031452104")
    assert key is not None
    assert _matching_work({"pmid": "31452104"}, None, {}, {}, {key: "rf:w-1"}, {"rf:w-1": 0}) == (
        "rf:w-1"
    )
