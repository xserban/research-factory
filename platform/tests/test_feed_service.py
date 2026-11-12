"""The feed cycle (slice 4c, F4): configuration, fetch, held filter, ranking, exploration.

A scripted source and a fake embedder with fixed vectors stand in for arXiv and SPECTER2, so no
network, torch or weights are needed."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.feed import FeedFetched, FeedRanked
from factory.model.search import QuerySpec, RunStatus
from factory.model.versions import VersionLinked
from factory.model.work import Author, Dates, Identifiers, Provenance, Work
from factory.services import seeds as seeds_service
from factory.services.context import Project
from factory.services.core_works import (
    forward_core_sources,
    mark_core,
    seed_core_works,
)
from factory.services.dedup_incremental import held_matches
from factory.services.feed import (
    _entries,
    _reference_ids,
    configure,
    current_config,
    exploration_seed,
    feed_run,
    feed_run_all,
    feed_status,
    select_shown,
)
from factory.services.project import init_project
from factory.services.references import included_works
from factory.services.search import list_works
from factory.sources.base import PageSink, RawPage, SearchResult
from tests.helpers import SESSION, T0, SourcesFor, _of_type, _setup, openalex_item

TODAY = date(2026, 11, 11)
LISTING = 200
HELD = 5
CATEGORIES = ["cs.AI", "cs.LG"]
HELD_TITLES = [f"Held corpus paper {k}" for k in range(1, HELD + 1)]


class _Ordered(StrictModel):
    entry_id: str
    rank: int
    score: float


class FakeEmbedder:
    """Fixed vectors from a hash of the text."""

    model_id = "fake/model"
    weights_hash = "a" * 64
    software = "fake==1"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(b) - 127.5 for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]


def _work(
    n: int,
    run_id: str,
    query_id: str,
    raw_blob: str,
    *,
    title: str | None = None,
    author: str = "Bo Chen",
    doi: str | None = None,
) -> Work:
    arxiv = f"http://arxiv.org/abs/2611.{n:05d}v1"
    return Work.build(
        title=title or f"Feed paper {n:03d}",
        abstract=f"Abstract of feed paper {n:03d}.",
        authors=[Author(name=author)],
        identifiers=Identifiers(arxiv=arxiv, url=arxiv, doi=doi),
        dates=Dates(published=date(2026, 11, 10)),
        subjects=["cs.AI"],
        provenance=[
            Provenance(source="arxiv", run_id=run_id, query_id=query_id, at=T0, raw_blob=raw_blob)
        ],
    )


class FakeFeedSource:
    """Returns one page and the scripted works; counts its calls."""

    def __init__(self, specials: dict[int, dict[str, Any]] | None = None, size: int = LISTING):
        self.specials = specials or {}
        self.size = size
        self.specs: list[QuerySpec] = []

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        self.specs.append(spec)
        body = f"<feed>{self.size} entries for {spec.text}</feed>"
        blob = archive(RawPage(ordinal=0, body=body, url="https://arxiv.test/q", fetched_at=T0))
        works = [
            _work(n, run_id, query_id, blob, **self.specials.get(n, {}))
            for n in range(1, self.size + 1)
        ]
        return SearchResult(
            source="arxiv",
            query_sent=spec.text,
            reported_count=len(works),
            works=works,
            pages=1,
            status=RunStatus.COMPLETE,
        )


def _held_items() -> list[dict[str, Any]]:
    return [
        openalex_item(
            title=title,
            author="Bo Chen",
            published="2026-11-10",
            openalex_id=f"W9{k}",
            doi=f"10.2000/held{k}",
        )
        for k, title in enumerate(HELD_TITLES, start=1)
    ]


def _held_specials() -> dict[int, dict[str, Any]]:
    """Listing entries 1-3 repeat a corpus title, 4 repeats a corpus DOI under another title."""
    specials: dict[int, dict[str, Any]] = {n: {"title": HELD_TITLES[n - 1]} for n in (1, 2, 3)}
    specials[4] = {"title": "A differently titled preprint", "doi": "10.2000/held4"}
    return specials


def _world(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, held_to: int = 4
) -> None:
    _setup(
        project,
        agent,
        human,
        mock_sources,
        dual_sample=0.5,
        random_works=3,
        extra_items=_held_items()[:held_to],
    )


def _config(**over: object) -> dict[str, object]:
    return {"categories": CATEGORIES, "shown_per_cycle": 20, "exploration_share": 0.1, **over}


def _count(project: Project) -> int:
    return len(_of_type(project, "feed.fetched")) + len(_of_type(project, "feed.ranked"))


def _alias_world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
    """A corpus work with a published DOI that only a version link attached; returns its id."""
    _world(project, agent, human, mock_sources, held_to=0)
    target = list_works(project)[0].id
    link = VersionLinked(
        work_id=target,
        identifiers=Identifiers(doi="10.5555/published"),
        source="crossref",
        run_id=project.ids.new("run"),
    )
    project.record([project.events.make("version.linked", link, project.system_actor())])
    return target


# --- configuration ---


def test_configure_records_a_human_configuration(project: Project, human: Actor) -> None:
    configure(project, human, _config())
    config = current_config(project)
    assert config is not None and config.categories == tuple(CATEGORIES)
    assert len(_of_type(project, "feed.configured")) == 1


def test_agent_configure_is_refused_and_writes_nothing(project: Project, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError) as refused:
        configure(project, agent, _config())
    assert [(i.field, i.reason) for i in refused.value.issues] == [("actor", "human-only")]
    assert _of_type(project, "feed.configured") == []
    assert current_config(project) is None


def test_invalid_configuration_writes_nothing(project: Project, human: Actor) -> None:
    with pytest.raises(FactoryValidationError):
        configure(project, human, _config(categories=["Not A Category"]))
    with pytest.raises(FactoryValidationError):
        configure(project, human, _config(exploration_share=1.0))
    assert _of_type(project, "feed.configured") == []


# --- refusals ---


def test_run_without_configuration_is_refused(project: Project, embedder: FakeEmbedder) -> None:
    source = FakeFeedSource()
    with pytest.raises(FactoryValidationError) as refused:
        feed_run(project, embedder, source, today=TODAY)
    assert refused.value.issues[0].field == "config"
    assert source.specs == []


def test_run_without_references_is_refused_before_fetching(
    explore_project: Project, human: Actor, embedder: FakeEmbedder
) -> None:
    configure(explore_project, human, _config())
    source = FakeFeedSource()
    with pytest.raises(FactoryValidationError) as refused:
        feed_run(explore_project, embedder, source, today=TODAY)
    assert refused.value.issues[0].field == "references"
    assert source.specs == [] and _count(explore_project) == 0


# --- the cycle ---


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


def test_held_entries_are_recorded_and_never_shown(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config(shown_per_cycle=LISTING))
    source = FakeFeedSource(_held_specials())
    result = feed_run(project, embedder, source, today=TODAY)
    assert result.status == "complete" and result.fetched == LISTING and result.held == 4
    assert result.ranked == LISTING - 4
    [ranked] = _of_type(project, "feed.ranked")
    shown = {s.entry_id for s in FeedRanked.model_validate(ranked.payload).shown}
    assert not shown & {f"2611.{n:05d}" for n in (1, 2, 3, 4)}
    assert len(shown) == LISTING - 4
    with project.index.connect() as conn:
        held = conn.execute(
            text("SELECT entry_id, held_work_id FROM feed_entries WHERE held_work_id IS NOT NULL")
        ).all()
    assert sorted(str(e) for e, _ in held) == [f"2611.{n:05d}" for n in (1, 2, 3, 4)]
    [query] = source.specs
    assert query.text == "cat:cs.AI OR cat:cs.LG"
    assert query.filters == {"listed_since": "2026-11-10"}


def test_entries_blob_has_the_shape_the_fold_reads(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config())
    feed_run(project, embedder, FakeFeedSource(_held_specials()), today=TODAY)
    [fetched] = _of_type(project, "feed.fetched")
    records = project.blobs.get_json(str(fetched.payload["entries_blob"]))
    assert isinstance(records, list) and len(records) == LISTING
    first = records[0]
    assert isinstance(first, dict)
    assert set(first) == {
        "id",
        "version",
        "title",
        "abstract",
        "authors",
        "categories",
        "submitted",
        "held_work_id",
    }
    assert first["id"] == "2611.00001" and first["version"] == "v1"
    assert first["held_work_id"] is not None
    assert fetched.payload["count"] == LISTING and fetched.payload["held_count"] == 4
    assert fetched.payload["complete"] is True
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT COUNT(*) FROM feed_entries")).scalar_one()
    assert rows == LISTING  # the fold read the blob


def test_shown_list_has_the_exploration_share_and_labels(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config(shown_per_cycle=20, exploration_share=0.1))
    result = feed_run(project, embedder, FakeFeedSource(), today=TODAY)
    assert result.shown == 20 and result.explore == 2
    [event] = _of_type(project, "feed.ranked")
    ranked = FeedRanked.model_validate(event.payload)
    assert [s.rank for s in ranked.shown] == sorted(s.rank for s in ranked.shown)
    top = [s for s in ranked.shown if not s.explore]
    explore = [s for s in ranked.shown if s.explore]
    assert [s.rank for s in top] == list(range(1, 19))
    assert len(explore) == 2 and all(s.rank > 18 for s in explore)
    references = set(forward_core_sources(project, included_works(project)))
    assert all(s.nearest_reference in references for s in ranked.shown)
    assert ranked.reference_count == len(references)
    order = project.blobs.get_json(ranked.order_blob)
    assert isinstance(order, list) and len(order) == LISTING
    assert ranked.exploration_seed == exploration_seed(
        ranked.reference_hash,
        [(entry.entry_id, entry.score) for entry in (_Ordered.model_validate(o) for o in order)],
    )


def test_no_exploration_share_shows_only_the_top() -> None:
    order = [(f"2611.{n:05d}", 1.0 - n / 1000) for n in range(1, 41)]
    picks = select_shown(order, 10, 0.0, seed=7)
    assert [p[0] for p in picks] == list(range(1, 11)) and not any(p[3] for p in picks)
    few = select_shown(order[:5], 10, 0.3, seed=7)
    assert len(few) == 5 and not any(p[3] for p in few)


def test_an_order_no_longer_than_the_slots_is_shown_whole_without_exploration() -> None:
    order = [(f"2611.{n:05d}", 1.0 - n / 1000) for n in range(1, 9)]
    for count in (8, 9):
        picks = select_shown(order, count, 0.3, seed=7)
        assert [p[1] for p in picks] == [e for e, _ in order]
        assert [p[0] for p in picks] == list(range(1, 9)) and not any(p[3] for p in picks)


def test_same_inputs_give_the_same_order_and_payloads(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    embedder: FakeEmbedder,
    settings: Settings,
    clock: FixedClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The seed development/held-out split is drawn from `secrets.randbits` and fixes which
    # references the ranking sees; draw it identically for both projects.
    monkeypatch.setattr(seeds_service, "secrets", SimpleNamespace(randbits=lambda bits: 1234567))
    other = init_project(settings, "demo2", "pilot", session=SESSION, clock=clock)
    payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
    cache = tmp_path / "cache"
    source = FakeFeedSource(_held_specials())
    for each in (project, other):
        _world(each, agent, human, mock_sources)
        configure(each, human, _config())
        feed_run(each, embedder, source, today=TODAY, cache_root=cache)
        [fetched] = _of_type(each, "feed.fetched")
        [ranked] = _of_type(each, "feed.ranked")
        fetch = {k: v for k, v in fetched.payload.items() if k != "fetch_id"}
        rank = {k: v for k, v in ranked.payload.items() if k not in ("ranking_id", "fetch_ids")}
        payloads.append((fetch, rank))
    assert payloads[0] == payloads[1]
    assert len(source.specs) == 1  # the second project replayed the shared cache
    assert (cache / "arxiv").is_dir()
    # Each project holds the page in its own blobs and records the hash.
    for each in (project, other):
        [fetched] = _of_type(each, "feed.fetched")
        refs = FeedFetched.model_validate(fetched.payload).raw_blobs
        assert refs and each.blobs.exists(refs[0])


def test_entries_already_known_are_not_ranked_again(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config())
    source = FakeFeedSource()
    feed_run(project, embedder, source, today=TODAY)
    again = feed_run(project, embedder, source, due=False, today=TODAY)
    assert again.status == "nothing-new" and again.ranked == 0
    assert again.already_known == LISTING and again.ranking_id is None
    assert len(_of_type(project, "feed.ranked")) == 1
    status = feed_status(project, today=TODAY)
    assert status.rankings == 1 and status.entries == LISTING and status.fetches == 2


def test_not_due_writes_nothing(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config(interval_days=1))
    source = FakeFeedSource()
    feed_run(project, embedder, source, today=TODAY)
    before = _count(project)
    result = feed_run(project, embedder, source, due=True, today=TODAY)
    assert result.status == "not-due" and _count(project) == before
    assert len(source.specs) == 1
    assert feed_status(project, today=TODAY).due is False
    assert feed_status(project, today=date(2026, 11, 12)).due is True


def test_window_starts_at_the_last_window_minus_the_overlap(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config(interval_days=1, overlap_days=2))
    source = FakeFeedSource(size=5)
    feed_run(project, embedder, source, today=TODAY)
    feed_run(project, embedder, source, today=date(2026, 11, 12))
    assert [s.filters["listed_since"] for s in source.specs] == ["2026-11-10", "2026-11-09"]


def test_dry_run_fetches_and_writes_nothing(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config())
    source = FakeFeedSource()
    result = feed_run(project, embedder, source, dry_run=True, today=TODAY)
    assert result.status == "dry-run" and result.note and "cat:cs.AI OR cat:cs.LG" in result.note
    assert source.specs == [] and _count(project) == 0


# --- references and held-out seeds ---


def _held_out_works(project: Project) -> list[str]:
    return sorted(
        set(seed_core_works(project)) - set(seed_core_works(project, development_only=True))
    )


def test_core_included_references_leave_out_held_out_seed_works(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project, agent, human, mock_sources, held_to=0)
    held_out = _held_out_works(project)
    assert held_out
    plain = sorted(set(w.id for w in list_works(project)) - set(seed_core_works(project)))[0]
    monkeypatch.setattr(
        "factory.services.feed.included_works", lambda _project: sorted([*held_out, plain])
    )
    configure(project, human, _config(references="core+included"))
    ids = _reference_ids(project, current_config(project))  # type: ignore[arg-type]
    assert plain in ids and not set(held_out) & set(ids)
    result = feed_run(project, embedder, FakeFeedSource(size=30), today=TODAY)
    assert result.status == "complete"
    [ranked] = _of_type(project, "feed.ranked")
    nearest = {s.nearest_reference for s in FeedRanked.model_validate(ranked.payload).shown}
    assert not set(held_out) & nearest


def test_a_marked_core_held_out_work_is_a_reference(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project, agent, human, mock_sources, held_to=0)
    held_out = _held_out_works(project)
    mark_core(project, human, held_out[0])
    monkeypatch.setattr("factory.services.feed.included_works", lambda _project: held_out)
    configure(project, human, _config(references="core+included"))
    ids = _reference_ids(project, current_config(project))  # type: ignore[arg-type]
    assert held_out[0] in ids and not set(held_out[1:]) & set(ids)


# --- provenance of an agent-triggered run ---


def test_an_agent_run_is_recorded_with_its_provenance(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config())
    result = feed_run(project, embedder, FakeFeedSource(size=20), today=TODAY, actor=agent)
    assert result.status == "complete"
    for kind in ("feed.fetched", "feed.ranked"):
        [event] = _of_type(project, kind)
        assert event.actor.kind == "agent" and event.actor.model == agent.model
        assert event.actor.skill == agent.skill and event.input_blob is not None
    with project.index.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM feed_entries")).scalar_one() == 20
        assert conn.execute(text("SELECT COUNT(*) FROM feed_rankings")).scalar_one() == 1


def test_a_human_cannot_run_the_feed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config())
    with pytest.raises(FactoryValidationError) as refused:
        feed_run(project, embedder, FakeFeedSource(size=5), today=TODAY, actor=human)
    assert refused.value.issues[0].field == "actor" and _count(project) == 0


def test_reference_hash_and_count_cover_the_works_actually_embedded(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factory.index.ranking import corpus_hash

    _world(project, agent, human, mock_sources, held_to=0)
    configure(project, human, _config())
    real = _reference_ids(project, current_config(project))  # type: ignore[arg-type]
    monkeypatch.setattr(
        "factory.services.feed._reference_ids", lambda _p, _c: [*real, "rf:missing-00000000"]
    )
    feed_run(project, embedder, FakeFeedSource(size=15), today=TODAY)
    [ranked] = _of_type(project, "feed.ranked")
    payload = FeedRanked.model_validate(ranked.payload)
    assert payload.reference_count == len(real)
    assert payload.reference_hash == corpus_hash(real)


def test_send_refuses_an_entry_whose_paper_entered_the_corpus_after_the_fetch(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    embedder: FakeEmbedder,
) -> None:
    from factory.services.feed import send

    _world(project, agent, human, mock_sources, held_to=0)
    configure(project, human, _config(shown_per_cycle=20))
    feed_run(project, embedder, FakeFeedSource(size=10), today=TODAY)
    target = list_works(project)[0].id
    link = VersionLinked(
        work_id=target,
        identifiers=Identifiers(arxiv="2611.00003"),
        source="crossref",
        run_id=project.ids.new("run"),
    )
    project.record([project.events.make("version.linked", link, project.system_actor())])
    before = len(_of_type(project, "feed.sent"))
    with pytest.raises(FactoryValidationError) as refused:
        send(project, human, "2611.00003")
    assert [(i.field, i.reason) for i in refused.value.issues] == [("entry_id", "held")]
    assert len(_of_type(project, "feed.sent")) == before
    send(project, human, "2611.00004")
    assert len(_of_type(project, "feed.sent")) == before + 1


# --- aliases ---


def test_held_matches_consults_aliases(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    target = _alias_world(project, agent, human, mock_sources)
    probe = _work(
        900, "run_" + "0" * 26, "qry_" + "0" * 26, "sha256:" + "0" * 64,
        title="A title that matches nothing", doi="10.5555/published",
    )  # fmt: skip
    assert held_matches(project, [probe]) == {probe.id: target}


def test_alias_match_holds_the_entry(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, embedder: FakeEmbedder
) -> None:
    target = _alias_world(project, agent, human, mock_sources)
    configure(project, human, _config())
    source = FakeFeedSource(
        {7: {"title": "Unrelated preprint title", "doi": "10.5555/published"}}, size=12
    )
    result = feed_run(project, embedder, source, today=TODAY)
    assert result.held == 1 and result.ranked == 11
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT held_work_id FROM feed_entries WHERE entry_id = '2611.00007'")
        ).one()
    assert row[0] == target
    [ranked] = _of_type(project, "feed.ranked")
    shown = FeedRanked.model_validate(ranked.payload).shown
    assert "2611.00007" not in {s.entry_id for s in shown}


# --- all projects ---


def test_run_all_exit_status(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    embedder: FakeEmbedder,
    settings: Settings,
    clock: FixedClock,
) -> None:
    _world(project, agent, human, mock_sources)
    configure(project, human, _config())
    init_project(settings, "bare", "exploratory", session=SESSION, clock=clock)  # no config
    run = feed_run_all(
        settings, embedder=embedder, source=FakeFeedSource(size=10), session=SESSION,
        clock=clock, today=TODAY,
    )  # fmt: skip
    codes = {o.slug: o.code for o in run.outcomes}
    assert codes == {"bare": 0, "demo": 0} and run.exit_code == 0
    again = feed_run_all(
        settings, embedder=embedder, source=FakeFeedSource(size=10), session=SESSION,
        clock=clock, today=TODAY,
    )  # fmt: skip
    assert {o.slug: o.result.status for o in again.outcomes if o.result} == {
        "bare": "not-configured",
        "demo": "not-due",
    }
    # A configured project with no reference is a refusal: exit 2.
    configure(init_project(settings, "norefs", "exploratory", session=SESSION, clock=clock),
              human, _config())  # fmt: skip
    refused = feed_run_all(
        settings, embedder=embedder, source=FakeFeedSource(size=10), session=SESSION,
        clock=clock, today=TODAY,
    )  # fmt: skip
    assert refused.exit_code == 2


def test_entry_version_comes_from_the_raw_record_not_the_normalised_id() -> None:
    def build(identifiers: Identifiers, raw_ref: str | None) -> Work:
        return Work.build(
            title="T",
            identifiers=identifiers,
            provenance=[
                Provenance(
                    source="arxiv",
                    run_id="run_00000000000000000000000000",
                    query_id="qry_00000000000000000000000000",
                    at=T0,
                    raw_blob="sha256:" + "a" * 64,
                    raw_ref=raw_ref,
                )
            ],
        )

    raw = "http://arxiv.org/abs/2401.01234v2"
    # As sources/arxiv.py builds it: versioned raw id as arxiv, url and raw_ref.
    adapter = build(Identifiers(arxiv=raw, url=raw), raw)
    assert adapter.identifiers.arxiv == "2401.01234"  # normalised, version stripped
    [entry], _skipped = _entries([adapter])
    assert entry.version == "v2" and entry.entry_id == "2401.01234"
    # Only the url survives, or only the provenance ref survives.
    assert _entries([build(Identifiers(arxiv=raw, url=raw), None)])[0][0].version == "v2"
    assert _entries([build(Identifiers(arxiv=raw), raw)])[0][0].version == "v2"
    # Unversioned id: None.
    plain = "http://arxiv.org/abs/2401.01234"
    assert _entries([build(Identifiers(arxiv=plain, url=plain), plain)])[0][0].version is None
    # A non-arXiv url is never read as a version.
    other = build(Identifiers(arxiv="2401.01234", url="https://example.org/paper-v3"), None)
    assert _entries([other])[0][0].version is None
