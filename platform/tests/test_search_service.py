from collections.abc import Callable, Mapping
from typing import Any

import pydantic
import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
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
from factory.services.context import Project
from factory.services.project import project_status
from factory.services.search import (
    RunSummary,
    Shortfall,
    get_work,
    list_works,
    register_query,
    run_query,
)
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


def test_run_archives_pages_and_records_works(project: Project, fake_sources: SourcesFor) -> None:
    sources = fake_sources()
    qid = _register(project, sources, "linear attention")
    summary = run_query(project, qid, sources=sources)
    assert summary.status == RunStatus.COMPLETE
    assert summary.retrieved_count == 3 and summary.new_works == 3
    st = project_status(project)
    assert (st.works, st.records, st.search.runs, st.search.complete) == (3, 3, 1, 1)
    refs = _pages_of(project, summary.run_id)
    assert len(refs) == 2 and all(project.blobs.exists(ref) for ref in refs)  # R-03
    ids = [w.id for w in list_works(project)]
    assert ids == sorted(ids) and len(ids) == 3


def test_page_archived_event_precedes_its_records(
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    summary = run_query(project, _register(project, sources), sources=sources)
    archived = _of_type(project, "search.page_archived")
    parsed = _of_type(project, "search.records_parsed")
    assert len(archived) == 2 and len(parsed) == 2
    # Every page is archived before the adapter returns, so all archives precede all parsing.
    assert max(e.id for e in archived) < min(e.id for e in parsed)
    for page in archived:
        assert page.payload["run_id"] == summary.run_id
        [matching] = [e for e in parsed if e.payload["raw_blob"] == page.payload["raw_blob"]]
        assert page.id < matching.id  # page n is archived before its records are recorded


def test_failure_mid_run_records_partial_with_resume_token(
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources(fail_after=1)
    summary = run_query(project, _register(project, sources), sources=sources)
    assert summary.status == RunStatus.PARTIAL
    assert summary.retrieved_count == 2
    assert summary.resume_token == "1"
    assert summary.note is not None and "connection reset" in summary.note
    assert len(_pages_of(project, summary.run_id)) == 1
    st = project_status(project)
    assert (st.works, st.search.partial, st.search.failed) == (2, 1, 0)


def test_resume_continues_and_links_runs(project: Project, fake_sources: SourcesFor) -> None:
    qid = _register(project, fake_sources())
    first = run_query(project, qid, sources=fake_sources(fail_after=1))
    second = run_query(project, qid, sources=fake_sources(), resume_run=first.run_id)
    assert second.run_id != first.run_id
    assert second.status == RunStatus.COMPLETE
    assert second.retrieved_count == 1 and second.new_works == 1
    row = _run_row(project, second.run_id)
    assert row is not None and row["resume_of"] == first.run_id
    st = project_status(project)
    assert (st.works, st.records, st.search.runs) == (3, 3, 2)


def test_same_work_from_two_runs_has_two_provenance_rows(
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    qid = _register(project, sources)
    first = run_query(project, qid, sources=sources)
    second = run_query(project, qid, sources=sources)
    assert second.new_works == 0 and second.retrieved_count == 3
    st = project_status(project)
    assert (st.works, st.records) == (3, 6)
    work_id = list_works(project)[0].id
    work = get_work(project, work_id)
    assert work is not None
    assert [p.run_id for p in work.provenance] == [first.run_id, second.run_id]


def test_identifiers_from_later_records_fill_gaps(
    project: Project, fake_sources: SourcesFor
) -> None:
    qid = _register(project, fake_sources())
    bare = {"title": "Sparse attention", "authors": ["Ben Li"], "year": 2023}
    run_query(project, qid, sources=fake_sources(pages=[[bare]]))
    enriched = {**bare, "openalex": "W123", "abstract": "We study sparsity."}
    run_query(project, qid, sources=fake_sources(pages=[[enriched]]))
    conflicting = {**bare, "openalex": "W999", "abstract": "A different abstract."}
    run_query(project, qid, sources=fake_sources(pages=[[conflicting]]))

    [work] = list_works(project)
    assert work.identifiers.openalex == "W123"  # first seen wins once filled
    assert work.abstract == "We study sparsity."
    assert len(work.provenance) == 3


def test_status_lists_shortfalls(project: Project, fake_sources: SourcesFor) -> None:
    sources = fake_sources(reported=5)
    summary = run_query(project, _register(project, sources), sources=sources)
    assert summary.status == RunStatus.COMPLETE
    assert (summary.reported_count, summary.retrieved_count) == (5, 3)
    assert summary.note is not None
    assert project_status(project).search.shortfalls == [
        Shortfall(
            run_id=summary.run_id,
            source="fake",
            reported_count=5,
            retrieved_count=3,
            note=summary.note,
        )
    ]


def test_duplicate_within_a_run_is_skipped_not_counted_twice(
    project: Project, fake_sources: SourcesFor
) -> None:
    pages = [[{"title": "Same paper", "authors": ["Ada Zhou"], "year": 2024}]] * 2
    sources = fake_sources(pages=pages)
    summary = run_query(project, _register(project, sources), sources=sources)
    assert summary.retrieved_count == 1 and summary.skipped == 1
    assert summary.note == "1 duplicate record(s) skipped"
    assert len(_pages_of(project, summary.run_id)) == 2
    assert project_status(project).works == 1


def test_unknown_source_or_kind_is_rejected_and_writes_nothing(
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    before = project_status(project).events_total
    human = project.human_actor()
    with pytest.raises(FactoryValidationError) as unknown:
        register_query(
            project,
            human,
            QuerySpec(source="nope", kind=QueryKind.KEYWORD, text="x"),
            sources=sources,
        )
    assert [i.field for i in unknown.value.issues] == ["source"]
    with pytest.raises(FactoryValidationError) as wrong:
        register_query(
            project,
            human,
            QuerySpec(source="fake", kind=QueryKind.FILTER, text="doi:1", filters={"a": "b"}),
            sources=sources,
        )
    assert [i.field for i in wrong.value.issues] == ["kind", "filters"]
    assert project_status(project).events_total == before


def test_filters_are_accepted_for_openalex(project: Project) -> None:
    spec = QuerySpec(
        source="openalex",
        kind=QueryKind.KEYWORD,
        text="attention",
        filters={"publication_year": "2024"},
    )
    qid = register_query(project, project.human_actor(), spec, sources=default_sources())
    [event] = _of_type(project, "query.registered")
    assert event.payload["query_id"] == qid and str(event.payload["interface"]).startswith(
        "OpenAlex"
    )


def test_agent_registered_query_carries_input_blob(
    project: Project, agent: Actor, fake_sources: SourcesFor
) -> None:
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="screening")
    register_query(project, agent, spec, sources=fake_sources())
    [event] = _of_type(project, "query.registered")
    assert event.actor.kind == "agent" and event.input_blob is not None
    assert project.blobs.get_json(event.input_blob) == spec.model_dump(mode="json")


def test_interrupted_run_is_counted(project: Project, fake_sources: SourcesFor) -> None:
    qid = _register(project, fake_sources())
    run_id = project.ids.new("run")
    project.record(
        [
            project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=run_id, query_id=qid),
                project.system_actor(),
                refs=(run_id,),
            )
        ]
    )
    st = project_status(project)
    assert (st.search.runs, st.search.interrupted, st.search.complete) == (1, 1, 0)


def test_search_projection_rebuild_equals_incremental(
    project: Project, fake_sources: SourcesFor
) -> None:
    good = fake_sources()
    run_query(project, _register(project, good), sources=good)
    partial = fake_sources(fail_after=1)
    run_query(project, _register(project, partial, "other"), sources=partial)
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    st = project_status(project)
    assert (st.works, st.records) == (3, 5)  # the partial run re-delivers page 0's works


def test_parse_failure_mid_run_is_resumable(project: Project, fake_sources: SourcesFor) -> None:
    sources = fake_sources(parse_fail_at=1)
    qid = _register(project, sources)
    summary = run_query(project, qid, sources=sources)
    assert summary.status == RunStatus.PARTIAL
    assert summary.retrieved_count == 2 and summary.new_works == 2
    assert summary.note is not None and summary.note.startswith("SourceError: ")
    assert summary.resume_token == "1"
    archived = _pages_of(project, summary.run_id)
    parsed = [str(e.payload["raw_blob"]) for e in _of_type(project, "search.records_parsed")]
    # Every archived page but the failing one (page 1) has its records recorded.
    assert len(archived) == 2 and parsed == [archived[0]]
    assert project_status(project).works == 2

    resumed = run_query(project, qid, sources=fake_sources(), resume_run=summary.run_id)
    assert resumed.status == RunStatus.COMPLETE
    assert resumed.retrieved_count == 1 and resumed.new_works == 1
    assert project_status(project).works == 3


def test_source_error_raised_by_an_adapter_is_still_recorded(
    project: Project, fake_sources: SourcesFor
) -> None:
    """Safety net: an adapter that raises instead of returning is recorded, not lost."""
    sources = fake_sources(raise_at=1)
    summary = run_query(project, _register(project, sources), sources=sources)
    assert summary.status == RunStatus.PARTIAL
    assert summary.note == "SourceError: fake page unreadable"
    assert summary.resume_token is None and summary.retrieved_count == 0
    assert len(_pages_of(project, summary.run_id)) == 1
    assert _of_type(project, "search.records_parsed") == []


def test_unexpected_error_is_recorded_then_reraised(
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources(raise_at=0, raise_error=RuntimeError("boom"))
    qid = _register(project, sources)
    with pytest.raises(RuntimeError, match="boom"):
        run_query(project, qid, sources=sources)
    [started] = _of_type(project, "search.run_started")
    row = _run_row(project, str(started.payload["run_id"]))
    assert row is not None
    assert (row["status"], row["note"], row["pages"]) == ("failed", "RuntimeError: boom", 0)


@pytest.mark.parametrize("case", ["unknown", "complete", "other_query", "no_token"])
def test_resume_run_must_be_a_resumable_run_of_this_query(
    project: Project, fake_sources: SourcesFor, case: str
) -> None:
    qid = _register(project, fake_sources())
    other = _register(project, fake_sources(), "other")
    complete = run_query(project, qid, sources=fake_sources())
    resume: str
    if case == "unknown":
        resume = project.ids.new("run")
    elif case == "complete":
        resume = complete.run_id
    elif case == "other_query":
        resume = run_query(project, other, sources=fake_sources(fail_after=1)).run_id
    else:
        resume = run_query(project, qid, sources=fake_sources(raise_at=0)).run_id
    with pytest.raises(FactoryValidationError) as err:
        run_query(project, qid, sources=fake_sources(), resume_run=resume)
    assert [i.field for i in err.value.issues] == ["resume_run"]


def test_run_query_rejects_an_unknown_query(project: Project, fake_sources: SourcesFor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        run_query(project, project.ids.new("qry"), sources=fake_sources())
    assert [i.field for i in err.value.issues] == ["query_id"]


def test_projection_ignores_events_that_do_not_apply(
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    summary: RunSummary = run_query(project, _register(project, sources), sources=sources)
    ghost_run = project.ids.new("run")
    ghost_query = project.ids.new("qry")
    system = project.system_actor()
    project.record(
        [
            project.events.make(
                "search.page_archived",
                SearchPageArchived(
                    run_id=ghost_run, ordinal=0, url="u", fetched_at=T0, raw_blob=REF
                ),
                system,
                refs=(ghost_run,),
            ),
            project.events.make(
                "search.records_parsed",
                SearchRecordsParsed(run_id=ghost_run, raw_blob=REF, records=()),
                system,
                refs=(ghost_run,),
            ),
            project.events.make(
                "search.run_finished",
                SearchRunFinished(
                    run_id=ghost_run, status=RunStatus.FAILED, retrieved_count=0, note="x"
                ),
                system,
                refs=(ghost_run,),
            ),
            project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=ghost_run, query_id=ghost_query),
                system,
                refs=(ghost_run,),
            ),
        ]
    )
    # Known run, but the event repeats an outcome already folded in: each is ignored.
    project.record(
        [
            project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=summary.run_id, query_id=summary.query_id),
                system,
                refs=(summary.run_id,),
            ),
            project.events.make(
                "search.page_archived",
                SearchPageArchived(
                    run_id=summary.run_id, ordinal=0, url="u", fetched_at=T0, raw_blob=REF
                ),
                system,
                refs=(summary.run_id,),
            ),
            project.events.make(
                "search.run_finished",
                SearchRunFinished(
                    run_id=summary.run_id, status=RunStatus.FAILED, retrieved_count=0, note="late"
                ),
                system,
                refs=(summary.run_id,),
            ),
        ]
    )
    st = project_status(project)
    assert (st.search.runs, st.search.complete, st.search.failed, st.works) == (1, 1, 0, 3)
    row = _run_row(project, summary.run_id)
    assert row is not None and (row["status"], row["pages"]) == ("complete", 2)
    assert _run_row(project, ghost_run) is None


