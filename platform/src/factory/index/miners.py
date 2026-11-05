"""Projection of registered miners (slice M, M-C): one row per `(name, version)`.

`miners` holds the first registration of each `(name, version)`: a later event naming the same pair
changes nothing (the service refuses a different digest, so a replayed log only repeats). `retired`
becomes true on `miner.retired` (M-D). The table is empty for a log without `miner.registered`,
so it is left out of the state hash then.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Boolean, Column, Index, Integer, MetaData, String, Table, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.miner_calibration import MinerCalibrationDrawn, MinerCalibrationLabelled
from factory.model.miners import MinerRegistered, MinerRetired


@dataclass(frozen=True)
class MinerTables:
    miners: Table
    calibrations: Table
    calibration_units: Table
    calibration_labels: Table
    label_sessions: Table


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
    calibrations = Table(
        "miner_calibrations",
        metadata,
        Column("calibration_id", String, primary_key=True),
        Column("name", String, nullable=False),
        Column("version", Integer, nullable=False),
        Column("digest", String, nullable=False),
        Column("random_seed", Integer, nullable=False),
        Column("population", Integer, nullable=False),
        Column("population_digest", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_miner_calibrations_miner", "name", "version"),
    )
    units = Table(
        "miner_calibration_units",
        metadata,
        Column("calibration_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("conversion_id", String, nullable=False),
    )
    labels = Table(
        "miner_calibration_labels",
        metadata,
        Column("calibration_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("empty", Boolean, nullable=False),
        Column("rows_json", String, nullable=False),
        Column("channel", String, nullable=False),
        Column("session", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    label_sessions = Table(
        "miner_calibration_label_sessions",
        metadata,
        Column("calibration_id", String, primary_key=True),
        Column("session", String, primary_key=True),
    )
    return MinerTables(miners, calibrations, units, labels, label_sessions)


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

    def retired(conn: Connection, event: Event) -> None:
        payload = MinerRetired.model_validate(event.payload)
        conn.execute(
            update(t.miners)
            .where(t.miners.c.name == payload.name, t.miners.c.version == payload.version)
            .values(retired=True)
        )

    def drawn(conn: Connection, event: Event) -> None:
        payload = MinerCalibrationDrawn.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.calibrations)
            .values(
                calibration_id=payload.calibration_id,
                name=payload.name,
                version=payload.version,
                digest=payload.digest,
                random_seed=payload.random_seed,
                population=payload.population,
                population_digest=payload.population_digest,
                protocol_id=payload.protocol_id,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["calibration_id"])
        )
        if inserted.rowcount:
            conn.execute(
                sqlite_insert(t.calibration_units),
                [
                    {
                        "calibration_id": payload.calibration_id,
                        "work_id": u.work_id,
                        "conversion_id": u.conversion_id,
                    }
                    for u in payload.units
                ],
            )

    def labelled(conn: Connection, event: Event) -> None:
        payload = MinerCalibrationLabelled.model_validate(event.payload)
        unit = conn.execute(
            select(t.calibration_units.c.work_id).where(
                t.calibration_units.c.calibration_id == payload.calibration_id,
                t.calibration_units.c.work_id == payload.work_id,
            )
        ).first()
        if unit is None:
            return  # a label of no drawn unit changes nothing
        conn.execute(
            sqlite_insert(t.label_sessions)
            .values(calibration_id=payload.calibration_id, session=event.actor.session)
            .on_conflict_do_nothing()
        )
        rows = canonical_json([r.model_dump(mode="json") for r in payload.rows]).decode()
        values = {
            "empty": payload.empty,
            "rows_json": rows,
            "channel": payload.channel.value,
            "session": event.actor.session,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.calibration_labels)
            .values(calibration_id=payload.calibration_id, work_id=payload.work_id, **values)
            .on_conflict_do_update(index_elements=["calibration_id", "work_id"], set_=values)
        )

    return {
        "miner.registered": registered,
        "miner.retired": retired,
        "miner.calibration_drawn": drawn,
        "miner.calibration_labelled": labelled,
    }
