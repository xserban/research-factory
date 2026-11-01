import threading
from collections.abc import Callable, Mapping
from typing import Any

import pydantic
import pytest
from sqlalchemy import text

from factory.clock import SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.dedup import DedupMerged, DedupReverted
from factory.model.search import QueryKind, QuerySpec
from factory.services.context import Project, open_project
from factory.services.dedup import (
    active_merges,
    canonical_works,
    dedup_run,
    revert_merge,
)
from factory.services.project import project_status
from factory.services.search import list_works, register_query, run_query
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION

SourcesFor = Callable[..., Mapping[str, SourceFactory]]

# The same paper, published and as a preprint: one cascade merge (title + first author + year).
PUBLISHED: dict[str, Any] = {
    "title": "Linear attention in transformers",
    "authors": ["Ada Zhou"],
    "year": 2024,
    "doi": "10.1000/x",
    "type": "journal-article",
}
PREPRINT: dict[str, Any] = {
    "title": "Linear attention in transformers",
    "authors": ["Ada Zhou"],
    "year": 2024,
    "arxiv": "2301.00001",
    "type": "preprint",
}
# A third record of the same paper, under an OpenAlex id only.
OPENALEX_COPY: dict[str, Any] = {
    "title": "Linear attention in transformers",
    "authors": ["Ada Zhou"],
    "year": 2024,
    "openalex": "W2001",
}


def _ingest(project: Project, fake_sources: SourcesFor, pages: list[list[dict[str, Any]]]) -> None:
    sources = fake_sources(pages=pages)
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="linear attention")
    qid = register_query(project, project.human_actor(), spec, sources=sources)
    run_query(project, qid, sources=sources)


def _of_type(project: Project, name: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == name]


def _work_id(project: Project, *, doi: str | None = None, arxiv: str | None = None) -> str:
    for work in list_works(project):
        if doi is not None and work.identifiers.doi == doi:
            return work.id
        if arxiv is not None and work.identifiers.arxiv == arxiv:
            return work.id
    raise AssertionError("no such work")


