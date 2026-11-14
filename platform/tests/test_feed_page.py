"""The ranked page of the feed: the entries after the shown ones, in ranked order, from the
`feed.ranked` order blob. Held entries never listed; the cap says how many were cut."""

from __future__ import annotations

from typing import Any

from factory.model.feed import FeedReaction  # noqa: F401  (import check only)
from factory.services.context import Project
from factory.services.feed_page import FeedRankedPage, feed_ranked_page
from tests.test_feed_index import CONFIG, _record
from tests.test_feed_read import FETCH, RANKING

REFERENCE = "rf:paper-0000aaaa"


def _eid(n: int) -> str:
    return f"2611.{n:05d}"


def world(project: Project, total: int = 40, shown: int = 5, held: tuple[int, ...] = ()) -> None:
    """`total` entries ranked 1..total (the held ones fetched but not ranked); the first `shown`
    are shown, plus entry `total` as an exploration pick."""
    _record(project, "feed.configured", {"config_id": CONFIG, "categories": ["cs.AI"]})
    entries: list[dict[str, Any]] = [
        {
            "id": _eid(n),
            "version": "v1",
            "title": f"Paper {n}",
            "abstract": f"Abstract {n} <b>x</b>",
            "authors": [f"Author {n}"],
        }
        for n in range(1, total + 1)
    ]
    for n in held:
        entries.append(
            {"id": _eid(900 + n), "version": "v1", "title": "Held", "held_work_id": REFERENCE}
        )
    payload = {
        "fetch_id": FETCH,
        "categories": ["cs.AI"],
        "window_from": "2026-11-10",
        "window_to": "2026-11-11",
        "raw_blobs": [],
        "entries_blob": project.blobs.put_json(entries),  # type: ignore[arg-type]
        "count": len(entries),
        "held_count": len(held),
        "complete": True,
    }
    _record(project, "feed.fetched", payload, project.system_actor())
    order = [
        {"entry_id": _eid(n), "rank": n, "score": round(1 - n / 100, 3)}
        for n in range(1, total + 1)
    ]
    # a held entry listed in the order blob must still never be shown
    for n in held:
        order.append({"entry_id": _eid(900 + n), "rank": total + n, "score": 0.0})
    shown_ids = [*range(1, shown + 1), total]
    ranked = {
        "ranking_id": RANKING,
        "fetch_ids": [FETCH],
        "reference_hash": "a" * 64,
        "reference_count": 1,
        "model": "m",
        "weights_hash": "b" * 64,
        "software": "s",
        "parameters": {"shown_per_cycle": 6, "exploration_share": 0.1, "references": "core"},
        "exploration_seed": 1,
        "order_blob": project.blobs.put_json(order),  # type: ignore[arg-type]
        "shown": [
            {"entry_id": _eid(n), "rank": n, "score": round(1 - n / 100, 3), "explore": n == total}
            for n in shown_ids
        ],
    }
    _record(project, "feed.ranked", ranked, project.system_actor())


def test_totals_and_further_entries_in_ranked_order(project: Project) -> None:
    world(project)
    page = feed_ranked_page(project)
    assert page.ranking_id == RANKING
    assert (page.total_ranked, page.total_shown) == (40, 6)
    ranks = [f.rank for f in page.further]
    assert ranks == list(range(6, 40))  # 6..39: the explore pick at 40 is shown, not further
    first = page.further[0]
    assert (first.entry_id, first.title, first.authors) == (_eid(6), "Paper 6", ("Author 6",))
    assert first.abstract == "Abstract 6 <b>x</b>"
    assert first.score == 0.94
    assert page.cut == 0


def test_held_entries_are_never_listed_or_counted(project: Project) -> None:
    world(project, held=(1, 2))
    page = feed_ranked_page(project)
    assert page.total_ranked == 40
    assert all(f.entry_id not in (_eid(901), _eid(902)) for f in page.further)


def test_cap_cuts_and_reports_the_rest(project: Project) -> None:
    world(project)
    page = feed_ranked_page(project, cap=10)
    assert len(page.further) == 10 and page.further[-1].rank == 15
    assert page.cut == 34 - 10
    assert page.cap == 10


def test_no_ranking_gives_an_empty_page(project: Project) -> None:
    page: FeedRankedPage = feed_ranked_page(project)
    assert page.ranking_id is None and page.total_ranked == 0 and page.further == ()


def test_an_empty_order_blob_falls_back_to_the_shown_items(project: Project) -> None:
    from tests.test_feed_read import _fetch, _ranked

    _fetch(project)
    _ranked(project)  # its order blob is empty; two entries shown, one held
    page = feed_ranked_page(project)
    assert page.total_shown == 2 and page.total_ranked == 2 and page.further == ()
