import multiprocessing
from pathlib import Path

from factory.clock import SystemClock
from factory.config import Settings
from factory.model.identity import IdGenerator
from factory.services.context import open_project
from factory.services.project import init_project, project_status
from factory.services.tasks import TaskSpec, create_tasks
from tests.test_index import make_index

WORKERS = 4
ITERATIONS = 15


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


def test_second_index_object_follows_the_others_rebuild(tmp_path: Path) -> None:
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
