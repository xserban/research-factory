"""`mine.reopened`: reopening one mined work after a selector miss (IDEA-99)."""

# ruff: noqa: F811
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mining.select import SELECTION_FALLBACK_BELOW, heading_share
from factory.mining.spec import MinerSpec
from factory.model.extraction import MinerScope
from factory.model.mine_reopen import MineReopened
from factory.model.screening import PassLabel
from factory.services import mining as mining_module
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.extraction import (
    MineBatch,
    MineBatchContent,
    UnitState,
    live_rows,
    scope_ledger,
    stale_extractions,
    unit_states,
)
from factory.services.mine_reopen import reopen_unit, served_share
from factory.services.mining import mine_next, mine_record
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.miner_helpers import (
    SESSION_M1,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_exploratory,
    mine_pass,
    mine_row,
    miner_actor,
)

A = PassLabel.A
REASON = "the heading selector missed the main text"


@pytest.fixture
def mina() -> Actor:
    return miner_actor(SESSION_M1, "claude-opus-5-5")


def _unmatched() -> MinerSpec:
    spec = method_vision()
    return replace(spec, selector=replace(spec.selector, heading_patterns=("zzz-no-such",)))


@pytest.fixture
def legacy_selection() -> Iterator[pytest.MonkeyPatch]:
    """Tasks created as before IDEA-99: the selector's own anchors, no fallback, no recorded
    share (what a task created before commit 108a073a holds). Yields its own patch object, so a
    test can end the legacy state with `legacy_selection.undo()` without reverting the shared
    `monkeypatch` fixture (the conftest's environment patches are part of the world-cache key)."""
    from factory.mining.select import Selection, selected_anchors

    def legacy(manifest: Any, selector: Any) -> Selection:
        return Selection(selected_anchors(manifest, selector), 0.0, False)

    real = MineBatchContent

    def without_share(**kw: Any) -> MineBatchContent:
        return real(**{**kw, "selection_matched_share": None, "selection_fallback": False})

    patch = pytest.MonkeyPatch()
    patch.setattr(mining_module, "select_with_fallback", legacy)
    patch.setattr(mining_module, "MineBatchContent", without_share)
    yield patch
    patch.undo()


def _mined_legacy(
    project: Project, agent: Actor, mina: Actor, legacy_selection: pytest.MonkeyPatch
) -> tuple[str, list[str]]:
    """List the unmatched miner and mine every work in pass A the old way; return the first work
    and the works mined."""
    list_miner(project, agent, _unmatched())
    done = mine_pass(project, mina, A, lambda w: [mine_row()])
    assert done
    return done[0], done


def _a_units(project: Project) -> list[UnitState]:
    return [s for s in unit_states(project, scope=MinerScope(VISION_NAME)) if s.pass_label == A]


def _events(project: Project, kind: str) -> list[Any]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def test_old_task_share_is_computed_from_stored_anchors(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    legacy_selection: pytest.MonkeyPatch,
) -> None:
    work, _ = _mined_legacy(project, agent, mina, legacy_selection)
    task = _a_units(project)[0]
    assert task.state == "current"
    content = scope_ledger(project, MinerScope(VISION_NAME)).tasks[(work, A)][-1].content
    assert isinstance(content, MineBatchContent)
    assert content.selection_matched_share is None and content.selection_fallback is False
    share = served_share(project, content, _unmatched().selector)
    manifest = conversion_manifest(project, content.records[0]["conversion_id"])
    assert share == heading_share(manifest, _unmatched().selector) == 0.0  # no section matched
    assert share is not None and share < SELECTION_FALLBACK_BELOW


def test_reopen_accepted_and_the_next_task_falls_back(
    project: Project,
    agent: Actor,
    human: Actor,
    mina: Actor,
    world: list[str],
    legacy_selection: pytest.MonkeyPatch,
) -> None:
    work, _ = _mined_legacy(project, agent, mina, legacy_selection)
    old_rows = {r.extraction_id for r in live_rows(project, scope=MinerScope(VISION_NAME))}
    legacy_selection.undo()  # the fresh task is created with today's selector
    event_id = reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    [event] = _events(project, "mine.reopened")
    assert event.id == event_id and event.actor.kind == "human"
    assert MineReopened.model_validate(event.payload).reason == REASON
    states = {s.work_id: s for s in _a_units(project) if s.pass_label == A}
    assert (states[work].state, states[work].reason) == ("stale", "reopened")
    served = mine_next(project, mina, VISION_NAME, 1, A).batch
    assert isinstance(served, MineBatch)
    assert served.records[0]["work_id"] == work
    assert served.selection_fallback is True and served.selection_matched_share == 0.0
    assert {s.work_id: s.state for s in _a_units(project)}[work] == "open"
    # The old rows are not live once the fresh task's rows are recorded; the same row key does
    # not collide with them, so no supersedes is passed.
    result = mine_record(project, mina, served.task_id, [mine_row()], finish=True)
    assert result.completed, result.rows.rejected
    stale = stale_extractions(project, scope=MinerScope(VISION_NAME))
    work_rows = [r for r in live_rows(project, scope=MinerScope(VISION_NAME)) if r.work_id == work]
    new_rows = {r.extraction_id for r in work_rows if r.task_id == served.task_id}
    old_here = {r.extraction_id for r in work_rows if r.extraction_id in old_rows}
    assert new_rows and old_here and not (new_rows & stale)
    assert old_here <= stale
    assert {s.work_id: s.state for s in _a_units(project)}[work] == "current"
    other = [r for r in live_rows(project, scope=MinerScope(VISION_NAME)) if r.work_id != work]
    assert all(r.extraction_id not in stale for r in other)  # other works are untouched


