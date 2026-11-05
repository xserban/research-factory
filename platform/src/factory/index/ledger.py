"""Confirmations of the contribution ledger: `ledger_confirmations`, one row per person, the latest.

The ledger itself is computed on read. A confirmation is a table because whether one counts depends
on who held `owner` at that point of the log, which a read cannot ask.

Invariants:
- Handlers are total: a malformed payload, or an event that fails a guard, changes nothing, on
  rebuild too.
- Only a person confirms, in their own name, and never over a relay.
- A person confirms their own entry. Confirming for another needs a reason and `owner` at that point
  of the log (or, while no grant has counted, a person: the fold cannot know `Settings.user`).
- The fold cannot ask the lab whether the user is deactivated, since a rebuild reads this log
  alone. That check is the service's.
- A pin to a hash that is not the ledger's is harmless: it folds, and reads as stale.
"""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Actor, Event
from factory.index.members import MemberTables, any_grant, live_roles
from factory.index.projection import Handler
from factory.model.ledger import LEDGER_CONFIRMED, LedgerConfirmed
from factory.model.members import ProjectRole
from factory.model.screening import Channel


@dataclass(frozen=True)
class LedgerTables:
    confirmations: Table


def ledger_tables(metadata: MetaData) -> LedgerTables:
    return LedgerTables(
        confirmations=Table(
            "ledger_confirmations",
            metadata,
            Column("user", String, primary_key=True),
            Column("ledger_hash", String, nullable=False),
            Column("map_version", String, nullable=False),
            Column("channel", String, nullable=False),
            Column("event_id", String, nullable=False),
        )
    )


LEDGER_TABLES = ledger_tables(MetaData())
"""A handle for the services' reads, as the projection's tables are built per index."""


def in_own_name(actor: Actor) -> bool:
    return actor.kind == "human" and actor.id == actor.user


def governs(conn: Connection, members: MemberTables, actor: Actor) -> bool:
    """Whether a person may act as owner at this point of the log. While no grant has counted the
    project has an implicit owner the fold cannot name, so that check is the service's."""
    if not in_own_name(actor):
        return False
    if not any_grant(conn, members):
        return True
    return ProjectRole.OWNER in live_roles(conn, members, actor.user)


def _confirmed(tables: LedgerTables, members: MemberTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = LedgerConfirmed.model_validate(event.payload)
        except ValidationError:
            return
        if not in_own_name(event.actor) or payload.channel is Channel.MCP:
            return
        if payload.user != event.actor.user and (
            payload.reason is None or not governs(conn, members, event.actor)
        ):
            return
        values = {
            "ledger_hash": payload.ledger_hash,
            "map_version": payload.map_version,
            "channel": payload.channel.value,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(tables.confirmations)
            .values(user=payload.user, **values)
            .on_conflict_do_update(index_elements=["user"], set_=values)
        )

    return fold


def ledger_handlers(tables: LedgerTables, members: MemberTables) -> dict[str, Handler]:
    return {LEDGER_CONFIRMED: _confirmed(tables, members)}
