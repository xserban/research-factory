import threading
from collections.abc import Callable, Mapping
from typing import Any

import pydantic
import pytest
from sqlalchemy import text

from factory.clock import SystemClock
from factory.errors import FactoryError, FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.search import (
    QueryKind,
    QuerySpec,
    RunStatus,
    SearchPageArchived,
    SearchRecordsParsed,
    SearchRunFinished,
    SearchRunStarted,
)
from factory.services.context import Project, open_project
from factory.services.project import project_status
from factory.services.search import (
    RunSummary,
    Shortfall,
    get_work,
    list_works,
    register_query,
    resume_query_id,
    run_query,
)
from factory.sources.base import Source
from factory.sources.registry import SourceFactory, default_sources
from tests.helpers import SESSION, T0

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
REF = "sha256:" + "a" * 64


def _register(project: Project, sources: Mapping[str, SourceFactory], text_: str = "x") -> str:
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text=text_)
    return register_query(project, project.human_actor(), spec, sources=sources)


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _of_type(project: Project, name: str) -> list[Event]:
    return [e for e in _events(project) if e.type == name]


def _pages_of(project: Project, run_id: str) -> list[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT raw_blob FROM pages WHERE run_id = :run ORDER BY ordinal"),
            {"run": run_id},
        ).all()
    return [str(row[0]) for row in rows]


def _run_row(project: Project, run_id: str) -> dict[str, Any] | None:
    with project.index.connect() as conn:
        row = (
            conn.execute(text("SELECT * FROM runs WHERE run_id = :run"), {"run": run_id})
            .mappings()
            .one_or_none()
        )
    return dict(row) if row is not None else None


