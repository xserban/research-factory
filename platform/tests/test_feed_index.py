"""Projection of feed events (slice 4c, F2): human-only and inbox-item guards.

Events are recorded directly, as the other index tests do.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.index.default import PROJECTION_VERSION
from factory.services.context import Project
from tests.test_inbox_model import ITEM, added

ULID = "01HZX3K4M5N6P7Q8R9S0TVWXYZ"
CONFIG = f"fdc_{ULID}"
FETCH = f"fdf_{ULID}"
RANKING = f"fdr_{ULID}"
ENTRY = "2611.01234"
OTHER = "2611.01235"
ITEM_UNKNOWN = "inb_01HZX3K4M5N6P7Q8R9S0TVWXZ9"


def _record(project: Project, type_: str, payload: Any, actor: Actor | None = None) -> Event:
    model = project.catalog.get(type_).payload.model_validate(payload)
    actor = actor or project.human_actor()
    blob = project.blobs.put_json(payload) if actor.kind == "agent" else None
    event = project.events.make(type_, model, actor, input_blob=blob)
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def _config() -> dict[str, Any]:
    return {"config_id": CONFIG, "categories": ["cs.AI"]}


def _fetch(project: Project) -> Event:
    entries = [
        {"id": ENTRY, "version": "v1", "title": "A paper"},
        {"id": OTHER, "version": "v2", "title": "Another paper", "held_work_id": None},
    ]
    payload = {
        "fetch_id": FETCH,
        "categories": ["cs.AI"],
        "window_from": "2026-11-10",
        "window_to": "2026-11-11",
        "raw_blobs": [],
        "entries_blob": project.blobs.put_json(entries),  # type: ignore[arg-type]
        "count": 2,
        "held_count": 0,
        "complete": True,
    }
    return _record(project, "feed.fetched", payload, project.system_actor())


def _ranked(project: Project) -> Event:
    payload = {
        "ranking_id": RANKING,
        "fetch_ids": [FETCH],
        "reference_hash": "a" * 64,
        "reference_count": 3,
        "model": "m",
        "weights_hash": "b" * 64,
        "software": "s",
        "parameters": {"shown_per_cycle": 2, "exploration_share": 0.0, "references": "core"},
        "exploration_seed": 1,
        "order_blob": project.blobs.put_json([]),
        "shown": [{"entry_id": ENTRY, "rank": 1, "score": 0.5, "explore": False}],
    }
    return _record(project, "feed.ranked", payload, project.system_actor())


def _reaction(entry: str = ENTRY, ranking: str = RANKING) -> dict[str, Any]:
    return {
        "entry_id": entry,
        "reaction": "like",
        "ranking_id": ranking,
        "rank_shown": 1,
        "score_shown": 0.5,
    }


def _sent(entry: str = ENTRY, item: str = ITEM) -> dict[str, Any]:
    return {"entry_id": entry, "ranking_id": RANKING, "inbox_item_id": item}


def _world(project: Project) -> None:
    _record(project, "feed.configured", _config())
    _fetch(project)
    _ranked(project)
    _record(project, "inbox.link_added", added())


def _count(project: Project, table: str) -> int:
    [(n,)] = _rows(project, f"SELECT COUNT(*) FROM {table}")
    return int(n)


def test_projection_version_bumped() -> None:
    assert int(PROJECTION_VERSION) >= 78


def test_human_events_fold(project: Project) -> None:
    _world(project)
    _record(project, "feed.reacted", _reaction())
    _record(project, "feed.sent", _sent())
    assert _count(project, "feed_configs") == 1
    assert _rows(project, "SELECT entry_id, version, first_fetch_id FROM feed_entries") == [
        (ENTRY, "v1", FETCH),
        (OTHER, "v2", FETCH),
    ]
    assert _count(project, "feed_reactions") == 1
    assert _rows(project, "SELECT entry_id, inbox_item_id FROM feed_sends") == [(ENTRY, ITEM)]


def test_agent_written_events_fold_to_nothing(project: Project, agent: Actor) -> None:
    _world(project)
    _record(project, "feed.configured", {**_config(), "config_id": f"fdc_{ULID[:-1]}A"}, agent)
    _record(project, "feed.reacted", _reaction(), agent)
    _record(project, "feed.sent", _sent(), agent)
    assert _rows(project, "SELECT config_id FROM feed_configs") == [(CONFIG,)]
    assert _count(project, "feed_reactions") == 0
    assert _count(project, "feed_sends") == 0


def test_send_of_unknown_inbox_item_folds_to_nothing(project: Project) -> None:
    _world(project)
    _record(project, "feed.sent", _sent(item=ITEM_UNKNOWN))
    assert _count(project, "feed_sends") == 0


def test_second_send_of_the_same_entry_is_ignored(project: Project) -> None:
    _world(project)
    first = _record(project, "feed.sent", _sent())
    _record(project, "inbox.link_added", added(item_id=ITEM_UNKNOWN))
    _record(project, "feed.sent", _sent(item=ITEM_UNKNOWN))
    assert _rows(project, "SELECT inbox_item_id, event_id FROM feed_sends") == [(ITEM, first.id)]


def test_reaction_to_unknown_entry_or_ranking_folds_to_nothing(project: Project) -> None:
    _world(project)
    _record(project, "feed.reacted", _reaction(entry="2611.99999"))
    _record(project, "feed.reacted", _reaction(ranking=f"fdr_{ULID[:-1]}A"))
    assert _count(project, "feed_reactions") == 0


def test_rebuild_equals_incremental_fold(project: Project) -> None:
    _world(project)
    _record(project, "feed.reacted", _reaction())
    _record(project, "feed.sent", _sent())
    project.index.sync()
    before = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == before
