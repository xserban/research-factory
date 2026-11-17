"""`collect` is cached on the project's feed events: a second view reads no event file, an event
of another kind does not invalidate it, a new feed event does, the cached view equals a fresh one,
and the feed events are read from the files without parsing the rest of the log."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from factory.events import reader
from factory.services import feed_events, site_feed
from factory.services import site_hub_feed as feed
from factory.services.context import Project
from tests.test_site_feed import _ranked, _world, stub_titles  # noqa: F401


@pytest.fixture(autouse=True)
def _fresh() -> None:
    feed._CACHE.clear()
    feed_events.clear()


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count every event line the reader parses (a full-log read parses them all)."""
    calls: list[int] = []
    orig = reader._parse_line

    def wrapped(*a: Any) -> Any:
        calls.append(1)
        return orig(*a)

    monkeypatch.setattr(reader, "_parse_line", wrapped)
    return calls


def test_second_view_reads_no_event_file_and_takes_the_new_token(
    project: Project,
    stub_titles: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project)
    first = feed.collect(project, "s", "T", "tok1")
    assert first.error is None and first.listing is not None and first.listing.items
    calls = _spy(monkeypatch)
    again = feed.collect(project, "s", "T2", "tok2")
    assert calls == []
    assert (again.title, again.token) == ("T2", "tok2")
    assert dataclasses.replace(again, title="T", token="tok1") == first


def test_a_cold_view_never_reads_the_whole_log(
    project: Project,
    stub_titles: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project)
    project.index.sync()
    calls = _spy(monkeypatch)
    view = feed.collect(project, "s", "T", "t")
    assert view.error is None and view.ranked is not None
    assert calls == []


def test_an_event_of_another_kind_does_not_invalidate(
    project: Project,
    stub_titles: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _world(project)
    feed.collect(project, "s", "T", "t")
    key = (str(project.paths.events_dir), "s")
    before = feed._CACHE[key][0]
    # an unrelated event file appended to
    files = sorted(project.paths.events_dir.glob("*/*.jsonl"))
    with files[0].open("ab") as f:
        f.write(b'{"type":"other.thing"}\n')
    calls: list[int] = []
    monkeypatch.setattr(feed, "_collect", lambda *a: calls.append(1))  # type: ignore[arg-type,return-value]
    feed.collect(project, "s", "T", "t")
    assert calls == [] and feed._CACHE[key][0] == before


def test_a_new_feed_event_invalidates_and_matches_a_fresh_read(
    project: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    _world(project)
    feed.collect(project, "s", "T", "t")
    key = (str(project.paths.events_dir), "s")
    old = feed._CACHE[key][0]
    _ranked(project)
    cached = feed.collect(project, "s", "T", "t")
    assert feed._CACHE[key][0] != old
    feed._CACHE.clear()
    feed_events.clear()
    assert feed.collect(project, "s", "T", "t") == cached


def test_feed_events_equal_the_feed_events_of_a_full_read(project: Project) -> None:
    _world(project)
    expected = [
        e
        for e in reader.read_all(project.paths.events_dir, project.catalog)
        if e.type.startswith("feed.")
    ]
    got = feed_events.feed_events(project.paths.events_dir, project.catalog)
    assert [e.id for e in got] == [e.id for e in expected] and got
    again = feed_events.feed_events(project.paths.events_dir, project.catalog)
    assert again == got


def test_entry_records_come_from_the_feed_scan(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _world(project)
    calls = _spy(monkeypatch)
    assert site_feed._entry_records(project)
    assert calls == []


def test_an_error_is_not_cached(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def failing(project: Project, slug: str, title: str, token: str) -> feed.ProjectFeed:
        calls.append(1)
        return feed.ProjectFeed(slug, title, token, error="boom")

    monkeypatch.setattr(feed, "_collect", failing)
    feed.collect(project, "s", "T", "t")
    feed.collect(project, "s", "T", "t")
    assert len(calls) == 2
