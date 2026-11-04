"""Slice-1 criterion 1: deleting the index, then `factory rebuild`, gives the same state hash."""

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services.context import Project, open_project
from factory.services.project import init_project
from factory.services.tasks import TaskSpec, claim_next, complete_task, create_tasks, release_task
from tests.helpers import S2, S3, SESSION

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"


def agent_on(project: Project, role: str) -> Actor:
    return Actor(
        kind="agent",
        id=role,
        user="obd",
        session=project.session,
        model="claude-opus-5-5",
        skill="rf-screen@1a2b3c4d",
    )


def test_rebuild_after_deleting_index_yields_same_state_hash(
    tmp_path: Path, clock: FixedClock
) -> None:
    settings = Settings(root=tmp_path, user="obd")
    p1 = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    p2 = open_project(settings, "demo", session=S2, clock=clock)
    ids = create_tasks(p1, p1.system_actor(), [TaskSpec("demo", i) for i in range(5)]).written
    assert len(ids) == 5

    # Events from two sessions in one millisecond sort randomly (R3): step the clock on each switch.
    clock.advance(timedelta(milliseconds=1))
    a, b = agent_on(p1, "screener-a"), agent_on(p2, "screener-b")
    t1 = claim_next(p1, a, "demo")
    clock.advance(timedelta(milliseconds=1))
    t2 = claim_next(p2, b, "demo")
    assert t1 is not None and t2 is not None
    clock.advance(timedelta(milliseconds=1))
    complete_task(p1, a, t1.task_id)
    clock.advance(timedelta(milliseconds=1))
    release_task(p2, b, t2.task_id, "context limit")
    clock.advance(timedelta(minutes=1))
    assert claim_next(p2, b, "demo") is not None

    before = p1.index.state_hash()
    shutil.rmtree(p1.paths.dir / ".index")

    out = CliRunner().invoke(
        app,
        ["--root", str(tmp_path), "rebuild"],
        env={"FACTORY_USER": "obd", "FACTORY_ROOT": None, "FACTORY_PROJECT": None},
    )
    assert out.exit_code == 0, out.stderr
    assert out.stdout.strip() == f"state {before}"

    copy = tmp_path / "elsewhere"
    shutil.copytree(tmp_path / "projects", copy / "projects")
    rebuilt = open_project(Settings(root=copy, user="obd"), "demo", session=S3, clock=clock)
    assert rebuilt.index.rebuild() == before
