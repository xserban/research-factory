"""Queries, search runs, archived pages and the works they yield.

A search is a sequence of events, never a mutation: `query.registered`, then per run
`search.run_started`, one `search.page_archived` per raw response (recorded before its records
are parsed, R-03), `search.records_parsed` per page that yielded records, and `search.run_finished`.
The SQLite projection (`factory.index.search`) is the only place these are read back as state.
"""

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from factory.clock import parse_ts
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.search import (
    QueryKind,
    QueryPurpose,
    QueryRegistered,
    QuerySpec,
    RunStatus,
    SearchPageArchived,
    SearchRecordsParsed,
    SearchRunFinished,
    SearchRunStarted,
)
from factory.model.work import Provenance, ProvenanceMethod, Work
from factory.services.context import Project
from factory.sources.base import RawPage, SourceError
from factory.sources.http import redact
from factory.sources.registry import INTERFACES, SourceFactory

_PROVENANCE_COLUMNS = "work_id, run_id, query_id, source, method, raw_blob, raw_ref, at"


class RunSummary(StrictModel):
    """What one `run_query` call recorded, as the caller needs it."""

    run_id: str
    query_id: str
    source: str
    status: RunStatus
    reported_count: int | None
    retrieved_count: int
    skipped: int
    note: str | None
    resume_token: str | None
    new_works: int


class Shortfall(StrictModel):
    """A finished run that delivered fewer records than its source reported."""

    run_id: str
    source: str
    reported_count: int
    retrieved_count: int
    note: str | None


class SearchCounts(StrictModel):
    queries: int
    runs: int
    complete: int
    partial: int
    failed: int
    interrupted: int
    shortfalls: list[Shortfall]


def register_query(
    project: Project,
    actor: Actor,
    spec: QuerySpec,
    *,
    sources: Mapping[str, SourceFactory],
) -> str:
    """Record a query as the caller stated it. Writes nothing if the spec does not fit."""
    issues = _spec_issues(project, spec, sources)
    if issues:
        raise FactoryValidationError(issues)
    query_id = project.ids.new("qry")
    # An agent's request is kept verbatim, so the query can be reproduced and audited later.
    input_blob = (
        project.blobs.put_json(spec.model_dump(mode="json")) if actor.kind == "agent" else None
    )
    payload = QueryRegistered(
        query_id=query_id,
        spec=spec,
        interface=INTERFACES.get(spec.source, spec.source),
    )
    project.record(
        [
            project.events.make(
                "query.registered",
                payload,
                actor,
                refs=(query_id,),
                input_blob=input_blob,
            )
        ]
    )
    return query_id


