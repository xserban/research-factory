"""The updates view: baseline, additions with their route, growth and the watch (read-only)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from factory.events.envelope import Actor
from factory.model.inbox import ResolveStatus
from factory.services.context import Project
from factory.services.snapshots import snapshot, snapshots
from factory.services.updates import updates_view
from factory.services.watch import watch_run
from tests.helpers import SourcesFor
from tests.living_helpers import screening_watch_setup
from tests.watch_helpers import ScriptedSource, adapters, by_text, record

A = record("Alpha methods for sparse graphs", author="Ana Li", year=2021)
B = record("Beta bounds on federated drift", author="Bo Chen", year=2022)
D = record("Delta kernels for streaming", author="Di Eng", year=2024)


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    screening_watch_setup(project, agent, human, mock_sources)
    return project


def _cycle(project: Project, records: list[dict[str, Any]]) -> None:
    project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    source = ScriptedSource(by_text({"attention": [records]}))
    assert watch_run(project, sources=adapters(source), trigger="scheduler") is not None


def test_no_snapshot_has_no_baseline_and_no_additions(ready: Project) -> None:
    view = updates_view(ready)
    assert view.baseline is None and view.open_period is None
    assert view.additions == () and view.growth == ()
    assert view.watch.has_plan


def test_watch_work_after_snapshot_is_listed_before_is_not(ready: Project, human: Actor) -> None:
    _cycle(ready, [A])
    snapshot(ready, human, trigger="human")
    _cycle(ready, [D])
    view = updates_view(ready)
    assert view.baseline is not None
    assert view.baseline.snapshot_id == snapshots(ready)[0].snapshot_id
    titles = [r.title for r in view.additions]
    assert titles == [D["title"]]
    assert view.additions[0].route == "watch"
    assert view.open_period is not None and view.open_period.new_works == 1


def test_supplied_work_after_snapshot_has_route_inbox(
    ready: Project, human: Actor, other_session_human: Actor
) -> None:
    from factory.services.protocol import record_deviation
    from tests.inbox_helpers import Keyed, capture, link_item, resolve

    _cycle(ready, [A])
    snapshot(ready, human, trigger="human")
    capture(ready, other_session_human, "10.2000/s1", note="from a colleague")
    deviation = record_deviation(ready, human, description="Supplied", reason="Colleague.")
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})
    outcomes = resolve(ready, other_session_human, keyed, deviation_id=deviation)
    assert [o.status for o in outcomes] == [ResolveStatus.NEW]
    view = updates_view(ready)
    assert len(view.additions) == 1
    row = view.additions[0]
    assert row.route == "inbox" and row.note == "from a colleague"
    assert A["title"] not in [r.title for r in view.additions]


def test_growth_has_one_point_per_snapshot(ready: Project, human: Actor) -> None:
    _cycle(ready, [A])
    snapshot(ready, human, trigger="human")
    _cycle(ready, [B])
    snapshot(ready, human, trigger="human")
    view = updates_view(ready)
    assert [g.snapshot_id for g in view.growth] == [s.snapshot_id for s in snapshots(ready)]
    assert view.growth[0].identified is None or view.growth[0].identified >= 0
    assert view.growth[1].identified == 1
