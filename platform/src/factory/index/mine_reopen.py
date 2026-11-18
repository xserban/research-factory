"""Projection of `mine.reopened` (IDEA-99): one row per accepted reopening of a mined unit.

`mine_reopenings` says which unit (miner, work, pass) was reopened, at which event, and which
completed task it reopened. The extraction ledger reads it: the unit is stale (`reopened`) until a
task created after the event completes, and the rows recorded before the event are stale.

The handler is total and atomic. It writes nothing unless every guard holds, for a hand-written
event as for a replayed one, and it reads only this project's tables, never a blob or the library
(decision 39: the state hash depends on events alone):
- the payload parses and its writer is a human (the researcher's act, relayed or not);
- the miner version is registered here;
- `extraction.closed` closed the task for this miner, work and pass, no later closure of the unit
  exists (it is the unit's latest closed task), and the unit was not reopened since.
Whether the task's selection fell below the fallback threshold needs the manifest, so the service
judges it before it writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.extraction import ExtractionTables
from factory.index.miners import MinerTables
from factory.index.projection import Handler
from factory.model.extraction import MinerScope
from factory.model.mine_reopen import MineReopened


@dataclass(frozen=True)
class MineReopenTables:
    reopenings: Table


def mine_reopen_tables(metadata: MetaData) -> MineReopenTables:
    reopenings = Table(
        "mine_reopenings",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("miner", String, nullable=False),
        Column("version", Integer, nullable=False),
        Column("work_id", String, nullable=False),
        Column("pass_label", String, nullable=False),
        Column("task_id", String, nullable=False),
        Column("reason", String, nullable=False),
        Index("ix_mine_reopenings_unit", "miner", "work_id", "pass_label"),
    )
    return MineReopenTables(reopenings)


def mine_reopen_handlers(
    t: MineReopenTables, extraction: ExtractionTables, miners: MinerTables
) -> dict[str, Handler]:
    def stands(conn: Connection, p: MineReopened) -> bool:
        registered = conn.execute(
            select(miners.miners.c.name)
            .where(miners.miners.c.name == p.miner)
            .where(miners.miners.c.version == p.version)
        ).first()
        if registered is None:
            return False
        closed = extraction.closures
        scope = MinerScope(p.miner).value
        found = conn.execute(
            select(closed.c.event_id)
            .where(closed.c.task_id == p.task_id)
            .where(closed.c.scope == scope)
            .where(closed.c.work_id == p.work_id)
            .where(closed.c.pass_label == p.pass_label.value)
        ).first()
        if found is None:
            return False
        closed_at = str(found[0])
        later = conn.execute(  # the task is the unit's latest closed one
            select(closed.c.task_id)
            .where(closed.c.scope == scope)
            .where(closed.c.work_id == p.work_id)
            .where(closed.c.pass_label == p.pass_label.value)
            .where(closed.c.event_id > closed_at)
        ).first()
        again = conn.execute(  # and not reopened since it closed
            select(t.reopenings.c.event_id)
            .where(t.reopenings.c.miner == p.miner)
            .where(t.reopenings.c.work_id == p.work_id)
            .where(t.reopenings.c.pass_label == p.pass_label.value)
            .where(t.reopenings.c.event_id > closed_at)
        ).first()
        return later is None and again is None

    def reopened(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        try:
            p = MineReopened.model_validate(event.payload)
        except ValidationError:
            return
        if not stands(conn, p):
            return
        conn.execute(
            sqlite_insert(t.reopenings)
            .values(
                event_id=event.id,
                miner=p.miner,
                version=p.version,
                work_id=p.work_id,
                pass_label=p.pass_label.value,
                task_id=p.task_id,
                reason=p.reason,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return {"mine.reopened": reopened}