def run_query(
    project: Project,
    query_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    resume_run: str | None = None,
    actor: Actor | None = None,
) -> RunSummary:
    """Run one registered query against its source and record everything it returns.

    `actor` is the triggering actor, recorded on `search.run_started`; without one the run is
    recorded as the system's. An agent's run keeps its input (`query_id`, `resume_run`) verbatim.

    Raw pages are archived as they arrive. Records are recorded once the adapter returns, one
    `search.records_parsed` per page. A `SourceError` is an outcome, recorded and returned; any
    other exception is recorded as a failed run and then re-raised.
    """
    project.index.sync()
    spec = _query_spec(project, query_id)
    if spec is None:
        raise FactoryValidationError([ValidationIssue("query_id", "unknown query")])
    factory = sources.get(spec.source)
    if factory is None:
        raise FactoryValidationError([ValidationIssue("source", f"no adapter for {spec.source!r}")])
    adapter = factory(project.settings, project.clock)

    system = project.system_actor()
    started_by = actor or system
    known = _known_work_ids(project)
    run_id = project.ids.new("run")
    input_blob = (
        project.blobs.put_json({"query_id": query_id, "resume_run": resume_run})
        if started_by.kind == "agent"
        else None
    )
    # The resume check and the run's start are one critical section, so two resumes of the same
    # run cannot both pass the check. The lock is not held during the fetch that follows.
    with project.index.exclusive():
        project.index.sync()
        resume_token = None if resume_run is None else _resume_token(project, query_id, resume_run)
        project.record(
            [
                project.events.make(
                    "search.run_started",
                    SearchRunStarted(
                        run_id=run_id,
                        query_id=query_id,
                        resume_of=resume_run,
                        resume_from=resume_token,
                    ),
                    started_by,
                    refs=(run_id,),
                    input_blob=input_blob,
                )
            ]
        )

    archived: list[str] = []

    def archive(page: RawPage) -> str:
        ref = project.blobs.put(page.body.encode("utf-8"))
        project.record(
            [
                project.events.make(
                    "search.page_archived",
                    SearchPageArchived(
                        run_id=run_id,
                        ordinal=page.ordinal,
                        url=page.url,
                        fetched_at=page.fetched_at,
                        raw_blob=ref,
                    ),
                    system,
                    refs=(run_id,),
                )
            ]
        )
        archived.append(ref)
        return ref

    try:
        result = adapter.run(
            spec, run_id=run_id, query_id=query_id, archive=archive, resume_from=resume_token
        )
    except Exception as exc:
        # The pages already archived stay recorded; nothing from them is parsed here.
        status = RunStatus.PARTIAL if archived else RunStatus.FAILED
        error_note = redact(f"{type(exc).__name__}: {exc}", project.settings.mailto)
        project.record(
            [
                project.events.make(
                    "search.run_finished",
                    SearchRunFinished(
                        run_id=run_id,
                        status=status,
                        retrieved_count=0,
                        note=error_note,
                    ),
                    system,
                    refs=(run_id,),
                )
            ]
        )
        if not isinstance(exc, SourceError):
            raise
        return RunSummary(
            run_id=run_id,
            query_id=query_id,
            source=spec.source,
            status=status,
            reported_count=None,
            retrieved_count=0,
            skipped=0,
            note=error_note,
            resume_token=None,
            new_works=0,
        )

    note = result.note
    if resume_run is not None and note is not None:
        note = f"resumed from {resume_run}: {note}"
    finished = SearchRunFinished(
        run_id=run_id,
        status=result.status,
        reported_count=result.reported_count,
        retrieved_count=result.retrieved_count,
        skipped=result.skipped,
        note=note,
        resume_token=result.resume_token,
    )
    project.record(
        [
            *_records_events(project, run_id, result.works),
            project.events.make("search.run_finished", finished, system, refs=(run_id,)),
        ]
    )
    return RunSummary(
        run_id=run_id,
        query_id=query_id,
        source=spec.source,
        status=result.status,
        reported_count=result.reported_count,
        retrieved_count=result.retrieved_count,
        skipped=result.skipped,
        note=note,
        resume_token=result.resume_token,
        new_works=len({work.id for work in result.works} - known),
    )


def run_query_id(project: Project, run_id: str) -> str | None:
    """The query a run belongs to, or None if no run has that id."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT query_id FROM runs WHERE run_id = :run"), {"run": run_id}
        ).one_or_none()
    return None if row is None else str(row[0])


def resume_query_id(project: Project, resume_run: str, spec: QuerySpec) -> str:
    """The query behind `resume_run`, provided `spec` restates it.

    A resume continues the registered query, so a caller that names a different source, query
    text or kind has misunderstood what will run; that is refused under `resume_run` rather than
    silently ignored. Purpose and limit are not compared: they do not change what is fetched.
    """
    query_id = run_query_id(project, resume_run)
    if query_id is None:
        raise FactoryValidationError([ValidationIssue("resume_run", "unknown run")])
    registered = _query_spec(project, query_id)
    if registered is None:
        # The projector creates a run only alongside its query, so this is an index fault.
        raise FactoryError(f"run {resume_run} names query {query_id}, not in the index")
    if (registered.source, registered.text, registered.kind) != (
        spec.source,
        spec.text,
        spec.kind,
    ):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "resume_run",
                    "source, query and kind must match the run being resumed "
                    f"({registered.source} {registered.kind.value} {registered.text!r})",
                )
            ]
        )
    return query_id


def get_work(project: Project, work_id: str) -> Work | None:
    """One work, with every provenance row that names it."""
    works = _load_works(project, work_id)
    return works[0] if works else None


def list_works(project: Project, *, include_probe: bool = False) -> list[Work]:
    """The corpus, sorted by id: works with at least one provenance row from a non-probe query.

    A corpus work carries only its non-probe provenance, so its records are the corpus's records.
    `include_probe` lists every stored work, probe-only ones included, with all their provenance.
    """
    return _load_works(project, corpus=not include_probe)


def corpus_size(project: Project) -> tuple[int, int]:
    """The corpus's (works, records), counted as `list_works` would see them."""
    project.index.sync()
    with project.index.connect() as conn:
        works, records = conn.execute(
            text(
                "SELECT COUNT(DISTINCT work_id), COUNT(*) FROM provenance "
                "WHERE query_id NOT IN (SELECT query_id FROM queries WHERE purpose = :probe)"
            ),
            {"probe": QueryPurpose.PROBE.value},
        ).one()
    return int(works), int(records)


