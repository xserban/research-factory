"""Slice 6 acceptance on constructed runs (plan XP-B task 8; acceptance 15, 17-25 in fixture form).

One project runs the pilot flow of the slice on the evidence world: a promoted lead citing a work, a
hypothesis drafted, reviewed by an independent critic and registered by the human, a design with a
baseline and a two-axis multiverse, freeze, reproduction runs, unlock, exploratory runs of another
universe, ablation and control runs, the primary runs, the computed evaluation (refuted), the
registry row, a later lead whose `prior` lists it, the state hash after a rebuild, and the
differential test: the evidence report, the final rows, the live claims and the PRISMA counts are
byte-identical with and without every slice-6 event.

The card, matching, finder and import stages have their own acceptance tests (plans H-A, H-B); their
worlds are not this evidence world, so they are not repeated here (cross-project card import is
Later).
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.hypotheses import Trigger, TriggerKind
from factory.services.benchmark_ledger import ledger
from factory.services.context import Project, open_project
from factory.services.directions import registry_query
from factory.services.evaluation import latest_evaluation
from factory.services.evidence_report import evidence_report
from factory.services.experiments import unlock_experiment
from factory.services.extraction import live_claims
from factory.services.extraction_agreement import final_rows
from factory.services.leads import lead_view, record_lead
from factory.services.methods import methods_report, render_methods
from factory.services.multiverse import ablations, controls, specification_curve
from factory.services.prisma import prisma_flow
from factory.services.trace import trace
from tests.evaluation_helpers import REFUTED, SUPPORTED, own_result, report_runs
from tests.experiment_helpers import XW, frozen_design, xw
from tests.helpers import SESSION, T0
from tests.hypothesis_helpers import HW, LEAD_AUTHOR, LEAD_TEXT, gw, hw, lead_input
from tests.test_reproduction import _repro

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

SLICE6_PREFIXES = (
    "lead.",
    "hypothesis.",
    "model.",
    "experiment.",
    "xrun.",
    "baseline.",
    "direction.",
    "card.",
    "contradiction.",
    "vocabulary.",
)


def _without_slice6(settings: Settings, project: Project, tmp_path: Path) -> Project:
    """A copy of the project whose log lacks every slice-6 event."""
    source = settings.root / "projects" / "demo"
    target_root = tmp_path / "copy"
    shutil.copytree(
        source,
        target_root / "projects" / "demo",
        ignore=shutil.ignore_patterns("*.sqlite", "*.sqlite-*", "*.db", "*.db-*", "index*"),
    )
    removed = 0
    for path in (target_root / "projects" / "demo" / "events").rglob("*.jsonl"):
        kept: list[str] = []
        for line in path.read_text("utf-8").splitlines(keepends=True):
            if json.loads(line)["type"].startswith(SLICE6_PREFIXES):
                removed += 1
            else:
                kept.append(line)
        path.write_text("".join(kept), "utf-8")
    assert removed > 20
    return open_project(
        Settings(root=target_root, user="obd"), "demo", session=SESSION, clock=FixedClock(T0)
    )


def test_pilot_flow_with_constructed_runs(
    settings: Settings, project: Project, human: Actor, xw: XW, hw: HW, tmp_path: Path
) -> None:
    before_report = evidence_report(project).model_dump_json()
    before_rows = [r.model_dump_json() for r in final_rows(project)]
    before_claims = [c.model_dump_json() for c in live_claims(project)]
    before_prisma = prisma_flow(project).model_dump_json()

    exp = frozen_design(project, human, xw)  # a baseline and a two-axis-style multiverse
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1.0", 2: "1.0", 3: "1.0"})
    unlock_experiment(project, human, exp)
    # the other universe, the ablation and the controls run on the dev split
    report_runs(project, human, tmp_path, exp, SUPPORTED, split="dev", resolution="384")
    report_runs(
        project, human, tmp_path, exp, {("baseline", s): "76.0" for s in (1, 2, 3)}, split="dev"
    )
    report_runs(
        project,
        human,
        tmp_path,
        exp,
        {("control:planted", s): "78.0" for s in (1, 2, 3)},
        split="dev",
    )
    report_runs(
        project,
        human,
        tmp_path,
        exp,
        {("control:shuffled", s): "76.0" for s in (1, 2, 3)},
        split="dev",
    )
    report_runs(
        project,
        human,
        tmp_path,
        exp,
        {("ablation:no-norm", s): "75.0" for s in (1, 2, 3)},
        split="dev",
    )
    report_runs(project, human, tmp_path, exp, REFUTED)  # the primary runs: the last cell evaluates

    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.outcome == "refuted"
    assert set(live.payload.flags) == {"fragile", "only-non-primary"}
    assert {c.name: c.passed for c in controls(project, exp)} == {"planted": True, "shuffled": True}
    assert len(specification_curve(project, exp).points) == 2
    assert [a.name for a in ablations(project, exp)] == ["no-norm"]

    # registry: a refuted hypothesis is a row with its conditions, and a later lead's prior lists it
    rows = {r.direction_id: r for r in registry_query(project, keys=[xw.hid]).rows}
    assert rows[xw.hid].reason == "below-baseline" and rows[xw.hid].conditions.e_version
    later = record_lead(
        project, LEAD_AUTHOR, lead_input(LEAD_TEXT, Trigger(kind=TriggerKind.WORK, ref=hw.works[0]))
    )
    view = lead_view(project, later)
    assert view is not None and xw.hid in view.prior

    # the benchmark ledger: reported and reproduced apart, the own result beside the group
    second = own_result(project, human, hw, xw, tmp_path, REFUTED)
    own = {o.hypothesis_id: o.outcome for g in ledger(project) for o in g.own_results}
    assert own == {second: "refuted"}  # the first reports another metric than the world's groups
    reproduced = {r.row_key: r.reproduction for g in ledger(project) for r in g.rows}
    assert reproduced[xw.rows[0]] == "reproduced"

    # methods count the refuted outcome; trace reaches the question from the outcome
    methods = methods_report(project).hypotheses
    assert methods is not None and methods.outcomes == {"refuted": 2}
    assert "refuted 2" in render_methods(methods_report(project))
    kinds: set[str] = set()

    def walk(node: Any) -> None:
        kinds.add(node.kind)
        for child in node.children:
            walk(child)

    walk(trace(project, live.event_id))
    assert {"xrun", "experiment", "hypothesis", "lead", "work"} <= kinds

    # rebuild: the same tables and state hash
    live_hash = project.index.state_hash()
    assert project.index.rebuild() == live_hash
    again = latest_evaluation(project, xw.hid)
    assert again is not None and again.payload == live.payload

    # differential: nothing of the evidence changes with the slice-6 events
    assert evidence_report(project).model_dump_json() == before_report
    assert [r.model_dump_json() for r in final_rows(project)] == before_rows
    assert [c.model_dump_json() for c in live_claims(project)] == before_claims
    assert prisma_flow(project).model_dump_json() == before_prisma
    bare = _without_slice6(settings, project, tmp_path)
    assert evidence_report(bare).model_dump_json() == before_report
    assert [r.model_dump_json() for r in final_rows(bare)] == before_rows
    assert [c.model_dump_json() for c in live_claims(bare)] == before_claims
    assert prisma_flow(bare).model_dump_json() == before_prisma
