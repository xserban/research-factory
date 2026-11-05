"""Queries, search runs, archived pages and the works they yield.

A search is a sequence of events, never a mutation: `query.registered`, then per run
`search.run_started`, one `search.page_archived` per raw response (recorded before its records
are parsed, R-03), `search.records_parsed` per page that yielded records, and `search.run_finished`.
The SQLite projection (`factory.index.search`) is the only place these are read back as state.
"""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field
from sqlalchemy import bindparam, text
from sqlalchemy.sql.elements import TextClause

from factory.clock import parse_ts
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.protocol import SubmitterKind
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
from factory.services.call_memo import memoised
from factory.services.context import Project
from factory.sources.base import RawPage, SourceError, StatusRecord
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
    status_records: tuple[StatusRecord, ...] = Field(default=(), exclude=True)
    """What a STATUS lookup read; empty for every other purpose, and never serialised."""


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
    deviation_id: str | None = None,
    round_id: str | None = None,
    cycle_id: str | None = None,
    inbox_item: str | None = None,
    import_id: str | None = None,
    names_works: Sequence[str] = (),
) -> str:
    """Record a query as the caller stated it. Writes nothing if the spec does not fit.

    A search in a pilot or systematic project must be authorised by the protocol
    (`protocol.search_authorization`); `deviation_id` names a recorded deviation that allows a
    query the protocol does not plan. `round_id` names the recorded snowball (`snw_`) or chase
    (`chs_`) round that planned the query, so its runs are linked to the round by reference; a
    snowball round's texts are waived only for a query that names it. `inbox_item` names the
    open inbox item a `supplied` lookup resolves: the gate is then told the kind of actor that
    captured it (`supplied_by`, slice 4a ruling 7), here and again at run time. The event
    refers to the protocol, the deviation, the inbox item and the round (last).

    `cycle_id` names the open watch cycle (`wcy_`) that plans a window query (slice 4b, ruling 3);
    it takes the last ref as `round_id` does, and a query names a round or a cycle, not both.

    `import_id` names the import (`imp_`) whose recorded admission planned an `import`-purpose
    query (slice 3d); it is the last ref, and only such a query may name it.

    `names_works` lists the work ids a status lookup asks about (living-C); they are refs of the
    event, before the cycle, so "when was this work last looked up" is an indexed read. Only a
    status query may name works.
    """
    # Imported here: the protocol service reads seeds, which read this module.
    from factory.services import protocol as protocol_service

    with project.index.exclusive():
        project.index.sync()
        issues = _spec_issues(project, spec, sources)
        if round_id is not None and protocol_service.recorded_round(project, round_id) is None:
            issues.append(ValidationIssue("round_id", "not a recorded snowball or chase round"))
        if cycle_id is not None and round_id is not None:
            issues.append(ValidationIssue("cycle_id", "a query names a round or a cycle, not both"))
        elif cycle_id is not None and not protocol_service.is_watch_cycle(project, cycle_id):
            issues.append(ValidationIssue("cycle_id", "not a recorded watch cycle"))
        if spec.purpose is QueryPurpose.STATUS:
            # Gate living.status_lookup: only the platform's identifier lookups, inside a cycle.
            if cycle_id is None or not protocol_service.is_open_watch_cycle(project, cycle_id):
                issues.append(ValidationIssue("cycle_id", "a status query names an open cycle"))
            if spec.kind not in (QueryKind.ID_LIST, QueryKind.FILTER):
                issues.append(ValidationIssue("kind", "a status query is an id_list or a filter"))
        supplied_by = None
        if inbox_item is not None:
            supplied_by = _item_submitter(project, inbox_item, open_only=True)
            if supplied_by is None or spec.purpose is not QueryPurpose.SUPPLIED:
                issues.append(
                    ValidationIssue("inbox_item", "must be an open item and a supplied lookup")
                )
        issues += protocol_service.search_authorization(
            project,
            spec,
            deviation_id=deviation_id,
            round_id=round_id,
            cycle_id=cycle_id,
            supplied_by=supplied_by,
            import_id=import_id,
        )
        if names_works and spec.purpose is not QueryPurpose.STATUS:
            issues.append(ValidationIssue("names_works", "only a status query names works"))
        if import_id is not None and spec.purpose is not QueryPurpose.IMPORT:
            issues.append(
                ValidationIssue("import_id", "only an import-purpose query names an import")
            )
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
        refs = protocol_service.search_refs(project, spec, deviation_id)
        refs += () if inbox_item is None else (inbox_item,)
        refs += () if round_id is None else (round_id,)
        refs += tuple(names_works)
        refs += () if cycle_id is None else (cycle_id,)
        refs += () if import_id is None else (import_id,)
        project.record(
            [
                project.events.make(
                    "query.registered",
                    payload,
                    actor,
                    refs=(query_id, *refs),
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
    cycle_id: str | None = None,
) -> RunSummary:
    """Run one registered query against its source and record everything it returns.

    `actor` is the triggering actor, recorded on `search.run_started`; without one the run is
    recorded as the system's. An agent's run keeps its input (`query_id`, `resume_run`) verbatim.
    `cycle_id`, the watch cycle (`wcy_`) the run belongs to, is the last ref of the start event.

    A query that the protocol no longer authorises (see `protocol.search_authorization`) is
    refused before anything is written, including on a resume.

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

    # Imported here: the protocol service reads seeds, which read this module.
    from factory.services import protocol as protocol_service

    system = project.system_actor()
    started_by = actor or system
    known = _known_work_ids(project, spec.purpose)
    run_id = project.ids.new("run")
    # The gate is re-checked at run time: the protocol or question may have changed since the
    # query was registered. The check, the resume check and the run's start are one critical
    # section, so two resumes of the same run cannot both pass. The lock is not held during the
    # fetch that follows.
    with project.index.exclusive():
        project.index.sync()
        gate = protocol_service.search_authorization(
            project,
            spec,
            deviation_id=protocol_service.registered_deviation(project, query_id),
            round_id=protocol_service.registered_round(project, query_id),
            cycle_id=protocol_service.registered_cycle(project, query_id),
            supplied_by=_registered_submitter(project, query_id),
            import_id=protocol_service.registered_import(project, query_id),
        )
        if gate:
            raise FactoryValidationError(gate)
        resume_token = None if resume_run is None else _resume_token(project, query_id, resume_run)
        input_blob = (
            project.blobs.put_json({"query_id": query_id, "resume_run": resume_run})
            if started_by.kind == "agent"
            else None
        )
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
                    refs=(run_id,) if cycle_id is None else (run_id, cycle_id),
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

    if spec.purpose is QueryPurpose.STATUS:
        # A status lookup never yields corpus works, whatever an adapter returns.
        result = dataclasses.replace(result, works=[])
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
        status_records=result.status_records,
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


def load_works(project: Project, work_ids: Sequence[str]) -> list[Work]:
    """The corpus works among `work_ids` (at most a few hundred per call), sorted by id."""
    return _load_works(project, work_ids=work_ids, corpus=True)


def get_work(project: Project, work_id: str) -> Work | None:
    """One work, with every provenance row that names it."""
    works = _load_works(project, work_id)
    return works[0] if works else None


@memoised
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
        queries = conn.execute(
            text("SELECT COUNT(*) FROM queries WHERE purpose != :status"),
            {"status": QueryPurpose.STATUS.value},
        ).scalar_one()
        by_status = {
            str(status): int(count)
            for status, count in conn.execute(
                text(
                    "SELECT r.status, COUNT(*) FROM runs r "
                    "JOIN queries q ON q.query_id = r.query_id "
                    "WHERE q.purpose != :status GROUP BY r.status"
                ),
                {"status": QueryPurpose.STATUS.value},
            ).all()
        }
        short = (
            conn.execute(
                text(
                    "SELECT r.run_id, r.source, r.reported_count, r.retrieved_count, r.note "
                    "FROM runs r JOIN queries q ON q.query_id = r.query_id "
                    "WHERE r.status != :running AND r.reported_count IS NOT NULL "
                    "AND r.retrieved_count < r.reported_count AND q.purpose != :status "
                    "ORDER BY r.run_id"
                ),
                {"running": RunStatus.RUNNING.value, "status": QueryPurpose.STATUS.value},
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


def query_issues(
    project: Project, spec: QuerySpec, sources: Mapping[str, SourceFactory]
) -> list[ValidationIssue]:
    """Every problem `register_query` would refuse the spec for, without writing anything."""
    return _spec_issues(project, spec, sources)


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


def _item_submitter(project: Project, item_id: str, *, open_only: bool) -> SubmitterKind | None:
    """The actor kind that captured inbox item `item_id` (only if open, when `open_only`)."""
    sql = "SELECT actor_kind FROM inbox_items WHERE item_id = :item"
    sql += " AND status = 'open'" if open_only else ""
    with project.index.connect() as conn:
        row = conn.execute(text(sql), {"item": item_id}).one_or_none()
    kind = None if row is None else str(row[0])
    return "human" if kind == "human" else "agent" if kind == "agent" else None


def _registered_submitter(project: Project, query_id: str) -> SubmitterKind | None:
    """The capturing actor kind of the inbox item a registered query names in its refs."""
    with project.index.connect() as conn:
        events = conn.execute(
            text("SELECT refs FROM events WHERE type = 'query.registered' AND refs LIKE :pattern"),
            {"pattern": f'%"{query_id}"%'},
        ).all()
    for (refs,) in events:
        for ref in json.loads(str(refs)):
            if str(ref).startswith("inb_"):
                return _item_submitter(project, str(ref), open_only=False)
    return None


def _known_work_ids(project: Project, purpose: QueryPurpose) -> set[str]:
    """The works a run of `purpose` does not count as new: for a probe, every stored work; for any
    other run, the corpus, so a work stored only by a probe lookup is new to the corpus."""
    if purpose is not QueryPurpose.PROBE:
        return corpus_work_ids(project)
    with project.index.connect() as conn:
        return {str(row[0]) for row in conn.execute(text("SELECT work_id FROM works")).all()}


def corpus_work_ids(project: Project) -> set[str]:
    """The ids of the corpus works, as `list_works` would give them, without loading the works."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT work_id FROM provenance "
                "WHERE query_id NOT IN (SELECT query_id FROM queries WHERE purpose = :probe)"
            ),
            {"probe": QueryPurpose.PROBE.value},
        ).all()
    return {str(row[0]) for row in rows}


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


