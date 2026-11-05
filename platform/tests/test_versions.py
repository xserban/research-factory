"""Version observation and identifier aliases: newer arXiv versions, published-version links."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.search import QuerySpec
from factory.model.work import Identifiers
from factory.services.agreement import final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run
from factory.services.living_hooks import make_status_hook
from factory.services.versions import aliases, link_conflicts, newer_versions, vor_available
from factory.services.watch import watch_run
from factory.sources.base import StatusRecord
from tests.helpers import SourcesFor
from tests.notice_helpers import (
    NoticeWorld,
    StatusScript,
    dependent_world,
    fetch_arxiv_version,
    status_factories,
    version_in_cycle,
    version_record,
)
from tests.watch_helpers import ScriptedSource, adapters, by_text, record

PRE = {**record("Preprint of sparse routing", author="Pre Print", year=2023), "arxiv": "2301.00001"}
PRE2 = {**record("Preprint of dense gating", author="Gat Ing", year=2023), "arxiv": "2301.00002"}
HELD = record("Unrelated title about kernels", author="Ken Nel", year=2022, doi="10.3000/held")
PUBLISHED = "10.3000/pub"


def _events(project: Project, type_: str) -> list[Any]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == type_]


def _answer_by_arxiv(
    latest: dict[str, int], linked: dict[str, str] | None = None
) -> Callable[[QuerySpec], list[StatusRecord]]:
    def answer(spec: QuerySpec) -> list[StatusRecord]:
        return [
            version_record(a, latest=latest[a], linked_doi=(linked or {}).get(a))
            for a in spec.text.split(",")
            if a in latest
        ]

    return answer


@pytest.fixture
def world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    built = dependent_world(project, agent, human, mock_sources, [PRE, PRE2, HELD])
    first, second = (
        built.by_title["Preprint of sparse routing"],
        built.by_title["Preprint of dense gating"],
    )
    fetch_arxiv_version(project, first, "2301.00001v2")
    fetch_arxiv_version(project, second, "2301.00002v1")
    return built


def _ids(world: NoticeWorld) -> tuple[str, str, str]:
    t = world.by_title
    return (
        t["Preprint of sparse routing"],
        t["Preprint of dense gating"],
        t["Unrelated title about kernels"],
    )


def test_newer_arxiv_version_observed_no_fetch(world: NoticeWorld) -> None:
    pre, pre2, _ = _ids(world)
    before = len(
        [
            e
            for e in read_all(world.project.paths.events_dir, world.project.catalog)
            if e.type.startswith("fulltext.")
        ]
    )
    arxiv = StatusScript("arxiv", _answer_by_arxiv({"2301.00001": 3, "2301.00002": 1}))
    _, summary = version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    [event] = _events(world.project, "version.observed")
    assert event.payload["work_id"] == pre and event.payload["route"] == "arxiv-html"
    assert event.payload["source_version"] == "2301.00001v3"
    assert summary.newer == 1 and summary.linked == 0 and summary.conflicts == 0
    after = len(
        [
            e
            for e in read_all(world.project.paths.events_dir, world.project.catalog)
            if e.type.startswith("fulltext.")
        ]
    )
    assert after == before  # nothing fetched
    assert [(v.work_id, v.source_version) for v in newer_versions(world.project)] == [
        (pre, "2301.00001v3")
    ]
    # Observing again writes nothing.
    version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    assert len(_events(world.project, "version.observed")) == 1


def test_newer_version_cleared_after_refresh(world: NoticeWorld) -> None:
    pre, pre2, _ = _ids(world)
    arxiv = StatusScript("arxiv", _answer_by_arxiv({"2301.00001": 3}))
    version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    assert newer_versions(world.project)
    fetch_arxiv_version(world.project, pre, "2301.00001v3")
    assert newer_versions(world.project) == []


def test_vor_link_adds_alias(world: NoticeWorld) -> None:
    pre, pre2, _ = _ids(world)
    arxiv = StatusScript(
        "arxiv", _answer_by_arxiv({"2301.00001": 2}, linked={"2301.00001": PUBLISHED})
    )
    _, summary = version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    [event] = _events(world.project, "version.linked")
    assert event.payload["work_id"] == pre and event.payload["source"] == "arxiv"
    assert event.payload["identifiers"]["doi"] == PUBLISHED
    assert event.payload["conflicts_with"] is None
    assert summary.linked == 1
    assert aliases(world.project, pre) == Identifiers(doi=PUBLISHED)
    assert aliases(world.project, pre2) == Identifiers()
    assert vor_available(world.project) == [pre]  # its document is still the preprint's
    version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    assert len(_events(world.project, "version.linked")) == 1


def test_later_database_record_merges_by_alias(world: NoticeWorld) -> None:
    pre, pre2, _ = _ids(world)
    arxiv = StatusScript(
        "arxiv", _answer_by_arxiv({"2301.00001": 2}, linked={"2301.00001": PUBLISHED})
    )
    version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    # The journal record shares neither title nor author with the preprint: only the alias joins.
    journal = record(
        "Journal edition of expert dispatch", author="Zed Quux", year=2024, doi=PUBLISHED
    )
    world.project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    summary = watch_run(
        world.project,
        sources=adapters(ScriptedSource(by_text({"attention": [[journal]]}))),
        trigger="scheduler",
    )
    assert summary is not None
    [merge] = active_merges(world.project)
    assert merge.rule == "identifier:doi" and pre in {merge.primary, *merge.absorbed}
    again = dedup_run(world.project)  # the full reconciler agrees
    assert again.created == [] and again.reverted == []


def test_version_link_conflict(world: NoticeWorld) -> None:
    pre, pre2, held = _ids(world)
    arxiv = StatusScript(
        "arxiv", _answer_by_arxiv({"2301.00001": 2}, linked={"2301.00001": "10.3000/held"})
    )
    _, summary = version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    [event] = _events(world.project, "version.linked")
    assert event.payload["conflicts_with"] == held
    assert summary.conflicts == 1 and summary.linked == 0
    assert aliases(world.project, pre) == Identifiers()
    assert [(c.work_id, c.doi, c.other_work_id) for c in link_conflicts(world.project)] == [
        (pre, "10.3000/held", held)
    ]
    assert active_merges(world.project) == []
    version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    assert len(_events(world.project, "version.linked")) == 1  # the refusal is recorded once


def test_link_changes_no_decision(world: NoticeWorld) -> None:
    pre, pre2, _ = _ids(world)
    before = {k: v.value for k, v in final_outcomes(world.project).items()}
    arxiv = StatusScript(
        "arxiv", _answer_by_arxiv({"2301.00001": 2}, linked={"2301.00001": PUBLISHED})
    )
    version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    assert {k: v.value for k, v in final_outcomes(world.project).items()} == before


def test_link_after_same_cycle_merge_is_not_conflict(world: NoticeWorld) -> None:
    pre, pre2, _ = _ids(world)
    same = record("Preprint of sparse routing", author="Pre Print", year=2023, doi="10.3000/same")
    arxiv = StatusScript(
        "arxiv", _answer_by_arxiv({"2301.00001": 2}, linked={"2301.00001": "10.3000/same"})
    )
    _, summary = version_in_cycle(
        world.project, status_factories(arxiv=arxiv), [pre, pre2], records=[same]
    )
    assert active_merges(world.project)  # the cycle's dedup merged the two records
    [event] = _events(world.project, "version.linked")
    assert event.payload["conflicts_with"] is None
    assert summary.conflicts == 0 and summary.linked == 1


def test_status_hook_tracks_versions_of_the_selected_works(world: NoticeWorld) -> None:
    pre, _, _ = _ids(world)
    arxiv = StatusScript("arxiv", _answer_by_arxiv({"2301.00001": 3, "2301.00002": 1}))
    factories = status_factories(
        arxiv=arxiv, openalex=StatusScript("openalex"), crossref=StatusScript("crossref")
    )
    world.project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    summary = watch_run(
        world.project,
        sources=adapters(ScriptedSource(by_text({"attention": [[]]}))),
        trigger="scheduler",
        after_runs=(make_status_hook(factories),),
    )
    assert summary is not None
    assert [e.payload["work_id"] for e in _events(world.project, "version.observed")] == [pre]


def test_version_events_rebuild_identical(world: NoticeWorld) -> None:
    pre, pre2, _ = _ids(world)
    arxiv = StatusScript(
        "arxiv", _answer_by_arxiv({"2301.00001": 3}, linked={"2301.00001": PUBLISHED})
    )
    version_in_cycle(world.project, status_factories(arxiv=arxiv), [pre, pre2])
    before = world.project.index.state_hash()
    assert world.project.index.rebuild() == before
    assert aliases(world.project, pre) == Identifiers(doi=PUBLISHED)
