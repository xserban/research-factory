"""The benchmark ledger (slice 6, plan XP-B task 5; acceptance 20; R-125)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.services.benchmark_ledger import ledger
from factory.services.context import Project
from factory.services.evaluation import latest_evaluation
from factory.services.evidence_report import evidence_report
from factory.services.experiments import accept_baseline, unlock_experiment
from factory.services.extraction_agreement import final_rows
from factory.services.hypotheses import draft_hypothesis
from tests.evaluation_helpers import SUPPORTED, report_runs, unlocked
from tests.experiment_helpers import XW, frozen_design, register_with_review, xw
from tests.hypothesis_helpers import DRAFTER, HW, gw, hw, make_spec
from tests.test_reproduction import _repro


def test_empty_project_has_an_empty_ledger(project: Project) -> None:
    assert ledger(project) == []


def test_reported_and_reproduced_columns(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    before = ledger(project)
    assert {r.reproduction for g in before for r in g.rows} == {"none"}
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1.0", 2: "1.0", 3: "1.0"})
    rows = {r.row_key: r for g in ledger(project) for r in g.rows}
    first = rows[xw.rows[0]]
    assert (first.reproduction, first.reported, first.reproduced) == ("reproduced", "1", "1")
    assert first.experiment_id == exp and first.trace_id
    others = [r for k, r in rows.items() if k != xw.rows[0]]
    assert others and {(r.reproduction, r.reproduced) for r in others} == {("none", None)}


def test_not_reproduced_then_accepted(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "50.0", 2: "50.0", 3: "50.0"})
    state = {r.row_key: r.reproduction for g in ledger(project) for r in g.rows}
    assert state[xw.rows[0]] == "not-reproduced"
    accept_baseline(project, human, exp, xw.rows[0], "the paper used other data")
    state = {r.row_key: r.reproduction for g in ledger(project) for r in g.rows}
    assert state[xw.rows[0]] == "accepted"


def test_own_results_attached_by_conditions(
    project: Project, human: Any, xw: XW, hw: HW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    hid2, _ = draft_hypothesis(
        project,
        DRAFTER,
        make_spec(lead=hw.lead, rationale="detection", conditions={"task": "detection"}),
    )
    register_with_review(project, human, hid2)
    fresh = [
        {"name": "imagenet-dev", "version": "1", "sha256": "a" * 64, "role": "dev"},
        {"name": "imagenet-test2", "version": "1", "sha256": "c" * 64, "role": "confirmatory"},
    ]
    second = unlocked(project, human, XW(hid2, xw.rows), datasets=fresh)
    report_runs(project, human, tmp_path, second, SUPPORTED)
    groups = ledger(project)
    detection = [g for g in groups if ("task", "detection") in g.key]
    other = [g for g in groups if ("task", "detection") not in g.key]
    assert detection and other
    assert all({o.hypothesis_id for o in g.own_results} == {xw.hid, hid2} for g in detection)
    assert all({o.hypothesis_id for o in g.own_results} == {xw.hid} for g in other)  # no condition
    own = next(o for o in detection[0].own_results if o.hypothesis_id == xw.hid)
    live = latest_evaluation(project, xw.hid)
    assert live is not None
    assert (own.outcome, own.mean, own.ci_low, own.n) == ("supported", "1", "0.503167", 3)
    # own results never enter a group's rows
    assert all(
        r.row_key in {x.row_key for x in final_rows(project)} for g in groups for r in g.rows
    )


def test_evidence_report_unchanged(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    before = evidence_report(project).model_dump_json()
    counts_before = [(g.group_id, g.counts, g.frontiers) for g in evidence_report(project).groups]
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1.0", 2: "1.0", 3: "1.0"})
    unlock_experiment(project, human, exp)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    assert latest_evaluation(project, xw.hid) is not None
    assert ledger(project)
    after = evidence_report(project)
    assert after.model_dump_json() == before
    assert [(g.group_id, g.counts, g.frontiers) for g in after.groups] == counts_before


def test_group_filter(project: Project, human: Any, xw: XW) -> None:
    groups = ledger(project)
    assert len(groups) > 1
    [one] = ledger(project, group_id=groups[0].group_id)
    assert one == groups[0]
    with pytest.raises(FactoryValidationError) as err:
        ledger(project, group_id="grp_unknown")
    assert [(i.field, i.reason) for i in err.value.issues] == [("group_id", "unknown")]
    assert ledger(project, agent=True) == groups  # the ledger carries no withheld figure