def works_by_ids(project: Project, work_ids: Sequence[str]) -> list[Work]:
    """The corpus works among `work_ids` (as `list_works` would give them), sorted by id.

    Reads by primary key in chunks, never the whole corpus.
    """
    found: list[Work] = []
    unique = sorted(set(work_ids))
    for start in range(0, len(unique), _ID_CHUNK):
        found.extend(_load_works(project, corpus=True, work_ids=unique[start : start + _ID_CHUNK]))
    return found


_ID_CHUNK = 500


def _load_works(
    project: Project,
    work_id: str | None = None,
    *,
    corpus: bool = False,
    work_ids: Sequence[str] | None = None,
) -> list[Work]:
    """Works rebuilt from their stored records and their provenance, sorted by id.

    With `corpus`, probe-purpose provenance rows are dropped and a work left with none is omitted.
    `work_ids` restricts the read to those ids (at most `_ID_CHUNK` per call).
    """
    project.index.sync()
    params: dict[str, Any] = {}
    where = ""
    if work_id is not None:
        where = " WHERE work_id = :work"
        params = {"work": work_id}
    elif work_ids is not None:
        where = " WHERE work_id IN :ids"
        params = {"ids": list(work_ids)}

    def run(sql: str) -> TextClause:
        statement = text(sql)
        return (
            statement.bindparams(bindparam("ids", expanding=True))
            if work_ids is not None
            else statement
        )

    with project.index.connect() as conn:
        rows = conn.execute(
            run(f"SELECT work_id, data FROM works{where} ORDER BY work_id"), params
        ).all()
        prov_rows = (
            conn.execute(
                run(f"SELECT {_PROVENANCE_COLUMNS} FROM provenance{where} ORDER BY at, run_id"),
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
