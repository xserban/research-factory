"""Projection of queries, search runs, archived pages, works and their provenance.

Handlers are total: an event that does not apply (an unknown run or query, a repeat of an
outcome already folded in) is ignored and leaves the rows unchanged. Rules use only event data
(`event.ts`), never the wall clock, so a rebuild reproduces the incremental state exactly.
"""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.search import (
    QueryRegistered,
    RunStatus,
    SearchPageArchived,
    SearchRecordsParsed,
    SearchRunFinished,
    SearchRunStarted,
)
from factory.model.work import Work


@dataclass(frozen=True)
class SearchTables:
    queries: Table
    runs: Table
    pages: Table
    works: Table
    provenance: Table


def search_tables(metadata: MetaData) -> SearchTables:
    queries = Table(
        "queries",
        metadata,
        Column("query_id", String, primary_key=True),
        Column("source", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("text", String, nullable=False),
        Column("purpose", String, nullable=False),
        Column("filters", String, nullable=False),
        Column("limit", Integer),
        Column("interface", String, nullable=False),
        Column("registered_at", String, nullable=False),
        Column("actor_id", String, nullable=False),
    )
    runs = Table(
        "runs",
        metadata,
        Column("run_id", String, primary_key=True),
        Column("query_id", String, nullable=False),
        Column("source", String, nullable=False),
        Column("status", String, nullable=False),
        Column("started_at", String, nullable=False),
        Column("finished_at", String),
        Column("reported_count", Integer),
        Column("retrieved_count", Integer),
        Column("skipped", Integer),
        Column("note", String),
        Column("resume_token", String),
        Column("resume_of", String),
        Column("pages", Integer, nullable=False),
    )
    pages = Table(
        "pages",
        metadata,
        Column("run_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("raw_blob", String, nullable=False),
        Column("url", String, nullable=False),
        Column("fetched_at", String, nullable=False),
    )
    works = Table(
        "works",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("data", String, nullable=False),
        Column("first_event_id", String, nullable=False),
    )
    provenance = Table(
        "provenance",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("run_id", String, primary_key=True),
        Column("query_id", String, nullable=False),
        Column("source", String, nullable=False),
        Column("method", String, nullable=False),
        Column("raw_blob", String, nullable=False),
        Column("raw_ref", String),
        Column("at", String, nullable=False),
    )
    return SearchTables(queries, runs, pages, works, provenance)


def search_handlers(t: SearchTables) -> dict[str, Handler]:
    return {
        "query.registered": _query_registered(t),
        "search.run_started": _run_started(t),
        "search.page_archived": _page_archived(t),
        "search.records_parsed": _records_parsed(t),
        "search.run_finished": _run_finished(t),
    }


def _query_registered(t: SearchTables) -> Handler:
    def query_registered(conn: Connection, event: Event) -> None:
        payload = QueryRegistered.model_validate(event.payload)
        spec = payload.spec
        filters: dict[str, JsonValue] = {key: value for key, value in spec.filters.items()}
        # First registration wins: a query id is never re-pointed at a different request.
        conn.execute(
            sqlite_insert(t.queries)
            .values(
                query_id=payload.query_id,
                source=spec.source,
                kind=spec.kind.value,
                text=spec.text,
                purpose=spec.purpose.value,
                filters=canonical_json(filters).decode(),
                limit=spec.limit,
                interface=payload.interface,
                registered_at=format_ts(event.ts),
                actor_id=event.actor.id,
            )
            .on_conflict_do_nothing(index_elements=["query_id"])
        )

    return query_registered


def _run_started(t: SearchTables) -> Handler:
    def run_started(conn: Connection, event: Event) -> None:
        payload = SearchRunStarted.model_validate(event.payload)
        query = conn.execute(
            select(t.queries.c.source).where(t.queries.c.query_id == payload.query_id)
        ).one_or_none()
        if query is None:
            return
        conn.execute(
            sqlite_insert(t.runs)
            .values(
                run_id=payload.run_id,
                query_id=payload.query_id,
                source=query.source,
                status=RunStatus.RUNNING.value,
                started_at=format_ts(event.ts),
                finished_at=None,
                reported_count=None,
                retrieved_count=None,
                skipped=None,
                note=None,
                resume_token=None,
                resume_of=payload.resume_of,
                pages=0,
            )
            .on_conflict_do_nothing(index_elements=["run_id"])
        )

    return run_started


def _page_archived(t: SearchTables) -> Handler:
    def page_archived(conn: Connection, event: Event) -> None:
        payload = SearchPageArchived.model_validate(event.payload)
        if not _run_exists(conn, t, payload.run_id):
            return
        inserted = conn.execute(
            sqlite_insert(t.pages)
            .values(
                run_id=payload.run_id,
                ordinal=payload.ordinal,
                raw_blob=payload.raw_blob,
                url=payload.url,
                fetched_at=format_ts(payload.fetched_at),
            )
            .on_conflict_do_nothing(index_elements=["run_id", "ordinal"])
        ).rowcount
        # A repeated ordinal is the same page: it is counted once.
        if inserted:
            conn.execute(
                update(t.runs)
                .where(t.runs.c.run_id == payload.run_id)
                .values(pages=t.runs.c.pages + 1)
            )

    return page_archived


def _records_parsed(t: SearchTables) -> Handler:
    def records_parsed(conn: Connection, event: Event) -> None:
        payload = SearchRecordsParsed.model_validate(event.payload)
        if not _run_exists(conn, t, payload.run_id):
            return
        for work in payload.records:
            _upsert_work(conn, t, work, event.id)
            for prov in work.provenance:
                conn.execute(
                    sqlite_insert(t.provenance)
                    .values(
                        work_id=work.id,
                        run_id=prov.run_id,
                        query_id=prov.query_id,
                        source=prov.source,
                        method=prov.method.value,
                        raw_blob=prov.raw_blob,
                        raw_ref=prov.raw_ref,
                        at=format_ts(prov.at),
                    )
                    .on_conflict_do_nothing(index_elements=["work_id", "run_id"])
                )

    return records_parsed


def _run_finished(t: SearchTables) -> Handler:
    def run_finished(conn: Connection, event: Event) -> None:
        payload = SearchRunFinished.model_validate(event.payload)
        current = conn.execute(
            select(t.runs.c.status).where(t.runs.c.run_id == payload.run_id)
        ).one_or_none()
        # Only a running run can finish: an unknown run, or a repeated outcome, changes nothing.
        if current is None or current.status != RunStatus.RUNNING.value:
            return
        conn.execute(
            update(t.runs)
            .where(t.runs.c.run_id == payload.run_id)
            .values(
                status=payload.status.value,
                finished_at=format_ts(event.ts),
                reported_count=payload.reported_count,
                retrieved_count=payload.retrieved_count,
                skipped=payload.skipped,
                note=payload.note,
                resume_token=payload.resume_token,
            )
        )

    return run_finished


def _run_exists(conn: Connection, t: SearchTables, run_id: str) -> bool:
    return (
        conn.execute(select(t.runs.c.run_id).where(t.runs.c.run_id == run_id)).one_or_none()
        is not None
    )


def _upsert_work(conn: Connection, t: SearchTables, work: Work, event_id: str) -> None:
    """Store a work's record without provenance; later records only fill gaps.

    First seen wins, except that an identifier or abstract missing from the stored record is
    filled from a later one. Provenance is a separate table and never touches this row.
    """
    record: dict[str, Any] = work.model_dump(mode="json", exclude={"provenance"})
    stored = conn.execute(
        select(t.works.c.data).where(t.works.c.work_id == work.id)
    ).scalar_one_or_none()
    if stored is None:
        conn.execute(
            insert(t.works).values(
                work_id=work.id,
                data=canonical_json(record).decode(),
                first_event_id=event_id,
            )
        )
        return
    current: dict[str, Any] = json.loads(str(stored))
    merged = _fill_gaps(current, record)
    if merged != current:
        conn.execute(
            update(t.works)
            .where(t.works.c.work_id == work.id)
            .values(data=canonical_json(merged).decode())
        )


def _fill_gaps(stored: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    identifiers: dict[str, Any] = dict(stored["identifiers"])
    for key, value in new["identifiers"].items():
        if identifiers.get(key) is None and value is not None:
            identifiers[key] = value
    merged = {**stored, "identifiers": identifiers}
    if merged.get("abstract") is None:
        merged["abstract"] = new.get("abstract")
    return merged
