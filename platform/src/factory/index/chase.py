"""Projection of citation chasing and late admission: rounds, sample extensions and seed admissions.

`chase_rounds` keeps each round (directions, source works, unchasable works, canonical JSON) and
`chase_queries` its query texts in registration order. `round_texts` returns those texts, the ones
the authorisation gate may waive for a chase spec.

`sample_extensions` keeps each pass-B extension draw. `sample_considered` keeps every work any
extension considered, once, with `added` set when pass B took it; `extended_works` and
`considered_works` read it.

`seed_admissions` keeps the first admission per seed.

Handlers are total and first-write-wins: a second round, extension or admission with a known key
changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.chase import ChaseRoundStarted, SampleExtended, SeedAdmitted


@dataclass(frozen=True)
class ChaseTables:
    rounds: Table
    queries: Table
    extensions: Table
    considered: Table
    admissions: Table


def chase_tables(metadata: MetaData) -> ChaseTables:
    rounds = Table(
        "chase_rounds",
        metadata,
        Column("round_id", String, primary_key=True),
        Column("directions", String, nullable=False),
        Column("from_works", String, nullable=False),
        Column("unchasable", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    queries = Table(
        "chase_queries",
        metadata,
        Column("round_id", String, primary_key=True),
        Column("position", Integer, primary_key=True),
        Column("query", String, nullable=False),
    )
    extensions = Table(
        "sample_extensions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("random_seed", Integer, nullable=False),
    )
    considered = Table(
        "sample_considered",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("added", Integer, nullable=False),
    )
    admissions = Table(
        "seed_admissions",
        metadata,
        Column("seed_id", String, primary_key=True),
        Column("run_id", String, nullable=False),
        Column("work_id", String),
        Column("event_id", String, nullable=False),
    )
    return ChaseTables(rounds, queries, extensions, considered, admissions)


def chase_handlers(t: ChaseTables) -> dict[str, Handler]:
    return {
        "chase.round_started": _round_started(t),
        "screening.sample_extended": _sample_extended(t),
        "seed.admitted": _seed_admitted(t),
    }


def _round_started(t: ChaseTables) -> Handler:
    def round_started(conn: Connection, event: Event) -> None:
        payload = ChaseRoundStarted.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.rounds)
            .values(
                round_id=payload.round_id,
                directions=canonical_json([d.value for d in payload.directions]).decode(),
                from_works=canonical_json(list(payload.from_works)).decode(),
                unchasable=canonical_json(list(payload.unchasable)).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["round_id"])
        )
        if inserted.rowcount == 0:
            return
        for position, query in enumerate(payload.queries):
            conn.execute(
                sqlite_insert(t.queries)
                .values(round_id=payload.round_id, position=position, query=query)
                .on_conflict_do_nothing(index_elements=["round_id", "position"])
            )

    return round_started


def _sample_extended(t: ChaseTables) -> Handler:
    def sample_extended(conn: Connection, event: Event) -> None:
        payload = SampleExtended.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.extensions)
            .values(event_id=event.id, random_seed=payload.random_seed)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        if inserted.rowcount == 0:
            return
        added = set(payload.added)
        for work_id in payload.considered:
            conn.execute(
                sqlite_insert(t.considered)
                .values(
                    work_id=work_id,
                    event_id=event.id,
                    added=1 if work_id in added else 0,
                )
                .on_conflict_do_nothing(index_elements=["work_id"])
            )

    return sample_extended


def _seed_admitted(t: ChaseTables) -> Handler:
    def seed_admitted(conn: Connection, event: Event) -> None:
        payload = SeedAdmitted.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.admissions)
            .values(
                seed_id=payload.seed_id,
                run_id=payload.run_id,
                work_id=payload.work_id,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["seed_id"])
        )

    return seed_admitted


def round_texts(conn: Connection) -> set[str]:
    """Every chase query text a recorded round registered (the texts the gate may waive)."""
    rows = conn.execute(text("SELECT query FROM chase_queries")).all()
    return {str(row[0]) for row in rows}


def extended_works(conn: Connection) -> set[str]:
    """The works pass B's sample was extended with: considered and drawn into the sample."""
    rows = conn.execute(text("SELECT work_id FROM sample_considered WHERE added = 1")).all()
    return {str(row[0]) for row in rows}


def considered_works(conn: Connection) -> set[str]:
    """Every work any sample extension has considered, drawn or not."""
    rows = conn.execute(text("SELECT work_id FROM sample_considered")).all()
    return {str(row[0]) for row in rows}
