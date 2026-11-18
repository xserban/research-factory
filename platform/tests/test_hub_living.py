"""Hub living analytics (plan hub-ui, step 8): feed river, horizon, heartbeat."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from factory.events.catalog import default_catalog
from factory.events.reader import read_all
from factory.index.lab import lab_catalog
from factory.model.views import HorizonView, ViewMeta, ViewNotice
from factory.services import hub_living as hl
from factory.services.context import Project
from tests.test_feed_index import (
    ENTRY,
    FETCH,
    OTHER,
    _fetch,
    _reaction,
    _record,
    _sent,
    _world,
)

SECOND_FETCH = "fdf_01HZX3K4M5N6P7Q8R9S0TVWXZ0"
THIRD = "2611.01299"


def row(entry: str, day: str, rank: int | None = None, **kw: Any) -> hl.FeedRow:
    return hl.FeedRow(
        entry_id=entry,
        title=f"t-{entry}",
        day=day,
        rank=rank,
        score=None if rank is None else 1.0 / rank,
        reaction=kw.get("reaction"),
        sent=kw.get("sent", False),
    )


def test_feed_river_counts_and_top_k_per_day() -> None:
    rows = [
        row("e3", "2026-11-11", 3, reaction="like"),
        row("e1", "2026-11-11", 1, reaction="dislike", sent=True),
        row("e2", "2026-11-11", 2, reaction="like"),
        row("e9", "2026-11-11"),
        row("e5", "2026-11-10"),
    ]
    river = hl.feed_river(rows, top_k=2)
    assert river.total == 5
    assert [d.day for d in river.days] == ["2026-11-10", "2026-11-11"]
    day = river.days[1]
    assert (day.count, day.shown, day.sent) == (4, 3, 1)
    assert day.reactions == {"dislike": 1, "like": 2}
    assert [r.entry_id for r in day.top] == ["e1", "e2"]
    assert [r.entry_id for r in river.days[0].top] == ["e5"]  # unranked entries still listed


def test_feed_river_unranked_follow_by_entry_id_and_empty() -> None:
    river = hl.feed_river([row("b", "d"), row("a", "d"), row("z", "d", 7)], top_k=5)
    assert [r.entry_id for r in river.days[0].top] == ["z", "a", "b"]
    assert hl.feed_river([]) == hl.FeedRiver(total=0, days=())
    assert hl.feed_river([row("a", "d")], top_k=0).days[0].top == ()


def test_loader_reads_the_projection(project: Project) -> None:
    _world(project)
    _record(project, "feed.reacted", _reaction())
    _record(project, "feed.sent", _sent())
    rows = {r.entry_id: r for r in hl.load_feed_rows(project)}
    assert set(rows) == {ENTRY, OTHER}
    assert (rows[ENTRY].rank, rows[ENTRY].score) == (1, 0.5)
    assert rows[ENTRY].reaction == "like" and rows[ENTRY].sent
    assert rows[ENTRY].day == "2026-11-11"
    assert rows[OTHER].rank is None and rows[OTHER].reaction is None and not rows[OTHER].sent


def test_loader_two_days_and_no_ranking(project: Project) -> None:
    _record(
        project,
        "feed.configured",
        {"config_id": "fdc_01HZX3K4M5N6P7Q8R9S0TVWXYZ", "categories": ["cs.AI"]},
    )
    _fetch(project)
    second = [{"id": THIRD, "version": "v1", "title": "Third"}]
    _record(
        project,
        "feed.fetched",
        {
            "fetch_id": SECOND_FETCH,
            "categories": ["cs.AI"],
            "window_from": "2026-11-11",
            "window_to": "2026-11-12",
            "raw_blobs": [],
            "entries_blob": project.blobs.put_json(second),  # type: ignore[arg-type]
            "count": 1,
            "held_count": 0,
            "complete": True,
        },
        project.system_actor(),
    )
    payload = hl.living_payload(project)
    days = payload["feed_river"]["days"]
    assert [(d["day"], d["count"]) for d in days] == [("2026-11-11", 2), ("2026-11-12", 1)]
    assert all(r["rank"] is None for d in days for r in d["top"])
    assert FETCH != SECOND_FETCH


def test_horizon_summary() -> None:
    view = HorizonView(
        meta=ViewMeta(
            view="horizon",
            version=1,
            project="p",
            as_of=None,
            filter={},
            notices=[ViewNotice(code="c", text="note")],
        ),
        years=[2023, 2025],
        idea_members={},
        new_ideas={2023: ["i1", "i2"], 2025: ["i3"]},
        new_edges={2024: 4},
        group_records={},
        undated={"new_ideas": 1},
        horizon={"openalex": "2026-11-01", "arxiv": "bad"},
        total_ideas=3,
        total_groups=0,
        listed_groups=0,
    )
    h = hl.horizon_summary(view, date(2026, 11, 11))
    assert [(s.source, s.days_ago) for s in h.sources] == [("arxiv", None), ("openalex", 10)]
    assert (h.first_year, h.latest_year) == (2023, 2025)
    assert h.ideas_per_year == {2023: 2, 2025: 1}
    assert h.edges_per_year == {2024: 4} and h.notices == ("note",)
    empty = hl.horizon_summary(view.model_copy(update={"years": [], "horizon": {}}), date.today())
    assert empty.first_year is None and empty.sources == ()


def test_heartbeat_by_family() -> None:
    counts = [
        ("2026-11-02", "search.run_finished", 2),
        ("2026-11-01", "screening.decision_recorded", 3),
        ("2026-11-01", "search.run_finished", 1),
        ("2026-11-01", "no.such_type", 1),
        ("2026-11-01", "feed.fetched", 1),
        ("2026-11-01", "feed.fetched", 1),
    ]
    beat = hl.heartbeat(counts)
    assert (beat.total, beat.first_day, beat.last_day) == (9, "2026-11-01", "2026-11-02")
    first = beat.days[0]
    assert first.total == 7
    assert first.families == {"search": 1, "screening": 3, "feed": 2, "other": 1}
    assert first.types["feed.fetched"] == 2
    assert beat.family_totals == {"search": 3, "screening": 3, "feed": 2, "other": 1}
    assert hl.heartbeat([]).days == () and hl.heartbeat([]).first_day is None


def test_every_catalog_prefix_is_assigned() -> None:
    names = default_catalog().names() + lab_catalog().names()
    prefixes = {n.split(".", 1)[0] for n in names}
    assert prefixes <= set(hl.family_table()), sorted(prefixes - set(hl.family_table()))
    assert set(hl.family_table().values()) <= set(hl.FAMILIES)
    assert all(hl.family_of(n) in hl.FAMILIES for n in names)
    assert hl.family_of("search.run_started") == "search"
    assert hl.family_of("zzz.unknown") == "other"
    assert hl.family_of("nodot") == "other"
    # a recorded synthesis page is neither a search nor an acquisition event
    assert hl.family_of("page.recorded") == "other"


def test_heartbeat_loader_matches_the_log(project: Project) -> None:
    _world(project)
    _record(project, "feed.reacted", _reaction())
    counts = hl.load_event_counts(project)
    assert sum(n for _, _, n in counts) == len(read_all(project.paths.events_dir, project.catalog))
    kinds = {t for _, t, _ in counts}
    assert {"feed.fetched", "feed.ranked", "feed.reacted"} <= kinds
    beat = hl.heartbeat(counts)
    assert beat.family_totals["feed"] == 4


def test_living_payload_is_json_safe(project: Project) -> None:
    import json

    _world(project)
    payload = hl.living_payload(project, top_k=1)
    json.dumps(payload)
    assert set(payload) == {"methods", "families", "feed_river", "horizon", "heartbeat"}
    assert payload["feed_river"]["total"] == 2
    assert set(payload["methods"]) == {"feed_river", "horizon", "heartbeat"}


@pytest.mark.parametrize("kind", sorted(hl.METHODS))
def test_methods_are_plain_sentences(kind: str) -> None:
    assert hl.METHODS[kind].endswith(".")
