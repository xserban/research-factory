"""Shared builders for the evaluation tests (slice 6, plan XP-B): the XP-A fixtures plus
`report_runs`, which registers and ingests runs from a table of values."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.experiments import unlock_experiment, unlock_nonce
from factory.services.hypotheses import draft_hypothesis
from factory.services.xruns import ingest_results, register_run
from tests.experiment_helpers import (
    XW,
    cell,
    frozen_design,
    register_with_review,
    results_file,
    xe,
    xw,
)
from tests.hypothesis_helpers import DRAFTER, HW, gw, hw, make_spec

Table = Mapping[tuple[str, int], str | None]
"""(arm, seed) to the primary metric of the run; `None` is a failed run."""

SUPPORTED: dict[tuple[str, int], str | None] = {
    ("treatment", 1): "77.0",
    ("baseline", 1): "76.0",
    ("treatment", 2): "77.2",
    ("baseline", 2): "76.0",
    ("treatment", 3): "76.8",
    ("baseline", 3): "76.0",
}
"""Per-seed differences 1.0, 1.2, 0.8: at the 0.95 level the interval is [0.503167, 1.496833], so
the rule (superiority, margin 0.5) holds."""

REFUTED: dict[tuple[str, int], str | None] = {
    ("treatment", 1): "75.0",
    ("baseline", 1): "76.0",
    ("treatment", 2): "74.8",
    ("baseline", 2): "76.0",
    ("treatment", 3): "75.2",
    ("baseline", 3): "76.0",
}
"""Differences -1.0, -1.2, -0.8: the interval is [-1.496833, -0.503167], below the margin."""

_counter = {"n": 0}


def report_runs(
    project: Project,
    human: Actor,
    tmp_path: Path,
    exp: str,
    table: Table,
    *,
    split: str = "confirmatory",
    resolution: str = "224",
    metric: str | None = None,
) -> dict[tuple[str, int], str]:
    """Register one run per entry of `table` (in the table's order) and report it. A confirmatory
    run carries the unlock nonce."""
    runs: dict[tuple[str, int], str] = {}
    for (arm, seed), value in table.items():
        _counter["n"] += 1
        run = register_run(
            project, DRAFTER, exp, cell(arm, seed=seed, split=split, resolution=resolution)
        )
        nonce = unlock_nonce(project, exp) if split == "confirmatory" else None
        extra: dict[str, Any] = (
            {"metrics": {}, "exit_status": 1} if value is None else {"value": value}
        )
        if metric is not None and value is not None:
            extra = {"metrics": {metric: {"value": value, "unit": "%"}}}
        path = results_file(tmp_path, run, nonce=nonce, name=f"run{_counter['n']}.json", **extra)
        ingest_results(project, human, path)
        runs[(arm, seed)] = run
    return runs


def unlocked(project: Project, human: Actor, w: XW, **over: Any) -> str:
    """A frozen and unlocked design of `w` with no baseline to reproduce."""
    over.setdefault("baselines", [])
    exp = frozen_design(project, human, w, **over)
    unlock_experiment(project, human, exp)
    return exp


LOW_DESIGN_METRIC = {
    "name": "Low",
    "direction": "higher",
    "unit_family": "score",
    "unit": "%",
    "primary": True,
}


def own_result(
    project: Project,
    human: Actor,
    hw: HW,
    w: XW,
    tmp_path: Path,
    table: Table,
    *,
    letter: str = "c",
    **spec: Any,
) -> str:
    """A second hypothesis on the metric the evidence world's groups report (`Low`), run on its own
    confirmatory data: an own result the benchmark ledger can attach."""
    metric = {"name": "Low", "direction": "higher", "unit_family": "score", "unit": "points"}
    hid, _ = draft_hypothesis(
        project, DRAFTER, make_spec(lead=hw.lead, rationale="own", metric=metric, **spec)
    )
    register_with_review(project, human, hid)
    datasets = [
        {"name": "imagenet-dev", "version": "1", "sha256": "a" * 64, "role": "dev"},
        {"name": f"test-{letter}", "version": "1", "sha256": letter * 64, "role": "confirmatory"},
    ]
    exp = unlocked(project, human, XW(hid, w.rows), datasets=datasets, metrics=[LOW_DESIGN_METRIC])
    report_runs(project, human, tmp_path, exp, table, metric="Low")
    return hid
