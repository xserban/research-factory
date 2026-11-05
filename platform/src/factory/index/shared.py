"""Schema and writes of the shared mining store (slice M rulings 18-20; R-47).

A second SQLite projection at `<root>/.mining/shared.sqlite`, across every project under the root.
It is its own schema with its own version and state hash, and has nothing to do with a project's
index. `services.shared_mining.SharedStore` is its only writer.

Invariants:
- No document text: keys, hashes, pass identities and statuses only. No column holds a value, a
  quote or an anchor's text; `field_digests` holds a SHA-256 per stored field.
- Everything of one project is replaced in one transaction, offsets included, so a failed fold
  leaves that project as it was and is tried again on the next sync.
- `shared_conversions` maps a project's conversion to its content hash: a conversion id is minted
  per project, so two projects hold one conversion when these hashes are equal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, delete, insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

SHARED_PROJECTION_VERSION = "1"
"""Bump on any change to the tables below or to what a fold writes; the store is then rebuilt."""

NON_STATE_TABLES = frozenset({"shared_meta", "shared_sync_state"})
"""Tables outside the state hash: the version, and the offsets that only say how far a sync read."""

STATUS_OK = "ok"
STATUS_OPTED_OUT = "opted-out"
STATUS_UNREADABLE = "unreadable"

FINAL_STATUSES = ("agreed", "resolved", "single")
"""A record a project stands by. `superseded` and `stale` no longer stand; `pending` is a live row
that is not final yet (an open unit, an unresolved disagreement)."""


@dataclass(frozen=True)
class SharedTables:
    meta: Table
    projects: Table
    sync_state: Table
    miners: Table
    conversions: Table
    records: Table


def shared_tables(metadata: MetaData) -> SharedTables:
    meta = Table(
        "shared_meta",
        metadata,
        Column("key", String, primary_key=True),
        Column("value", String, nullable=False),
    )
    projects = Table(
        "shared_projects",
        metadata,
        Column("slug", String, primary_key=True),
        Column("last_event_id", String),
        Column("status", String, nullable=False),
    )
    sync_state = Table(
        "shared_sync_state",
        metadata,
        Column("project", String, primary_key=True),
        Column("file", String, primary_key=True),
        Column("offset", Integer, nullable=False),
    )
    miners = Table(
        "shared_miners",
        metadata,
        Column("project", String, primary_key=True),
        Column("name", String, primary_key=True),
        Column("version", Integer, primary_key=True),
        Column("digest", String, nullable=False),
        Column("miner_id", String, nullable=False),
    )
    conversions = Table(
        "shared_conversions",
        metadata,
        Column("project", String, primary_key=True),
        Column("conversion_id", String, primary_key=True),
        Column("content_hash", String, nullable=False),
        Index("ix_shared_conversions_hash", "content_hash"),
    )
    records = Table(
        "shared_records",
        metadata,
        Column("project", String, primary_key=True),
        Column("miner", String, primary_key=True),
        Column("version", Integer, primary_key=True),
        Column("conversion_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("row_key", String, primary_key=True),
        Column("digest", String, nullable=False),
        Column("status", String, nullable=False),
        Column("extraction_ids", String, nullable=False),
        Column("pass_labels", String, nullable=False),
        Column("models", String, nullable=False),
        Column("field_digests", String, nullable=False),
        Column("source_last_event", String, nullable=False),
        Index("ix_shared_lookup", "miner", "version", "digest", "conversion_id"),
    )
    return SharedTables(meta, projects, sync_state, miners, conversions, records)


@dataclass(frozen=True)
class SharedFold:
    """What one project contributes, as table rows; `offsets` is how far its files were read."""

    last_event_id: str | None
    offsets: Mapping[str, int]
    miners: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    conversions: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    records: Sequence[Mapping[str, object]] = field(default_factory=tuple)


def clear_project(conn: Connection, t: SharedTables, slug: str) -> None:
    """Remove everything of `slug`, its row in `shared_projects` too."""
    for table in (t.sync_state, t.miners, t.conversions, t.records):
        conn.execute(delete(table).where(table.c.project == slug))
    conn.execute(delete(t.projects).where(t.projects.c.slug == slug))


def replace_project(conn: Connection, t: SharedTables, slug: str, fold: SharedFold) -> None:
    """Replace what the store holds of `slug` with `fold`. The caller holds the transaction."""
    clear_project(conn, t, slug)
    conn.execute(
        insert(t.projects).values(slug=slug, last_event_id=fold.last_event_id, status=STATUS_OK)
    )
    offsets = [{"project": slug, "file": f, "offset": o} for f, o in sorted(fold.offsets.items())]
    for table, rows in (
        (t.sync_state, offsets),
        (t.miners, fold.miners),
        (t.conversions, fold.conversions),
        (t.records, fold.records),
    ):
        if rows:
            conn.execute(insert(table), [dict(row) for row in rows])


def opt_out_project(conn: Connection, t: SharedTables, slug: str) -> None:
    """`slug` declines to be a source: nothing of it stays, and the opt-out is reported."""
    clear_project(conn, t, slug)
    conn.execute(insert(t.projects).values(slug=slug, last_event_id=None, status=STATUS_OPTED_OUT))


def mark_unreadable(conn: Connection, t: SharedTables, slug: str) -> None:
    """`slug` could not be read: what the store held of it stays, but no lookup offers it."""
    stmt = sqlite_insert(t.projects).values(slug=slug, last_event_id=None, status=STATUS_UNREADABLE)
    conn.execute(
        stmt.on_conflict_do_update(index_elements=["slug"], set_={"status": STATUS_UNREADABLE})
    )


def set_meta(conn: Connection, t: SharedTables, key: str, value: str) -> None:
    stmt = sqlite_insert(t.meta).values(key=key, value=value)
    conn.execute(
        stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
    )
