"""Projection of the discovery feed (slice 4c, decision 117): configuration, fetches, entries,
rankings, reactions and sends.

Tables: `feed_configs` (one row, the latest configuration, replaced), `feed_fetches`,
`feed_entries` (read from the `entries_blob` of `feed.fetched` through the project's blob store,
as the ranking projection reads its order blob), `feed_rankings` (the newest by event order is
the latest), `feed_reactions` (every reaction is kept) and `feed_sends` (one row per entry).

Folded only if (a hand-written event failing a guard changes nothing on rebuild):
- `feed.configured`: the actor is a human. The row replaces the previous configuration.
- `feed.fetched`: the actor is the system or an agent (never a human) and the entries blob is
  a readable list. An entry that is not valid, or already known, is skipped (the first fetch
  that saw it stands).
- `feed.ranked`: the actor is the system or an agent (never a human).
- `feed.reacted`: the actor is a human; the entry and the ranking are known.
- `feed.sent`: the actor is a human; the entry is known; the inbox item exists in the inbox
  projection; the entry is not already sent (the first send stands).

Handlers are total: an event that does not validate, or whose blob is unreadable, changes nothing.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from pydantic import JsonValue, ValidationError
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, delete, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.feed import (
    FEED_ENTRY_RE,
    FeedConfigured,
    FeedFetched,
    FeedRanked,
    FeedReacted,
    FeedSent,
)
from factory.model.work_ids import WORK_ID_RE

_ENTRY = re.compile(FEED_ENTRY_RE)
_WORK = re.compile(WORK_ID_RE)


@dataclass(frozen=True)
class FeedTables:
    configs: Table
    fetches: Table
    entries: Table
    rankings: Table
    reactions: Table
    sends: Table


def feed_tables(metadata: MetaData) -> FeedTables:
    configs = Table(
        "feed_configs",
        metadata,
        Column("config_id", String, primary_key=True),
        Column("config", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    fetches = Table(
        "feed_fetches",
        metadata,
        Column("fetch_id", String, primary_key=True),
        Column("window_from", String, nullable=False),
        Column("window_to", String, nullable=False),
        Column("complete", Integer, nullable=False),
        Column("count", Integer, nullable=False),
        Column("held_count", Integer, nullable=False),
        Column("event_id", String, nullable=False),
    )
    entries = Table(
        "feed_entries",
        metadata,
        Column("entry_id", String, primary_key=True),
        Column("version", String),
        Column("title", String, nullable=False),
        Column("first_fetch_id", String, nullable=False),
        Column("held_work_id", String),
    )
    rankings = Table(
        "feed_rankings",
        metadata,
        Column("ranking_id", String, primary_key=True),
        Column("reference_hash", String, nullable=False),
        Column("shown", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    reactions = Table(
        "feed_reactions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("entry_id", String, nullable=False, index=True),
        Column("reaction", String, nullable=False),
        Column("ranking_id", String, nullable=False),
        Column("rank_shown", Integer, nullable=False),
        Column("score_shown", Float, nullable=False),
        Column("actor", String, nullable=False),
    )
    sends = Table(
        "feed_sends",
        metadata,
        Column("entry_id", String, primary_key=True),
        Column("ranking_id", String, nullable=False),
        Column("inbox_item_id", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return FeedTables(configs, fetches, entries, rankings, reactions, sends)


def _total(handler: Handler) -> Handler:
    def run(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (
            ValidationError,
            ValueError,
            ArithmeticError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
        ):
            return

    return run


def _parsed_entries(blobs: BlobStore, ref: str) -> list[tuple[str, str | None, str, str | None]]:
    """`(entry_id, version, title, held_work_id)` of each valid entry of the blob; an empty list
    for an unreadable blob or one that is not a list (the caller then folds nothing)."""
    try:
        value = blobs.get_json(ref)
    except (FactoryError, OSError, EOFError, ValueError, zlib.error):
        raise ValueError("unreadable entries blob") from None
    if not isinstance(value, list):
        raise ValueError("entries blob is not a list")
    out: list[tuple[str, str | None, str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entry_id, title = item.get("id", item.get("entry_id")), item.get("title")
        if not isinstance(entry_id, str) or not _ENTRY.match(entry_id):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        version = item.get("version")
        held = item.get("held_work_id")
        out.append(
            (
                entry_id,
                None if version is None or isinstance(version, bool) else str(version),
                title,
                held if isinstance(held, str) and _WORK.match(held) else None,
            )
        )
    return out


def feed_handlers(t: FeedTables, blobs: BlobStore | None) -> dict[str, Handler]:
    def configured(conn: Connection, event: Event) -> None:
        p = FeedConfigured.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        conn.execute(delete(t.configs))
        conn.execute(
            t.configs.insert().values(
                config_id=p.config_id,
                config=canonical_json(p.model_dump(mode="json")).decode(),
                event_id=event.id,
            )
        )

    def fetched(conn: Connection, event: Event) -> None:
        if blobs is None:
            raise RuntimeError("the feed projection needs the project's blob store")
        if event.actor.kind not in ("system", "agent"):
            return
        p = FeedFetched.model_validate(event.payload)
        entries = _parsed_entries(blobs, p.entries_blob)
        inserted = conn.execute(
            sqlite_insert(t.fetches)
            .values(
                fetch_id=p.fetch_id,
                window_from=p.window_from.isoformat(),
                window_to=p.window_to.isoformat(),
                complete=int(p.complete),
                count=p.count,
                held_count=p.held_count,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["fetch_id"])
        )
        if not inserted.rowcount:
            return
        for entry_id, version, title, held in entries:
            conn.execute(
                sqlite_insert(t.entries)
                .values(
                    entry_id=entry_id,
                    version=version,
                    title=title,
                    first_fetch_id=p.fetch_id,
                    held_work_id=held,
                )
                .on_conflict_do_nothing(index_elements=["entry_id"])
            )

    def ranked(conn: Connection, event: Event) -> None:
        p = FeedRanked.model_validate(event.payload)
        if event.actor.kind not in ("system", "agent"):
            return
        shown: list[JsonValue] = [s.model_dump(mode="json") for s in p.shown]
        conn.execute(
            sqlite_insert(t.rankings)
            .values(
                ranking_id=p.ranking_id,
                reference_hash=p.reference_hash,
                shown=canonical_json(shown).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["ranking_id"])
        )

    def reacted(conn: Connection, event: Event) -> None:
        p = FeedReacted.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        entry = conn.execute(
            text("SELECT 1 FROM feed_entries WHERE entry_id = :e"), {"e": p.entry_id}
        ).first()
        ranking = conn.execute(
            text("SELECT 1 FROM feed_rankings WHERE ranking_id = :r"), {"r": p.ranking_id}
        ).first()
        if entry is None or ranking is None:
            return
        conn.execute(
            sqlite_insert(t.reactions)
            .values(
                event_id=event.id,
                entry_id=p.entry_id,
                reaction=p.reaction.value,
                ranking_id=p.ranking_id,
                rank_shown=p.rank_shown,
                score_shown=p.score_shown,
                actor=event.actor.id,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    def sent(conn: Connection, event: Event) -> None:
        p = FeedSent.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        entry = conn.execute(
            text("SELECT 1 FROM feed_entries WHERE entry_id = :e"), {"e": p.entry_id}
        ).first()
        item = conn.execute(
            text("SELECT 1 FROM inbox_items WHERE item_id = :i"), {"i": p.inbox_item_id}
        ).first()
        if entry is None or item is None:
            return
        conn.execute(
            sqlite_insert(t.sends)
            .values(
                entry_id=p.entry_id,
                ranking_id=p.ranking_id,
                inbox_item_id=p.inbox_item_id,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["entry_id"])
        )

    return {
        "feed.configured": _total(configured),
        "feed.fetched": _total(fetched),
        "feed.ranked": _total(ranked),
        "feed.reacted": _total(reacted),
        "feed.sent": _total(sent),
    }
