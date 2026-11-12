"""`held_matches`: where a not-yet-recorded work would merge, read-only."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from factory.model.work import Work
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.dedup_incremental import dedup_new, held_matches
from factory.services.search import list_works
from factory.sources.registry import SourceFactory
from tests.helpers import _of_type, _work
from tests.screening_helpers import PREPRINT, PUBLISHED, _ingest

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _held(project: Project, record: dict[str, Any]) -> Work:
    return _work(
        record,
        run_id=project.ids.new("run"),
        query_id=project.ids.new("qry"),
        raw_blob="sha256:" + "0" * 64,
    )


def _seed(project: Project, fake_sources: SourcesFor, records: list[dict[str, Any]]) -> list[str]:
    _ingest(project, fake_sources, [records])
    ids = [w.id for w in list_works(project)]
    dedup_new(project, ids)
    return ids


def test_arxiv_id_match(explore_project: Project, fake_sources: SourcesFor) -> None:
    _seed(explore_project, fake_sources, [PREPRINT])
    [stored] = list_works(explore_project)
    held = _held(
        explore_project,
        {"title": "Unrelated wording", "authors": ["Zed Q"], "year": 1999, "arxiv": "2301.00001"},
    )
    assert held_matches(explore_project, [held]) == {held.id: stored.id}


def test_doi_match(explore_project: Project, fake_sources: SourcesFor) -> None:
    _seed(explore_project, fake_sources, [PUBLISHED])
    [stored] = list_works(explore_project)
    held = _held(
        explore_project,
        {"title": "Other title", "authors": ["Zed Q"], "year": 1999, "doi": "10.1000/x"},
    )
    assert held_matches(explore_project, [held]) == {held.id: stored.id}


def test_title_and_year_match(explore_project: Project, fake_sources: SourcesFor) -> None:
    _seed(explore_project, fake_sources, [PUBLISHED])
    [stored] = list_works(explore_project)
    held = _held(explore_project, {**PUBLISHED, "doi": None, "year": 2025})
    assert held_matches(explore_project, [held]) == {held.id: stored.id}


def test_title_outside_year_window_is_not_a_match(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    _seed(explore_project, fake_sources, [PUBLISHED])
    held = _held(explore_project, {**PUBLISHED, "doi": None, "year": 2015})
    assert held_matches(explore_project, [held]) == {}


def test_no_match_and_nothing_written(explore_project: Project, fake_sources: SourcesFor) -> None:
    _seed(explore_project, fake_sources, [PUBLISHED])
    before = len(_of_type(explore_project, "dedup.merged"))
    held = _held(explore_project, {"title": "Quantum gravity", "authors": ["Zed Q"], "year": 2024})
    assert held_matches(explore_project, [held]) == {}
    assert len(_of_type(explore_project, "dedup.merged")) == before


def test_absorbed_work_maps_to_canonical(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    _seed(explore_project, fake_sources, [PUBLISHED, PREPRINT])
    [merge] = active_merges(explore_project)
    [absorbed] = merge.absorbed
    absorbed_work = next(w for w in list_works(explore_project) if w.id == absorbed)
    held = _held(
        explore_project,
        {
            "title": "Different",
            "authors": ["Zed Q"],
            "year": 1999,
            "doi": absorbed_work.identifiers.doi,
            "arxiv": absorbed_work.identifiers.arxiv,
        },
    )
    assert held_matches(explore_project, [held]) == {held.id: merge.primary}
