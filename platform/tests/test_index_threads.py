"""One `Index` shared by several threads (the site hub serves requests on threads): the lock
hold and the snapshot flag belong to the thread that took them."""

import threading
from pathlib import Path

from factory.clock import SystemClock
from factory.config import Settings
from factory.model.identity import IdGenerator
from factory.services.context import Project
from factory.services.project import init_project, project_status
from factory.services.tasks import TaskSpec, create_tasks

WAIT = 0.3


def _project(tmp_path: Path) -> Project:
    clock = SystemClock()
    settings = Settings(root=tmp_path, user="obd")
    return init_project(settings, "demo", "pilot", session=IdGenerator(clock).ulid(), clock=clock)


def test_another_thread_waits_for_the_hold(tmp_path: Path) -> None:
    project = _project(tmp_path)
    held, release, done = threading.Event(), threading.Event(), threading.Event()

    def hold() -> None:
        with project.index.exclusive():
            held.set()
            release.wait(5)

    def sync() -> None:
        project.index.sync()
        done.set()

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(5)
    other = threading.Thread(target=sync, daemon=True)
    other.start()
    assert not done.wait(WAIT)  # it must not borrow the holder's lock
    release.set()
    assert done.wait(5)
    holder.join(5)


def test_a_snapshot_in_one_thread_does_not_refuse_another_threads_write(tmp_path: Path) -> None:
    project = _project(tmp_path)
    inside, release = threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def read() -> None:
        with project.index.snapshot():
            inside.set()
            release.wait(5)

    def write() -> None:
        try:
            with project.index.exclusive():
                pass
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    assert inside.wait(5)
    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    release.set()
    writer.join(5)
    reader.join(5)
    assert errors == []


def test_threads_recording_on_one_project_never_fold_an_event_twice(tmp_path: Path) -> None:
    project = _project(tmp_path)
    errors: list[str] = []

    def work(n: int) -> None:
        for i in range(10):
            try:
                create_tasks(project, project.human_actor(), [TaskSpec("k", {"n": n, "i": i})])
                project.index.sync()
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []
    assert project_status(project).tasks.open == 40
    assert project.index.state_hash() == project.index.rebuild()
