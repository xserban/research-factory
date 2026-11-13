"""The hub feed (plan 2026-11-13-hub-feed, parts 1 to 3): core-layer references, the 24 h cache and
the refetch that skips it, and the runner and timer the main hub server starts.

Same scripted source and fake embedder as `test_feed_service`: no network, torch or weights."""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.feed import FeedRanked
from factory.services import seeds as seeds_service
from factory.services import site_server
from factory.services.context import Project
from factory.services.core_works import mark_core, seed_core_works
from factory.services.feed import (
    CACHE_MAX_AGE,
    FeedRunAll,
    _reference_ids,
    configure,
    current_config,
    feed_run,
    feed_run_all,
    prune_cache,
)
from factory.services.project import init_project
from factory.services.search import list_works
from factory.services.work_layers import WorkLayer
from tests.helpers import SESSION, SourcesFor, _of_type
from tests.test_feed_service import TODAY, FakeEmbedder, FakeFeedSource, _config, _world


def _layer(layer: str) -> WorkLayer:
    return WorkLayer(layer=layer, source="moved", scheme_version=3, miner_layer=None)


def _held_out(project: Project) -> list[str]:
    return sorted(
        set(seed_core_works(project)) - set(seed_core_works(project, development_only=True))
    )


def _plain(project: Project) -> str:
    """A work that is not a seed's work."""
    return sorted({w.id for w in list_works(project)} - set(seed_core_works(project)))[0]


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


# --- part 1: core-layer references ---


def test_core_layer_references_are_the_works_of_the_core_layer(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project, agent, human, mock_sources, held_to=0)
    works = [w.id for w in list_works(project)]
    core = _plain(project)
    other = next(w for w in works if w != core and w not in seed_core_works(project))
    monkeypatch.setattr(
        "factory.services.feed.layers_of",
        lambda _p: {core: _layer("core"), other: _layer("applied")},
    )
    configure(project, human, _config(references="core-layer"))
    assert _reference_ids(project, current_config(project)) == [core]  # type: ignore[arg-type]


def test_core_layer_leaves_out_held_out_seed_works_unless_marked_core(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project, agent, human, mock_sources, held_to=0)
    held_out = _held_out(project)
    assert len(held_out) >= 1
    plain = _plain(project)
    monkeypatch.setattr(
        "factory.services.feed.layers_of",
        lambda _p: {w: _layer("core") for w in [*held_out, plain]},
    )
    configure(project, human, _config(references="core-layer"))
    config = current_config(project)
    assert config is not None
    assert _reference_ids(project, config) == [plain]
    mark_core(project, human, held_out[0])
    assert held_out[0] in _reference_ids(project, config)
    assert not set(held_out[1:]) & set(_reference_ids(project, config))


def test_a_run_ranks_against_the_core_layer_and_records_it(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project, agent, human, mock_sources, held_to=0)
    core = _plain(project)
    monkeypatch.setattr("factory.services.feed.layers_of", lambda _p: {core: _layer("core")})
    configure(project, human, _config(references="core-layer"))
    result = feed_run(project, embedder, FakeFeedSource(size=30), today=TODAY)
    assert result.status == "complete"
    [ranked] = _of_type(project, "feed.ranked")
    payload = FeedRanked.model_validate(ranked.payload)
    assert payload.parameters.references.value == "core-layer"
    assert payload.reference_count == 1
    assert {s.nearest_reference for s in payload.shown} == {core}


def test_a_project_without_a_core_layer_is_refused_before_fetching(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project, agent, human, mock_sources, held_to=0)
    monkeypatch.setattr("factory.services.feed.layers_of", lambda _p: {})
    configure(project, human, _config(references="core-layer"))
    source = FakeFeedSource()
    with pytest.raises(FactoryValidationError) as refused:
        feed_run(project, embedder, source, today=TODAY)
    assert refused.value.issues[0].field == "references"
    assert source.specs == [] and _of_type(project, "feed.fetched") == []


def test_an_earlier_configuration_without_the_new_value_still_reads(
    project: Project, human: Actor
) -> None:
    configure(project, human, _config())
    config = current_config(project)
    assert config is not None and config.references.value == "core"


# --- part 2: the cache (24 h, refetch) ---


