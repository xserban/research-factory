"""The factory scope's catalog and projection: `<root>/factory/.index/factory.sqlite`.

Versioned on its own (`FACTORY_PROJECTION_VERSION`), apart from the project index: a project
projection bump never rebuilds it, nor the reverse (decision 169, proposed).

Invariants:
- Every handler is total: a malformed payload, or an event that fails a guard, changes nothing, on
  rebuild too. A hand-written event stays in the log and counts for nothing.
- A reaction counts only from a human actor (R-F3); a ranker training only from a system actor,
  and only as the next version (1, 2, ...); a ranking from a non-human actor.
- The latest reaction of an entry is the one with the greatest event id. Labels are `like` and
  `dislike`; `unset` withdraws the label. The reading list is `save`, withdrawn by `unsave`.
  `dismiss` is neither.
"""

from collections.abc import Mapping
from typing import TypeVar

from pydantic import JsonValue, ValidationError
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, func, insert, select
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.catalog import EventCatalog, EventType, default_catalog
from factory.events.envelope import Event
from factory.index.projection import Handler, Projection, core_tables
from factory.model.base import StrictModel
from factory.model.factory_scope import FACTORY_EVENT_TYPES
from factory.model.feed import FeedRanked, FeedRankerTrained, FeedReacted, FeedReaction

# Bump on any change to the tables or handlers below; the factory index is then rebuilt.
FACTORY_PROJECTION_VERSION = "1"

_M = TypeVar("_M", bound=StrictModel)

LABELS = (FeedReaction.LIKE.value, FeedReaction.DISLIKE.value)


def factory_catalog() -> EventCatalog:
    """The allow-list: exactly the event types of `FACTORY_EVENT_TYPES`, with the project
    catalog's payloads. Any other type is unknown to this catalog and so refused."""
    full = default_catalog()
    catalog = EventCatalog()
    for name in FACTORY_EVENT_TYPES:
        event_type = full.get(name)
        catalog.register(EventType(event_type.name, event_type.payload, event_type.schema))
    return catalog


def factory_tables(metadata: MetaData) -> dict[str, Table]:
    return {
        "reactions": Table(
            "factory_reactions",
            metadata,
            Column("event_id", String, primary_key=True),
            Column("entry_id", String, nullable=False),
            Column("reaction", String, nullable=False),
            Column("ranking_id", String, nullable=False),
            Column("rank_shown", Integer, nullable=False),
            Column("score_shown", Float, nullable=False),
            Column("actor", String, nullable=False),
            Column("ts", String, nullable=False),
        ),
        "rankings": Table(
            "factory_rankings",
            metadata,
            Column("ranking_id", String, primary_key=True),
            Column("event_id", String, nullable=False),
            Column("reference_hash", String, nullable=False),
            Column("order_blob", String, nullable=False),
            Column("shown", String, nullable=False),
            Column("ts", String, nullable=False),
        ),
        "trainings": Table(
            "factory_ranker_trainings",
            metadata,
            Column("ranker_version", Integer, primary_key=True),
            Column("event_id", String, nullable=False),
            Column("training_set_hash", String, nullable=False),
            Column("ids", String, nullable=False),
            Column("likes", Integer, nullable=False),
            Column("dislikes", Integer, nullable=False),
            Column("features", String, nullable=False),
            Column("library_versions", String, nullable=False),
            Column("state_blob", String, nullable=False),
            Column("triggered_by", String, nullable=False),
            Column("ts", String, nullable=False),
        ),
    }


def _parsed(model: type[_M], event: Event) -> _M | None:
    try:
        return model.model_validate(event.payload)
    except ValidationError:
        return None


def _reacted(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(FeedReacted, event)
        if payload is None or event.actor.kind != "human":
            return
        conn.execute(
            insert(tables["reactions"]).values(
                event_id=event.id,
                entry_id=payload.entry_id,
                reaction=payload.reaction.value,
                ranking_id=payload.ranking_id,
                rank_shown=payload.rank_shown,
                score_shown=payload.score_shown,
                actor=event.actor.id,
                ts=format_ts(event.ts),
            )
        )

    return fold


def _ranked(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(FeedRanked, event)
        if payload is None or event.actor.kind == "human":
            return
        table = tables["rankings"]
        if conn.execute(
            select(table.c.ranking_id).where(table.c.ranking_id == payload.ranking_id)
        ).first():
            return
        shown: list[JsonValue] = [s.model_dump(mode="json") for s in payload.shown]
        conn.execute(
            insert(table).values(
                ranking_id=payload.ranking_id,
                event_id=event.id,
                reference_hash=payload.reference_hash,
                order_blob=payload.order_blob,
                shown=canonical_json(shown).decode(),
                ts=format_ts(event.ts),
            )
        )

    return fold


def latest_version(conn: Connection, tables: Mapping[str, Table]) -> int:
    """The newest ranker version folded, 0 before the first training."""
    table = tables["trainings"]
    return int(
        conn.execute(select(func.coalesce(func.max(table.c.ranker_version), 0))).scalar_one()
    )


def _trained(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(FeedRankerTrained, event)
        if payload is None or event.actor.kind != "system":
            return
        if payload.ranker_version != latest_version(conn, tables) + 1:
            return
        conn.execute(
            insert(tables["trainings"]).values(
                ranker_version=payload.ranker_version,
                event_id=event.id,
                training_set_hash=payload.training_set_hash,
                ids=canonical_json(list(payload.ids)).decode(),
                likes=payload.likes,
                dislikes=payload.dislikes,
                features=canonical_json(list(payload.features)).decode(),
                library_versions=canonical_json(
                    dict[str, JsonValue](payload.library_versions)
                ).decode(),
                state_blob=payload.state_blob,
                triggered_by=payload.triggered_by,
                ts=format_ts(event.ts),
            )
        )

    return fold


def latest_reactions(
    conn: Connection, tables: Mapping[str, Table]
) -> dict[str, dict[str, str | None]]:
    """Per arXiv id: `label` (`like`, `dislike` or None once unset) and `saved` ('save' or None).

    Each follows the latest reaction of its own kind by event id; `dismiss` moves neither."""
    table = tables["reactions"]
    out: dict[str, dict[str, str | None]] = {}
    rows = conn.execute(select(table.c.entry_id, table.c.reaction).order_by(table.c.event_id))
    for entry_id, reaction in rows:
        state = out.setdefault(str(entry_id), {"label": None, "saved": None})
        if reaction in LABELS:
            state["label"] = str(reaction)
        elif reaction == FeedReaction.UNSET.value:
            state["label"] = None
        elif reaction == FeedReaction.SAVE.value:
            state["saved"] = "save"
        elif reaction == FeedReaction.UNSAVE.value:
            state["saved"] = None
    return out


def factory_projection() -> tuple[Projection, dict[str, Table]]:
    """The factory projection and its tables by name, which the services read through."""
    metadata = MetaData()
    core_tables(metadata)
    tables = factory_tables(metadata)
    handlers: dict[str, Handler] = {
        "feed.reacted": _reacted(tables),
        "feed.ranked": _ranked(tables),
        "feed.ranker_trained": _trained(tables),
    }
    projection = Projection(
        version=FACTORY_PROJECTION_VERSION, metadata=metadata, handlers=handlers
    )
    return projection, tables
