"""The factory feed: pool, project scores, general order, the factory `feed.ranked`, the reads.

Projects hold hand-written `feed.fetched` events; the reference sets are patched in and a fake
embedder with chosen vectors stands in for SPECTER2 (no network, no weights)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Event
from factory.index import factory_scope as fx
from factory.model.feed import FeedFetched, FeedRanked, FeedRankerTrained, FeedReacted, FeedReaction
from factory.model.work import Identifiers, Provenance, Work
from factory.services import factory_feed as ff
from factory.services import feed_ranker
from factory.services.context import Project
from factory.services.factory_scope import FactoryScope, open_factory_scope
from factory.services.project import init_project
from tests.helpers import SESSION, T0

RANKING = "fdr_" + "0" * 26
VECTORS: dict[str, list[float]] = {}


class FakeEmbedder:
    model_id = "fake/model"
    weights_hash = "a" * 64
    software = "fake==1"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [VECTORS[t.split(" [SEP]")[0]] for t in texts]


def _vec(*lead: float) -> list[float]:
    return [*lead, *([0.0] * (12 - len(lead)))]


def _ref(title: str, n: int) -> Work:
    return Work.build(
        title=title,
        abstract="",
        identifiers=Identifiers(doi=f"10.1/{n}"),
        provenance=[
            Provenance(
                source="openalex",
                run_id="run_" + "0" * 26,
                query_id="qry_" + "0" * 26,
                at=T0,
                raw_blob="sha256:" + "c" * 64,
            )
        ],
    )


def _rec(
    n: int,
    *,
    title: str | None = None,
    submitted: str = "2026-11-20",
    cats: Sequence[str] = ("cs.AI",),
    held: str | None = None,
) -> dict[str, object]:
    return {
        "id": f"2611.{n:05d}",
        "version": "v1",
        "title": title or f"Paper {n}",
        "abstract": "",
        "authors": ["Bo Chen"],
        "categories": list(cats),
        "submitted": submitted,
        "held_work_id": held,
    }


def _fetch(project: Project, k: int, records: list[dict[str, object]]) -> str:
    fetch_id = f"fdf_{k:026d}"
    payload = FeedFetched(
        fetch_id=fetch_id,
        categories=("cs.AI",),
        window_from=date(2026, 11, 19),
        window_to=date(2026, 11, 20),
        raw_blobs=(),
        entries_blob=project.blobs.put_json(records),  # type: ignore[arg-type]
        count=len(records),
        held_count=sum(1 for r in records if r["held_work_id"]),
        complete=True,
    )
    project.record(
        [project.events.make("feed.fetched", payload, project.system_actor(), refs=(fetch_id,))]
    )
    return fetch_id


@pytest.fixture
def world(
    tmp_path: Path, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, Project, Project]:
    settings = Settings(root=tmp_path, user="obd")
    a = init_project(settings, "alpha", "exploratory", session=SESSION, clock=clock)
    b = init_project(settings, "beta", "exploratory", session=SESSION, clock=clock)
    refs = {"alpha": [_ref("A core 1", 1), _ref("A core 2", 2)], "beta": [_ref("B core", 3)]}
    monkeypatch.setattr(ff, "reference_set", lambda p: refs.get(p.paths.slug))
    VECTORS.clear()
    VECTORS.update(
        {
            "A core 1": _vec(1, 0),
            "A core 2": _vec(0, 1),
            "B core": _vec(-1, 0),
            "Paper 1": _vec(1, 0.1),  # near A core 1
            "Paper 2": _vec(0.1, 1),  # near A core 2
            "Paper 3": _vec(-1, 0.1),  # near B core
            "Paper 4": _vec(0, 0, 1),
        }
    )
    _fetch(
        a, 1, [_rec(1, submitted="2026-11-18"), _rec(2, submitted="2026-11-22", cats=("cs.LG",))]
    )
    _fetch(
        b,
        2,
        [
            _rec(2, submitted="2026-11-01", cats=("cs.CL",), held="wrk_" + "1" * 26),
            _rec(3, submitted="2026-11-22"),
            _rec(4, submitted="2026-11-22"),
        ],
    )
    return settings, a, b


def _rank(
    settings: Settings, clock: FixedClock, emb: FakeEmbedder | None = None, **kw: float
) -> ff.RankResult:
    return ff.rank_pool(settings, emb or FakeEmbedder(), session=SESSION, clock=clock, **kw)  # type: ignore[arg-type]


def test_pool_is_deduplicated_with_union_of_categories_and_held_in(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    pool = {e.entry_id: e for e in ff.load_pool(settings, clock=clock)}
    assert sorted(pool) == ["2611.00001", "2611.00002", "2611.00003", "2611.00004"]
    two = pool["2611.00002"]
    assert two.categories == ("cs.CL", "cs.LG")
    assert two.held_in == ("beta",)
    assert two.submitted == "2026-11-22"  # the first fetch seen (alpha) supplies the metadata
    assert len(two.fetch_ids) == 2


def test_empty_pool_writes_nothing(tmp_path: Path, clock: FixedClock) -> None:
    settings = Settings(root=tmp_path, user="obd")
    result = _rank(settings, clock)
    assert result.ranking_id is None and not (tmp_path / "factory").exists()
    assert ff.today(settings).cards == ()


def test_project_scores_and_closest_core_work(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    emb = FakeEmbedder()
    result = _rank(settings, clock, emb)
    assert result.projects == ("alpha", "beta") and result.entries == 4
    assert len(emb.calls) == 1 and len(emb.calls[0]) == len(set(emb.calls[0]))  # one call, distinct
    cards = {c.entry_id: c for c in ff.today(settings, clock=clock).cards}
    near_a = {b.slug: b for b in cards["2611.00001"].badges}
    assert near_a["alpha"].closest_title == "A core 1" and near_a["alpha"].score > 0.99
    assert near_a["beta"].score < 0
    assert {b.slug: b.closest_title for b in cards["2611.00002"].badges}["alpha"] == "A core 2"
    assert cards["2611.00003"].badges[0].slug == "beta"  # best score first
    assert [b.slug for b in cards["2611.00002"].badges if b.held] == ["beta"]


def test_newest_first_before_any_training(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    _rank(settings, clock, shown_per_cycle=100)
    page = ff.today(settings, clock=clock)
    assert [c.entry_id for c in page.cards] == [
        "2611.00002",
        "2611.00003",
        "2611.00004",
        "2611.00001",
    ]
    assert all(c.score is None and c.ranker_version is None and not c.explore for c in page.cards)
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    ranked = FeedRanked.model_validate(_events(scope, "feed.ranked")[0].payload)
    assert ranked.ranker_version is None and set(ranked.project_references or {}) == {
        "alpha",
        "beta",
    }
    blob: Any = scope.blobs.get_json(ranked.order_blob)
    assert (
        isinstance(blob, list) and blob[0]["ranker_version"] == "none" and blob[0]["score"] is None
    )
    assert set(blob[0]["projects"]["alpha"]) == {"score", "closest_core_work", "closest_title"}
    assert _events(scope, "feed.ranked")[0].actor.kind == "system"


def _events(scope: FactoryScope, kind: str) -> list[Event]:
    from factory.events.reader import read_all

    return [e for e in read_all(scope.paths.events_dir, scope.catalog) if e.type == kind]


def _train(scope: FactoryScope, version: int = 1) -> None:
    vectors = {
        "2611.00001": _vec(1, 0.1),
        "2611.00002": _vec(0.1, 1),
        "2611.00003": _vec(-1, 0.1),
        "2611.00004": _vec(0, 0, 1),
        "2611.00005": _vec(0.5, 0.5),
    }
    labels = {k: k != "2611.00004" for k in vectors}
    state = feed_ranker.train(labels, vectors, embedding_model="fake/model")
    payload = FeedRankerTrained(
        training_set_hash=state.training_set_hash.removeprefix("sha256:"),
        ids=tuple(sorted(labels)),
        likes=4,
        dislikes=1,
        features=feed_ranker.FEATURE_NAMES,
        library_versions=state.library_versions,
        state_blob=scope.blobs.put(state.to_json().encode()),
        ranker_version=version,
        triggered_by="test",
    )
    scope.record([scope.events.make("feed.ranker_trained", payload, scope.system_actor())])


def test_trained_ranker_orders_today_and_is_named(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    _train(scope)
    result = _rank(settings, clock)
    assert result.ranker_version == 1
    cards = ff.today(settings, clock=clock).cards
    scores = [c.score for c in cards]
    assert all(s is not None for s in scores) and scores == sorted(scores, reverse=True)  # type: ignore[type-var]
    assert cards[-1].entry_id == "2611.00004"  # the disliked direction ranks last
    assert {c.ranker_version for c in cards} == {1}
    assert FeedRanked.model_validate(_events(scope, "feed.ranked")[0].payload).ranker_version == 1


def test_damaged_latest_training_falls_back_to_previous(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    _train(scope, 1)
    bad = FeedRankerTrained(
        training_set_hash="b" * 64,
        ids=("2611.00001",),
        likes=1,
        dislikes=0,
        features=("x",),
        library_versions={},
        state_blob=scope.blobs.put(b"not json"),
        ranker_version=2,
        triggered_by="t",
    )
    scope.record([scope.events.make("feed.ranker_trained", bad, scope.system_actor())])
    assert _rank(settings, clock).ranker_version == 1


def test_exploration_is_seeded_labelled_and_reproducible(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    _rank(settings, clock, shown_per_cycle=2, exploration_share=0.5)
    _rank(settings, clock, shown_per_cycle=2, exploration_share=0.5)
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    first, second = (FeedRanked.model_validate(e.payload) for e in _events(scope, "feed.ranked"))
    assert first.exploration_seed == second.exploration_seed
    assert [s.explore for s in first.shown].count(True) == 1 and len(first.shown) == 2
    cards = ff.today(settings, clock=clock).cards
    assert [c.explore for c in cards].count(True) == 1
    assert cards[0].rank == 1 and cards[1].explore  # shown picks lead, the rest follow


def test_today_pages_and_newest_sort(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    _rank(settings, clock)
    p2 = ff.today(settings, page=2, page_size=3, clock=clock)
    assert (p2.page, p2.pages, p2.total, len(p2.cards)) == (2, 2, 4, 1)
    newest = ff.today(settings, sort="newest", clock=clock)
    assert newest.cards[-1].entry_id == "2611.00001"


def test_project_view_sorted_by_score_and_windowed(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    _rank(settings, clock)
    everything = ff.project_view(settings, "alpha", window_days=None, clock=clock)
    assert [c.entry_id for c in everything][:2] == ["2611.00001", "2611.00002"]
    scores = [next(b.score for b in c.badges if b.slug == "alpha") for c in everything]
    assert scores == sorted(scores, reverse=True)
    clock.advance(datetime(2026, 11, 23, 12, tzinfo=UTC) - clock.now())

    def ids(days: int | None) -> set[str]:
        view = ff.project_view(settings, "alpha", window_days=days, clock=clock)
        return {c.entry_id for c in view}

    assert ids(1) == {"2611.00002", "2611.00003", "2611.00004"}
    assert ids(7) == ids(30) == ids(None)
    with pytest.raises(FactoryValidationError):
        ff.project_view(settings, "alpha", window_days=3, clock=clock)
    assert ff.project_view(settings, "nope", window_days=None, clock=clock) == []


def _react(scope: FactoryScope, entry: str, reaction: FeedReaction) -> None:
    payload = FeedReacted(
        entry_id=entry, reaction=reaction, ranking_id=RANKING, rank_shown=1, score_shown=0.5
    )
    scope.record([scope.events.make("feed.reacted", payload, scope.human_actor(), refs=(entry,))])


def test_liked_and_reading_list_follow_latest_reactions(
    world: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = world
    _rank(settings, clock)
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    for entry, reaction in (
        ("2611.00001", FeedReaction.LIKE),
        ("2611.00002", FeedReaction.LIKE),
        ("2611.00002", FeedReaction.UNSET),
        ("2611.00003", FeedReaction.SAVE),
        ("2611.00004", FeedReaction.SAVE),
        ("2611.00004", FeedReaction.UNSAVE),
    ):
        _react(scope, entry, reaction)
    assert [c.entry_id for c in ff.liked(settings, clock=clock)] == ["2611.00001"]
    assert [c.entry_id for c in ff.reading_list(settings, clock=clock)] == ["2611.00003"]
    cards = {c.entry_id: c for c in ff.today(settings, clock=clock).cards}
    assert cards["2611.00001"].label == "like" and cards["2611.00003"].saved
    assert scope.read(lambda c: fx.latest_reactions(c, scope.tables))["2611.00002"]["label"] is None