def _two_projects(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> Project:
    monkeypatch.setattr(seeds_service, "secrets", SimpleNamespace(randbits=lambda bits: 1234567))
    other = init_project(settings, "demo2", "pilot", session=SESSION, clock=clock)
    for each in (project, other):
        _world(each, agent, human, mock_sources)
        configure(each, human, _config())
    return other


def test_a_second_project_replays_the_cache_and_a_refetch_skips_it(
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
    other = _two_projects(project, agent, human, mock_sources, settings, clock, monkeypatch)
    cache = tmp_path / "cache"
    source = FakeFeedSource()
    first = feed_run(project, embedder, source, today=TODAY, cache_root=cache)
    second = feed_run(other, embedder, source, today=TODAY, cache_root=cache)
    assert (first.cached, second.cached) == (False, True) and len(source.specs) == 1
    again = feed_run(
        other, embedder, source, today=TODAY, cache_root=cache, due=False, bypass_cache=True
    )
    assert again.cached is False and len(source.specs) == 2
    # the refetch wrote its result back: the next plain run replays it
    last = feed_run(other, embedder, source, today=TODAY, cache_root=cache, due=False)
    assert last.cached is True and len(source.specs) == 2


def _stamp(window: Path, when: datetime) -> None:
    for path in (window / "meta.json", window):
        os.utime(path, (when.timestamp(), when.timestamp()))


def _cache_window(root: Path, key: str, window: str, when: datetime) -> Path:
    folder = root / "arxiv" / key / window
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text('{"status": "complete"}')
    _stamp(folder, when)
    return folder


def test_prune_removes_windows_older_than_24_hours_and_keeps_the_rest(tmp_path: Path) -> None:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    old = _cache_window(tmp_path, "k1", "2026-11-11_2026-11-12", now - timedelta(hours=25))
    fresh = _cache_window(tmp_path, "k1", "2026-11-12_2026-11-13", now - timedelta(hours=23))
    gone = _cache_window(tmp_path, "k2", "2026-11-10_2026-11-11", now - timedelta(days=3))
    assert prune_cache(tmp_path, now=now) == 2
    assert not old.exists() and not gone.exists() and fresh.is_dir()
    assert (tmp_path / "arxiv" / "k1").is_dir() and not (tmp_path / "arxiv" / "k2").exists()
    assert prune_cache(tmp_path, now=now) == 0


def test_prune_without_a_cache_folder_does_nothing(tmp_path: Path) -> None:
    assert prune_cache(tmp_path / "none", now=datetime(2026, 11, 13, tzinfo=UTC)) == 0


def test_the_default_age_is_24_hours() -> None:
    assert timedelta(hours=24) == CACHE_MAX_AGE


def test_feed_run_all_prunes_old_windows_but_not_on_a_dry_run(
    settings: Settings, clock: FixedClock, project: Project, embedder: FakeEmbedder, tmp_path: Path
) -> None:
    now = clock.now()
    cache = tmp_path / "cache"
    old = _cache_window(cache, "k", "w", now - timedelta(hours=30))
    common = {
        "embedder": embedder,
        "source": FakeFeedSource(),
        "session": SESSION,
        "clock": clock,
        "slugs": [],
        "cache_root": cache,
    }
    feed_run_all(settings, dry_run=True, **common)  # type: ignore[arg-type]
    assert old.is_dir()
    feed_run_all(settings, **common)  # type: ignore[arg-type]
    assert not old.exists()


def test_feed_run_all_passes_the_refetch_to_each_project(
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
    """Three projects with the same window: the second replays the first's fetch, the third,
    run as a refetch, goes to arXiv again."""
    second = _two_projects(project, agent, human, mock_sources, settings, clock, monkeypatch)
    third = init_project(settings, "demo3", "pilot", session=SESSION, clock=clock)
    _world(third, agent, human, mock_sources)
    configure(third, human, _config())
    source = FakeFeedSource()
    common = {
        "embedder": embedder,
        "source": source,
        "session": SESSION,
        "clock": clock,
        "cache_root": tmp_path / "cache",
        "today": TODAY,
    }
    feed_run_all(settings, slugs=[project.paths.slug], **common)  # type: ignore[arg-type]
    feed_run_all(settings, slugs=[second.paths.slug], **common)  # type: ignore[arg-type]
    assert len(source.specs) == 1  # replayed the cache
    feed_run_all(settings, slugs=[third.paths.slug], bypass_cache=True, **common)  # type: ignore[arg-type]
    assert len(source.specs) == 2


# --- part 3: the runner and the timer ---


def _wait(condition: object, seconds: float = 5.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if callable(condition) and condition():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def _outcome() -> FeedRunAll:
    return FeedRunAll(exit_code=0, outcomes=())


def test_the_runner_runs_one_feed_at_a_time_and_keeps_the_outcome() -> None:
    release = threading.Event()
    seen: list[bool] = []

    def run(refetch: bool) -> FeedRunAll:
        seen.append(refetch)
        release.wait(5)
        return _outcome()

    runner = site_server.FeedRunner(run)
    assert runner.start(refetch=True) is True
    _wait(lambda: runner.running)
    assert runner.start() is False  # one at a time
    release.set()
    _wait(lambda: not runner.running and runner.last is not None)
    assert seen == [True]
    assert runner.last == {"refetch": True, "exit_code": 0, "outcomes": []}
    assert runner.start() is True  # free again
    _wait(lambda: not runner.running)
    assert seen == [True, False]


def test_a_failing_run_is_kept_as_an_error_and_frees_the_runner() -> None:
    def run(refetch: bool) -> FeedRunAll:
        raise RuntimeError("arXiv is down")

    runner = site_server.FeedRunner(run)
    assert runner.start() is True
    _wait(lambda: not runner.running and runner.last is not None)
    assert runner.last == {"refetch": False, "error": "RuntimeError: arXiv is down"}
    assert runner.start() is True


def test_the_timer_asks_for_a_run_at_start_and_again_every_period_until_stopped() -> None:
    calls: list[bool] = []

    def run(refetch: bool) -> FeedRunAll:
        calls.append(refetch)
        return _outcome()

    timer = site_server.FeedTimer(site_server.FeedRunner(run), every=0.05)
    timer.start()
    _wait(lambda: len(calls) >= 3)
    timer.stop()
    time.sleep(0.2)
    settled = len(calls)
    time.sleep(0.2)
    assert len(calls) == settled and not any(calls)  # never a refetch from the timer


def test_a_hub_without_a_background_has_no_timer(settings: Settings, project: Project) -> None:
    calls: list[bool] = []
    runner = site_server.FeedRunner(lambda refetch: calls.append(refetch) or _outcome())
    hub = site_server.MainHub(
        settings.root, lambda: [], lambda slug: project, min_gap=1, background=False, feed=runner
    )
    hub.start_feed()
    time.sleep(0.2)
    assert calls == []
    hub.stop()
