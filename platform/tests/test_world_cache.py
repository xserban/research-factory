"""The test-world snapshot cache restores an identical, independent world (tests/world_cache.py)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import event_files, read_all
from factory.model.identity import ulid_time
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.question import record_question
from tests import helpers, world_cache
from tests.helpers import SESSION, T0, install_skill, pilot_question_spec, record_pilot_question
from tests.world_cache import snapshot_world


@pytest.fixture(autouse=True)
def _cache_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests test the cache itself, so they run with it on even when it is disabled."""
    monkeypatch.delenv("FACTORY_TEST_NO_WORLD_CACHE", raising=False)


def _project(root: Path, clock: FixedClock | None = None) -> Project:
    settings = Settings(root=root, user="obd")
    install_skill(settings, "rf-screen")
    return init_project(settings, "demo", "pilot", session=SESSION, clock=clock or FixedClock(T0))


@snapshot_world
def _build(project: Project, primary: str) -> str:
    assert isinstance(project.clock, FixedClock)
    project.clock.advance(timedelta(seconds=5))
    return record_pilot_question(project, project.human_actor(), primary)


def _counts(name: str) -> dict[str, int]:
    return {o: n for (b, o), n in world_cache.STATS.items() if b.endswith(name)}


def _log(project: Project) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in event_files(project.paths.events_dir)}


def test_second_build_is_restored_identically(tmp_path: Path) -> None:
    before = _counts("_build").get("hit", 0)
    first = _project(tmp_path / "a")
    second = _project(tmp_path / "b")
    value = _build(first, "Primary one?")
    assert _build(second, "Primary one?") == value
    assert _counts("_build").get("hit", 0) == before + 1
    assert _log(second) == _log(first)
    assert second.clock.now() == first.clock.now() == T0 + timedelta(seconds=5)
    assert second.index.state_hash() == first.index.state_hash()
    # The restored id generator continues after the restored events, so the index stays
    # incremental and the order of events holds.
    last = max(e.id for e in read_all(second.paths.events_dir, second.catalog))
    following = second.ids.ulid()
    assert following > last.rsplit("_", 1)[-1]
    assert ulid_time(following) == second.clock.now()


def test_restored_world_is_independent(tmp_path: Path) -> None:
    first = _project(tmp_path / "a")
    second = _project(tmp_path / "b")
    _build(first, "Primary two?")
    _build(second, "Primary two?")
    actor = second.human_actor()
    first_log = _log(first)
    record_question(second, actor, pilot_question_spec(primary="Another?"), reason="refined")
    # The write applied incrementally to the restored index and left the template's copy alone.
    assert second.index.sync().rebuilt is False
    assert _log(first) == first_log
    assert sum(len(b) for b in _log(second).values()) > sum(len(b) for b in first_log.values())
    third = _project(tmp_path / "c")
    _build(third, "Primary two?")  # a third restore is unaffected by the second's write
    assert _log(third) == first_log


def test_different_arguments_or_start_state_build_again(tmp_path: Path) -> None:
    before = _counts("_build").get("miss", 0)
    _build(_project(tmp_path / "a"), "Primary three?")
    _build(_project(tmp_path / "b"), "Primary four?")
    _build(_project(tmp_path / "c", FixedClock(T0 + timedelta(days=1))), "Primary three?")
    assert _counts("_build").get("miss", 0) == before + 3


def test_unkeyable_argument_bypasses_the_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    @snapshot_world
    def build(project: Project, note: list[str]) -> None:
        note.append("built")

    def captures(_project: Project) -> None:
        calls.append("x")

    before = sum(n for (b, o), n in world_cache.STATS.items() if o.startswith("bypass"))
    build(_project(tmp_path / "a"), calls)
    build(_project(tmp_path / "b"), calls)
    assert calls == ["built", "built"]
    assert sum(n for (b, o), n in world_cache.STATS.items() if o.startswith("bypass")) == before
    # A list argument is keyed by value; a function capturing a mutable list is not keyable.
    with_list = snapshot_world(lambda project, f: f(project))
    with_list(_project(tmp_path / "c"), captures)
    with_list(_project(tmp_path / "d"), captures)
    assert calls == ["built", "built", "x", "x"]


def test_monkeypatched_module_binding_builds_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A builder may depend on module globals a test patches (as test_check does)."""
    before = _counts("_build").get("miss", 0)
    _build(_project(tmp_path / "a"), "Primary five?")
    original = helpers.pilot_question_spec
    monkeypatch.setattr(helpers, "pilot_question_spec", lambda p: original(p + " (patched)"))
    patched = _project(tmp_path / "b")
    _build(patched, "Primary five?")
    assert _counts("_build").get("miss", 0) == before + 2
    events = read_all(patched.paths.events_dir, patched.catalog)
    assert any("(patched)" in e.model_dump_json() for e in events)
    monkeypatch.undo()
    _build(_project(tmp_path / "c"), "Primary five?")  # the original binding is back: a hit
    assert _counts("_build").get("miss", 0) == before + 2


def test_environment_variable_builds_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _counts("_build").get("miss", 0)
    _build(_project(tmp_path / "a"), "Primary six?")
    monkeypatch.setenv("FACTORY_SOMETHING", "1")
    _build(_project(tmp_path / "b"), "Primary six?")
    assert _counts("_build").get("miss", 0) == before + 2


def test_function_capturing_a_container_is_keyed_by_its_value(tmp_path: Path) -> None:
    """Fixtures build `rows_for` closures over dicts: equal values share a snapshot."""
    built: list[str] = []

    @snapshot_world
    def build(project: Project, answer: Callable[[], str]) -> None:
        built.append(answer())

    def answering(table: dict[str, str]) -> Callable[[], str]:
        return lambda: table["key"]

    build(_project(tmp_path / "a"), answering({"key": "one"}))
    build(_project(tmp_path / "b"), answering({"key": "one"}))
    assert built == ["one"]
    build(_project(tmp_path / "c"), answering({"key": "two"}))
    assert built == ["one", "two"]


def test_build_that_writes_to_a_captured_container_is_never_restored(tmp_path: Path) -> None:
    """A captured list can be a side channel: a restore could not repeat the write."""
    builds = 0

    def noting(seen: list[str]) -> Callable[[], None]:
        return lambda: seen.append("seen")

    @snapshot_world
    def build(project: Project, note: Callable[[], None]) -> None:
        note()

    first: list[str] = []
    second: list[str] = []
    build(_project(tmp_path / "a"), noting(first))
    build(_project(tmp_path / "b"), noting(second))
    builds = len(first) + len(second)
    assert first == ["seen"]
    assert second == ["seen"]
    assert builds == 2
