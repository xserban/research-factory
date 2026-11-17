"""Ephemeral progress of long operations (slice 8, I2, IDEA-44; not yet run)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from factory.events.reader import read_all
from factory.services import dashboard as dashboard_service
from factory.services import progress as progress_service
from factory.services.context import Project
from factory.services.progress import Reporter, progress_list, read_directory, track


class Clocks:
    """A wall clock and a monotonic clock that the test advances together."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def wall(self) -> float:
        return self.now

    def mono(self) -> float:
        return self.now - 1_700_000_000.0


def _reporter(directory: Path, clocks: Clocks, total: int | None = 100) -> Reporter:
    return Reporter(
        directory,
        "search",
        "openalex main query",
        unit="records",
        total=total,
        clock=clocks.wall,
        monotonic=clocks.mono,
    )


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*"))


def test_update_is_throttled_to_one_write_per_second(tmp_path: Path) -> None:
    clocks = Clocks()
    reporter = _reporter(tmp_path, clocks)
    path = tmp_path / f"{reporter.op_id}.json"
    reporter.update(5)  # within a second of the write at start: held back
    assert json.loads(path.read_text())["done"] == 0
    clocks.now += 1.0
    reporter.update(6)
    assert json.loads(path.read_text())["done"] == 6
    clocks.now += 0.4
    reporter.update(7)
    assert json.loads(path.read_text())["done"] == 6
    reporter.finish()
    assert json.loads(path.read_text())["done"] == 100


def test_finish_always_writes_and_leaves_no_temp_file(tmp_path: Path) -> None:
    clocks = Clocks()
    reporter = _reporter(tmp_path, clocks)
    reporter.update(40)
    reporter.finish("done")
    data = json.loads((tmp_path / f"{reporter.op_id}.json").read_text())
    assert data["state"] == "finished" and data["done"] == 100 and data["message"] == "done"
    assert [p.suffix for p in _files(tmp_path)] == [".json"]


def test_context_manager_marks_failure_and_reraises(tmp_path: Path) -> None:
    clocks = Clocks()
    holder: list[Reporter] = []
    try:
        with _reporter(tmp_path, clocks) as reporter:
            holder.append(reporter)
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    data = json.loads((tmp_path / f"{holder[0].op_id}.json").read_text())
    assert data["state"] == "failed" and "boom" in data["message"]


def test_rate_and_eta_are_computed_by_the_reader(tmp_path: Path) -> None:
    clocks = Clocks()
    reporter = _reporter(tmp_path, clocks, total=100)
    clocks.now += 10
    reporter.update(25)
    clocks.now += 1.5
    reporter.update(25)
    (row,) = read_directory(tmp_path, clocks.now)
    assert row["state"] == "running"
    assert row["elapsed_seconds"] == 11.5
    assert row["rate_per_second"] is not None
    assert row["eta_seconds"] is not None and row["eta_seconds"] > 0
    unknown = _reporter(tmp_path / "other", clocks, total=None)
    unknown.update(3)
    (urow,) = read_directory(tmp_path / "other", clocks.now + 5)
    assert urow["eta_seconds"] is None


def test_finished_entries_are_pruned_after_ten_minutes(tmp_path: Path) -> None:
    clocks = Clocks()
    reporter = _reporter(tmp_path, clocks)
    reporter.finish()
    (row,) = read_directory(tmp_path, clocks.now + 300)
    assert row["state"] == "finished" and row["eta_seconds"] is None
    assert read_directory(tmp_path, clocks.now + 601) == []
    assert _files(tmp_path) == []


def test_abandoned_running_entry_turns_stale_then_is_pruned(tmp_path: Path) -> None:
    clocks = Clocks()
    _reporter(tmp_path, clocks)
    (row,) = read_directory(tmp_path, clocks.now + 700)
    assert row["state"] == "stale"
    assert read_directory(tmp_path, clocks.now + 4000) == []


def test_a_writer_failure_never_breaks_the_operation(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    clocks = Clocks()
    reporter = _reporter(blocker / "sub", clocks)  # the directory cannot be created
    reporter.update(1)
    reporter.finish()
    assert read_directory(blocker / "sub", clocks.now) == []


def test_unreadable_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "op_bad.json").write_text("{not json")
    (tmp_path / "op_list.json").write_text("[1]")
    assert read_directory(tmp_path) == []


def test_progress_writes_no_event_and_stays_out_of_the_index(project: Project) -> None:
    before = len(list(read_all(project.paths.events_dir, project.catalog)))
    with track(project, "dedup", "title comparison", unit="records", total=3) as reporter:
        reporter.update(3)
    after = len(list(read_all(project.paths.events_dir, project.catalog)))
    assert before == after
    assert (project.paths.dir / ".progress").is_dir()
    assert [row["kind"] for row in progress_list(project)] == ["dedup"]
    assert not any(".progress" in str(p) for p in project.paths.events_dir.rglob("*"))


def test_dashboard_state_has_a_progress_panel(project: Project) -> None:
    ticks = iter([0.0, 5.0])  # an update after the write throttle (one second) is written
    with Reporter(
        project.paths.dir / progress_service.PROGRESS_DIR,
        "ranking",
        "SPECTER2 embedding",
        unit="records",
        total=10,
        monotonic=lambda: next(ticks),
    ) as reporter:
        reporter.update(4)
        state = dashboard_service.dashboard_state(project)
    panel = state["progress"]
    assert isinstance(panel, list) and len(panel) == 1
    row = panel[0]
    assert isinstance(row, dict) and row["state"] == "running" and row["done"] == 4


def test_temp_file_is_renamed_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    real = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append((str(src), str(dst)))
        real(src, dst)

    monkeypatch.setattr(progress_service.os, "replace", spy)
    _reporter(tmp_path, Clocks())
    assert calls and calls[0][0].endswith(".json.tmp") and calls[0][1].endswith(".json")
