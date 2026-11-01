import fcntl
import multiprocessing
import threading
from datetime import timedelta
from pathlib import Path

from factory.clock import FixedClock, SystemClock
from factory.config import Settings
from factory.model.identity import IdGenerator
from factory.services.context import open_project
from factory.services.project import init_project, project_status
from factory.services.tasks import TaskSpec, create_tasks
from tests.helpers import S2, SESSION
from tests.test_index import make_index

WORKERS = 4
ITERATIONS = 15
ONE_MS = timedelta(milliseconds=1)


def _worker(root: str, iterations: int) -> list[str]:
    clock = SystemClock()
    settings = Settings(root=Path(root), user="obd")
    project = open_project(settings, "demo", session=IdGenerator(clock).ulid(), clock=clock)
    errors: list[str] = []
    for i in range(iterations):
        try:
            create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": i})])
            project_status(project)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
    return errors


def test_concurrent_processes_sync_without_errors(tmp_path: Path) -> None:
    clock = SystemClock()
    settings = Settings(root=tmp_path, user="obd")
    parent = init_project(settings, "demo", "pilot", session=IdGenerator(clock).ulid(), clock=clock)

    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(WORKERS) as pool:
        results = pool.starmap(_worker, [(str(tmp_path), ITERATIONS)] * WORKERS)

    assert results == [[]] * WORKERS
    status = project_status(parent)
    assert status.tasks.open == WORKERS * ITERATIONS
    assert status.events_total == WORKERS * ITERATIONS + 1
    assert parent.index.state_hash() == parent.index.rebuild()


def test_two_index_objects_agree_after_either_rebuilds(tmp_path: Path) -> None:
    first = make_index(tmp_path)
    second = make_index(tmp_path)
    first.sync()
    second.sync()
    first.rebuild()
    assert second.state_hash() == first.state_hash()
    second.sync()
    assert second.rebuild() == first.state_hash()
    # and the first still works after the second's rebuild
    assert first.state_hash() == second.state_hash()
    first.sync()


def test_second_index_object_follows_the_others_rebuild(
    settings: Settings, clock: FixedClock
) -> None:
    p1 = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    p2 = open_project(settings, "demo", session=S2, clock=clock)
    p2.index.sync()  # p2's engine is open on the current file
    clock.advance(ONE_MS)
    create_tasks(p1, p1.system_actor(), [TaskSpec("demo", 1)])
    p1.index.rebuild()  # replaces the DB file (new inode)
    assert project_status(p2).tasks.open == 1  # p2 must see the new file, not the unlinked one


def test_readers_wait_for_a_rebuild_in_progress(tmp_path: Path) -> None:
    index = make_index(tmp_path)
    index.sync()
    done = threading.Event()

    def read() -> None:
        index.state_hash()
        done.set()

    with (tmp_path / ".index" / "lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # a rebuild in progress
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        assert not done.wait(0.2)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    assert done.wait(2)
    reader.join()
