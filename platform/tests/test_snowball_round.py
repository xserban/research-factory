"""Backward snowball rounds (slice 3a, rulings 7, 8, 18, 19, 20): plan, refusals, runs, reflist.

Every entry and work is invented. Two included works carry converted documents with invented
bibliographies; the other included works have no document.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.protocol import SnowballPlan
from factory.model.references import Direction, SnowballRoundStarted
from factory.model.screening import PassLabel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod, WorkType
from factory.model.work_ids import work_id
from factory.services import snowball
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.references import extract_references, list_references
from factory.services.screening import open_pass
from factory.services.search import get_work, list_works, register_query, run_query
from factory.services.seeds import split_seeds
from factory.services.snowball import (
    RoundCandidate,
    plan_round,
    round_runs,
    snowball_queries,
    snowball_round,
    unqueryable_keys,
)
from factory.sources.registry import INTERFACES
from tests.document_helpers import (
    event_bytes,
    events_of_type,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.helpers import SourcesFor, _setup
from tests.references_service_helpers import Lookups, bib_html, oa_item
from tests.test_fulltext_service import _include_all
from tests.test_screening_next import _decide, _draw

PLAN = SnowballPlan(max_backward_rounds=2, max_forward_rounds=1)
LATTICE = ("A lattice is worth sixteen tokens", 2020, "Ana Quillfeather")
ENTRIES_A = [
    "A. Zhou. Paper 2. Journal of Tests, 2020. doi:10.1000/p2.",
    "A. Quillfeather. A lattice is worth sixteen tokens. arXiv:2010.99999v2, 2020.",
    "R. Thornbury. Sparse kernels for tidal data. Imaginary Methods, 2019. doi:10.5555/jim.4.",
    "B. Lee. Efficient reed transformers. Reed Conference, 2021.",
]
BODY_A = ["Prior work {cite:1}, {cite:2} and {cite:3}; see {cite:4} and {cite:2}."]
ENTRIES_B = ["A. Quillfeather. A lattice is worth sixteen tokens. arXiv:2010.99999, 2020."]
BODY_B = ["As in {cite:1}."]
NO_SOURCE = work_id(
    title="Sparse kernels for tidal data", authors=["Thornbury"], year=2019, doi="10.5555/jim.4"
)


def _lookups(**kw: Any) -> Lookups:
    return Lookups(
        openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")],
        arxiv={"2010.99999": LATTICE},
        **kw,
    )


def _amend(project: Project, agent: Actor, plan: SnowballPlan) -> None:
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_copy(update={"snowball_plan": plan})
    amend_protocol(project, agent, spec, reason="declare snowballing", semantic=True, effects={})


@pytest.fixture
def world(project: Project, corpus: None, agent: Actor) -> tuple[str, str]:
    """Two included works with extracted references; returns (work A, work B)."""
    work_a, work_b = promoted_works(project)[:2]
    fetched_document(project, work_a, bib_html(ENTRIES_A, BODY_A))
    fetched_document(project, work_b, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    summary = extract_references(project, agent, None, sources=_lookups().sources())
    assert len(summary.extractions) == 2
    return work_a, work_b


@pytest.fixture
def planned(project: Project, agent: Actor, world: tuple[str, str]) -> tuple[str, str]:
    _amend(project, agent, PLAN)
    return world


def _lattice(project: Project) -> str:
    page = list_references(project, state=None, work_id=None, after=0, limit=100)
    return next(i.work_id for i in page.items if i.arxiv == "2010.99999" and i.work_id)


def _sources(**kw: Any) -> Any:
    return _lookups(**kw).sources()


def _issue_fields(error: FactoryValidationError) -> list[str]:
    return [issue.field for issue in error.issues]


# --- Plan (dry run) ---


def test_dry_run_writes_nothing_and_ranks_by_cited_by(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    work_a, work_b = planned
    before = event_bytes(project)
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources())
    assert event_bytes(project) == before
    assert result.round_id is None and result.runs == [] and result.new_works == 0
    assert result.state.allowed and result.state.round_no == 1 and result.state.rule == PLAN
    counts = [c.cited_by_included for c in result.candidates]
    assert counts == [2, 1, 1]
    first, *rest = result.candidates
    assert first.work_key == _lattice(project) and first.arxiv == "2010.99999"
    assert {citer for citer, _ in first.citing_anchors} == {work_a, work_b}
    assert [c.work_key for c in rest] == sorted(c.work_key for c in rest)
    no_source = next(c for c in result.candidates if c.no_source_record)
    assert no_source.work_key.startswith("rex_") and no_source.work_key.endswith(":3")
    assert no_source.work_id == NO_SOURCE
    texts = {(q.source, q.kind, q.text) for q in result.queries}
    assert texts == {
        ("openalex", QueryKind.FILTER, "openalex:W501"),
        ("arxiv", QueryKind.ID_LIST, "2010.99999"),
        ("reflist", QueryKind.ID_LIST, no_source.work_key),
    }
    assert all(q.purpose is QueryPurpose.CHASE for q in result.queries)
    plan = plan_round(project, Direction.BACKWARD)
    assert plan.sources == sorted([work_a, work_b])
    assert len(plan.extraction_ids) == 2
    assert plan.candidates == result.candidates


def test_no_document_work_is_listed_not_blocking(
    project: Project, planned: tuple[str, str]
) -> None:
    plan = plan_round(project, Direction.BACKWARD)
    others = sorted(set(promoted_works(project)) - set(planned))
    assert others and plan.unextracted == [(w, "no-document") for w in others]
    assert plan.state.allowed


# --- Refusals ---


def test_round_refused_without_plan_in_pilot(
    project: Project, agent: Actor, world: tuple[str, str]
) -> None:
    before = event_bytes(project)
    state = plan_round(project, Direction.BACKWARD).state
    assert not state.allowed and state.rule is None
    assert [i.field for i in state.refusals] == ["snowball_plan"]
    with pytest.raises(FactoryValidationError) as caught:
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert "snowball_plan" in _issue_fields(caught.value)
    assert event_bytes(project) == before


@pytest.fixture
def explore_world(
    explore_project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> Project:
    """An exploratory project screened like `corpus`, with work A converted and extracted."""
    project = explore_project
    assert snowball._rigor_mode(project) is RigorMode.EXPLORATORY
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    split_seeds(project, random_seed=7)  # a pilot's probe draws the split; exploratory does not
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)
    work_a = promoted_works(project)[0]
    fetched_document(project, work_a, bib_html(ENTRIES_A, BODY_A))
    run_convert(project, make_registry())
    extract_references(project, agent, None, sources=_lookups().sources())
    return project


def test_exploratory_allowed_without_plan_rule_none(explore_world: Project, agent: Actor) -> None:
    project = explore_world
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert result.state.allowed and result.state.rule is None
    [event] = events_of_type(project, "snowball.round_started")
    assert SnowballRoundStarted.model_validate(event.payload).rule == "none"
    blob = json.loads(project.blobs.get(str(event.input_blob)).decode())
    assert blob == {"direction": "backward", "dry_run": False}


def test_failed_previous_round_does_not_trigger_the_no_yield_stop(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    snowball_round(
        project, agent, Direction.BACKWARD, sources=_sources(fail_openalex=True), dry_run=False
    )
    _screen_new(project, agent, "exclude")
    state = plan_round(project, Direction.BACKWARD).state
    assert "previous_round" not in [i.field for i in state.refusals]
    assert state.allowed and state.round_no == 2
    assert any("failed or partial" in note for note in state.notes)


def test_failed_previous_round_keeps_the_maximum(
    project: Project, agent: Actor, world: tuple[str, str]
) -> None:
    _amend(project, agent, SnowballPlan(max_backward_rounds=1, max_forward_rounds=0))
    snowball_round(
        project, agent, Direction.BACKWARD, sources=_sources(fail_openalex=True), dry_run=False
    )
    _screen_new(project, agent, "exclude")
    state = plan_round(project, Direction.BACKWARD).state
    assert [i.field for i in state.refusals] == ["round_no"]


def _unqueryable_only(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = RoundCandidate(
        work_key="rf:d2020-x-00000000",
        work_id="rf:d2020-x-00000000",
        cited_by_included=1,
        citing_anchors=(),
        no_source_record=False,
        doi="10.1000/a|b",
    )
    monkeypatch.setattr(snowball, "snowball_candidates", lambda _p, _s: [bad])


def test_round_with_only_unqueryable_candidates_is_refused(
    project: Project, agent: Actor, planned: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _unqueryable_only(monkeypatch)
    plan = plan_round(project, Direction.BACKWARD)
    assert plan.queries == [] and plan.unqueryable == ["rf:d2020-x-00000000"]
    assert [(i.field, i.reason) for i in plan.state.refusals] == [
        ("candidates", "no queryable candidate")
    ]
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError):
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert event_bytes(project) == before


def test_gate_is_called_even_without_queries(
    project: Project, agent: Actor, planned: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _unqueryable_only(monkeypatch)
    calls: list[QuerySpec] = []

    def gate(_p: Project, spec: QuerySpec, **_kw: Any) -> list[ValidationIssue]:
        calls.append(spec)
        return [ValidationIssue("protocol", "scripted refusal")]

    monkeypatch.setattr(snowball, "search_authorization", gate)
    with pytest.raises(FactoryValidationError) as caught:
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert len(calls) == 1 and calls[0].purpose is QueryPurpose.CHASE
    assert {"candidates", "protocol"} <= set(_issue_fields(caught.value))


def test_refused_at_maximum(project: Project, agent: Actor, world: tuple[str, str]) -> None:
    _amend(project, agent, SnowballPlan(max_backward_rounds=0, max_forward_rounds=0))
    before = event_bytes(project)
    state = plan_round(project, Direction.BACKWARD).state
    assert not state.allowed and [i.field for i in state.refusals] == ["round_no"]
    with pytest.raises(FactoryValidationError):
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert event_bytes(project) == before


def _screen_new(project: Project, agent: Actor, verdict: str) -> list[str]:
    """Both passes give `verdict` to every work still pending; returns those works."""
    current = current_protocol(project)
    assert current is not None
    pending = sorted(w for w, o in final_outcomes(project).items() if o is Outcome.PENDING)
    criterion = "EX01" if verdict == "exclude" else None
    for work in pending:
        for label in ("A", "B"):
            _decide(
                project, agent, work, label, "screening", verdict, criterion, current.protocol_id
            )
    assert all(o is not Outcome.PENDING for o in final_outcomes(project).values())
    return pending


def test_refused_while_pending(project: Project, agent: Actor, planned: tuple[str, str]) -> None:
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert result.new_works == 3
    before = event_bytes(project)
    state = plan_round(project, Direction.BACKWARD).state
    assert not state.allowed and state.round_no == 2
    [pending] = [i for i in state.refusals if i.field == "screening"]
    assert NO_SOURCE in pending.reason
    with pytest.raises(FactoryValidationError):
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert event_bytes(project) == before


def test_refused_while_unextracted(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    third = sorted(set(promoted_works(project)) - set(planned))[0]
    fetched_document(project, third, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    before = event_bytes(project)
    plan = plan_round(project, Direction.BACKWARD)
    assert (third, "not-extracted") in plan.unextracted
    [refusal] = plan.state.refusals
    assert refusal.field == "unextracted" and third in refusal.reason
    with pytest.raises(FactoryValidationError):
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert event_bytes(project) == before


def test_refused_when_previous_round_had_no_included_work(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    _screen_new(project, agent, "exclude")
    state = plan_round(project, Direction.BACKWARD).state
    assert "previous_round" in [i.field for i in state.refusals]
    assert not state.allowed


def test_previous_round_with_an_included_work_does_not_stop(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    _screen_new(project, agent, "include")
    state = plan_round(project, Direction.BACKWARD).state
    assert "previous_round" not in [i.field for i in state.refusals]
    assert "screening" not in [i.field for i in state.refusals]


def test_rule_without_stop_flag_allows_after_empty_round(
    project: Project, agent: Actor, world: tuple[str, str]
) -> None:
    _amend(project, agent, PLAN.model_copy(update={"stop_when_no_new_included": False}))
    snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    _screen_new(project, agent, "exclude")
    state = plan_round(project, Direction.BACKWARD).state
    assert "previous_round" not in [i.field for i in state.refusals]


# --- Recorded round ---


def test_round_event_precedes_every_query(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert result.round_id is not None and result.state.allowed
    [event] = events_of_type(project, "snowball.round_started")
    payload = SnowballRoundStarted.model_validate(event.payload)
    assert payload.round_id == result.round_id and payload.round_no == 1
    assert payload.rule == PLAN and payload.via.value == "document-reference-list"
    assert event.actor == agent and event.input_blob is not None
    assert [c.work_key for c in payload.candidates] == [c.work_key for c in result.candidates]
    assert len(payload.candidates[0].cited_by) == 2
    registered = events_of_type(project, "query.registered")
    chase = [e for e in registered if e.payload["spec"]["purpose"] == "chase"]  # type: ignore[index]
    assert len(chase) == 3 and all(e.id > event.id for e in chase)
    assert all(e.refs[-1] == result.round_id for e in chase)
    assert [e.payload["spec"]["text"] for e in chase] == list(payload.queries)  # type: ignore[index]
    assert {r.run_id for r in result.runs} == set(round_runs(project, result.round_id))


def test_candidates_are_pending_after_round_never_included(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    outcomes = final_outcomes(project)
    keys = [c.work_id for c in result.candidates]
    assert all(k is not None and outcomes[k] is Outcome.PENDING for k in keys)
    corpus = {w.id for w in list_works(project)}
    assert set(keys) <= corpus


def test_prisma_s_fields_on_runs(project: Project, agent: Actor, planned: tuple[str, str]) -> None:
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    by_source = {r.source: r for r in result.runs}
    assert set(by_source) == {"openalex", "arxiv", "reflist"}
    for run in result.runs:
        assert run.status is RunStatus.COMPLETE
        assert run.reported_count == 1 and run.retrieved_count == 1
    registered = events_of_type(project, "query.registered")
    reflist = next(e for e in registered if e.payload["spec"]["source"] == "reflist")  # type: ignore[index]
    assert reflist.payload["interface"] == INTERFACES["reflist"]
    started = events_of_type(project, "search.run_started")
    assert {e.payload["run_id"] for e in started} >= {r.run_id for r in result.runs}
    assert all(e.ts is not None for e in started)


def test_source_error_in_one_query_leaves_others_run(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    sources = _sources(fail_openalex=True)
    result = snowball_round(project, agent, Direction.BACKWARD, sources=sources, dry_run=False)
    status = {r.source: r.status for r in result.runs}
    assert status["openalex"] is RunStatus.FAILED
    assert status["arxiv"] is RunStatus.COMPLETE and status["reflist"] is RunStatus.COMPLETE
    assert result.new_works == 2
    assert len(events_of_type(project, "snowball.round_started")) == 1


def test_reflist_creates_other_type_work_with_entry_key_and_hash_provenance(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    key = next(c.work_key for c in result.candidates if c.no_source_record)
    work = get_work(project, NO_SOURCE)
    assert work is not None and work.type is WorkType.OTHER
    [prov] = work.provenance
    assert prov.source == "reflist" and prov.raw_ref == key
    assert prov.method is ProvenanceMethod.CITATION_CHASE
    page = json.loads(project.blobs.get(prov.raw_blob).decode())
    [entry] = page["entries"]
    extraction, ordinal = key.split(":")
    [extracted] = [
        e
        for e in events_of_type(project, "reference.extracted")
        if e.payload["extraction_id"] == extraction
    ]
    stored = extracted.payload["entries"][int(ordinal) - 1]  # type: ignore[index]
    assert entry["entry_sha256"] == stored["entry_sha256"]  # type: ignore[index]
    assert entry["key"] == key and entry["title"] == "Sparse kernels for tidal data"
    assert ENTRIES_A[2] not in project.blobs.get(prov.raw_blob).decode()


def test_round_waives_only_its_own_texts(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    sources = _sources()
    result = snowball_round(project, agent, Direction.BACKWARD, sources=sources, dry_run=False)
    assert result.round_id is not None
    own = QuerySpec(
        source="openalex", kind=QueryKind.FILTER, text="openalex:W501", purpose=QueryPurpose.CHASE
    )
    # the round's own text is waived only for a query that names the round
    register_query(project, agent, own, sources=sources, round_id=result.round_id)
    for text in ("openalex:W501", "openalex:W999"):
        hand = own.model_copy(update={"text": text})
        with pytest.raises(FactoryValidationError) as caught:
            register_query(project, agent, hand, sources=sources)
        assert "query" in _issue_fields(caught.value)


def test_identically_worded_later_query_is_not_counted(
    explore_world: Project, agent: Actor
) -> None:
    project = explore_world
    sources = _sources()
    result = snowball_round(project, agent, Direction.BACKWARD, sources=sources, dry_run=False)
    assert result.round_id is not None
    runs = set(round_runs(project, result.round_id))
    assert runs == {r.run_id for r in result.runs}
    same = QuerySpec(
        source="openalex", kind=QueryKind.FILTER, text="openalex:W501", purpose=QueryPurpose.CHASE
    )
    query_id = register_query(project, agent, same, sources=sources)
    run_query(project, query_id, sources=sources, actor=agent)
    assert set(round_runs(project, result.round_id)) == runs


def test_id_longer_than_a_query_is_unqueryable() -> None:
    long_doi = _candidate("rf:e2020-x-00000000", doi="10.1000/" + "x" * 395)
    fine = _candidate("rf:f2020-x-00000000", doi="10.1000/ok")
    assert [q.text for q in snowball_queries([long_doi, fine])] == ["doi:10.1000/ok"]
    assert unqueryable_keys([long_doi, fine]) == ["rf:e2020-x-00000000"]


def test_round_refused_when_query_does_not_fit(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    sources = {k: v for k, v in _sources().items() if k != "arxiv"}
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as caught:
        snowball_round(project, agent, Direction.BACKWARD, sources=sources, dry_run=False)
    assert "source" in _issue_fields(caught.value)
    assert event_bytes(project) == before


# --- Queries (pure) ---


def _candidate(key: str, **kw: Any) -> RoundCandidate:
    return RoundCandidate(
        work_key=key,
        work_id=None if key.startswith("rex_") else key,
        cited_by_included=1,
        citing_anchors=(),
        no_source_record=key.startswith("rex_"),
        **kw,
    )


def test_queries_chunk_by_count_and_length() -> None:
    oa = [_candidate(f"rf:a{i:03d}-x-00000000", openalex=f"W{4000000000 + i}") for i in range(70)]
    ax = [_candidate(f"rf:b{i:03d}-x-00000000", arxiv=f"2101.{i:05d}") for i in range(3)]
    doi = [_candidate(f"rf:c{i:03d}-x-00000000", doi=f"10.1000/{i}") for i in range(2)]
    bad = [_candidate("rf:d000-x-00000000", doi="10.1000/a|b")]
    keys = [_candidate(f"rex_01JZ9Q3K5M7N8P0R2S4T6V8W1A:{i}") for i in range(1, 25)]
    queries = snowball_queries([*oa, *ax, *doi, *bad, *keys])
    assert all(len(q.text) <= 400 for q in queries)
    oa_texts = [q.text for q in queries if q.text.startswith("openalex:")]
    assert sum(len(t.split("|")) for t in oa_texts) == 70
    assert all(len(t.split("|")) <= 50 for t in oa_texts)
    assert [q.text for q in queries if q.source == "arxiv"] == ["2101.00000,2101.00001,2101.00002"]
    assert [q.text for q in queries if q.text.startswith("doi:")] == ["doi:10.1000/0|10.1000/1"]
    reflist = [q.text for q in queries if q.source == "reflist"]
    assert sum(len(t.split(",")) for t in reflist) == 24
    assert all("a|b" not in q.text for q in queries)


def test_unconverted_document_blocks_as_not_extracted(
    project: Project, planned: tuple[str, str]
) -> None:
    third = sorted(set(promoted_works(project)) - set(planned))[0]
    fetched_document(project, third, bib_html(ENTRIES_B, BODY_B))
    plan = plan_round(project, Direction.BACKWARD)
    assert (third, "not-extracted") in plan.unextracted and not plan.state.allowed
