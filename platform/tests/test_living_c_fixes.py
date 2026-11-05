"""Fix round 1 of living-C: no held-out oracle, batch-local link conflicts, relay convention,
visible status failures, status runs outside shortfalls and last-search time."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.notices import NoticeKind
from factory.model.project import RigorMode
from factory.services.check import _findings_as, agent_check
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run
from factory.services.living_hooks import default_hooks
from factory.services.portfolio import _last_search_at
from factory.services.search import search_counts
from factory.services.trace import agent_trace
from factory.services.watch import watch_run
from tests.helpers import SourcesFor, open_session
from tests.notice_helpers import (
    NoticeWorld,
    StatusScript,
    check_in_cycle,
    crossref_notices,
    dependent_world,
    notice_record,
    numbered_records,
    status_factories,
    version_in_cycle,
)
from tests.test_notices import _kinds
from tests.test_versions import HELD, PRE, PRE2, _answer_by_arxiv, _events, _ids
from tests.watch_helpers import ScriptedSource, adapters, by_text

AGENT = {"role": "watcher", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


@pytest.fixture
def world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    built = dependent_world(project, agent, human, mock_sources, numbered_records(3, no_doi=1))
    work = built.included[1]
    doi = built.doi(work)
    assert doi is not None
    crossref = StatusScript(
        "crossref",
        crossref_notices({doi: [notice_record(doi, NoticeKind.CORRECTION, "10.2000/c")]}),
    )
    check_in_cycle(project, status_factories(crossref=crossref, openalex=StatusScript("openalex")))
    return built


# --- 1. a held-out seed's work reads as any corpus work ---


@pytest.mark.anyio
async def test_notice_list_and_assess_treat_held_out_works_as_any_work(
    world: NoticeWorld,
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = world.included[1]
    source = ScriptedSource(by_text({}))
    async with open_session(settings, clock, dict(adapters(source))) as session:
        plain = await session.call("notice_list", project="demo")
        monkeypatch.setattr(
            "factory.services.seeds.held_out_work_ids", lambda _p: frozenset({held})
        )
        marked = await session.call("notice_list", project="demo")
        notice = marked["data"]["notices"][0]["notice_id"]
        assessed = await session.call(
            "notice_assess",
            project="demo",
            notice_id=notice,
            decision="no-effect",
            rationale="typo only",
        )
    assert plain["ok"] is True and plain["data"]["count"] == 1
    assert marked == plain  # nothing in the listing tells a seed's work apart
    assert assessed["ok"] is True, assessed


def test_check_and_trace_treat_held_out_works_as_any_work(
    world: NoticeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = world.included[1]
    project = world.project
    before_check = [f.model_dump() for f in agent_check(project).findings]
    before_trace = _kinds(agent_trace(project, held, direction="forward"))
    monkeypatch.setattr("factory.services.seeds.held_out_work_ids", lambda _p: frozenset({held}))
    assert [f.model_dump() for f in agent_check(project).findings] == before_check
    assert _kinds(agent_trace(project, held, direction="forward")) == before_trace
    assert any(f["code"] == "notice-unassessed" for f in before_check)
    assert any(kind == "notice" for kind, _ in before_trace)


# --- 2. a link is checked against the batch as well as the index ---


def test_two_works_linked_to_one_doi_in_one_batch_conflict(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = dependent_world(project, agent, human, mock_sources, [PRE, PRE2, HELD])
    pre, pre2, _ = _ids(world)
    arxiv = StatusScript(
        "arxiv",
        _answer_by_arxiv(
            {"2301.00001": 1, "2301.00002": 1},
            linked={"2301.00001": "10.3000/shared", "2301.00002": "10.3000/shared"},
        ),
    )
    _, summary = version_in_cycle(project, status_factories(arxiv=arxiv), [pre, pre2])
    events = _events(project, "version.linked")
    assert len(events) == 2 and summary.linked == 1 and summary.conflicts == 1
    refused = [e for e in events if e.payload["conflicts_with"] is not None]
    [applied] = [e for e in events if e.payload["conflicts_with"] is None]
    assert refused[0].payload["conflicts_with"] == applied.payload["work_id"]
    # Two distinct works are never merged by the shared identifier.
    dedup_run(project)
    assert active_merges(project) == []


# --- 3. the relay follows decision 37 item 6 ---


@pytest.mark.anyio
async def test_relayed_assessment_records_channel_and_bars_the_session(
    world: NoticeWorld, settings: Settings, clock: FixedClock
) -> None:
    source = ScriptedSource(by_text({}))
    async with open_session(settings, clock, dict(adapters(source))) as session:
        listed = await session.call("notice_list", project="demo")
        notice = listed["data"]["notices"][0]["notice_id"]
        done = await session.call(
            "notice_assess",
            project="demo",
            notice_id=notice,
            decision="no-effect",
            rationale="typo only",
        )
        assert done["ok"] is True, done
        joined = await session.call("screen_next", project="demo", pass_label="A", **AGENT)
    assert joined["ok"] is False and joined["errors"][0]["field"] == "session"
    [assessed] = [
        e
        for e in read_all(world.project.paths.events_dir, world.project.catalog)
        if e.type == "notice.assessed"
    ]
    assert assessed.payload["channel"] == "mcp"


# --- 4. status failures are visible, per source ---


def _codes(project: Project) -> dict[str, Any]:
    return {f.code: f for f in _findings_as(project, RigorMode.PILOT)}


def test_failed_source_is_not_hidden_by_another_sources_success(world: NoticeWorld) -> None:
    project = world.project
    crossref = StatusScript("crossref")
    crossref.fail = True
    factories = status_factories(crossref=crossref, openalex=StatusScript("openalex"))
    cycle, summary = check_in_cycle(project, factories, budget=2)
    assert summary.failed == 1
    finding = _codes(project)["status-lookup-failed"]
    assert finding.refs == [summary.run_ids[-1]] or set(finding.refs) <= set(summary.run_ids)
    assert cycle.status.value == "complete"  # a status failure never fails the cycle
    # The next sweep takes the same two works again: OpenAlex's success did not mark them checked.
    crossref.queried.clear()
    check_in_cycle(project, factories, budget=2)
    first_two = {world.doi(w) for w in world.included if world.doi(w)}
    asked = {d for q in crossref.queried for d in q.replace("updates:", "").split(",")}
    assert asked and asked <= first_two
    # Coverage age fires although OpenAlex answers every cycle.
    for _ in range(3):
        check_in_cycle(project, factories)
    assert "notice-coverage-age" in _codes(project)
    # Recovery closes both findings.
    crossref.fail = False
    check_in_cycle(project, factories)
    codes = _codes(project)
    assert "status-lookup-failed" not in codes and "notice-coverage-age" not in codes


def test_a_crashing_adapter_keeps_its_run_id(world: NoticeWorld) -> None:
    crossref = StatusScript("crossref")
    crossref.raises = True
    factories = status_factories(crossref=crossref, openalex=StatusScript("openalex"))
    cycle, summary = check_in_cycle(world.project, factories)
    assert summary.failed >= 1 and len(summary.run_ids) >= 2  # the crashed run is named
    finished = [
        e
        for e in read_all(world.project.paths.events_dir, world.project.catalog)
        if e.type == "watch.cycle_finished" and e.refs[0] == cycle.cycle_id
    ]
    assert set(summary.run_ids) <= set(finished[0].payload["status_run_ids"])
    assert "status-lookup-failed" in _codes(world.project)


# --- 5. minors ---


def test_status_runs_stay_out_of_shortfalls_and_last_search(world: NoticeWorld) -> None:
    from sqlalchemy import text

    from factory.clock import parse_ts

    project = world.project
    openalex = StatusScript("openalex")
    openalex.reported = 9  # fewer records than reported: a shortfall if it were a search
    openalex.tick = lambda: project.clock.advance(timedelta(hours=1))  # type: ignore[attr-defined]
    check_in_cycle(project, status_factories(openalex=openalex, crossref=StatusScript("crossref")))
    assert openalex.queried
    assert search_counts(project).shortfalls == []
    with project.index.connect() as conn:
        latest = conn.execute(
            text(
                "SELECT MAX(r.finished_at) FROM runs r JOIN queries q ON q.query_id = r.query_id "
                "WHERE q.purpose = 'search'"
            )
        ).scalar_one()
        last_status = conn.execute(
            text(
                "SELECT MAX(r.finished_at) FROM runs r JOIN queries q ON q.query_id = r.query_id "
                "WHERE q.purpose = 'status'"
            )
        ).scalar_one()
    assert last_status is not None and str(last_status) > str(latest)  # status ran last
    assert _last_search_at(project) == parse_ts(str(latest))


def test_default_hooks_use_the_injected_adapters(world: NoticeWorld) -> None:
    openalex = StatusScript("openalex")
    crossref = StatusScript("crossref")
    hooks = default_hooks(status_factories(openalex=openalex, crossref=crossref))
    world.project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    summary = watch_run(
        world.project,
        sources=adapters(ScriptedSource(by_text({"attention": [[]]}))),
        trigger="scheduler",
        after_runs=hooks,
    )
    assert summary is not None and openalex.queried and crossref.queried
