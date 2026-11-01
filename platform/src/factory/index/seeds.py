"""Projection of seeds: added seeds, their first outcome, the hold-out split and explanations.

`seeds` keeps each added seed and the first outcome recorded for it. `seed_split` holds the one
split (a singleton row; its lists are canonical JSON). `seed_explanations` keeps the first
explanation per seed. Handlers are total: an outcome for an unknown seed, or a second outcome for
a seed that already has one, changes nothing (first write wins).
"""

from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.seed import (
    SeedAdded,
    SeedMissExplained,
    SeedResolved,
    SeedSplitDrawn,
    SeedUnresolved,
)


@dataclass(frozen=True)
class SeedTables:
    seeds: Table
    split: Table
    explanations: Table


def seed_tables(metadata: MetaData) -> SeedTables:
    seeds = Table(
        "seeds",
        metadata,
        Column("seed_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("spec", String, nullable=False),
        Column("work_id", String),
        Column("run_id", String),
        Column("unresolved_reason", String),
        Column("added_event", String, nullable=False),
    )
    split = Table(
        "seed_split",
        metadata,
        Column("singleton", Integer, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("random_seed", Integer, nullable=False),
        Column("procedure", String, nullable=False),
        Column("development", String, nullable=False),
        Column("held_out", String, nullable=False),
    )
    explanations = Table(
        "seed_explanations",
        metadata,
        Column("seed_id", String, primary_key=True),
        Column("reason", String, nullable=False),
        Column("route", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return SeedTables(seeds, split, explanations)


def seed_handlers(t: SeedTables) -> dict[str, Handler]:
    return {
        "seed.added": _added(t),
        "seed.resolved": _resolved(t),
        "seed.unresolved": _unresolved(t),
        "seed.split_drawn": _split_drawn(t),
        "seed.miss_explained": _miss_explained(t),
    }


def _split_drawn(t: SeedTables) -> Handler:
    def split_drawn(conn: Connection, event: Event) -> None:
        payload = SeedSplitDrawn.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.split)
            .values(
                singleton=1,
                event_id=event.id,
                random_seed=payload.random_seed,
                procedure=payload.procedure,
                development=canonical_json(list(payload.development)).decode(),
                held_out=canonical_json(list(payload.held_out)).decode(),
            )
            .on_conflict_do_nothing(index_elements=["singleton"])
        )

    return split_drawn


def _miss_explained(t: SeedTables) -> Handler:
    def miss_explained(conn: Connection, event: Event) -> None:
        payload = SeedMissExplained.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.explanations)
            .values(
                seed_id=payload.seed_id,
                reason=payload.reason,
                route=payload.route.value,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["seed_id"])
        )

    return miss_explained


def _added(t: SeedTables) -> Handler:
    def added(conn: Connection, event: Event) -> None:
        payload = SeedAdded.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.seeds)
            .values(
                seed_id=payload.seed_id,
                kind=payload.spec.kind.value,
                spec=canonical_json(payload.spec.model_dump(mode="json")).decode(),
                work_id=None,
                run_id=None,
                unresolved_reason=None,
                added_event=event.id,
            )
            .on_conflict_do_nothing(index_elements=["seed_id"])
        )

    return added


def _resolved(t: SeedTables) -> Handler:
    def resolved(conn: Connection, event: Event) -> None:
        payload = SeedResolved.model_validate(event.payload)
        conn.execute(
            update(t.seeds)
            .where(t.seeds.c.seed_id == payload.seed_id)
            .where(t.seeds.c.work_id.is_(None), t.seeds.c.unresolved_reason.is_(None))
            .values(work_id=payload.work_id, run_id=payload.run_id)
        )

    return resolved


def _unresolved(t: SeedTables) -> Handler:
    def unresolved(conn: Connection, event: Event) -> None:
        payload = SeedUnresolved.model_validate(event.payload)
        conn.execute(
            update(t.seeds)
            .where(t.seeds.c.seed_id == payload.seed_id)
            .where(t.seeds.c.work_id.is_(None), t.seeds.c.unresolved_reason.is_(None))
            .values(run_id=payload.run_id, unresolved_reason=payload.reason)
        )

    return unresolved
