"""Reactions and send (slice 4c, F5): human-only, shown-only, one batch through the inbox.

The feed world is recorded directly (a fetch with three entries, one of them held, and one
ranking), as the index tests do; no source, embedder or network is involved."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.feed import FeedReaction
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.feed import react, send
from factory.services.inbox import LinkInput, add_links
from tests.test_feed_index import FETCH, RANKING, _record
from tests.test_inbox_service import ARXIV_URL

ENTRY = "2611.01234"
OTHER = "2611.01235"
HELD = "2611.01236"
UNSHOWN = "2611.01237"
HELD_WORK = "rf:held-00000001"
LATER_RANKING = "fdr_01HZX3K4M5N6P7Q8R9S0TVWXY0"


def _events(project: Project) -> list[Event]:
    return list(read_all(project.paths.events_dir, project.catalog))


def _types(project: Project, type_: str) -> list[Event]:
    return [e for e in _events(project) if e.type == type_]


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def _ranking(project: Project, ranking_id: str, shown: list[dict[str, Any]]) -> None:
    payload = {
        "ranking_id": ranking_id,
        "fetch_ids": [FETCH],
        "reference_hash": "a" * 64,
        "reference_count": 3,
        "model": "m",
        "weights_hash": "b" * 64,
        "software": "s",
        "parameters": {"shown_per_cycle": 3, "exploration_share": 0.0, "references": "core"},
        "exploration_seed": 1,
        "order_blob": project.blobs.put_json([]),
        "shown": shown,
    }
    _record(project, "feed.ranked", payload, project.system_actor())


def _shown(entry: str, rank: int, score: float) -> dict[str, Any]:
    return {"entry_id": entry, "rank": rank, "score": score, "explore": False}


@pytest.fixture
def world(project: Project) -> Project:
    entries = [
        {"id": ENTRY, "version": "v1", "title": "A paper"},
        {"id": OTHER, "version": "v1", "title": "Another paper"},
        {"id": HELD, "version": "v1", "title": "Held paper", "held_work_id": HELD_WORK},
        {"id": UNSHOWN, "version": "v1", "title": "Never shown"},
    ]
    payload = {
        "fetch_id": FETCH,
        "categories": ["cs.AI"],
        "window_from": "2026-11-10",
        "window_to": "2026-11-11",
        "raw_blobs": [],
        "entries_blob": project.blobs.put_json(entries),  # type: ignore[arg-type]
        "count": 4,
        "held_count": 1,
        "complete": True,
    }
    _record(project, "feed.fetched", payload, project.system_actor())
    _ranking(project, RANKING, [_shown(ENTRY, 1, 0.9), _shown(OTHER, 2, 0.5)])
    return project


def _count(project: Project) -> int:
    return len(_events(project))


def _refused(caught: pytest.ExceptionInfo[FactoryValidationError]) -> tuple[str, str]:
    issue = caught.value.issues[0]
    return issue.field, issue.reason


def test_agent_react_and_send_are_refused_and_write_nothing(world: Project, agent: Actor) -> None:
    before = _count(world)
    with pytest.raises(FactoryValidationError) as caught:
        react(world, agent, ENTRY, FeedReaction.LIKE)
    assert _refused(caught) == ("actor", "human-only")
    with pytest.raises(FactoryValidationError) as caught:
        send(world, agent, ENTRY)
    assert _refused(caught) == ("actor", "human-only")
    assert _count(world) == before


def test_react_records_rank_and_score_shown_and_the_latest_counts(
    world: Project, human: Actor
) -> None:
    react(world, human, ENTRY, FeedReaction.LIKE)
    react(world, human, ENTRY, FeedReaction.DISLIKE)
    events = _types(world, "feed.reacted")
    assert [e.payload["reaction"] for e in events] == ["like", "dislike"]
    assert events[0].payload["rank_shown"] == 1 and events[0].payload["score_shown"] == 0.9
    assert events[0].payload["ranking_id"] == RANKING
    rows = _rows(world, "SELECT reaction FROM feed_reactions ORDER BY event_id")
    assert [r[0] for r in rows] == ["like", "dislike"]


def test_default_ranking_is_the_latest_that_showed_the_entry(world: Project, human: Actor) -> None:
    _ranking(world, LATER_RANKING, [_shown(ENTRY, 4, 0.2)])
    react(world, human, ENTRY, FeedReaction.SAVE)
    react(world, human, OTHER, FeedReaction.SAVE)
    first, second = [e.payload for e in _types(world, "feed.reacted")]
    assert (first["ranking_id"], first["rank_shown"]) == (LATER_RANKING, 4)
    assert (second["ranking_id"], second["rank_shown"]) == (RANKING, 2)
    react(world, human, ENTRY, FeedReaction.SAVE, ranking_id=RANKING)
    assert _types(world, "feed.reacted")[-1].payload["rank_shown"] == 1


@pytest.mark.parametrize(
    ("entry", "ranking", "reason"),
    [
        ("2699.99999", None, "unknown"),
        (UNSHOWN, None, "not-shown"),
        (OTHER, LATER_RANKING, "not-shown"),
    ],
)
def test_react_refuses_unknown_and_not_shown(
    world: Project, human: Actor, entry: str, ranking: str | None, reason: str
) -> None:
    _ranking(world, LATER_RANKING, [_shown(ENTRY, 4, 0.2)])
    before = _count(world)
    with pytest.raises(FactoryValidationError) as caught:
        react(world, human, entry, FeedReaction.LIKE, ranking_id=ranking)
    assert _refused(caught) == ("entry_id", reason)
    assert _count(world) == before


def test_send_refuses_unknown_not_shown_and_held(world: Project, human: Actor) -> None:
    # A held entry is refused even when a ranking lists it (a forged or stale listing).
    _ranking(world, LATER_RANKING, [_shown(HELD, 1, 0.1)])
    before = _count(world)
    for entry, reason in (("2699.99999", "unknown"), (UNSHOWN, "not-shown"), (HELD, "held")):
        with pytest.raises(FactoryValidationError) as caught:
            send(world, human, entry)
        assert _refused(caught) == ("entry_id", reason)
    assert _count(world) == before


def test_send_writes_one_inbox_item_and_one_feed_sent_in_the_same_batch(
    world: Project, human: Actor
) -> None:
    item_id = send(world, human, ENTRY, note="for the review")
    [added] = _types(world, "inbox.link_added")
    [sent] = _types(world, "feed.sent")
    assert added.payload["item_id"] == item_id
    assert added.payload["link"] == f"https://arxiv.org/abs/{ENTRY}"
    assert added.payload["channel"] == Channel.CLI.value
    assert added.payload["note"] == "for the review"
    assert sent.payload["inbox_item_id"] == item_id and sent.payload["entry_id"] == ENTRY
    assert sent.payload["ranking_id"] == RANKING
    assert item_id in sent.refs
    events = _events(world)
    assert events.index(added) + 1 == events.index(sent)
    assert _rows(world, "SELECT entry_id, inbox_item_id FROM feed_sends") == [(ENTRY, item_id)]


def test_second_send_is_refused_and_writes_nothing(world: Project, human: Actor) -> None:
    send(world, human, ENTRY)
    before = _count(world)
    with pytest.raises(FactoryValidationError) as caught:
        send(world, human, ENTRY)
    assert _refused(caught) == ("entry_id", "already-sent")
    assert _count(world) == before


def test_add_links_is_unchanged_for_an_ordinary_link(project: Project, human: Actor) -> None:
    result = add_links(
        project, human, [LinkInput(ARXIV_URL, note="n"), LinkInput("nope")], Channel.CLI
    )
    assert len(result.written) == 1
    assert [e.index for e in result.rejected] == [1]
    [added] = _types(project, "inbox.link_added")
    assert added.payload["item_id"] == result.written[0]
    assert added.payload["note"] == "n" and added.payload["channel"] == "cli"
    assert added.refs == (result.written[0],)
    assert _types(project, "feed.sent") == []


def test_forged_agent_feed_sent_folds_to_nothing(
    world: Project, human: Actor, agent: Actor
) -> None:
    [item] = add_links(world, human, [LinkInput(ARXIV_URL)], Channel.CLI).written
    forged = {"entry_id": ENTRY, "ranking_id": RANKING, "inbox_item_id": item}
    _record(world, "feed.sent", forged, agent)
    assert _rows(world, "SELECT * FROM feed_sends") == []


def test_feed_sent_for_an_unknown_entry_folds_to_nothing(world: Project, human: Actor) -> None:
    [item] = add_links(world, human, [LinkInput(ARXIV_URL)], Channel.CLI).written
    forged = {"entry_id": "2699.99999", "ranking_id": RANKING, "inbox_item_id": item}
    _record(world, "feed.sent", forged, human)
    assert _rows(world, "SELECT * FROM feed_sends") == []
