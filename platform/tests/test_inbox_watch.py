"""The watch route in the candidate inbox: a computed view of pending works (living-B Task 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.inbox import ResolveStatus
from factory.model.screening import PassLabel
from factory.services.calibration import calibration_items, draw_calibration
from factory.services.context import Project
from factory.services.inbox_watch import InboxEntry, inbox_entries
from factory.services.protocol import current_protocol, record_deviation
from factory.services.screening import open_pass, screen_next
from factory.services.watch import watch_run
from tests.helpers import SourcesFor
from tests.inbox_helpers import Keyed, capture, link_item, resolve
from tests.screening_helpers import decide
from tests.watch_helpers import ScriptedSource, adapters, by_text, record, watch_ready

A = [record("Alpha methods for sparse graphs", author="Ana Li", year=2021)]
B = [record("Beta bounds on federated drift", author="Bo Chen", year=2022)]


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    watch_ready(project, agent, human, mock_sources)
    return project


def _cycle(project: Project, extra: int = 0) -> tuple[str, tuple[str, ...]]:
    more = [
        record(f"Filler study {k} of drift", author=f"Fil {k}", year=2020) for k in range(extra)
    ]
    source = ScriptedSource(by_text({"attention": [A + more], "transformers": [B]}))
    summary = watch_run(project, sources=adapters(source), trigger="scheduler")
    assert summary is not None
    return summary.cycle_id, summary.new_work_ids


def _events(project: Project) -> int:
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM events")).scalar_one())


def test_watch_work_listed_with_cycle_ref(ready: Project) -> None:
    cycle_id, new = _cycle(ready)
    entries = inbox_entries(ready, route="database:openalex")
    assert {e.work_id for e in entries} == set(new)
    assert {e.route_ref for e in entries} == {cycle_id}
    assert all(isinstance(e, InboxEntry) and e.surfaced_at for e in entries)
    assert [e.surfaced_at for e in entries] == sorted(e.surfaced_at for e in entries)


def test_included_work_leaves_inbox(ready: Project, agent: Actor) -> None:
    _cycle(ready, extra=40)
    draw_calibration(ready, ready.system_actor(), random_seed=11)
    screen_next(ready, agent, PassLabel.A)  # opens pass A and queues the ordinary works
    protocol = current_protocol(ready)
    assert protocol is not None
    calibration = set(calibration_items(ready))
    [first, *_] = [e for e in inbox_entries(ready) if e.work_id not in calibration]
    before = {e.work_id for e in inbox_entries(ready)}
    open_pass(ready, agent, PassLabel.B)
    for label in PassLabel:
        decide(ready, agent, first.work_id, protocol.protocol_id, "include", pass_label=label)
    after = {e.work_id for e in inbox_entries(ready)}
    assert before - after == {first.work_id}


def test_link_and_watch_routes_listed_together(
    ready: Project, human: Actor, other_session_human: Actor
) -> None:
    cycle_id, new = _cycle(ready)
    capture(ready, other_session_human, "10.2000/s1")
    deviation = record_deviation(ready, human, description="Supplied link", reason="Colleague.")
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})
    [outcome] = resolve(ready, other_session_human, keyed, deviation_id=deviation)
    assert outcome.status is ResolveStatus.NEW and outcome.work_id is not None
    entries = inbox_entries(ready)
    by_work = {e.work_id: e for e in entries}
    assert set(by_work) == {*new, outcome.work_id}
    assert by_work[outcome.work_id].route != "database:openalex"
    assert {by_work[w].route_ref for w in new} == {cycle_id}
    assert [e.surfaced_at for e in entries] == sorted(e.surfaced_at for e in entries)
    page = inbox_entries(ready, limit=1)
    rest = inbox_entries(ready, after=page[0].work_id)
    assert [e.work_id for e in [*page, *rest]] == [e.work_id for e in entries]


def test_screen_order_unchanged_by_view(ready: Project, agent: Actor) -> None:
    """The view writes nothing and leaves the screening queue as it is (R-34)."""
    _cycle(ready, extra=40)
    draw_calibration(ready, ready.system_actor(), random_seed=11)
    screen_next(ready, agent, PassLabel.A)
    before = _events(ready)
    with ready.index.connect() as conn:
        queue = conn.execute(text("SELECT * FROM tasks ORDER BY 1")).all()
    inbox_entries(ready)
    assert _events(ready) == before
    with ready.index.connect() as conn:
        assert conn.execute(text("SELECT * FROM tasks ORDER BY 1")).all() == queue


def test_cli_lists_watch_entries(ready: Project) -> None:
    from typer.testing import CliRunner

    from factory.cli.main import app
    from tests.cli_helpers import _env

    cycle_id, new = _cycle(ready)
    result = CliRunner().invoke(
        app, ["--project", "demo", "inbox", "list", "--watch"], env=_env(ready.settings.root)
    )
    assert result.exit_code == 0, result.stdout
    lines = result.stdout.strip().splitlines()
    assert sorted(line.split()[0] for line in lines) == sorted(new)
    assert all(f"database:openalex  {cycle_id}" in line for line in lines)
