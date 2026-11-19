"""The call-scoped speed-ups of the mining calls: the read scope of the event log, the typed read,
the clean-hold sync of the index and the memo drop on a write. Each has an invalidation rule."""

from pathlib import Path

from factory.clock import SystemClock
from factory.config import Settings
from factory.events.reader import cached_reads, read_all, read_typed
from factory.model.identity import IdGenerator
from factory.services import call_memo
from factory.services.project import init_project
from factory.services.tasks import TaskSpec, create_tasks


def _project(tmp_path: Path):  # type: ignore[no-untyped-def]
    clock = SystemClock()
    settings = Settings(root=tmp_path, user="obd")
    return init_project(settings, "demo", "pilot", session=IdGenerator(clock).ulid(), clock=clock)


def _ids(events) -> list[str]:  # type: ignore[no-untyped-def]
    return [e.id for e in events]


def test_cached_read_equals_plain_read_and_sees_appends(tmp_path: Path) -> None:
    project = _project(tmp_path)
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
    plain = read_all(project.paths.events_dir, project.catalog)
    with cached_reads():
        first = read_all(project.paths.events_dir, project.catalog)
        assert _ids(first) == _ids(plain)
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 2})])
        second = read_all(project.paths.events_dir, project.catalog)
        assert _ids(second) == _ids(read_all(project.paths.events_dir, project.catalog))
        assert len(second) > len(first)
        second.clear()  # a caller's list is its own
        assert len(read_all(project.paths.events_dir, project.catalog)) > len(first)


def test_typed_read_is_the_type_filter_of_the_full_read(tmp_path: Path) -> None:
    project = _project(tmp_path)
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1}), TaskSpec("k", {"i": 2})])
    wanted = {"task.created"}
    expected = [
        e.id for e in read_all(project.paths.events_dir, project.catalog) if e.type in wanted
    ]
    assert expected
    assert _ids(read_typed(project.paths.events_dir, project.catalog, wanted)) == expected
    with cached_reads():
        assert _ids(read_typed(project.paths.events_dir, project.catalog, wanted)) == expected
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 3})])
        again = _ids(read_typed(project.paths.events_dir, project.catalog, wanted))
    assert len(again) == len(expected) + 1


def test_sync_after_an_append_in_a_hold_reads_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with project.index.exclusive():
        project.index.sync()
        assert project.index.sync().applied == 0  # clean: nothing to read
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
        with project.index.connect() as conn:
            rows = conn.exec_driver_sql("SELECT COUNT(*) FROM tasks").scalar()
        assert rows == 1


def test_a_write_drops_the_memo_of_the_open_scope(tmp_path: Path) -> None:
    project = _project(tmp_path)
    calls: list[int] = []

    @call_memo.memoised
    def probe(proj) -> int:  # type: ignore[no-untyped-def]
        calls.append(1)
        return len(calls)

    with call_memo.entering():
        assert probe(project) == probe(project) == 1
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
        assert probe(project) == 2