def search_counts(project: Project) -> SearchCounts:
    project.index.sync()
    with project.index.connect() as conn:
        queries = conn.execute(text("SELECT COUNT(*) FROM queries")).scalar_one()
        by_status = {
            str(status): int(count)
            for status, count in conn.execute(
                text("SELECT status, COUNT(*) FROM runs GROUP BY status")
            ).all()
        }
        short = (
            conn.execute(
                text(
                    "SELECT run_id, source, reported_count, retrieved_count, note FROM runs "
                    "WHERE status != :running AND reported_count IS NOT NULL "
                    "AND retrieved_count < reported_count ORDER BY run_id"
                ),
                {"running": RunStatus.RUNNING.value},
            )
            .mappings()
            .all()
        )
    return SearchCounts(
        queries=int(queries),
        runs=sum(by_status.values()),
        complete=by_status.get(RunStatus.COMPLETE.value, 0),
        partial=by_status.get(RunStatus.PARTIAL.value, 0),
        failed=by_status.get(RunStatus.FAILED.value, 0),
        interrupted=by_status.get(RunStatus.RUNNING.value, 0),
        shortfalls=[
            Shortfall(
                run_id=str(row["run_id"]),
                source=str(row["source"]),
                reported_count=int(row["reported_count"]),
                retrieved_count=int(row["retrieved_count"]),
                note=None if row["note"] is None else str(row["note"]),
            )
            for row in short
        ],
    )


def _spec_issues(
    project: Project, spec: QuerySpec, sources: Mapping[str, SourceFactory]
) -> list[ValidationIssue]:
    """Every problem with the spec, reported together so one call shows them all."""
    factory = sources.get(spec.source)
    if factory is None:
        return [ValidationIssue("source", f"unknown source {spec.source!r}")]
    issues: list[ValidationIssue] = []
    if spec.kind not in factory.kinds:
        issues.append(
            ValidationIssue("kind", f"{spec.source} does not take {spec.kind.value} queries")
        )
    if spec.filters and spec.source != "openalex":
        issues.append(ValidationIssue("filters", f"{spec.source} does not take filters"))
    if spec.source == "openalex" and any(
        sep in part for part in (*spec.filters, *spec.filters.values()) for sep in (",", ":")
    ):
        # The adapter writes `,key:value` clauses, so a separator inside a key or value would
        # split or re-open the expression.
        issues.append(
            ValidationIssue("filters", "OpenAlex filter keys and values cannot contain ',' or ':'")
        )
    if spec.source == "openalex" and spec.kind is QueryKind.KEYWORD and "," in spec.text:
        # The adapter joins filter clauses with commas, so a comma in the text would start a
        # bogus clause rather than search for it.
        issues.append(
            ValidationIssue("text", "OpenAlex keyword queries cannot contain ','; use FILTER kind")
        )
    return issues


