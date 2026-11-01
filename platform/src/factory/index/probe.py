"""Projection of probes: one row per (probe, query) measured or failed.

`probes` keeps the measured payload as canonical JSON, with the source, the reported count and
the status, so the report of a probe can be rebuilt from the index. A failed query has a reason
and no measurement. Handlers are total: a second row for the same (probe, query) is ignored
(first write wins). Page archives need no row: their raw blobs are read from the events.
"""

from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.probe import ProbeFailed, ProbeMeasured


@dataclass(frozen=True)
class ProbeTables:
    probes: Table


def probe_tables(metadata: MetaData) -> ProbeTables:
    probes = Table(
        "probes",
        metadata,
        Column("probe_id", String, primary_key=True),
        Column("query_id", String, primary_key=True),
        Column("source", String, nullable=False),
        Column("status", String, nullable=False),
        Column("reported_count", Integer),
        Column("reason", String),
        Column("payload", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return ProbeTables(probes)


def probe_handlers(t: ProbeTables) -> dict[str, Handler]:
    return {
        "probe.measured": _measured(t),
        "probe.failed": _failed(t),
    }


def _measured(t: ProbeTables) -> Handler:
    def measured(conn: Connection, event: Event) -> None:
        payload = ProbeMeasured.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.probes)
            .values(
                probe_id=payload.probe_id,
                query_id=payload.query_id,
                source=payload.source,
                status="measured",
                reported_count=payload.reported_count,
                reason=None,
                payload=canonical_json(payload.model_dump(mode="json")).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["probe_id", "query_id"])
        )

    return measured


def _failed(t: ProbeTables) -> Handler:
    def failed(conn: Connection, event: Event) -> None:
        payload = ProbeFailed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.probes)
            .values(
                probe_id=payload.probe_id,
                query_id=payload.query_id,
                source=payload.source,
                status="failed",
                reported_count=None,
                reason=payload.reason,
                payload=canonical_json(payload.model_dump(mode="json")).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["probe_id", "query_id"])
        )

    return failed
