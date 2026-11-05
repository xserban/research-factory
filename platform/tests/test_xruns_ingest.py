"""Results-file ingestion with runner provenance (slice 6, plan XP-A task 4)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.experiments import CanonicalMetric, XrunReported
from factory.services.context import Project
from factory.services.experiments import experiment_view
from factory.services.xruns import ingest_results, register_run, xrun_view
from tests.experiment_helpers import (
    COMMIT,
    XW,
    cell,
    frozen_design,
    results_file,
    xe,
    xw,
)
from tests.hypothesis_helpers import DRAFTER, HW, OTHER, gw, hw


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


@pytest.fixture
def run(project: Project, human: Actor, xw: XW) -> tuple[str, str]:
    """A frozen design and one planned dev-split ablation run of it."""
    exp = frozen_design(project, human, xw)
    return exp, register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))


def test_ingest_stores_blob_and_canonical_metrics(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:
    exp, xrn = run
    path = results_file(tmp_path, xrn, value="76.50")
    event_id = ingest_results(project, human, path)
    [event] = _events(project, "xrun.reported")
    assert event.id == event_id and event.actor.kind == "human" and event.input_blob is None
    payload = XrunReported.model_validate(event.payload)
    assert project.blobs.get(payload.results_blob) == path.read_bytes()
    assert payload.metrics == {
        "top-1 accuracy": CanonicalMetric(printed="76.50", unit="%", value="76.5")
    }
    assert (payload.gpu_hours, payload.exit_status, payload.flags) == ("1.5", 0, ())
    view = xrun_view(project, xrn)
    assert view is not None and view.state == "completed"
    assert view.metrics == {"top-1 accuracy": "76.5"} and view.gpu_hours == "1.5"
    assert view.reported_event_id == event_id
    exp_view = experiment_view(project, exp)
    assert exp_view is not None and exp_view.budget.gpu_hours_used == "1.5"


def test_missing_or_undeclared_metric_refused(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:
    _, xrn = run
    missing = results_file(tmp_path, xrn, metrics={})
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, missing)
    assert _fields(err) == [("metrics.top-1 accuracy", "missing")]
    extra = results_file(
        tmp_path,
        xrn,
        metrics={
            "top-1 accuracy": {"value": "70", "unit": "%"},
            "top-5 accuracy": {"value": "90", "unit": "%"},
        },
    )
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, extra)
    assert _fields(err) == [("metrics.top-5 accuracy", "undeclared")]
    bad_unit = results_file(tmp_path, xrn, metrics={"top-1 accuracy": {"value": "7", "unit": "K"}})
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, bad_unit)
    assert _fields(err) == [("metrics.top-1 accuracy", "unit-invalid")]
    no_unit = results_file(tmp_path, xrn, metrics={"top-1 accuracy": {"value": "7"}})
    with pytest.raises(FactoryValidationError) as err:  # the design declares %
        ingest_results(project, human, no_unit)
    assert _fields(err) == [("metrics.top-1 accuracy", "unit-invalid")]
    text = results_file(tmp_path, xrn, metrics={"top-1 accuracy": {"value": "high", "unit": "%"}})
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, text)
    assert _fields(err) == [("metrics.top-1 accuracy", "not-a-number")]
    assert _events(project, "xrun.reported") == []


def test_agent_actor_refused(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:  # spec ruling 19
    _, xrn = run
    path = results_file(tmp_path, xrn)
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, DRAFTER, path)
    assert _fields(err) == [("actor", "human-or-runner-only")]
    with pytest.raises(FactoryValidationError) as err:  # an agent cannot borrow a runner's name
        ingest_results(project, DRAFTER, path, runner="gpu1")
    assert _fields(err) == [("actor", "human-or-runner-only")]
    assert _events(project, "xrun.reported") == []


def test_runner_actor_recorded(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:
    _, xrn = run
    ingest_results(project, human, results_file(tmp_path, xrn), runner="gpu1")
    [event] = _events(project, "xrun.reported")
    assert (event.actor.kind, event.actor.id) == ("system", "runner-gpu1")
    assert event.actor.session == project.session
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, results_file(tmp_path, xrn), runner="GPU 1")
    assert _fields(err) == [("runner", "lowercase words joined by single hyphens")]


def test_failed_run_recorded_and_counted(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:
    exp, xrn = run
    path = results_file(tmp_path, xrn, metrics={}, exit_status=137, gpu_hours="2")
    ingest_results(project, human, path)
    view = xrun_view(project, xrn)
    assert view is not None and view.state == "failed" and view.flags == ("failed",)
    exp_view = experiment_view(project, exp)
    assert exp_view is not None
    assert (exp_view.budget.gpu_hours_used, exp_view.budget.runs_registered) == ("2", 1)


def test_environment_differs_recorded_not_dropped(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:  # Review Focus 4; acceptance 15
    exp, xrn = run
    other = register_run(project, DRAFTER, exp, cell("ablation:no-norm", seed=2, split="dev"))
    ingest_results(project, human, results_file(tmp_path, xrn, commit="deadbee"))
    ingest_results(project, human, results_file(tmp_path, other, environment="sha256:other"))
    for ident in (xrn, other):
        view = xrun_view(project, ident)
        assert view is not None and view.state == "completed"
        assert view.flags == ("environment-differs",)
        assert view.metrics == {"top-1 accuracy": "76.5"}  # kept, not dropped


def test_second_report_for_run_refused(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:
    _, xrn = run
    ingest_results(project, human, results_file(tmp_path, xrn))
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, results_file(tmp_path, xrn, value="99"))
    assert _fields(err) == [("run", "already-reported")]
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(
            project, human, results_file(tmp_path, "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W99", name="b.json")
        )
    assert _fields(err) == [("run", "unknown")]
    assert len(_events(project, "xrun.reported")) == 1


def test_oversized_and_malformed_files_refused(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:
    _, xrn = run
    big = results_file(tmp_path, xrn, name="big.json", artifacts=[], padding="x" * 70_000)
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, big)
    assert _fields(err) == [("path", "too-large")]
    not_json = tmp_path / "bad.json"
    not_json.write_text("{nope")
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, not_json)
    assert _fields(err) == [("path", "not-json")]
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, tmp_path / "absent.json")
    assert _fields(err) == [("path", "unreadable")]
    wrong_schema = results_file(tmp_path, xrn, name="w.json", schema=2)
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, wrong_schema)
    assert [f for f, _ in _fields(err)] == ["file.schema"]
    unknown_key = results_file(tmp_path, xrn, name="u.json", padding="x")
    with pytest.raises(FactoryValidationError) as err:
        ingest_results(project, human, unknown_key)
    assert [f for f, _ in _fields(err)] == ["file.padding"]
    assert _events(project, "xrun.reported") == []


def test_projector_ignores_a_forged_report(
    project: Project, human: Actor, run: tuple[str, str], tmp_path: Path
) -> None:
    _, xrn = run
    blob = project.blobs.put(b"{}")
    good = XrunReported(
        run_id=xrn,
        results_blob=blob,
        metrics={"top-1 accuracy": CanonicalMetric(printed="1", value="1", unit="%")},
        gpu_hours="1",
        exit_status=0,
        code_commit=COMMIT,
        environment="sha256:lockfile-1",
    )
    agent_blob = project.blobs.put_json({})
    project.record([project.events.make("xrun.reported", good, OTHER, input_blob=agent_blob)])
    undeclared = good.model_copy(
        update={"metrics": {"made-up": CanonicalMetric(printed="1", value="1")}}
    )
    project.record([project.events.make("xrun.reported", undeclared, human)])
    view = xrun_view(project, xrn)
    assert view is not None and view.state == "planned" and view.metrics is None
    assert len(_events(project, "xrun.reported")) == 2
    project.record([project.events.make("xrun.reported", good, human)])  # the honest one folds
    assert xrun_view(project, xrn).state == "completed"  # type: ignore[union-attr]
