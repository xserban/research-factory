"""Incremental deduplication: same rules and events as `dedup_run`, reading by indexed keys."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run, revert_merge
from factory.services.dedup_incremental import DEDUP_BATCH, considered_works, dedup_new
from factory.services.search import list_works
from factory.sources.registry import SourceFactory
from tests.test_dedup_service import OPENALEX_COPY, PREPRINT, PUBLISHED, _ingest, _of_type

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _ingest_new(
    project: Project, fake_sources: SourcesFor, records: list[dict[str, Any]]
) -> list[str]:
    """Ingest one page and return the ids of the works that were not in the corpus before."""
    before = {w.id for w in list_works(project)}
    _ingest(project, fake_sources, [records])
    return [w.id for w in list_works(project) if w.id not in before]


def _event_count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def test_new_doi_duplicate_merges(explore_project: Project, fake_sources: SourcesFor) -> None:
    first = {"title": "Sparse routing for experts", "authors": ["Ana Li"], "year": 2024}
    second = {
        "title": "A different title entirely",
        "authors": ["Bo Chen"],
        "year": 2021,
        "doi": "10.1000/same",
    }
    third = {**first, "doi": "10.1000/same", "title": "Sparse routing for experts, revisited"}
    ids = _ingest_new(explore_project, fake_sources, [{**second}])
    assert dedup_new(explore_project, ids).created == []
    ids = _ingest_new(explore_project, fake_sources, [third])
    summary = dedup_new(explore_project, ids)
    [merge] = active_merges(explore_project)
    assert summary.created == [merge.merge_id]
    assert merge.rule == "identifier:doi"
    [event] = _of_type(explore_project, "dedup.merged")
    assert event.refs == (merge.primary, *merge.absorbed)
    assert event.actor.kind == "system"
    # The full reconciler agrees with it.
    again = dedup_run(explore_project)
    assert again.created == [] and again.reverted == []


def test_title_bucket_merge_within_year_window(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    older = {**PUBLISHED, "year": 2023}
    ids = _ingest_new(explore_project, fake_sources, [older])
    dedup_new(explore_project, ids)
    ids = _ingest_new(explore_project, fake_sources, [PREPRINT])  # 2024: one year apart
    summary = dedup_new(explore_project, ids)
    assert len(summary.created) == 1
    [merge] = active_merges(explore_project)
    assert merge.rule.startswith("title+author") and merge.records == 2

    far = {**PREPRINT, "arxiv": "2301.00002", "year": 2027}
    ids = _ingest_new(explore_project, fake_sources, [far])
    assert dedup_new(explore_project, ids).created == []


def test_new_record_joining_a_group_supersedes_the_merge(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    ids = _ingest_new(explore_project, fake_sources, [PUBLISHED, PREPRINT])
    first = dedup_new(explore_project, ids)
    ids = _ingest_new(explore_project, fake_sources, [OPENALEX_COPY])
    second = dedup_new(explore_project, ids)
    assert second.reverted == first.created and len(second.created) == 1
    [revert] = _of_type(explore_project, "dedup.reverted")
    assert revert.payload["manual"] is False
    assert dedup_run(explore_project).created == []


def test_blocked_pair_stays_apart(
    explore_project: Project, human: Actor, fake_sources: SourcesFor
) -> None:
    ids = _ingest_new(explore_project, fake_sources, [PUBLISHED, PREPRINT])
    [mid] = dedup_new(explore_project, ids).created
    revert_merge(explore_project, human, mid, "different papers")
    [published, preprint] = sorted(ids)
    ids = _ingest_new(explore_project, fake_sources, [OPENALEX_COPY])
    dedup_new(explore_project, ids)
    for merge in active_merges(explore_project):
        assert not {published, preprint} <= {merge.primary, *merge.absorbed}
    before = _event_count(explore_project)
    dedup_run(explore_project)
    assert _event_count(explore_project) == before


def test_idempotent_for_known_ids(explore_project: Project, fake_sources: SourcesFor) -> None:
    ids = _ingest_new(explore_project, fake_sources, [PUBLISHED, PREPRINT])
    dedup_new(explore_project, ids)
    before = _event_count(explore_project)
    again = dedup_new(explore_project, ids)
    assert again.created == [] and again.reverted == [] and again.unchanged == 1
    assert _event_count(explore_project) == before
    assert dedup_new(explore_project, []).works == 0
    assert dedup_new(explore_project, ["wrk_missing"]).works == 0
    assert _event_count(explore_project) == before


def test_considered_works_are_new_plus_candidates(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    other = {"title": "Unrelated graph theory", "authors": ["Cy Dee"], "year": 2010}
    _ingest(explore_project, fake_sources, [[PUBLISHED, other]])
    ids = _ingest_new(explore_project, fake_sources, [PREPRINT])
    considered = {w.id for w in considered_works(explore_project, ids)}
    published = next(w.id for w in list_works(explore_project) if w.identifiers.doi)
    assert considered == {*ids, published}


def test_reads_bounded_by_batch(
    explore_project: Project, fake_sources: SourcesFor, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _ingest_new(explore_project, fake_sources, [PUBLISHED])
    dedup_new(explore_project, ids)
    ids = _ingest_new(explore_project, fake_sources, [PREPRINT])

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("loaded the whole corpus")

    monkeypatch.setattr("factory.services.search.list_works", forbidden)
    monkeypatch.setattr("factory.services.dedup.list_works", forbidden)
    monkeypatch.setattr("factory.services.dedup.canonical_works", forbidden)
    monkeypatch.setattr("factory.services.dedup_incremental.list_works", forbidden, raising=False)
    assert len(dedup_new(explore_project, ids).created) == 1
    assert DEDUP_BATCH == 2_000


# --- the property: incremental runs, then the full reconciler, write nothing further. ---

_TITLES = (
    "Linear attention in transformers",
    "Sparse routing for expert models",
    "Graph neural networks for molecules",
    "Federated learning under drift",
    "Attention is not explanation",
)
_SURNAMES = ("Zhou", "Li", "Okafor", "Rossi")


def _record(rng: random.Random) -> dict[str, Any]:
    title = rng.choice(_TITLES)
    if rng.random() < 0.3:
        title = title + rng.choice((" revisited", "", ": a study"))
    if rng.random() < 0.3:
        title = title.upper()
    record: dict[str, Any] = {
        "title": title,
        "authors": [f"Ada {rng.choice(_SURNAMES)}"],
        "year": rng.choice((2022, 2023, 2024, 2024)),
    }
    if rng.random() < 0.5:
        record["doi"] = f"10.1000/d{rng.randrange(5)}"
    if rng.random() < 0.3:
        record["arxiv"] = f"2301.0000{rng.randrange(4)}"
    if rng.random() < 0.3:
        record["openalex"] = f"W{rng.randrange(6)}"
    return record


@pytest.mark.parametrize("seed", range(30))
def test_incremental_then_full_writes_nothing(
    seed: int, explore_project: Project, fake_sources: SourcesFor
) -> None:
    rng = random.Random(seed)
    for _ in range(3):  # three arrival batches
        batch = [_record(rng) for _ in range(rng.randrange(1, 9))]
        ids = _ingest_new(explore_project, fake_sources, batch)
        dedup_new(explore_project, ids)
    before = _event_count(explore_project)
    full = dedup_run(explore_project)
    assert full.created == [] and full.reverted == []
    assert _event_count(explore_project) == before
