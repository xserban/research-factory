"""`collect` is cached on the event files: a second view reads nothing, an appended event or a
changed index invalidates it, a failure is not cached."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.services import site_hub_feed as feed
from factory.services.context import Project


class _Paths:
    def __init__(self, root: Path) -> None:
        self.events_dir = root / "events"
        self.index_path = root / "index.sqlite"


class _P:
    def __init__(self, root: Path) -> None:
        self.paths = _Paths(root)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    (tmp_path / "events").mkdir()
    (tmp_path / "events" / "a.jsonl").write_text("one\n")
    return _P(tmp_path)  # type: ignore[return-value]


def _count(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def fake(project: Project, slug: str, title: str, token: str) -> feed.ProjectFeed:
        calls.append(1)
        return feed.ProjectFeed(slug, title, token)

    monkeypatch.setattr(feed, "_collect", fake)
    feed._CACHE.clear()
    return calls


def test_second_view_reads_nothing_and_takes_the_new_token(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _count(monkeypatch)
    feed.collect(project, "s", "T", "tok1")
    again = feed.collect(project, "s", "T2", "tok2")
    assert len(calls) == 1
    assert (again.title, again.token) == ("T2", "tok2")


def test_an_appended_event_invalidates(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count(monkeypatch)
    feed.collect(project, "s", "T", "t")
    with (project.paths.events_dir / "a.jsonl").open("a") as f:
        f.write("two\n")
    feed.collect(project, "s", "T", "t")
    assert len(calls) == 2


def test_a_changed_index_invalidates(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count(monkeypatch)
    feed.collect(project, "s", "T", "t")
    project.paths.index_path.write_text("x")
    feed.collect(project, "s", "T", "t")
    feed.collect(project, "s", "T", "t")
    assert len(calls) == 2


def test_an_error_is_not_cached(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def failing(project: Project, slug: str, title: str, token: str) -> feed.ProjectFeed:
        calls.append(1)
        return feed.ProjectFeed(slug, title, token, error="boom")

    monkeypatch.setattr(feed, "_collect", failing)
    feed._CACHE.clear()
    feed.collect(project, "s", "T", "t")
    feed.collect(project, "s", "T", "t")
    assert len(calls) == 2