def test_run_archives_pages_and_records_works(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    qid = _register(explore_project, sources, "linear attention")
    summary = run_query(explore_project, qid, sources=sources)
    assert summary.status == RunStatus.COMPLETE
    assert summary.retrieved_count == 3 and summary.new_works == 3
    st = project_status(explore_project)
    assert (st.works, st.records, st.search.runs, st.search.complete) == (3, 3, 1, 1)
    refs = _pages_of(explore_project, summary.run_id)
    assert len(refs) == 2 and all(explore_project.blobs.exists(ref) for ref in refs)  # R-03
    ids = [w.id for w in list_works(explore_project)]
    assert ids == sorted(ids) and len(ids) == 3


def test_page_archived_event_precedes_its_records(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    summary = run_query(explore_project, _register(explore_project, sources), sources=sources)
    archived = _of_type(explore_project, "search.page_archived")
    parsed = _of_type(explore_project, "search.records_parsed")
    assert len(archived) == 2 and len(parsed) == 2
    # Every page is archived before the adapter returns, so all archives precede all parsing.
    assert max(e.id for e in archived) < min(e.id for e in parsed)
    for page in archived:
        assert page.payload["run_id"] == summary.run_id
        [matching] = [e for e in parsed if e.payload["raw_blob"] == page.payload["raw_blob"]]
        assert page.id < matching.id  # page n is archived before its records are recorded


def test_failure_mid_run_records_partial_with_resume_token(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources(fail_after=1)
    summary = run_query(explore_project, _register(explore_project, sources), sources=sources)
    assert summary.status == RunStatus.PARTIAL
    assert summary.retrieved_count == 2
    assert summary.resume_token == "1"
    assert summary.note is not None and "connection reset" in summary.note
    assert len(_pages_of(explore_project, summary.run_id)) == 1
    st = project_status(explore_project)
    assert (st.works, st.search.partial, st.search.failed) == (2, 1, 0)


def test_resume_continues_and_links_runs(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    qid = _register(explore_project, fake_sources())
    first = run_query(explore_project, qid, sources=fake_sources(fail_after=1))
    second = run_query(explore_project, qid, sources=fake_sources(), resume_run=first.run_id)
    assert second.run_id != first.run_id
    assert second.status == RunStatus.COMPLETE
    assert second.retrieved_count == 1 and second.new_works == 1
    row = _run_row(explore_project, second.run_id)
    assert row is not None and row["resume_of"] == first.run_id
    st = project_status(explore_project)
    assert (st.works, st.records, st.search.runs) == (3, 3, 2)


def test_same_work_from_two_runs_has_two_provenance_rows(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    qid = _register(explore_project, sources)
    first = run_query(explore_project, qid, sources=sources)
    second = run_query(explore_project, qid, sources=sources)
    assert second.new_works == 0 and second.retrieved_count == 3
    st = project_status(explore_project)
    assert (st.works, st.records) == (3, 6)
    work_id = list_works(explore_project)[0].id
    work = get_work(explore_project, work_id)
    assert work is not None
    assert [p.run_id for p in work.provenance] == [first.run_id, second.run_id]


def test_identifiers_from_later_records_fill_gaps(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    qid = _register(explore_project, fake_sources())
    bare = {"title": "Sparse attention", "authors": ["Ben Li"], "year": 2023}
    run_query(explore_project, qid, sources=fake_sources(pages=[[bare]]))
    enriched = {**bare, "openalex": "W123", "abstract": "We study sparsity."}
    run_query(explore_project, qid, sources=fake_sources(pages=[[enriched]]))
    conflicting = {**bare, "openalex": "W999", "abstract": "A different abstract."}
    run_query(explore_project, qid, sources=fake_sources(pages=[[conflicting]]))

    [work] = list_works(explore_project)
    assert work.identifiers.openalex == "W123"  # first seen wins once filled
    assert work.abstract == "We study sparsity."
    assert len(work.provenance) == 3


def test_status_lists_shortfalls(explore_project: Project, fake_sources: SourcesFor) -> None:
    sources = fake_sources(reported=5)
    summary = run_query(explore_project, _register(explore_project, sources), sources=sources)
    assert summary.status == RunStatus.COMPLETE
    assert (summary.reported_count, summary.retrieved_count) == (5, 3)
    assert summary.note is not None
    assert project_status(explore_project).search.shortfalls == [
        Shortfall(
            run_id=summary.run_id,
            source="fake",
            reported_count=5,
            retrieved_count=3,
            note=summary.note,
        )
    ]


def test_duplicate_within_a_run_is_skipped_not_counted_twice(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    pages = [[{"title": "Same paper", "authors": ["Ada Zhou"], "year": 2024}]] * 2
    sources = fake_sources(pages=pages)
    summary = run_query(explore_project, _register(explore_project, sources), sources=sources)
    assert summary.retrieved_count == 1 and summary.skipped == 1
    assert summary.note == "1 duplicate record(s) skipped"
    assert len(_pages_of(explore_project, summary.run_id)) == 2
    assert project_status(explore_project).works == 1


def test_unknown_source_or_kind_is_rejected_and_writes_nothing(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    before = project_status(explore_project).events_total
    human = explore_project.human_actor()
    with pytest.raises(FactoryValidationError) as unknown:
        register_query(
            explore_project,
            human,
            QuerySpec(source="nope", kind=QueryKind.KEYWORD, text="x"),
            sources=sources,
        )
    assert [i.field for i in unknown.value.issues] == ["source"]
    with pytest.raises(FactoryValidationError) as wrong:
        register_query(
            explore_project,
            human,
            QuerySpec(source="fake", kind=QueryKind.FILTER, text="doi:1", filters={"a": "b"}),
            sources=sources,
        )
    assert [i.field for i in wrong.value.issues] == ["kind", "filters"]
    assert project_status(explore_project).events_total == before


def test_openalex_keyword_text_with_a_comma_is_rejected_and_writes_nothing(
    explore_project: Project,
) -> None:
    # A comma would start a second, bogus filter clause in the OpenAlex expression.
    before = project_status(explore_project).events_total
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="vessels, segmentation")
    with pytest.raises(FactoryValidationError) as bad:
        register_query(
            explore_project, explore_project.human_actor(), spec, sources=default_sources()
        )
    assert [i.field for i in bad.value.issues] == ["text"]
    assert "FILTER" in bad.value.issues[0].reason
    assert project_status(explore_project).events_total == before


def test_comma_is_fine_in_a_filter_query_and_in_arxiv_keywords(explore_project: Project) -> None:
    human = explore_project.human_actor()
    sources = default_sources()
    flt = QuerySpec(source="openalex", kind=QueryKind.FILTER, text="doi:10.1/a|10.1/b")
    arxiv = QuerySpec(source="arxiv", kind=QueryKind.KEYWORD, text="all:vessel, segmentation")
    register_query(explore_project, human, flt, sources=sources)
    register_query(explore_project, human, arxiv, sources=sources)


def test_filters_are_accepted_for_openalex(explore_project: Project) -> None:
    spec = QuerySpec(
        source="openalex",
        kind=QueryKind.KEYWORD,
        text="attention",
        filters={"publication_year": "2024"},
    )
    qid = register_query(
        explore_project, explore_project.human_actor(), spec, sources=default_sources()
    )
    [event] = _of_type(explore_project, "query.registered")
    assert event.payload["query_id"] == qid and str(event.payload["interface"]).startswith(
        "OpenAlex"
    )


def test_agent_registered_query_carries_input_blob(
    explore_project: Project, agent: Actor, fake_sources: SourcesFor
) -> None:
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="screening")
    register_query(explore_project, agent, spec, sources=fake_sources())
    [event] = _of_type(explore_project, "query.registered")
    assert event.actor.kind == "agent" and event.input_blob is not None
    assert explore_project.blobs.get_json(event.input_blob) == spec.model_dump(mode="json")


def test_interrupted_run_is_counted(explore_project: Project, fake_sources: SourcesFor) -> None:
    qid = _register(explore_project, fake_sources())
    run_id = explore_project.ids.new("run")
    explore_project.record(
        [
            explore_project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=run_id, query_id=qid),
                explore_project.system_actor(),
                refs=(run_id,),
            )
        ]
    )
    st = project_status(explore_project)
    assert (st.search.runs, st.search.interrupted, st.search.complete) == (1, 1, 0)


def test_search_projection_rebuild_equals_incremental(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    good = fake_sources()
    run_query(explore_project, _register(explore_project, good), sources=good)
    partial = fake_sources(fail_after=1)
    run_query(explore_project, _register(explore_project, partial, "other"), sources=partial)
    before = explore_project.index.state_hash()
    assert explore_project.index.rebuild() == before
    st = project_status(explore_project)
    assert (st.works, st.records) == (3, 5)  # the partial run re-delivers page 0's works


def test_parse_failure_mid_run_is_resumable(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources(parse_fail_at=1)
    qid = _register(explore_project, sources)
    summary = run_query(explore_project, qid, sources=sources)
    assert summary.status == RunStatus.PARTIAL
    assert summary.retrieved_count == 2 and summary.new_works == 2
    assert summary.note is not None and summary.note.startswith("SourceError: ")
    assert summary.resume_token == "1"
    archived = _pages_of(explore_project, summary.run_id)
    parsed = [
        str(e.payload["raw_blob"]) for e in _of_type(explore_project, "search.records_parsed")
    ]
    # Every archived page but the failing one (page 1) has its records recorded.
    assert len(archived) == 2 and parsed == [archived[0]]
    assert project_status(explore_project).works == 2

    resumed = run_query(explore_project, qid, sources=fake_sources(), resume_run=summary.run_id)
    assert resumed.status == RunStatus.COMPLETE
    assert resumed.retrieved_count == 1 and resumed.new_works == 1
    assert project_status(explore_project).works == 3


def test_source_error_raised_by_an_adapter_is_still_recorded(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    """Safety net: an adapter that raises instead of returning is recorded, not lost."""
    sources = fake_sources(raise_at=1)
    summary = run_query(explore_project, _register(explore_project, sources), sources=sources)
    assert summary.status == RunStatus.PARTIAL
    assert summary.note == "SourceError: fake page unreadable"
    assert summary.resume_token is None and summary.retrieved_count == 0
    assert len(_pages_of(explore_project, summary.run_id)) == 1
    assert _of_type(explore_project, "search.records_parsed") == []


def test_unexpected_error_is_recorded_then_reraised(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources(raise_at=0, raise_error=RuntimeError("boom"))
    qid = _register(explore_project, sources)
    with pytest.raises(RuntimeError, match="boom"):
        run_query(explore_project, qid, sources=sources)
    [started] = _of_type(explore_project, "search.run_started")
    row = _run_row(explore_project, str(started.payload["run_id"]))
    assert row is not None
    assert (row["status"], row["note"], row["pages"]) == ("failed", "RuntimeError: boom", 0)


@pytest.mark.parametrize("case", ["unknown", "complete", "other_query", "no_token"])
def test_resume_run_must_be_a_resumable_run_of_this_query(
    explore_project: Project, fake_sources: SourcesFor, case: str
) -> None:
    qid = _register(explore_project, fake_sources())
    other = _register(explore_project, fake_sources(), "other")
    complete = run_query(explore_project, qid, sources=fake_sources())
    resume: str
    if case == "unknown":
        resume = explore_project.ids.new("run")
    elif case == "complete":
        resume = complete.run_id
    elif case == "other_query":
        resume = run_query(explore_project, other, sources=fake_sources(fail_after=1)).run_id
    else:
        resume = run_query(explore_project, qid, sources=fake_sources(raise_at=0)).run_id
    with pytest.raises(FactoryValidationError) as err:
        run_query(explore_project, qid, sources=fake_sources(), resume_run=resume)
    assert [i.field for i in err.value.issues] == ["resume_run"]


def test_run_query_rejects_an_unknown_query(project: Project, fake_sources: SourcesFor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        run_query(project, project.ids.new("qry"), sources=fake_sources())
    assert [i.field for i in err.value.issues] == ["query_id"]


def test_projection_ignores_events_that_do_not_apply(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    summary: RunSummary = run_query(
        explore_project, _register(explore_project, sources), sources=sources
    )
    ghost_run = explore_project.ids.new("run")
    ghost_query = explore_project.ids.new("qry")
    system = explore_project.system_actor()
    explore_project.record(
        [
            explore_project.events.make(
                "search.page_archived",
                SearchPageArchived(
                    run_id=ghost_run, ordinal=0, url="u", fetched_at=T0, raw_blob=REF
                ),
                system,
                refs=(ghost_run,),
            ),
            explore_project.events.make(
                "search.records_parsed",
                SearchRecordsParsed(run_id=ghost_run, raw_blob=REF, records=()),
                system,
                refs=(ghost_run,),
            ),
            explore_project.events.make(
                "search.run_finished",
                SearchRunFinished(
                    run_id=ghost_run, status=RunStatus.FAILED, retrieved_count=0, note="x"
                ),
                system,
                refs=(ghost_run,),
            ),
            explore_project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=ghost_run, query_id=ghost_query),
                system,
                refs=(ghost_run,),
            ),
        ]
    )
    # Known run, but the event repeats an outcome already folded in: each is ignored.
    explore_project.record(
        [
            explore_project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=summary.run_id, query_id=summary.query_id),
                system,
                refs=(summary.run_id,),
            ),
            explore_project.events.make(
                "search.page_archived",
                SearchPageArchived(
                    run_id=summary.run_id, ordinal=0, url="u", fetched_at=T0, raw_blob=REF
                ),
                system,
                refs=(summary.run_id,),
            ),
            explore_project.events.make(
                "search.run_finished",
                SearchRunFinished(
                    run_id=summary.run_id, status=RunStatus.FAILED, retrieved_count=0, note="late"
                ),
                system,
                refs=(summary.run_id,),
            ),
        ]
    )
    st = project_status(explore_project)
    assert (st.search.runs, st.search.complete, st.search.failed, st.works) == (1, 1, 0, 3)
    row = _run_row(explore_project, summary.run_id)
    assert row is not None and (row["status"], row["pages"]) == ("complete", 2)
    assert _run_row(explore_project, ghost_run) is None


def test_resumed_run_with_a_note_says_what_it_resumed_from(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    qid = _register(explore_project, fake_sources())
    first = run_query(explore_project, qid, sources=fake_sources(fail_after=1))
    # Two of five reported records were already delivered; the remainder is one record.
    second = run_query(
        explore_project, qid, sources=fake_sources(reported=5), resume_run=first.run_id
    )
    assert second.retrieved_count == 1 and second.reported_count == 5
    assert second.note == f"resumed from {first.run_id}: 4 of 5 reported not delivered"
    [shortfall] = project_status(explore_project).search.shortfalls
    assert shortfall.run_id == second.run_id


def test_query_whose_adapter_is_gone_is_refused_before_running(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    qid = _register(explore_project, fake_sources())
    with pytest.raises(FactoryValidationError) as err:
        run_query(explore_project, qid, sources={})
    assert [i.field for i in err.value.issues] == ["source"]
    assert project_status(explore_project).search.runs == 0


@pytest.mark.parametrize(
    "fields",
    [
        {"status": RunStatus.RUNNING, "retrieved_count": 0, "note": "x"},
        {"status": RunStatus.COMPLETE, "reported_count": 5, "retrieved_count": 3, "note": None},
        {"status": RunStatus.PARTIAL, "retrieved_count": 0, "note": "  "},
    ],
)
def test_run_finished_payload_must_be_an_explained_outcome(fields: dict[str, Any]) -> None:
    with pytest.raises(pydantic.ValidationError):
        SearchRunFinished(run_id=f"run_{SESSION}", **fields)


def test_query_fields_survive_the_projection_and_reach_the_adapter(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="  sparse  ", limit=2)
    qid = register_query(explore_project, explore_project.human_actor(), spec, sources=sources)
    with explore_project.index.connect() as conn:
        row = (
            conn.execute(
                text(
                    'SELECT source, kind, "text", purpose, "limit" FROM queries WHERE query_id = :q'
                ),
                {"q": qid},
            )
            .mappings()
            .one()
        )
    assert dict(row) == {
        "source": "fake",
        "kind": "keyword",
        "text": "sparse",
        "purpose": "search",
        "limit": 2,
    }
    summary = run_query(explore_project, qid, sources=sources)
    assert summary.status == RunStatus.COMPLETE and summary.query_id == qid


def test_get_work_for_an_unknown_id_is_none(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    run_query(explore_project, _register(explore_project, sources), sources=sources)
    assert get_work(explore_project, "rf:nobody0000-nothing-00000000") is None


def test_run_summary_carries_the_recorded_outcome(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    qid = _register(explore_project, sources)
    summary = run_query(explore_project, qid, sources=sources)
    assert summary.source == "fake" and summary.query_id == qid
    assert summary.reported_count is None and summary.skipped == 0 and summary.note is None
    assert summary.run_id.startswith("run_") and summary.resume_token is None


def test_validation_builds_no_adapter(explore_project: Project) -> None:
    def build(_settings: object, _clock: object) -> Source:
        raise AssertionError("validation must not build an adapter")

    sources = {"fake": SourceFactory(kinds=frozenset({QueryKind.KEYWORD}), build=build)}
    human = explore_project.human_actor()
    with pytest.raises(FactoryValidationError) as wrong:
        register_query(
            explore_project,
            human,
            QuerySpec(source="fake", kind=QueryKind.FILTER, text="doi:1"),
            sources=sources,
        )
    assert [i.field for i in wrong.value.issues] == ["kind"]
    assert _register(explore_project, sources) != ""


def test_openalex_filter_value_with_comma_rejected(explore_project: Project) -> None:
    # A comma or colon in a filter key or value would corrupt the OpenAlex filter expression.
    before = project_status(explore_project).events_total
    human = explore_project.human_actor()
    for filters in (
        {"publication_year": "2019,2020"},
        {"publication_year": ">2019:x"},
        {"a:b": "1"},
    ):
        spec = QuerySpec(
            source="openalex", kind=QueryKind.FILTER, text="doi:10.1/a", filters=filters
        )
        with pytest.raises(FactoryValidationError) as bad:
            register_query(explore_project, human, spec, sources=default_sources())
        assert [i.field for i in bad.value.issues] == ["filters"]
    assert project_status(explore_project).events_total == before


def test_run_started_records_the_triggering_agent(
    explore_project: Project, agent: Actor, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    qid = _register(explore_project, sources)
    run_query(explore_project, qid, sources=sources, actor=agent)
    [started] = _of_type(explore_project, "search.run_started")
    assert started.actor == agent
    assert started.input_blob is not None
    blob = explore_project.blobs.get_json(started.input_blob)
    assert blob == {"query_id": qid, "resume_run": None}


def test_run_cannot_be_resumed_twice(explore_project: Project, fake_sources: SourcesFor) -> None:
    seeded = fake_sources(fail_after=1)
    qid = _register(explore_project, seeded)
    partial = run_query(explore_project, qid, sources=seeded)
    first = run_query(explore_project, qid, sources=fake_sources(), resume_run=partial.run_id)
    with pytest.raises(FactoryValidationError) as again:
        run_query(explore_project, qid, sources=fake_sources(), resume_run=partial.run_id)
    assert [(i.field, i.reason) for i in again.value.issues] == [
        ("resume_run", f"already resumed by {first.run_id}")
    ]
    assert len(_of_type(explore_project, "search.run_started")) == 2


def test_concurrent_resumes_start_one_run(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    seeded = fake_sources(fail_after=1)
    qid = _register(explore_project, seeded)
    partial = run_query(explore_project, qid, sources=seeded)
    barrier = threading.Barrier(2)
    errors: list[FactoryValidationError] = []

    def resume() -> None:
        opened = open_project(
            explore_project.settings, "demo", session=SESSION, clock=SystemClock()
        )
        barrier.wait()
        try:
            run_query(opened, qid, sources=fake_sources(), resume_run=partial.run_id)
        except FactoryValidationError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=resume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    resumed = [
        e
        for e in _of_type(explore_project, "search.run_started")
        if e.payload["resume_of"] == partial.run_id
    ]
    assert len(resumed) == 1
    assert len(errors) == 1 and errors[0].issues[0].reason.startswith("already resumed by ")


def test_resume_lookup_raises_when_the_run_query_row_is_missing(
    explore_project: Project, fake_sources: SourcesFor, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The projector never creates a run without its query, so the missing row is simulated.
    seeded = fake_sources(fail_after=1)
    qid = _register(explore_project, seeded)
    partial = run_query(explore_project, qid, sources=seeded)
    monkeypatch.setattr("factory.services.search._query_spec", lambda *_: None)
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="x")
    with pytest.raises(FactoryError):
        resume_query_id(explore_project, partial.run_id, spec)
