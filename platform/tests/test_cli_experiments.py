"""The `factory experiments` and `factory runs` commands (slice 6, plan XP-A task 7)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.experiments import (
    design_experiment,
    experiment_view,
    freeze_experiment,
    unlock_nonce,
)
from factory.services.xruns import register_run, xrun_view
from tests.cli_helpers import _env
from tests.experiment_helpers import XW, cell, frozen_design, results_file, xw
from tests.hypothesis_helpers import DRAFTER, HW, gw, hw

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


def test_list_show_freeze_unlock(settings: Settings, project: Project, xw: XW) -> None:
    root = settings.root
    code, out, _ = _run(root, "experiments", "list")
    assert code == 0 and out.strip() == "no experiment designs"
    exp, version = design_experiment(project, DRAFTER, xw.design(baselines=[]))
    code, out, _ = _run(root, "experiments", "list")
    assert code == 0 and exp in out and version in out and "draft" in out
    code, out, _ = _run(root, "experiments", "show", exp)
    assert code == 0 and f"{exp}  {version}  draft" in out
    assert "factor: attention: softmax -> linear" in out and "seeds: 1, 2, 3" in out
    assert "budget: 0 of 100 GPU-hours; 0 of 40 runs" in out
    assert _run(root, "experiments", "show", "exp_01JZ9Q3K5M7N8P0R2S4T6V8W99")[0] == 1
    code, out, _ = _run(root, "experiments", "unlock", exp)
    assert code == 1  # not frozen yet
    code, out, _ = _run(root, "experiments", "freeze", exp)
    assert code == 0 and out.strip() == f"frozen {exp} {version}"
    event = _of(project, "experiment.frozen")[0]
    assert event.actor.kind == "human" and event.payload["policy"] == "human"
    code, out, _ = _run(root, "experiments", "unlock", exp)
    nonce = unlock_nonce(project, exp)
    assert code == 0 and nonce is not None
    assert f"unlocked {exp}" in out and f"nonce {nonce}" in out and "only time" in out
    code, shown, _ = _run(root, "experiments", "show", exp)
    assert code == 0 and "unlocked" in shown and nonce not in shown  # printed once, then never
    code, out, _ = _run(root, "experiments", "unlock", exp)
    assert code == 1


def test_runs_record_list_and_runner_actor(
    settings: Settings, project: Project, xw: XW, human: Actor, tmp_path: Path
) -> None:
    root = settings.root
    exp = frozen_design(project, human, xw)
    run = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    code, out, _ = _run(root, "runs", "list", exp)
    assert code == 0 and run in out and "planned" in out and "ablation:no-norm" in out
    path = results_file(tmp_path, run, value="71.25")
    code, out, err = _run(root, "runs", "record", str(path), "--runner", "gpu1")
    assert code == 0, err
    [event] = _of(project, "xrun.reported")
    assert (event.actor.kind, event.actor.id) == ("system", "runner-gpu1")
    code, out, _ = _run(root, "runs", "list", exp)
    assert "completed" in out and "top-1 accuracy=71.25" in out
    code, out, _ = _run(root, "runs", "list", exp, "--arm", "baseline")
    assert out.strip() == "no runs"
    code, _, err = _run(root, "runs", "record", str(path))
    assert code == 1 and "already-reported" in err
    code, _, err = _run(root, "runs", "record", str(path), "--runner", "BAD NAME")
    assert code == 1


def test_runs_record_as_the_researcher(
    settings: Settings, project: Project, xw: XW, human: Actor, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    run = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    code, _, err = _run(settings.root, "runs", "record", str(results_file(tmp_path, run)))
    assert code == 0, err
    [event] = _of(project, "xrun.reported")
    assert event.actor.kind == "human"


def test_deviation_and_accept_baseline(
    settings: Settings, project: Project, xw: XW, human: Actor, tmp_path: Path
) -> None:
    root = settings.root
    exp = frozen_design(project, human, xw)
    code, out, _ = _run(
        root, "experiments", "deviation", exp, "--kind", "environment", "--text", "new image"
    )
    assert code == 0 and "recorded environment deviation" in out
    assert (
        _run(root, "experiments", "deviation", exp, "--kind", "test-reuse", "--text", "x")[0] == 2
    )
    assert _run(root, "experiments", "deviation", exp, "--kind", "other", "--text", " ")[0] == 1
    rk = xw.rows[0]
    code, _, err = _run(root, "experiments", "accept-baseline", exp, rk, "--rationale", "too early")
    assert code == 1 and "pending" in err
    for seed in (1, 2, 3):
        run = register_run(project, DRAFTER, exp, cell(f"reproduction:{rk}", seed=seed))
        path = results_file(tmp_path, run, value="2", name=f"r{seed}.json")
        assert _run(root, "runs", "record", str(path))[0] == 0
    code, shown, _ = _run(root, "experiments", "show", exp)
    assert f"baselines: {rk} not-reproduced" in shown
    code, out, _ = _run(
        root, "experiments", "accept-baseline", exp, rk, "--rationale", "other data"
    )
    assert code == 0 and out.strip() == f"accepted baseline {rk} of {exp}"
    code, shown, _ = _run(root, "experiments", "show", exp)
    assert f"baselines: {rk} accepted" in shown and "baseline-not-reproduced" in shown
    assert "deviation (baseline-accepted" in shown
    view = experiment_view(project, exp)
    assert view is not None and [d.kind for d in view.deviations] == [
        "environment",
        "baseline-accepted",
    ]