def test_cross_identifier_duplicates_become_one_recorded_merge(
    project: Project, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    summary = dedup_run(project)
    assert len(summary.created) == 1 and summary.reverted == []
    assert (summary.works, summary.canonical) == (2, 1)
    assert summary.records == 2

    [merge] = active_merges(project)
    assert merge.merge_id == summary.created[0]
    assert merge.primary == _work_id(project, doi="10.1000/x")
    assert merge.absorbed == (_work_id(project, arxiv="2301.00001"),)
    assert merge.rule.startswith("title+author")
    assert merge.records == 2
    [event] = _of_type(project, "dedup.merged")
    assert event.refs == (merge.primary, *merge.absorbed)


def test_rerun_is_idempotent(project: Project, fake_sources: SourcesFor) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    first = dedup_run(project)
    second = dedup_run(project)
    assert len(first.created) == 1
    assert second.created == [] and second.reverted == [] and second.unchanged == 1
    assert len(_of_type(project, "dedup.merged")) == 1
    assert _of_type(project, "dedup.reverted") == []


def test_new_record_joining_a_group_supersedes_the_merge(
    project: Project, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    first = dedup_run(project)
    _ingest(project, fake_sources, [[OPENALEX_COPY]])
    second = dedup_run(project)

    assert second.reverted == first.created
    assert len(second.created) == 1
    [revert] = _of_type(project, "dedup.reverted")
    assert revert.payload["merge_id"] == first.created[0]
    assert revert.payload["manual"] is False
    assert revert.payload["reason"] == f"superseded by {second.created[0]}"
    assert revert.input_blob is None

    [merge] = active_merges(project)
    assert merge.merge_id == second.created[0]
    assert len(merge.absorbed) == 2
    assert {merge.primary, *merge.absorbed} == {w.id for w in list_works(project)}
    assert len(canonical_works(project)) == 1


def test_manual_revert_is_not_reapplied(
    project: Project, agent: Actor, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    mid = dedup_run(project).created[0]
    revert_merge(project, agent, mid, "different papers")

    [revert] = _of_type(project, "dedup.reverted")
    assert revert.payload["manual"] is True and revert.input_blob is not None

    again = dedup_run(project)
    assert again.created == [] and again.reverted == [] and again.unchanged == 0
    assert len(canonical_works(project)) == 2
    assert project_status(project).merges_active == 0


def test_manual_revert_of_a_three_way_merge_keeps_every_pair_apart(
    project: Project, human: Actor, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT, OPENALEX_COPY]])
    [mid] = dedup_run(project).created
    [merge] = active_merges(project)
    assert len(merge.absorbed) == 2

    revert_merge(project, human, mid, "three different papers")
    again = dedup_run(project)

    assert again.created == [] and active_merges(project) == []
    assert len(canonical_works(project)) == 3
    _, blocked = _dedup_rows(project)
    assert len(blocked) == 3  # every pair among the three members, not just primary-absorbed


def test_revert_validation(project: Project, human: Actor, fake_sources: SourcesFor) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    mid = dedup_run(project).created[0]

    with pytest.raises(FactoryValidationError) as unknown:
        revert_merge(project, human, f"mrg_{SESSION}", "different papers")
    assert [issue.field for issue in unknown.value.issues] == ["merge_id"]

    with pytest.raises(FactoryValidationError) as blank:
        revert_merge(project, human, mid, "   ")
    assert [issue.field for issue in blank.value.issues] == ["reason"]

    with pytest.raises(FactoryValidationError) as both:
        revert_merge(project, human, f"mrg_{SESSION}", "")
    assert [issue.field for issue in both.value.issues] == ["merge_id", "reason"]

    revert_merge(project, human, mid, "  different papers  ")
    [revert] = _of_type(project, "dedup.reverted")
    assert revert.input_blob is None
    assert revert.payload["reason"] == "different papers"

    with pytest.raises(FactoryValidationError) as twice:
        revert_merge(project, human, mid, "again")
    assert [issue.field for issue in twice.value.issues] == ["merge_id"]


def test_status_counts_active_merges(
    project: Project, human: Actor, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    assert project_status(project).merges_active == 0
    mid = dedup_run(project).created[0]
    assert project_status(project).merges_active == 1
    revert_merge(project, human, mid, "different papers")
    assert project_status(project).merges_active == 0


def test_dedup_rebuild_equals_incremental(
    project: Project, agent: Actor, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    dedup_run(project)
    _ingest(project, fake_sources, [[OPENALEX_COPY]])
    dedup_run(project)
    [merge] = active_merges(project)
    revert_merge(project, agent, merge.merge_id, "different papers")
    dedup_run(project)

    assert project.index.state_hash() == project.index.rebuild()


def test_merge_no_longer_produced_is_reverted(project: Project, fake_sources: SourcesFor) -> None:
    # Three unrelated records: the cascade produces no merge, so a merge recorded by hand is stale.
    sources = fake_sources()
    qid = register_query(
        project,
        project.human_actor(),
        QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="attention"),
        sources=sources,
    )
    run_query(project, qid, sources=sources)
    works = list_works(project)
    first = next(w.id for w in works if w.title == "Linear attention")
    second = next(w.id for w in works if w.title == "Sparse attention")
    merge_id = project.ids.new("mrg")
    project.record(
        [
            project.events.make(
                "dedup.merged",
                DedupMerged(
                    merge_id=merge_id,
                    primary=first,
                    absorbed=(second,),
                    rule="identifier:doi",
                    records=2,
                ),
                project.system_actor(),
                refs=(first, second),
            )
        ]
    )

    summary = dedup_run(project)
    assert summary.created == [] and summary.reverted == [merge_id]
    [revert] = [e for e in _of_type(project, "dedup.reverted") if e.payload["merge_id"] == merge_id]
    assert revert.payload["reason"] == "no longer matched"
    assert active_merges(project) == []


def test_canonical_merges_the_members_that_exist(
    project: Project, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    works = list_works(project)
    other = next(w.id for w in works if w.title == "Linear attention in transformers")
    missing = "rf:missing-00000000"
    project.record(
        [
            project.events.make(
                "dedup.merged",
                DedupMerged(
                    merge_id=project.ids.new("mrg"),
                    primary=other,
                    absorbed=(missing,),
                    rule="identifier:doi",
                    records=2,
                ),
                project.system_actor(),
                refs=(other, missing),
            )
        ]
    )
    assert len(canonical_works(project)) == 2


def _dedup_rows(project: Project) -> tuple[list[Any], list[Any]]:
    with project.index.connect() as conn:
        merges = conn.execute(text("SELECT * FROM merges ORDER BY merge_id")).all()
        blocked = conn.execute(text("SELECT * FROM blocked_pairs ORDER BY a, b")).all()
    return [tuple(row) for row in merges], [tuple(row) for row in blocked]


def test_projection_ignores_reverts_of_unknown_or_reverted_merges(
    project: Project, human: Actor, fake_sources: SourcesFor
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    mid = dedup_run(project).created[0]
    before = _dedup_rows(project)
    unknown = DedupReverted(merge_id=f"mrg_{SESSION}", reason="stale", manual=True)
    project.record(
        [project.events.make("dedup.reverted", unknown, project.system_actor(), refs=(mid,))]
    )
    assert _dedup_rows(project) == before

    revert_merge(project, human, mid, "different papers")
    after = _dedup_rows(project)
    assert len(after[1]) == 1  # the manual revert blocked the one pair
    repeat = DedupReverted(merge_id=mid, reason="again", manual=True)
    project.record(
        [project.events.make("dedup.reverted", repeat, project.system_actor(), refs=(mid,))]
    )
    assert _dedup_rows(project) == after


def test_merge_payloads_are_validated() -> None:
    merge = {"merge_id": f"mrg_{SESSION}", "primary": "rf:a-00000000", "rule": "x", "records": 2}
    with pytest.raises(pydantic.ValidationError):
        DedupMerged.model_validate({**merge, "absorbed": ["rf:c-00000000", "rf:b-00000000"]})
    with pytest.raises(pydantic.ValidationError):
        DedupMerged.model_validate({**merge, "absorbed": ["rf:a-00000000"]})
    with pytest.raises(pydantic.ValidationError):
        DedupReverted(merge_id=f"mrg_{SESSION}", reason="  ", manual=True)


def test_concurrent_dedup_runs_record_one_merge(
    project: Project, fake_sources: SourcesFor, settings: Settings
) -> None:
    _ingest(project, fake_sources, [[PUBLISHED, PREPRINT]])
    barrier = threading.Barrier(2)
    created: list[list[str]] = []
    lock = threading.Lock()

    def run() -> None:
        opened = open_project(settings, "demo", session=SESSION, clock=SystemClock())
        barrier.wait()
        summary = dedup_run(opened)
        with lock:
            created.append(summary.created)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(len(ids) for ids in created) == [0, 1]
    assert len(_of_type(project, "dedup.merged")) == 1
