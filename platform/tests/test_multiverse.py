"""Specification curve, ablations and controls (slice 6, plan XP-B task 4; acceptance 19)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.services.context import Project
from factory.services.evaluation import latest_evaluation
from factory.services.multiverse import ablations, controls, specification_curve
from tests.evaluation_helpers import REFUTED, SUPPORTED, report_runs, unlocked
from tests.experiment_helpers import XW, xw
from tests.hypothesis_helpers import HW, gw, hw

INCONCLUSIVE = {
    ("treatment", 1): "76.9",
    ("baseline", 1): "76.0",
    ("treatment", 2): "76.1",
    ("baseline", 2): "76.0",
    ("treatment", 3): "76.5",
    ("baseline", 3): "76.0",
}
"""Differences 0.9, 0.1, 0.5: the interval [-0.493666, 1.493666] holds the margin 0.5."""


def _dev(project: Project, human: Any, tmp_path: Path, exp: str, table: Any, **kw: Any) -> None:
    report_runs(project, human, tmp_path, exp, table, split="dev", **kw)


def test_only_non_primary_flag(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    _dev(project, human, tmp_path, exp, SUPPORTED, resolution="384")
    report_runs(project, human, tmp_path, exp, INCONCLUSIVE)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.outcome == "inconclusive"
    assert live.payload.flags == ("only-non-primary",)
    curve = specification_curve(project, exp)
    assert curve.flags == ("only-non-primary",)
    by_universe = {p.universe["resolution"]: p for p in curve.points}
    assert by_universe["384"].outcome_descriptive == "supported"
    assert by_universe["224"].outcome_descriptive == "inconclusive"


def test_fragile_flag(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    _dev(project, human, tmp_path, exp, REFUTED, resolution="384")
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.outcome == "supported"
    assert live.payload.flags == ("fragile",)  # signs differ; the rule holds in the primary one


def test_no_flag_when_universes_agree(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    _dev(project, human, tmp_path, exp, SUPPORTED, resolution="384")
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.flags == ()


def test_curve_sorted_and_primary_marked(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    assert specification_curve(project, exp).points == []  # empty with nothing run
    _dev(project, human, tmp_path, exp, REFUTED, resolution="384")
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    points = specification_curve(project, exp).points
    assert [(p.universe["resolution"], p.primary, p.split) for p in points] == [
        ("384", False, "dev"),
        ("224", True, "confirmatory"),
    ]
    assert [p.mean for p in points] == ["-1", "1"]


def test_exploratory_runs_never_in_curve(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    wild = {k: ("99.0" if k[0] == "treatment" else "1.0") for k in SUPPORTED}
    _dev(project, human, tmp_path, exp, wild)  # dev runs of the primary universe: exploratory
    one_pair = {("treatment", 1): "80.0", ("baseline", 1): "70.0"}
    _dev(project, human, tmp_path, exp, one_pair, resolution="384")  # fewer than two pairs
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    points = specification_curve(project, exp).points
    assert [(p.universe["resolution"], p.n, p.mean) for p in points] == [("224", 3, "1")]
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.flags == ()


def test_ablation_effect_oriented(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp = unlocked(project, human, xw)
    _dev(
        project,
        human,
        tmp_path,
        exp,
        {("treatment", s): v for (a, s), v in SUPPORTED.items() if a == "treatment"},
    )
    _dev(project, human, tmp_path, exp, {("ablation:no-norm", s): "76.0" for s in (1, 2, 3)})
    [result] = ablations(project, exp)
    assert (result.name, result.key, result.n) == ("no-norm", "use_norm", 3)
    assert (result.mean, result.ci_low, result.ci_high) == ("-1", "-1.496833", "-0.503167")


def test_positive_and_negative_control_pass_fail(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    assert [c.passed for c in controls(project, exp)] == [None, None]  # not run: not passed
    _dev(project, human, tmp_path, exp, {("baseline", s): "76.0" for s in (1, 2, 3)})
    _dev(
        project,
        human,
        tmp_path,
        exp,
        {
            ("control:planted", 1): "78.0",
            ("control:planted", 2): "78.2",
            ("control:planted", 3): "77.8",
        },
    )
    _dev(
        project,
        human,
        tmp_path,
        exp,
        {
            ("control:shuffled", 1): "76.1",
            ("control:shuffled", 2): "75.9",
            ("control:shuffled", 3): "76.0",
        },
    )
    by_name = {c.name: c for c in controls(project, exp)}
    assert (by_name["planted"].kind, by_name["planted"].passed) == ("positive", True)
    assert (by_name["shuffled"].kind, by_name["shuffled"].passed) == ("negative", True)
    assert by_name["planted"].n == 3 and by_name["planted"].mean == "2"


def test_failed_control_flags_the_outcome(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    _dev(project, human, tmp_path, exp, {("baseline", s): "76.0" for s in (1, 2, 3)})
    # the positive control shows no effect, the negative control shows one
    _dev(project, human, tmp_path, exp, {("control:planted", s): "76.0" for s in (1, 2, 3)})
    _dev(
        project,
        human,
        tmp_path,
        exp,
        {
            ("control:shuffled", 1): "78.0",
            ("control:shuffled", 2): "78.2",
            ("control:shuffled", 3): "77.8",
        },
    )
    by_name = {c.name: c.passed for c in controls(project, exp)}
    assert by_name == {"planted": False, "shuffled": False}
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.flags == ("control-failed",)