def test_refused_when_the_share_is_at_or_above_the_threshold(
    project: Project, agent: Actor, human: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    work = mine_pass(project, mina, A, lambda w: [mine_row()])[0]
    before = len(_events(project, "mine.reopened"))
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    assert raised.value.issues[0].field == "work_id"
    assert "not under" in raised.value.issues[0].reason
    assert len(_events(project, "mine.reopened")) == before


def test_refused_when_the_task_already_fell_back(
    project: Project, agent: Actor, human: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent, _unmatched())
    work = mine_pass(project, mina, A, lambda w: [mine_row()])[0]
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    assert "already served every section" in raised.value.issues[0].reason


@pytest.mark.parametrize(
    ("name", "version", "field"),
    [("m-no-such", 1, "miner"), (VISION_NAME, 9, "miner")],
)
def test_refused_for_an_unknown_miner_or_version(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    name: str,
    version: int,
    field: str,
) -> None:
    list_miner(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, name, version, world[0], A, REASON)
    assert raised.value.issues[0].field == field


def test_refused_without_a_completed_task(
    project: Project, agent: Actor, human: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent, _unmatched())
    with pytest.raises(FactoryValidationError) as raised:  # no task at all
        reopen_unit(project, human, VISION_NAME, 1, world[0], A, REASON)
    assert raised.value.issues[0].field == "work_id"
    batch = mine_exploratory(
        project, mina, VISION_NAME, 1, A
    ).batch  # a claimed task, not completed
    assert batch is not None
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, VISION_NAME, 1, batch.records[0]["work_id"], A, REASON)
    assert "not completed" in raised.value.issues[0].reason


def test_refused_for_a_blank_reason_and_an_agent(
    project: Project, agent: Actor, human: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, VISION_NAME, 1, world[0], A, "   ")
    assert raised.value.issues[0].field == "reason"
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, mina, VISION_NAME, 1, world[0], A, REASON)
    assert raised.value.issues[0].field == "actor"
    assert not _events(project, "mine.reopened")


def test_refused_when_already_reopened(
    project: Project,
    agent: Actor,
    human: Actor,
    mina: Actor,
    world: list[str],
    legacy_selection: pytest.MonkeyPatch,
) -> None:
    work, _ = _mined_legacy(project, agent, mina, legacy_selection)
    reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    assert "already reopened" in raised.value.issues[0].reason
    assert len(_events(project, "mine.reopened")) == 1


