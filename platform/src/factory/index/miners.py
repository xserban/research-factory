"""Projection of registered miners (slice M, M-C): one row per `(name, version)`.

`miners` holds the first registration of each `(name, version)`: a later event naming the same pair
changes nothing (the service refuses a different digest, so a replayed log only repeats). `retired`
is reserved for M-D and stays false here. The table is empty for a log without `miner.registered`,
so it is left out of the state hash then.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.miners import MinerRegistered


@dataclass(frozen=True)
class MinerTables:
    miners: Table


def miner_tables(metadata: MetaData) -> MinerTables:
    miners = Table(
        "miners",
        metadata,
        Column("name", String, primary_key=True),
        Column("version", Integer, primary_key=True),
        Column("digest", String, nullable=False),
        Column("miner_id", String, nullable=False),
        Column("registered_by_kind", String, nullable=False),
        Column("proposer_session", String, nullable=False),
        Column("spec_blob", String, nullable=False),
        Column("retired", Boolean, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return MinerTables(miners)


def miner_handlers(t: MinerTables) -> dict[str, Handler]:
    def registered(conn: Connection, event: Event) -> None:
        payload = MinerRegistered.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.miners)
            .values(
                name=payload.name,
                version=payload.version,
                digest=payload.digest,
                miner_id=payload.miner_id,
                registered_by_kind=payload.proposer_kind,
                proposer_session=event.actor.session,
                spec_blob=payload.spec_blob,
                retired=False,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["name", "version"])
        )

    return {"miner.registered": registered}
