"""Projection of screening rankings (slice 8, IDEA-42): the history and the latest order.

`rankings` keeps one row per `ranking.computed` event. `ranking_positions` holds only the latest
ranking's order, replaced as a whole by each later event: the rank position (from 1) and score of
each work. Both are empty for a log without ranking events, so they are left out of the state hash
then.

Handlers are total. An event that does not come from the system actor, whose order blob cannot be
read, is not a list of distinct works matching `count` and `corpus_hash`, or repeats a known
ranking id, changes nothing: a logged event can never be removed, so the fold must not raise.
"""

from __future__ import annotations

import hashlib
import zlib
from typing import NamedTuple

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.ranking import RankingComputed

_CHUNK = 5000


class RankingTables(NamedTuple):
    rankings: Table
    positions: Table


def corpus_hash(work_ids: list[str]) -> str:
    """The sha256 of the sorted work ids joined by newlines (the ranked set's identity)."""
    return hashlib.sha256("\n".join(sorted(work_ids)).encode()).hexdigest()


def ranking_tables(metadata: MetaData) -> RankingTables:
    rankings = Table(
        "rankings",
        metadata,
        Column("ranking_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("ts", String, nullable=False),
        Column("model_id", String, nullable=False),
        Column("weights_hash", String, nullable=False),
        Column("software", String, nullable=False),
        Column("parameters", String, nullable=False),
        Column("corpus_hash", String, nullable=False),
        Column("count", Integer, nullable=False),
        Column("order_blob", String, nullable=False),
    )
    positions = Table(
        "ranking_positions",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("position", Integer, nullable=False),
        Column("score", Float, nullable=False),
        Column("ranking_id", String, nullable=False),
    )
    return RankingTables(rankings, positions)


def _order(blobs: BlobStore, p: RankingComputed) -> list[tuple[str, float]] | None:
    """The `(work_id, score)` list of the order blob, or None when it is unreadable or does not
    match the event's count and corpus hash."""
    try:
        value = blobs.get_json(p.order)
    except (FactoryError, OSError, EOFError, ValueError, zlib.error):
        return None
    if not isinstance(value, list):
        return None
    out: list[tuple[str, float]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        work, score = item.get("work_id"), item.get("score")
        if not isinstance(work, str) or isinstance(score, bool):
            return None
        if not isinstance(score, int | float):
            return None
        out.append((work, float(score)))
    ids = [work for work, _ in out]
    if len(set(ids)) != len(ids) or len(ids) != p.count or corpus_hash(ids) != p.corpus_hash:
        return None
    return out


def ranking_handlers(t: RankingTables, blobs: BlobStore | None) -> dict[str, Handler]:
    def computed(conn: Connection, event: Event) -> None:
        if blobs is None:
            raise RuntimeError("the ranking projection needs the project's blob store")
        if event.actor.kind != "system":
            return
        p = RankingComputed.model_validate(event.payload)
        order = _order(blobs, p)
        if order is None:
            return
        inserted = conn.execute(
            sqlite_insert(t.rankings)
            .values(
                ranking_id=p.ranking_id,
                event_id=event.id,
                ts=format_ts(event.ts),
                model_id=p.model_id,
                weights_hash=p.weights_hash,
                software=p.software,
                parameters=canonical_json(p.parameters.model_dump(mode="json")).decode(),
                corpus_hash=p.corpus_hash,
                count=p.count,
                order_blob=p.order,
            )
            .on_conflict_do_nothing(index_elements=["ranking_id"])
        )
        if not inserted.rowcount:
            return
        conn.execute(delete(t.positions))
        rows = [
            {"work_id": work, "position": i, "score": score, "ranking_id": p.ranking_id}
            for i, (work, score) in enumerate(order, start=1)
        ]
        for start in range(0, len(rows), _CHUNK):
            conn.execute(sqlite_insert(t.positions), rows[start : start + _CHUNK])

    return {"ranking.computed": computed}
