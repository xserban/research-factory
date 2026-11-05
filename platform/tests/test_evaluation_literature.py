"""Literature hypotheses: work-level comparisons inside the window (slice 6, plan XP-B task 3;
ruling 5; acceptance 18)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from decimal import Decimal
from typing import Any

from factory.hypotheses.literature import LitRow, compare_works
from factory.index.hypotheses import plan_in_force
from factory.services.context import Project
from factory.services.evaluation import (
    evaluate_hypothesis,
    evaluations_of,
    latest_evaluation,
    recompute,
)
from factory.services.hypotheses import draft_hypothesis, hypothesis_view, register_hypothesis
from factory.services.hypothesis_gates import effective_plan
from factory.services.hypothesis_review import record_review, review_next
from tests.experiment_helpers import inject, raw_event
from tests.hypothesis_helpers import CRITIC, DRAFTER, HW, gw, hw, make_spec
from tests.test_hypothesis_review import verdict

KEY = (("task", "classification"),)


def row(work: str, key: str, method: str, value: str | None, independent: bool = True) -> LitRow:
    return LitRow(work, key, method, value, independent)


def compare(rows: list[LitRow], **over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "treatment": "A",
        "baseline": "B",
        "requirements": [("task", frozenset({"classification"}))],
        "window_start": "2024-01-01",
        "dates": {"w1": "2024-05-01", "w2": "2023-05-01", "w3": "2024-01-01", "w4": "2025-01-01"},
        "direction": "higher",
        "margin": Decimal("1"),
    }
    args.update(over)
    return compare_works([(KEY, rows)], **args)


def test_works_before_the_window_are_ignored() -> None:
    rows = [
        row("w1", "rk_1", "A", "80"),
        row("w1", "rk_2", "B", "70"),
        row("w2", "rk_3", "A", "80"),  # published before the window
        row("w2", "rk_4", "B", "70"),
        row("w3", "rk_5", "A", "70"),  # on the window start: inside
        row("w3", "rk_6", "B", "80"),
    ]
    found = compare(rows)
    assert sorted(found) == ["w1", "w3"]
    assert found["w1"][2] == "treatment" and found["w3"][2] == "baseline"


def test_undated_copied_and_one_sided_works_are_left_out() -> None:
    rows = [
        row("w9", "rk_1", "A", "80"),  # undated
        row("w9", "rk_2", "B", "70"),
        row("w1", "rk_3", "A", "80", independent=False),  # copied
        row("w1", "rk_4", "B", "70"),
        row("w4", "rk_5", "A", "80"),  # no baseline row
    ]
    assert compare(rows) == {}


def test_ties_and_lower_is_better_and_first_row_by_key() -> None:
    rows = [
        row("w1", "rk_2", "A", "50"),
        row("w1", "rk_1", "A", "90"),  # smallest row key wins
        row("w1", "rk_3", "B", "90.5"),
        row("w4", "rk_4", "A", "10"),
        row("w4", "rk_5", "B", "20"),
    ]
    found = compare(rows, direction="lower")
    assert found["w1"] == ("rk_1", "rk_3", "tie")
    assert found["w4"][2] == "treatment"


def test_groups_must_hold_the_conditions() -> None:
    rows = [row("w1", "rk_1", "A", "80"), row("w1", "rk_2", "B", "70")]
    assert compare(rows, requirements=[("task", frozenset({"detection"}))]) == {}
    assert compare(rows, requirements=[]) != {}


def test_real_path_literature_evaluation_is_insufficient_without_comparing_works(
    project: Project, human: Any, hw: HW
) -> None:
    spec = make_spec(
        kind="literature",
        lead=hw.lead,
        rationale="literature",
        statement="Lorem beats Low in later literature on classification.",
        decision_rule={"rule": "literature-direction", "n_min": 2, "q": "0.75"},
        test={"kind": "literature", "window_start": "2020-01-01"},
        conditions={"task": "classification"},
    )
    hid, _ = draft_hypothesis(project, DRAFTER, spec)
    for _ in range(2):  # the critic is served the world's draft and this one
        served = review_next(project, CRITIC)
        assert served is not None
        record_review(project, CRITIC, served.task_id, verdict("register"))
    register_hypothesis(project, human, hid)
    event_id = evaluate_hypothesis(project, hid)
    live = latest_evaluation(project, hid)
    assert live is not None and live.event_id == event_id
    p = live.payload
    # the world's works each report one method only, so none compares the two
    assert (p.outcome, p.n, p.works, p.experiment_id) == ("inconclusive", 0, (), None)
    assert "insufficient-evidence" in p.flags and "cutoff-unknown" in p.flags
    assert recompute(project, hid) == p
    view = hypothesis_view(project, hid)
    assert view is not None and view.state == "evaluated"
    project.index.rebuild()
    again = latest_evaluation(project, hid)
    assert again is not None and again.payload == p
    # a hand-written literature evaluation that its own counts do not give changes nothing
    for over in (
        {"outcome": "supported", "inputs_hash": "3" * 16},
        {
            "counts": {"n": 2, "favour_treatment": 2, "favour_baseline": 0, "ties": 0},
            "n": 2,
            "works": ["wrk_a"],
            "inputs_hash": "4" * 16,
        },
    ):
        inject(
            project,
            raw_event(
                project,
                "hypothesis.evaluated",
                project.system_actor(),
                {**p.model_dump(mode="json"), **over},
            ),
        )
    project.index.rebuild()
    assert [e.event_id for e in evaluations_of(project, hid)] == [event_id]


def test_plan_in_force_agrees_with_the_service_plan(project: Project) -> None:
    project.index.sync()
    with project.index.connect() as conn:
        min_seeds, level = plan_in_force(conn)
    plan = effective_plan(project)
    assert (min_seeds, level) == (plan.min_seeds, plan.confidence)
