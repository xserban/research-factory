"""Notice observation in the cycle: dependents, budget and rotation, identity, rebuild."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.notices import NoticeKind
from factory.model.work import Identifiers
from factory.services.context import Project
from factory.services.living_hooks import make_status_hook
from factory.services.notices import dependent_works
from factory.services.watch import watch_run
from factory.sources.base import StatusRecord
from tests.helpers import SourcesFor
from tests.notice_helpers import (
    NoticeWorld,
    StatusScript,
    check_in_cycle,
    crossref_notices,
    dependent_world,
    ids_in,
    notice_record,
    numbered_records,
    status_factories,
)
from tests.watch_helpers import ScriptedSource, adapters, by_text


def _observed(project: Project) -> list[dict[str, object]]:
    return [
        {**e.payload, "_refs": e.refs}
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "notice.observed"
    ]


@pytest.fixture
def world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    return dependent_world(project, agent, human, mock_sources, numbered_records(5))


def test_dependents_are_the_included_works(world: NoticeWorld) -> None:
    assert dependent_works(world.project) == world.included


def test_retraction_observed_once(world: NoticeWorld) -> None:
    work = world.included[0]
    doi = world.doi(work)
    assert doi is not None
    crossref = StatusScript(
        "crossref",
        crossref_notices(
            {doi: [notice_record(doi, notice_doi="10.2000/ret1", when=date(2024, 1, 2))]}
        ),
    )
    factories = status_factories(crossref=crossref, openalex=StatusScript("openalex"))
    cycle, summary = check_in_cycle(world.project, factories)
    [event] = _observed(world.project)
    assert summary.new_notices == 1 and summary.checked == 5
    assert event["work_id"] == work and event["kind"] == "retraction"
    assert event["notice_doi"] == "10.2000/ret1" and event["notice_date"] == "2024-01-02"
    assert event["source"] == "crossref" and str(event["notice_id"]).startswith("ntc_")
    assert str(event["run_id"]) in summary.run_ids and event["raw_blob"]
    assert set(summary.run_ids) <= set(
        next(
            e.payload["status_run_ids"]
            for e in read_all(world.project.paths.events_dir, world.project.catalog)
            if e.type == "watch.cycle_finished" and e.refs[0] == cycle.cycle_id
        )
    )

    check_in_cycle(world.project, factories)  # the same notice again
    assert len(_observed(world.project)) == 1


def test_openalex_only_retraction_has_no_date(world: NoticeWorld) -> None:
    work = world.included[1]
    doi = world.doi(work)
    assert doi is not None

    def answer(spec):  # type: ignore[no-untyped-def]
        return [
            StatusRecord(
                target=Identifiers(doi=doi), kind="notice", notice_kind=NoticeKind.RETRACTION
            )
            for d in ids_in(spec)
            if d == doi
        ]

    factories = status_factories(openalex=StatusScript("openalex", answer))
    check_in_cycle(world.project, factories, notice_sources=("openalex",))
    [event] = _observed(world.project)
    assert event["source"] == "openalex" and event["work_id"] == work
    assert event["notice_doi"] is None and event["notice_date"] is None


def test_budget_limits_and_rotates(world: NoticeWorld) -> None:
    openalex = StatusScript("openalex")
    factories = status_factories(crossref=StatusScript("crossref"), openalex=openalex)
    by_doi = {world.doi(w): w for w in world.included}
    rounds: list[list[str]] = []
    for _ in range(3):
        openalex.queried.clear()
        _, summary = check_in_cycle(world.project, factories, budget=2)
        assert summary.checked == 2
        rounds.append(sorted(by_doi[d] for q in openalex.queried for d in ids_in_text(q)))
    ordered = world.included
    assert rounds[0] == ordered[0:2] and rounds[1] == ordered[2:4]
    # Third cycle: the never-checked work first, then the least recently checked (ties by id).
    assert rounds[2] == sorted([ordered[4], ordered[0]])


def ids_in_text(text: str) -> list[str]:
    from factory.model.search import QueryKind, QuerySpec

    return ids_in(QuerySpec(source="openalex", kind=QueryKind.FILTER, text=text))


def test_never_checked_first(world: NoticeWorld) -> None:
    openalex = StatusScript("openalex")
    factories = status_factories(crossref=StatusScript("crossref"), openalex=openalex)
    check_in_cycle(world.project, factories, budget=3)
    first_round = {d for q in openalex.queried for d in ids_in_text(q)}
    assert len(first_round) == 3
    openalex.queried.clear()
    check_in_cycle(world.project, factories, budget=3)
    second = {d for q in openalex.queried for d in ids_in_text(q)}
    never = {world.doi(w) for w in world.included} - first_round
    assert never <= second  # both never-checked works are taken before any re-check


def test_no_doi_listed_unchecked_crossref(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = dependent_world(project, agent, human, mock_sources, numbered_records(3, no_doi=1))
    openalex = StatusScript("openalex")
    crossref = StatusScript("crossref")
    _, summary = check_in_cycle(
        world.project, status_factories(openalex=openalex, crossref=crossref)
    )
    no_doi = world.by_title["Dependent study 0 of gating"]
    assert summary.unchecked_crossref == (no_doi,)
    assert summary.checked == 3
    # Looked up in OpenAlex by its OpenAlex id, never in Crossref.
    assert any("W700" in q for q in openalex.queried)
    assert not any("W700" in q for q in crossref.queried)


def test_failed_status_run_does_not_count_as_checked(world: NoticeWorld) -> None:
    openalex = StatusScript("openalex")
    openalex.fail = True
    factories = status_factories(openalex=openalex, crossref=StatusScript("crossref"))
    check_in_cycle(world.project, factories, budget=2, notice_sources=("openalex",))
    openalex.fail = False
    openalex.queried.clear()
    check_in_cycle(world.project, factories, budget=2, notice_sources=("openalex",))
    # The same two works are tried again: the failed run did not mark them checked.
    again = sorted(d for q in openalex.queried for d in ids_in_text(q))
    assert again == sorted(world.doi(w) or "" for w in world.included[:2])


def test_notice_events_rebuild_identical(world: NoticeWorld) -> None:
    work = world.included[2]
    doi = world.doi(work)
    assert doi is not None
    crossref = StatusScript(
        "crossref",
        crossref_notices({doi: [notice_record(doi, NoticeKind.CORRECTION, "10.2000/c")]}),
    )
    check_in_cycle(
        world.project, status_factories(crossref=crossref, openalex=StatusScript("openalex"))
    )
    before = world.project.index.state_hash()
    assert world.project.index.rebuild() == before


def test_status_hook_runs_in_the_cycle_and_names_its_runs(world: NoticeWorld) -> None:
    factories = status_factories(
        crossref=StatusScript("crossref"), openalex=StatusScript("openalex")
    )
    world.project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    source = ScriptedSource(by_text({"attention": [[]]}))
    summary = watch_run(
        world.project,
        sources=adapters(source),
        trigger="scheduler",
        after_runs=(make_status_hook(factories),),
    )
    assert summary is not None
    [finished] = [
        e
        for e in read_all(world.project.paths.events_dir, world.project.catalog)
        if e.type == "watch.cycle_finished" and e.refs[0] == summary.cycle_id
    ]
    # OpenAlex and Crossref notice batches, then the OpenAlex version lookup (no arxiv adapter).
    assert len(finished.payload["status_run_ids"]) == 3
    assert summary.status.value == "complete"
