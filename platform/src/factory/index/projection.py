from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.engine import Connection

from factory.events.envelope import Event

Handler = Callable[[Connection, Event], None]


@dataclass(frozen=True)
class Projection:
    """A versioned set of tables plus the handlers that fold events into them.

    Bump `version` whenever the tables or handlers change; the index is then rebuilt.
    The metadata must include the core tables (see `core_tables`).
    """

    version: str
    metadata: MetaData
    handlers: Mapping[str, Handler]


def core_tables(metadata: MetaData) -> None:
    """Add the tables every projection shares: meta, sync_state and events."""
    Table(
        "meta",
        metadata,
        Column("key", String, primary_key=True),
        Column("value", String, nullable=False),
    )
    Table(
        "sync_state",
        metadata,
        Column("file", String, primary_key=True),
        Column("offset", Integer, nullable=False),
    )
    Table(
        "events",
        metadata,
        Column("id", String, primary_key=True),
        Column("ts", String, nullable=False),
        Column("type", String, nullable=False),
        Column("actor_kind", String, nullable=False),
        Column("actor_id", String, nullable=False),
        Column("user", String, nullable=False),
        Column("session", String, nullable=False),
        Column("model", String),
        Column("skill", String),
        Column("input_blob", String),
        Column("refs", String, nullable=False),
    )
