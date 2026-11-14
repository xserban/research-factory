"""React and send on ranked entries outside the shown list: recorded with the real rank and score
of the ranking's order blob and `beyond_shown` true; unranked entries are refused."""

from __future__ import annotations

from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.feed import FeedReacted, FeedSent
from factory.model.feed import FeedReaction as R
from factory.services.context import Project
from factory.services.feed import react, send
from tests.test_feed_actions import (
    ENTRY,
    HELD,
    LATER_RANKING,
    OTHER,
    UNSHOWN,
    _count,
    _events,
    _refused,
    _rows,
    _types,
    world,  # noqa: F401  (fixture)
)
from tests.test_feed_index import FETCH, RANKING, _record

FAR = "2611.01238"


def _ranked(project: Project, ranking_id: str, order: list[tuple[str, int, float]]) -> None:
    payload: dict[str, Any] = {
        "ranking_id": ranking_id,
        "fetch_ids": [FETCH],
        "reference_hash": "a" * 64,
        "reference_count": 3,
        "model": "m",
        "weights_hash": "b" * 64,
        "software": "s",
        "parameters": {"shown_per_cycle": 1, "exploration_share": 0.0, "references": "core"},
        "exploration_seed": 1,
        "order_blob": project.blobs.put_json(
            [{"entry_id": e, "rank": r, "score": s} for e, r, s in order]  # type: ignore[arg-type]
        ),
        "shown": [
            {"entry_id": order[0][0], "rank": order[0][1], "score": order[0][2], "explore": False}
        ],
    }
    _record(project, "feed.ranked", payload, project.system_actor())


@pytest.fixture
def ranked(world: Project) -> Project:  # noqa: F811
    _ranked(world, LATER_RANKING, [(ENTRY, 1, 0.9), (OTHER, 2, 0.5), (UNSHOWN, 3, 0.25)])
    return world


def test_react_on_a_further_entry_records_real_rank_score_and_the_flag(
    ranked: Project, human: Actor
) -> None:
    react(ranked, human, UNSHOWN, R.LIKE)
    [event] = _types(ranked, "feed.reacted")
    p = event.payload
    assert (p["ranking_id"], p["rank_shown"], p["score_shown"]) == (LATER_RANKING, 3, 0.25)
    assert p["beyond_shown"] is True
    rows = _rows(ranked, "SELECT entry_id, reaction, rank_shown FROM feed_reactions")
    assert rows == [(UNSHOWN, "like", 3)]


def test_react_on_a_shown_entry_has_the_flag_false(ranked: Project, human: Actor) -> None:
    react(ranked, human, ENTRY, R.LIKE)
    [event] = _types(ranked, "feed.reacted")
    assert event.payload["beyond_shown"] is False and event.payload["rank_shown"] == 1


def test_a_named_ranking_is_used_for_the_fallback(ranked: Project, human: Actor) -> None:
    _ranked(ranked, "fdr_01HZX3K4M5N6P7Q8R9S0TVWXY1", [(ENTRY, 1, 0.8), (UNSHOWN, 7, 0.1)])
    react(ranked, human, UNSHOWN, R.SAVE, ranking_id=LATER_RANKING)
    assert _types(ranked, "feed.reacted")[-1].payload["rank_shown"] == 3
    react(ranked, human, UNSHOWN, R.SAVE)  # the latest ranking
    assert _types(ranked, "feed.reacted")[-1].payload["rank_shown"] == 7
    assert _types(ranked, "feed.reacted")[-1].payload["beyond_shown"] is True


def test_an_unknown_entry_stays_unknown(ranked: Project, human: Actor) -> None:
    before = _count(ranked)
    for act in (
        lambda: react(ranked, human, "2699.99999", R.LIKE),
        lambda: send(ranked, human, "2699.99999"),
    ):
        with pytest.raises(FactoryValidationError) as caught:
            act()
        assert _refused(caught) == ("entry_id", "unknown")
    assert _count(ranked) == before


def test_unranked_entry_refused_on_both_acts(ranked: Project, human: Actor) -> None:
    before = _count(ranked)
    for act in (
        lambda: react(ranked, human, UNSHOWN, R.LIKE, ranking_id=RANKING),
        lambda: send(ranked, human, UNSHOWN, ranking_id=RANKING),
    ):
        with pytest.raises(FactoryValidationError) as caught:
            act()
        assert _refused(caught) == ("entry_id", "not-ranked")
    assert _count(ranked) == before


def test_human_only_is_still_enforced(ranked: Project, agent: Actor) -> None:
    before = _count(ranked)
    for act in (
        lambda: react(ranked, agent, UNSHOWN, R.LIKE),
        lambda: send(ranked, agent, UNSHOWN),
    ):
        with pytest.raises(FactoryValidationError) as caught:
            act()
        assert _refused(caught) == ("actor", "human-only")
    assert _count(ranked) == before


def test_send_on_a_further_entry_sets_the_flag_and_a_second_send_is_refused(
    ranked: Project, human: Actor
) -> None:
    item = send(ranked, human, UNSHOWN)
    [sent] = _types(ranked, "feed.sent")
    assert sent.payload["beyond_shown"] is True and sent.payload["inbox_item_id"] == item
    assert sent.payload["ranking_id"] == LATER_RANKING
    before = _count(ranked)
    with pytest.raises(FactoryValidationError) as caught:
        send(ranked, human, UNSHOWN)
    assert _refused(caught) == ("entry_id", "already-sent")
    assert _count(ranked) == before


def test_a_held_entry_in_the_order_is_still_refused_on_send(ranked: Project, human: Actor) -> None:
    _ranked(ranked, "fdr_01HZX3K4M5N6P7Q8R9S0TVWXY2", [(ENTRY, 1, 0.8), (HELD, 2, 0.7)])
    before = _count(ranked)
    with pytest.raises(FactoryValidationError) as caught:
        send(ranked, human, HELD)
    assert _refused(caught) == ("entry_id", "held")
    assert _count(ranked) == before
    assert len(_events(ranked)) == before


def test_send_on_a_shown_entry_has_the_flag_false(ranked: Project, human: Actor) -> None:
    send(ranked, human, ENTRY)
    assert _types(ranked, "feed.sent")[0].payload["beyond_shown"] is False


_REACTED: dict[str, Any] = {
    "entry_id": ENTRY,
    "reaction": "like",
    "ranking_id": RANKING,
    "rank_shown": 1,
    "score_shown": 0.5,
}
_SENT: dict[str, Any] = {
    "entry_id": ENTRY,
    "ranking_id": RANKING,
    "inbox_item_id": "inb_01HZX3K4M5N6P7Q8R9S0TVWXY0",
}


def test_old_payloads_validate_without_the_flag_and_new_ones_round_trip() -> None:
    assert FeedReacted.model_validate(_REACTED).beyond_shown is False
    assert FeedSent.model_validate(_SENT).beyond_shown is False
    for model, data in ((FeedReacted, _REACTED), (FeedSent, _SENT)):
        new = model.model_validate({**data, "beyond_shown": True})
        assert new.beyond_shown is True
        assert model.model_validate(new.model_dump(mode="json")) == new
        with pytest.raises(ValueError):
            model.model_validate({**data, "extra": 1})
