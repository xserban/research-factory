"""The PRISMA update flow: what each update of a living review added (Task 5, R-103)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.inbox import ResolveStatus
from factory.services.context import Project
from factory.services.dedup import canonical_works
from factory.services.prisma import prisma_flow, search_report
from factory.services.prisma_update import prisma_update, update_work_ids
from factory.services.screening import decision_events
from factory.services.snapshots import snapshot, snapshot_blob, snapshots
from factory.services.watch import CycleSummary, watch_run
from tests.helpers import SourcesFor, open_session
from tests.living_helpers import agree, filler, screening_watch_setup, start_screening
from tests.watch_helpers import ScriptedSource, adapters, by_text, record

A = record("Alpha methods for sparse graphs", author="Ana Li", year=2021)
B = record("Beta bounds on federated drift", author="Bo Chen", year=2022)
C = record("Gamma routing of experts", author="Cy Dee", year=2023, doi="10.5555/gamma")
C2 = record("Gamma routing of expert models", author="Cy Dee", year=2023, doi="10.5555/gamma")
D = record("Delta kernels for streaming", author="Di Eng", year=2024)
E = record("Epsilon pruning at scale", author="Ed Fox", year=2024)


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    screening_watch_setup(project, agent, human, mock_sources)
    return project


def _cycle(project: Project, records: list[dict[str, Any]]) -> CycleSummary:
    """One watch cycle; the protocol plans the one query `attention`."""
    project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    source = ScriptedSource(by_text({"attention": [records]}))
    summary = watch_run(project, sources=adapters(source), trigger="scheduler")
    assert summary is not None
    return summary


def _two_updates(project: Project, human: Actor) -> None:
    """Cycle 1 (A, B), a snapshot, then cycle 2 (B again, C, a duplicate of C, D, E)."""
    _cycle(project, [A, B])
    snapshot(project, human, trigger="human")
    _cycle(project, [B, C, C2, D, E])


def test_update_flow_counts_only_update_records(ready: Project, human: Actor) -> None:
    _two_updates(ready, human)
    update = prisma_update(ready)
    assert update.identified_databases == {"fake": 5}
    assert sum(update.identified_other.values()) == 0
    assert update.duplicates_removed == 2  # B again, and the second record of C
    assert update.screened == 3
    works, duplicates = update_work_ids(ready, snapshots(ready)[0].cutoff_event, None)
    assert duplicates == 2 and len(works) == 3
    titles = {w.id: w.title for w in canonical_works(ready)}
    assert not {titles[w] for w in works} & {A["title"], B["title"]}
    assert update.provisional and update.pending == 3
    first = update_work_ids(ready, None, snapshots(ready)[0].cutoff_event)
    titles = {w.id: w.title for w in canonical_works(ready)}
    assert {A["title"], B["title"]} <= {titles[w] for w in first[0]} and first[1] == 0


def test_update_flow_identities(ready: Project, agent: Actor, human: Actor) -> None:
    _cycle(ready, filler(10))
    snapshot(ready, human, trigger="human")
    _cycle(ready, [*filler(40, first=10), C, C2, E])
    protocol_id, calibration = start_screening(ready, agent)
    cutoff = snapshots(ready)[0].cutoff_event
    new, _ = update_work_ids(ready, cutoff, None)
    ordinary = [w for w in sorted(new) if w not in calibration]
    agree(ready, agent, ordinary[0], protocol_id, "include")
    agree(ready, agent, ordinary[1], protocol_id, "exclude")
    update = prisma_update(ready)
    identified = sum(update.identified_databases.values()) + sum(update.identified_other.values())
    assert identified - update.duplicates_removed == update.screened == 42
    assert update.excluded == {"EX01": 1} and update.included == 1
    assert update.excluded_total + update.pending + update.included == update.screened
    assert update.provisional is (update.pending > 0)
    # Recomputed from events: the update's works are the canonical works first found after the
    # snapshot, and their outcomes are the cumulative flow's over those works.
    assert len(new) == update.screened
    assert update.total_included == prisma_flow(ready).included == 1
    assert (
        update.full_text.sought + update.full_text.not_sought == update.included == 1
        and not update.full_text.stage_run
    )


def test_duplicate_of_earlier_work_counted_in_update_duplicates(
    ready: Project, human: Actor
) -> None:
    _cycle(ready, [A])
    snapshot(ready, human, trigger="human")
    _cycle(ready, [A])
    update = prisma_update(ready)
    assert update.identified_databases == {"fake": 1}
    assert (update.duplicates_removed, update.screened) == (1, 0)
    assert update.pending == 0 and not update.provisional


def test_previous_included_from_snapshot_blob(ready: Project, agent: Actor, human: Actor) -> None:
    first = _cycle(ready, filler(40))
    protocol_id, calibration = start_screening(ready, agent)
    target = next(w for w in sorted(first.new_work_ids) if w not in calibration)
    agree(ready, agent, target, protocol_id, "include")
    taken = snapshot(ready, human, trigger="human")
    blob = snapshot_blob(ready, taken.snapshot_id)
    assert blob.prisma.included == 1
    _cycle(ready, filler(5, first=40))
    update = prisma_update(ready)
    assert update.previous_included == 1 == update.total_included
    assert update.changed_previous == ()
    assert update.screened == 5
    # An explicit window reads the same update.
    assert prisma_update(ready, since=taken.snapshot_id) == update


def test_changed_previous_lists_works(ready: Project, agent: Actor, human: Actor) -> None:
    first = _cycle(ready, filler(40))
    protocol_id, calibration = start_screening(ready, agent)
    target = next(w for w in sorted(first.new_work_ids) if w not in calibration)
    ids = agree(ready, agent, target, protocol_id, "include")
    snapshot(ready, human, trigger="human")
    _cycle(ready, filler(3, first=40))
    assert decision_events(ready)
    agree(ready, agent, target, protocol_id, "exclude", supersedes=ids)
    update = prisma_update(ready)
    assert update.previous_included == 1 and update.total_included == 0
    assert update.changed_previous == (target,)
    assert update.previous_included + update.included != update.total_included


def test_cumulative_equals_prisma_flow(ready: Project, agent: Actor, human: Actor) -> None:
    _two_updates(ready, human)
    flow = prisma_flow(ready)
    assert len(snapshots(ready)) == 1
    # A window that spans the whole log (until now, from the start) is the cumulative flow.
    whole = prisma_update(ready, since=None, until=None, whole_log=True)
    assert whole.identified_databases == flow.identified_databases
    assert whole.identified_other == flow.identified_other
    assert whole.duplicates_removed == flow.duplicates_removed
    assert (whole.screened, whole.pending, whole.included) == (
        flow.screened,
        flow.pending,
        flow.included,
    )
    assert whole.excluded == flow.excluded and whole.full_text == flow.full_text
    assert whole.previous_included == 0


def test_unknown_snapshot_refused(ready: Project) -> None:
    with pytest.raises(FactoryValidationError) as exc:
        prisma_update(ready, since="snp_00000000000000000000000000")
    assert [i.field for i in exc.value.issues] == ["since"]


def test_search_report_rows_carry_cycle_ids(ready: Project, human: Actor) -> None:
    summary = _cycle(ready, [A, B])
    report = search_report(ready)
    runs = [run for row in report.rows for run in row.runs]
    assert {run.cycle_id for run in runs if run.cycle_id is not None} == {summary.cycle_id}
    assert [run.cycle_id for run in runs].count(summary.cycle_id) == len(summary.run_ids)
    assert any(run.cycle_id is None for run in runs)  # the seed lookups were not cycle runs


@pytest.mark.anyio
async def test_mcp_prisma_update_refused_to_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    screening_watch_setup(project, agent, human, mock_sources)
    from tests.screening_helpers import _draw

    _draw(project)
    agent_args = {"role": "screener", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
    async with open_session(settings, clock, dict(adapters(ScriptedSource(by_text({}))))) as s:
        joined = await s.call("screen_next", project="demo", pass_label="A", **agent_args)
        assert joined["ok"] is True, joined
        refused = await s.call("report_prisma", project="demo", update="last")
    assert refused["ok"] is False
    assert [e["field"] for e in refused["errors"]] == ["session"]


@pytest.mark.anyio
async def test_mcp_prisma_update_for_an_outside_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    screening_watch_setup(project, agent, human, mock_sources)
    _cycle(project, [A, B])
    snapshot(project, human, trigger="human")
    _cycle(project, [C])
    async with open_session(settings, clock, dict(adapters(ScriptedSource(by_text({}))))) as s:
        body = await s.call("report_prisma", project="demo", update="last")
        plain = await s.call("report_prisma", project="demo")
    assert body["ok"] is True, body
    assert body["data"]["update"]["screened"] == 1
    assert "update" not in plain["data"] and "flow" in plain["data"]


def test_closed_update_is_pinned(ready: Project, agent: Actor, human: Actor) -> None:
    """A closed update is served from its snapshot: later decisions and cycles do not move it."""
    _cycle(ready, filler(40))
    protocol_id, calibration = start_screening(ready, agent)
    first = snapshot(ready, human, trigger="human")
    second = _cycle(ready, [*filler(5, first=40), C])
    closed = snapshot(ready, human, trigger="human")
    before = prisma_update(ready, until=closed.snapshot_id)
    assert before.screened == 6 and before.provisional
    pending = sorted(w for w in second.new_work_ids if w not in calibration)
    agree(ready, agent, pending[0], protocol_id, "include")
    agree(ready, agent, pending[1], protocol_id, "exclude")
    _cycle(ready, [C2, *filler(2, first=50)])  # a later cycle merges a record into C
    after = prisma_update(ready, until=closed.snapshot_id)
    assert after.model_dump_json() == before.model_dump_json()
    explicit = prisma_update(ready, since=first.snapshot_id, until=closed.snapshot_id)
    assert explicit == before


def test_changed_previous_for_a_past_window(ready: Project, agent: Actor, human: Actor) -> None:
    first = _cycle(ready, filler(40))
    protocol_id, calibration = start_screening(ready, agent)
    target = next(w for w in sorted(first.new_work_ids) if w not in calibration)
    ids = agree(ready, agent, target, protocol_id, "include")
    snapshot(ready, human, trigger="human")
    _cycle(ready, filler(3, first=40))
    excluded = agree(ready, agent, target, protocol_id, "exclude", supersedes=ids)
    closed = snapshot(ready, human, trigger="human")
    assert prisma_update(ready, until=closed.snapshot_id).changed_previous == (target,)
    agree(ready, agent, target, protocol_id, "include", supersedes=excluded)  # included again
    past = prisma_update(ready, until=closed.snapshot_id)
    assert past.changed_previous == (target,) and past.total_included == 0
    assert prisma_update(ready).changed_previous == (target,)  # the open window sees it now


def test_update_flow_database_precedence(
    ready: Project, human: Actor, other_session_human: Actor
) -> None:
    """A work found by a supplied link and a database search in the update counts under
    databases; a supplied-only work counts under other methods (decision 38 item 6)."""
    from factory.services.protocol import record_deviation
    from tests.inbox_helpers import Keyed, capture, link_item, resolve

    _cycle(ready, [A])
    snapshot(ready, human, trigger="human")
    capture(ready, other_session_human, "10.2000/s1", "10.2000/s2")
    deviation = record_deviation(ready, human, description="Supplied", reason="Colleague.")
    other = link_item(2, title="Quantum annealing for protein folding")
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)], "doi:10.2000/s2": [other]})
    outcomes = resolve(ready, other_session_human, keyed, deviation_id=deviation)
    assert [o.status for o in outcomes] == [ResolveStatus.NEW, ResolveStatus.NEW]
    both = record("Linked paper 1", author="Cy Park", year=2021, doi="10.2000/s1")
    _cycle(ready, [both])
    update = prisma_update(ready)
    assert update.screened == 2
    assert update.identified_other["supplied"] == 1  # the second link only
    assert update.identified_databases == {"fake": 1}
    assert update.duplicates_removed == 0
