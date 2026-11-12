"""The index rebuild guard (IDEA-62): one code version at a time rebuilds a project's index.

The holder is a real second process: it builds the index with its own projection version and
then either stays alive (holding) or exits (a crash). Temporary roots only.
"""

import multiprocessing
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from factory.index.index import (
    DEFAULT_HOLD_WINDOW,
    Holder,
    Index,
    IndexHeldError,
    code_path,
    holder_blocks,
)
from factory.index.index import (
    _holder as read_holder,
)
from factory.mcp.conventions import guarded
from tests.screening_helpers import demo_catalog, demo_projection

_SPAWN = multiprocessing.get_context("spawn")


def _index(project_dir: Path, version: str, **kwargs: Any) -> Index:
    return Index(
        project_dir / ".index" / "factory.sqlite",
        project_dir / "events",
        demo_catalog(),
        demo_projection(version),
        **kwargs,
    )


def _hold(project_dir: str, version: str, built: Any, release: Any) -> None:
    """Child process: build the index as `version`, report, then hold until released."""
    _index(Path(project_dir), version).sync()
    built.set()
    release.wait(60)


@contextmanager
def _holder(project_dir: Path, version: str, *, stay: bool = True) -> Iterator[int]:
    """A second process that built the index as `version`; alive inside the block when `stay`,
    already exited (as after a crash) otherwise. Yields its pid."""
    built, release = _SPAWN.Event(), _SPAWN.Event()
    child = _SPAWN.Process(target=_hold, args=(str(project_dir), version, built, release))
    child.start()
    try:
        assert built.wait(60), "holder did not build the index"
        if not stay:
            release.set()
            child.join(60)
        assert child.pid is not None
        yield child.pid
    finally:
        release.set()
        child.join(60)


def _events_snapshot(project_dir: Path) -> dict[str, bytes]:
    events = project_dir / "events"
    if not events.exists():
        return {}
    return {str(p): p.read_bytes() for p in sorted(events.rglob("*")) if p.is_file()}


# --- the guard, against a live second process ---


def test_older_version_is_refused_inside_the_window(tmp_path: Path) -> None:
    before = _events_snapshot(tmp_path)
    with _holder(tmp_path, "84") as pid:
        older = _index(tmp_path, "83")
        with pytest.raises(IndexHeldError) as refused:
            older.sync()
        with pytest.raises(IndexHeldError):
            older.rebuild()
        message = str(refused.value)
        assert "version 84" in message
        assert f"process {pid}" in message
        assert "version 83" in message
        # Nothing was rebuilt: the newer version still holds the index, by the same process.
        holder = _index(tmp_path, "84").holder()
        assert holder is not None and holder.version == "84" and holder.pid == pid
    assert _events_snapshot(tmp_path) == before


def test_rebuild_is_allowed_after_the_window(tmp_path: Path) -> None:
    with _holder(tmp_path, "84"):
        later = datetime.now(UTC) + DEFAULT_HOLD_WINDOW + timedelta(seconds=1)
        older = _index(tmp_path, "83", now=lambda: later)
        assert older.sync().rebuilt
        holder = older.holder()
        assert holder is not None and holder.version == "83" and holder.pid == os.getpid()


def test_a_configured_window_is_honoured(tmp_path: Path) -> None:
    with _holder(tmp_path, "84"):
        with pytest.raises(IndexHeldError):
            _index(tmp_path, "83", hold_window=timedelta(hours=1)).sync()
        assert _index(tmp_path, "83", hold_window=timedelta(0)).sync().rebuilt


def test_same_version_is_never_refused(tmp_path: Path) -> None:
    with _holder(tmp_path, "84"):
        same = _index(tmp_path, "84")
        assert not same.sync().rebuilt
        same.rebuild()  # a forced rebuild by the same version goes through


def test_newer_version_may_rebuild_over_an_older_one(tmp_path: Path) -> None:
    with _holder(tmp_path, "83"):
        newer = _index(tmp_path, "84")
        assert newer.sync().rebuilt
        holder = newer.holder()
        assert holder is not None and holder.version == "84"


def test_unordered_versions_refuse_each_other(tmp_path: Path) -> None:
    with _holder(tmp_path, "t1"), pytest.raises(IndexHeldError):
        _index(tmp_path, "t2").sync()


def test_a_crashed_holder_does_not_block(tmp_path: Path) -> None:
    with _holder(tmp_path, "84", stay=False):
        older = _index(tmp_path, "83")
        assert older.sync().rebuilt