def _query_spec(project: Project, query_id: str) -> QuerySpec | None:
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text(
                    'SELECT source, kind, "text", purpose, filters, "limit" '
                    "FROM queries WHERE query_id = :query"
                ),
                {"query": query_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    return QuerySpec(
        source=str(row["source"]),
        kind=QueryKind(row["kind"]),
        text=str(row["text"]),
        purpose=QueryPurpose(row["purpose"]),
        filters=json.loads(str(row["filters"])),
        limit=None if row["limit"] is None else int(row["limit"]),
    )


def _resume_token(project: Project, query_id: str, resume_run: str) -> str:
    """The token a partial or failed run of this query left behind, or a validation error."""
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text("SELECT query_id, status, resume_token FROM runs WHERE run_id = :run"),
                {"run": resume_run},
            )
            .mappings()
            .one_or_none()
        )
    resumable = (
        row is not None
        and row["query_id"] == query_id
        and row["status"] in {RunStatus.PARTIAL.value, RunStatus.FAILED.value}
        and row["resume_token"] is not None
    )
    if row is None or not resumable:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "resume_run",
                    "must name a partial or failed run of this query with a resume token",
                )
            ]
        )
    with project.index.connect() as conn:
        resumer = conn.execute(
            text("SELECT run_id FROM runs WHERE resume_of = :run ORDER BY run_id LIMIT 1"),
            {"run": resume_run},
        ).one_or_none()
    if resumer is not None:
        # A run continues at most once; a second continuation would fetch the same records twice.
        raise FactoryValidationError(
            [ValidationIssue("resume_run", f"already resumed by {resumer[0]}")]
        )
    return str(row["resume_token"])


def _known_work_ids(project: Project) -> set[str]:
    with project.index.connect() as conn:
        return {str(row[0]) for row in conn.execute(text("SELECT work_id FROM works")).all()}


def _records_events(project: Project, run_id: str, works: list[Work]) -> list[Event]:
    """One `search.records_parsed` per archived page that yielded records, in page order."""
    by_page: dict[str, list[Work]] = {}
    for work in works:
        by_page.setdefault(work.provenance[0].raw_blob, []).append(work)
    return [
        project.events.make(
            "search.records_parsed",
            SearchRecordsParsed(run_id=run_id, raw_blob=blob, records=tuple(records)),
            project.system_actor(),
            refs=(run_id,),
        )
        for blob, records in by_page.items()
    ]


def _load_works(
    project: Project, work_id: str | None = None, *, corpus: bool = False
) -> list[Work]:
    """Works rebuilt from their stored records and their provenance, sorted by id.

    With `corpus`, probe-purpose provenance rows are dropped and a work left with none is omitted.
    """
    project.index.sync()
    where = " WHERE work_id = :work" if work_id is not None else ""
    params: dict[str, Any] = {"work": work_id} if work_id is not None else {}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(f"SELECT work_id, data FROM works{where} ORDER BY work_id"), params
        ).all()
        prov_rows = (
            conn.execute(
                text(f"SELECT {_PROVENANCE_COLUMNS} FROM provenance{where} ORDER BY at, run_id"),
                params,
            )
            .mappings()
            .all()
        )
        probe_queries = (
            {
                str(row[0])
                for row in conn.execute(
                    text("SELECT query_id FROM queries WHERE purpose = :probe"),
                    {"probe": QueryPurpose.PROBE.value},
                ).all()
            }
            if corpus
            else set()
        )
    by_work: dict[str, list[Provenance]] = {}
    for row in prov_rows:
        if str(row["query_id"]) in probe_queries:
            continue
        by_work.setdefault(str(row["work_id"]), []).append(
            Provenance(
                source=str(row["source"]),
                run_id=str(row["run_id"]),
                query_id=str(row["query_id"]),
                at=parse_ts(str(row["at"])),
                raw_blob=str(row["raw_blob"]),
                raw_ref=None if row["raw_ref"] is None else str(row["raw_ref"]),
                method=ProvenanceMethod(row["method"]),
            )
        )
    works: list[Work] = []
    for wid, data in rows:
        provenance = by_work.get(str(wid), [])
        if provenance or not corpus:
            works.append(Work.model_validate({**json.loads(str(data)), "provenance": provenance}))
    return works