def test_resumed_run_with_a_note_says_what_it_resumed_from(
    project: Project, fake_sources: SourcesFor
) -> None:
    qid = _register(project, fake_sources())
    first = run_query(project, qid, sources=fake_sources(fail_after=1))
    # Two of five reported records were already delivered; the remainder is one record.
    second = run_query(project, qid, sources=fake_sources(reported=5), resume_run=first.run_id)
    assert second.retrieved_count == 1 and second.reported_count == 5
    assert second.note == f"resumed from {first.run_id}: 4 of 5 reported not delivered"
    [shortfall] = project_status(project).search.shortfalls
    assert shortfall.run_id == second.run_id


def test_query_whose_adapter_is_gone_is_refused_before_running(
    project: Project, fake_sources: SourcesFor
) -> None:
    qid = _register(project, fake_sources())
    with pytest.raises(FactoryValidationError) as err:
        run_query(project, qid, sources={})
    assert [i.field for i in err.value.issues] == ["source"]
    assert project_status(project).search.runs == 0


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
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="  sparse  ", limit=2)
    qid = register_query(project, project.human_actor(), spec, sources=sources)
    with project.index.connect() as conn:
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
    summary = run_query(project, qid, sources=sources)
    assert summary.status == RunStatus.COMPLETE and summary.query_id == qid


def test_get_work_for_an_unknown_id_is_none(project: Project, fake_sources: SourcesFor) -> None:
    sources = fake_sources()
    run_query(project, _register(project, sources), sources=sources)
    assert get_work(project, "rf:nobody0000-nothing-00000000") is None


def test_run_summary_carries_the_recorded_outcome(
    project: Project, fake_sources: SourcesFor
) -> None:
    sources = fake_sources()
    qid = _register(project, sources)
    summary = run_query(project, qid, sources=sources)
    assert summary.source == "fake" and summary.query_id == qid
    assert summary.reported_count is None and summary.skipped == 0 and summary.note is None
    assert summary.run_id.startswith("run_") and summary.resume_token is None