def test_a_short_lived_same_version_process_does_not_take_the_hold(tmp_path: Path) -> None:
    """Review item 1: a second process of the holder's version renews the hold but keeps the
    live holder named, so its own exit does not look like the holder's crash."""
    with _holder(tmp_path, "84") as pid:
        later = datetime.now(UTC) + timedelta(minutes=2)  # past the refresh step
        later = later.replace(microsecond=later.microsecond // 1000 * 1000)  # stored in ms
        visitor = _index(tmp_path, "84", now=lambda: later)
        assert not visitor.sync().rebuilt
        held = visitor.holder()
        assert held is not None and held.pid == pid and held.held_at == later
        with pytest.raises(IndexHeldError):
            _index(tmp_path, "83", now=lambda: later).sync()


def test_the_refusal_is_a_structured_mcp_error(tmp_path: Path) -> None:
    with _holder(tmp_path, "84"):
        older = _index(tmp_path, "83")
        result = guarded(lambda: older.sync().applied)
    assert result["ok"] is False
    assert "version 84" in str(result)


def test_an_index_without_a_marker_is_not_held(tmp_path: Path) -> None:
    """An index built before the marker existed carries a version but no hold."""
    first = _index(tmp_path, "84")
    first.sync()
    with first._engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM meta WHERE key LIKE 'holder_%' OR key = 'held_at'")
    assert _index(tmp_path, "83").sync().rebuilt


def test_sync_renews_the_hold(tmp_path: Path) -> None:
    clock = [datetime(2026, 11, 12, 12, 0, tzinfo=UTC)]
    index = _index(tmp_path, "84", now=lambda: clock[0])
    index.sync()
    first = index.holder()
    assert first is not None and first.held_at == clock[0]
    clock[0] += timedelta(seconds=10)
    index.sync()  # inside the refresh step: the marker is not rewritten
    assert index.holder() == first
    clock[0] += timedelta(minutes=2)
    index.sync()
    renewed = index.holder()
    assert renewed is not None and renewed.held_at == clock[0]


def test_the_marker_leaves_the_state_hash_alone(tmp_path: Path) -> None:
    clock = [datetime(2026, 11, 12, 12, 0, tzinfo=UTC)]
    index = _index(tmp_path, "84", now=lambda: clock[0])
    first = index.rebuild()
    clock[0] += timedelta(hours=1)
    assert index.rebuild() == first


def test_the_marker_names_this_process(tmp_path: Path) -> None:
    index = _index(tmp_path, "84")
    index.sync()
    holder = index.holder()
    assert holder is not None
    assert (holder.pid, holder.host, holder.code) == (
        os.getpid(),
        socket.gethostname(),
        code_path(),
    )


# --- the rule itself ---

_NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _blocks(holder: Holder, version: str = "83", *, alive: bool = True) -> bool:
    return holder_blocks(
        holder,
        version,
        now=_NOW,
        window=timedelta(minutes=10),
        pid=1000,
        host="here",
        alive=lambda _pid: alive,
    )


def _held(version: str = "84", *, ago: timedelta = timedelta(minutes=1), **kw: Any) -> Holder:
    fields: dict[str, Any] = {"pid": 2000, "host": "here", "code": "/w", "held_at": _NOW - ago}
    fields.update(kw)
    return Holder(version=version, **fields)


def test_rule_older_inside_the_window_is_blocked() -> None:
    assert _blocks(_held())


def test_rule_window_edge() -> None:
    assert _blocks(_held(ago=timedelta(minutes=10) - timedelta(milliseconds=1)))
    assert not _blocks(_held(ago=timedelta(minutes=10)))


def test_rule_exemptions() -> None:
    assert not _blocks(_held("83"))  # same version
    assert not _blocks(_held("82"))  # newer over older
    assert not _blocks(_held(held_at=None))  # no marker
    assert not _blocks(_held(pid=1000))  # this very process
    assert not _blocks(_held(), alive=False)  # holder gone on this host


def test_rule_a_holder_on_another_host_is_trusted_until_the_window_ends() -> None:
    assert _blocks(_held(host="elsewhere"), alive=False)
    assert not _blocks(_held(host="elsewhere", ago=timedelta(minutes=11)), alive=False)


def test_rule_versions_without_order() -> None:
    assert _blocks(_held("t1"), "t2")
    assert _blocks(_held("84"), "t2")


def test_rule_a_held_at_far_in_the_future_does_not_hold_for_ever() -> None:
    assert _blocks(_held(ago=-timedelta(minutes=5)))  # small skew still holds
    assert not _blocks(_held(ago=-timedelta(minutes=11)))


def test_rule_non_ascii_digits_are_unordered_not_a_crash() -> None:
    assert _blocks(_held("\u00b2"), "83")
    assert _blocks(_held("84"), "\u00b2")


def test_damaged_markers_are_read_as_unmarked() -> None:
    naive = read_holder(
        {"projection_version": "84", "held_at": "2026-11-12T12:00:00", "holder_pid": "\u00b2"}
    )
    assert naive is not None and naive.held_at is None and naive.pid is None
    garbage = read_holder({"projection_version": "84", "held_at": "not a time"})
    assert garbage is not None and garbage.held_at is None
