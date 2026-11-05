"""Review snapshots: the computed PRISMA flow and included set pinned at a cut-off (Task 4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from mcp import Client
from pydantic import JsonValue

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.living.facts import ConclusionFacts
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.living_hooks import DEFAULT_HOOKS, snapshot_hook
from factory.services.prisma import prisma_flow
from factory.services.snapshots import (
    build_snapshot_blob,
    snapshot,
    snapshot_blob,
    snapshots,
)
from factory.services.watch import CycleSummary, watch_run
from tests.helpers import SourcesFor, _of_type
from tests.living_helpers import agree, filler, screening_watch_setup, start_screening
from tests.watch_helpers import ScriptedSource, adapters, by_text


def _cycle(project: Project, count: int = 40, *, hooks: bool = False) -> CycleSummary:
    source = ScriptedSource(by_text({"attention": [filler(count)]}))
    summary = watch_run(
        project,
        sources=adapters(source),
        trigger="scheduler",
        after_runs=DEFAULT_HOOKS if hooks else (),
    )
    assert summary is not None
    return summary


def _ready(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    snapshot_every: int | None = None,
) -> None:
    screening_watch_setup(project, agent, human, mock_sources, snapshot_every=snapshot_every)


def test_snapshot_records_prisma_and_included(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    summary = _cycle(project)
    protocol_id, calibration = start_screening(project, agent)
    target = next(w for w in sorted(summary.new_work_ids) if w not in calibration)
    agree(project, agent, target, protocol_id, "include")
    last = read_all(project.paths.events_dir, project.catalog)[-1].id

    recorded = snapshot(project, human, trigger="human")

    assert recorded.snapshot_id.startswith("snp_") and recorded.trigger == "human"
    assert recorded.cutoff_event == last and recorded.protocol_id == protocol_id
    blob = snapshot_blob(project, recorded.snapshot_id)
    assert blob.prisma == prisma_flow(project)
    assert blob.included_ids == (target,)
    assert blob.conclusion_facts is None and blob.conclusions is None
    assert [s.snapshot_id for s in snapshots(project)] == [recorded.snapshot_id]
    [event] = _of_type(project, "living.snapshot_recorded")
    assert event.refs == (recorded.snapshot_id,) and event.actor.kind == "human"


def test_snapshot_refused_while_cycle_open(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready(project, agent, human, mock_sources)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("process died")

    monkeypatch.setattr("factory.services.watch._finish", boom)
    with pytest.raises(RuntimeError):
        _cycle(project, 5)
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as exc:
        snapshot(project, human, trigger="human")
    assert [i.field for i in exc.value.issues] == ["cycle"]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_snapshot_blob_deterministic(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    _cycle(project)
    recorded = snapshot(project, human, trigger="human")
    project.index.rebuild()
    again = build_snapshot_blob(
        project, cutoff_event=recorded.cutoff_event, snapshot_id=recorded.snapshot_id
    )
    assert project.blobs.put_json(again.model_dump(mode="json")) == recorded.blob
    assert snapshot_blob(project, recorded.snapshot_id) == again


def test_snapshot_sections_fill_the_living_d_slots(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)

    def facts(_project: Project) -> tuple[str, JsonValue]:
        return "conclusion_facts", {"included": 1, "groups": []}

    recorded = snapshot(project, human, trigger="human", extra=(facts,))
    blob = snapshot_blob(project, recorded.snapshot_id)
    assert blob.conclusion_facts == ConclusionFacts(included=1, groups=())
    assert blob.conclusions is None


def test_snapshot_hook_every_n_cycles(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, clock: FixedClock
) -> None:
    _ready(project, agent, human, mock_sources, snapshot_every=2)
    _cycle(project, 5, hooks=True)
    assert snapshots(project) == []
    clock.advance(timedelta(days=8))
    _cycle(project, 5, hooks=True)
    [taken] = snapshots(project)
    assert taken.trigger == "cycle"
    [event] = _of_type(project, "living.snapshot_recorded")
    assert event.actor.kind == "system"
    clock.advance(timedelta(days=8))
    _cycle(project, 5, hooks=True)
    assert len(snapshots(project)) == 1  # one cycle since the last snapshot
    clock.advance(timedelta(days=8))
    _cycle(project, 5, hooks=True)
    assert len(snapshots(project)) == 2


def test_snapshot_hook_without_plan_setting_writes_nothing(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    summary = _cycle(project, 5)
    assert snapshot_hook(project, summary.cycle_id, summary.new_work_ids) == ()
    assert snapshots(project) == []


def test_agent_cannot_snapshot(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as exc:
        snapshot(project, agent, trigger="human")
    assert [i.field for i in exc.value.issues] == ["actor"]
    with pytest.raises(FactoryValidationError):
        snapshot(project, human, trigger="cycle")  # a cycle snapshot is the system's
    assert _of_type(project, "living.snapshot_recorded") == []


@pytest.mark.anyio
async def test_mcp_has_no_snapshot_tool(settings: Settings, clock: FixedClock) -> None:
    server = build_server(settings, clock=clock)
    async with Client(server) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    # `region_snapshot` pins a region version (Regions-B); it is not a project snapshot.
    assert names and not [n for n in names if "snapshot" in n and n != "region_snapshot"]