def test_the_index_folds_only_a_guarded_human_event(
    project: Project,
    agent: Actor,
    human: Actor,
    mina: Actor,
    world: list[str],
    legacy_selection: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import text

    work, _ = _mined_legacy(project, agent, mina, legacy_selection)
    task = scope_ledger(project, MinerScope(VISION_NAME)).tasks[(work, A)][-1]

    def payload(**over: Any) -> MineReopened:
        base: dict[str, Any] = {
            "miner": VISION_NAME,
            "version": 1,
            "work_id": work,
            "pass_label": A,
            "task_id": task.task_id,
            "reason": REASON,
        }
        return MineReopened.model_validate({**base, **over})

    def count() -> int:
        project.index.sync()
        with project.index.connect() as conn:
            return int(conn.execute(text("SELECT COUNT(*) FROM mine_reopenings")).scalar_one())

    # An agent's event, a version never registered, and a task of another work change nothing.
    blob = project.blobs.put_json({"hand": "written"})
    project.record([project.events.make("mine.reopened", payload(), mina, input_blob=blob)])
    project.record([project.events.make("mine.reopened", payload(version=7), human)])
    other = next(w for w in world if w != work)
    project.record([project.events.make("mine.reopened", payload(work_id=other), human)])
    assert count() == 0
    assert {s.state for s in _a_units(project)} == {"current"}
    project.record([project.events.make("mine.reopened", payload(), human)])
    assert count() == 1
    project.record([project.events.make("mine.reopened", payload(), human)])  # a repeat
    assert count() == 1
    with pytest.raises(ValueError):
        payload(reason="  ")
    project.index.rebuild()
    assert count() == 1  # a rebuild folds the same


runner = CliRunner()


def test_cli_reopen_is_a_thin_wrapper(
    settings: Settings,
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    legacy_selection: pytest.MonkeyPatch,
) -> None:
    work, _ = _mined_legacy(project, agent, mina, legacy_selection)
    args = ["miner", "reopen", VISION_NAME, "1", work, "--pass", "A"]
    refused = runner.invoke(app, [*args, "--reason", " "], env=_env(settings.root))
    assert refused.exit_code != 0 and "reason" in (refused.stderr or refused.output)
    done = runner.invoke(app, [*args, "--reason", REASON], env=_env(settings.root))
    assert done.exit_code == 0, done.output
    assert f"reopened {work}" in done.stdout
    assert len(_events(project, "mine.reopened")) == 1


def test_mcp_tool_is_registered_and_thin(settings: Settings, tmp_path: Path) -> None:
    import inspect

    from factory.mcp import server

    source = inspect.getsource(server.build_server)
    assert "mine_reopen_service.reopen_unit(" in source


@pytest.fixture
def recorded_share(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Tasks created with a given recorded share and no fallback (the 3-decimal value a task
    stores), whatever the document holds."""

    def set_share(share: float) -> None:
        real = MineBatchContent

        def with_share(**kw: Any) -> MineBatchContent:
            return real(**{**kw, "selection_matched_share": share, "selection_fallback": False})

        monkeypatch.setattr(mining_module, "MineBatchContent", with_share)

    return set_share


def test_reopen_refused_at_exactly_the_threshold(
    project: Project, agent: Actor, human: Actor, mina: Actor, world: list[str], recorded_share: Any
) -> None:
    recorded_share(SELECTION_FALLBACK_BELOW)
    list_miner(project, agent)
    work = mine_pass(project, mina, A, lambda w: [mine_row()])[0]
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    assert "not under" in raised.value.issues[0].reason
    assert not _events(project, "mine.reopened")


def test_reopen_accepted_just_below_the_threshold(
    project: Project, agent: Actor, human: Actor, mina: Actor, world: list[str], recorded_share: Any
) -> None:
    recorded_share(0.099)
    list_miner(project, agent)
    work = mine_pass(project, mina, A, lambda w: [mine_row()])[0]
    reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    assert len(_events(project, "mine.reopened")) == 1


def test_reopen_refused_for_a_selector_that_never_falls_back(
    project: Project, agent: Actor, human: Actor, mina: Actor, world: list[str], recorded_share: Any
) -> None:
    from factory.document.anchors import AnchorKind

    recorded_share(0.0)  # a miss in paragraph words, but the selector asks for tables only
    spec = method_vision()
    tables = replace(spec, selector=replace(spec.selector, elements=(AnchorKind.TABLE,)))
    list_miner(project, agent, tables)
    work = mine_pass(project, mina, A, lambda w: [mine_row()])[0]
    with pytest.raises(FactoryValidationError) as raised:
        reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    assert "never falls back" in raised.value.issues[0].reason
    assert not _events(project, "mine.reopened")


def test_old_table_task_share_comes_from_the_selector_not_the_anchors(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    legacy_selection: pytest.MonkeyPatch,
) -> None:
    from factory.document.anchors import AnchorKind

    spec = method_vision()
    tables = replace(spec, selector=replace(spec.selector, elements=(AnchorKind.TABLE,)))
    list_miner(project, agent, tables)
    work = mine_pass(project, mina, A, lambda w: [mine_row()])[0]
    content = scope_ledger(project, MinerScope(VISION_NAME)).tasks[(work, A)][-1].content
    assert isinstance(content, MineBatchContent) and content.selection_matched_share is None
    manifest = conversion_manifest(project, content.records[0]["conversion_id"])
    assert served_share(project, content, tables.selector) == heading_share(
        manifest, tables.selector
    )


def test_reopening_pass_a_leaves_pass_b_untouched(
    project: Project,
    agent: Actor,
    human: Actor,
    mina: Actor,
    world: list[str],
    recorded_share: Any,
) -> None:
    from tests.miner_helpers import SESSION_M2

    recorded_share(0.0)
    list_miner(project, agent)
    minb = miner_actor(SESSION_M2, "claude-sonnet-5-5")
    work = mine_pass(project, mina, A, lambda w: [mine_row()])[0]
    mine_pass(project, minb, PassLabel.B, lambda w: [mine_row()])
    b_rows = {
        r.extraction_id
        for r in live_rows(project, scope=MinerScope(VISION_NAME))
        if r.work_id == work and r.pass_label == PassLabel.B
    }
    assert b_rows
    reopen_unit(project, human, VISION_NAME, 1, work, A, REASON)
    states = {
        (s.work_id, s.pass_label): s for s in unit_states(project, scope=MinerScope(VISION_NAME))
    }
    assert (states[(work, A)].state, states[(work, A)].reason) == ("stale", "reopened")
    assert states[(work, PassLabel.B)].state == "current"
    stale = stale_extractions(project, scope=MinerScope(VISION_NAME))
    assert not (b_rows & stale)
    still = {
        r.extraction_id
        for r in live_rows(project, scope=MinerScope(VISION_NAME))
        if r.work_id == work and r.pass_label == PassLabel.B
    }
    assert still == b_rows
