"""`factory activity` (IDEA-98): the plain-text panels. Read-only."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock, SystemClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services.activity import Activity
from factory.services.project import init_project
from factory.services.tasks import TaskSpec, claim_next, create_tasks
from tests.helpers import SESSION, T0

runner = CliRunner()


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def test_an_empty_project_says_each_panel_is_empty(tmp_path: Path) -> None:
    init_project(
        Settings(root=tmp_path, user="obd"), "alpha", "pilot", session=SESSION, clock=FixedClock(T0)
    )
    result = runner.invoke(app, ["--project", "alpha", "activity"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    for line in (
        "no task is held",
        "no pass is open",
        "no long operation is running",
        "no trace file changed",
    ):
        assert line in result.output


def test_a_held_task_is_listed_and_nothing_is_written(
    tmp_path: Path, settings: Settings, agent: Actor
) -> None:
    # a real clock: the command reads `now` itself and a lease from 2026-10 would have expired
    project = init_project(settings, "alpha", "pilot", session=SESSION, clock=SystemClock())
    create_tasks(
        project,
        project.system_actor(),
        [TaskSpec("demo", {"records": [{"work_id": "wrk_1", "title": "A paper"}]})],
    )
    assert claim_next(project, agent, "demo") is not None
    before = {p: p.read_bytes() for p in project.paths.events_dir.rglob("*") if p.is_file()}
    result = runner.invoke(app, ["--project", "alpha", "activity"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "A paper" in result.output and "demo" in result.output
    assert before == {p: p.read_bytes() for p in project.paths.events_dir.rglob("*") if p.is_file()}


def test_format_activity_labels_estimates() -> None:
    from factory.cli.activity import format_activity
    from factory.services.activity import PassRow

    found = Activity(
        now="t",
        active=[],
        passes=[
            PassRow(
                kind="miner",
                name="m-x",
                version=1,
                done=1,
                total=3,
                claimed=0,
                pass_label="A",
                mode="calibration",
                abandoned=2,
                completed_recent=0,
                rate_estimate_per_hour=0.0,
                eta_estimate_minutes=None,
                released=0,
            )
        ],
        dormant=[],
        operations=[],
        traces=[],
    )
    text = "\n".join(format_activity(found))
    assert "rate (estimate) 0.0/h" in text and "left (estimate) unknown" in text
    assert "m-x v1 pass A calibration: 1/3 done, 0 held, 2 abandoned" in text
    assert "dormant" not in text


def test_format_activity_summarises_dormant_passes_in_one_line() -> None:
    from factory.cli.activity import format_activity
    from factory.services.activity import PassRow

    row = PassRow(
        kind="demo",
        name="demo",
        done=3,
        total=3,
        claimed=0,
        completed_recent=0,
        rate_estimate_per_hour=0.0,
        eta_estimate_minutes=None,
        released=0,
    )
    found = Activity(now="t", active=[], passes=[], dormant=[row, row], operations=[], traces=[])
    lines = format_activity(found)
    assert sum("dormant" in line for line in lines) == 1
    assert "  2 dormant passes" in " ".join(lines)
