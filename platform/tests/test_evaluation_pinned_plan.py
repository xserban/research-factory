"""The confidence level and the minimum seeds are fixed at registration (review C1; R-121, rulings
12, 16, 17). An amendment after the fact cannot rescue an outcome; see decision 93 item 1 for the
same fix to the access limit."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from factory.model.hypothesis_plan import HypothesisPlan
from factory.services.check import check
from factory.services.context import Project
from factory.services.evaluation import (
    evaluate_hypothesis,
    evaluations_of,
    latest_evaluation,
    recompute,
)
from factory.services.hypotheses import draft_hypothesis, hypothesis_view
from factory.services.protocol import amend_protocol, current_protocol
from tests.evaluation_helpers import report_runs, unlocked
from tests.experiment_helpers import XW, inject, raw_event, register_with_review, xw
from tests.hypothesis_helpers import DRAFTER, HW, gw, hw, make_spec

BORDER = {
    ("treatment", 1): "76.9",
    ("baseline", 1): "76.0",
    ("treatment", 2): "77.1",
    ("baseline", 2): "76.0",
    ("treatment", 3): "76.7",
    ("baseline", 3): "76.0",
}
"""Differences 0.9, 1.1, 0.7: inconclusive at 0.95 ([0.403167, ...], margin 0.5), supported at
0.90."""


def _amend(project: Project, actor: Any, **plan: Any) -> None:
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        actor,
        current.spec.model_copy(update={"hypothesis_plan": HypothesisPlan(**plan)}),
        reason="tighter reporting",
        semantic=True,
        effects={},
    )


def test_amending_the_level_after_an_evaluation_changes_nothing(
    project: Project, agent: Any, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, BORDER)
    first = latest_evaluation(project, xw.hid)
    assert first is not None and first.payload.outcome == "inconclusive"
    assert first.payload.level == "0.95"
    _amend(project, agent, confidence="0.90")
    assert recompute(project, xw.hid) == first.payload
    assert evaluate_hypothesis(project, xw.hid) == first.event_id  # nothing new to write
    assert len(evaluations_of(project, xw.hid)) == 1
    project.index.rebuild()
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload == first.payload
    assert "evaluation-stale" not in {f.code for f in check(project).findings}


def test_amending_the_level_before_the_last_cell_changes_nothing(
    project: Project, agent: Any, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, dict(list(BORDER.items())[:4]))
    _amend(project, agent, confidence="0.90")
    report_runs(project, human, tmp_path, exp, dict(list(BORDER.items())[4:]))
    live = latest_evaluation(project, xw.hid)
    assert live is not None
    assert (live.payload.outcome, live.payload.level) == ("inconclusive", "0.95")


def test_amending_min_seeds_does_not_clear_the_flag(
    project: Project, agent: Any, human: Any, xw: XW, tmp_path: Path
) -> None:
    """Registered at the pilot's three seeds; a later plan of two does not excuse two pairs."""
    exp = unlocked(project, human, xw, seeds=[1, 2, 3])
    table = dict(list(BORDER.items())[:4])
    table[("treatment", 3)] = None  # a failed cell: two pairs
    table[("baseline", 3)] = "76.0"
    report_runs(project, human, tmp_path, exp, table)
    _amend(project, agent, min_seeds=2)
    evaluate_hypothesis(project, xw.hid, request_incomplete=True)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and "below-min-seeds" in live.payload.flags


def test_a_later_registration_takes_the_plan_then_in_force(
    project: Project, agent: Any, human: Any, xw: XW, hw: HW
) -> None:
    _amend(project, agent, confidence="0.99")
    hid2, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="second"))
    register_with_review(project, human, hid2)
    first = hypothesis_view(project, xw.hid)
    second = hypothesis_view(project, hid2)
    assert first is not None and second is not None
    assert "95%" in first.falsifier and "99%" in second.falsifier  # the falsifier is pinned too


def _registration_payload(project: Project, hid: str) -> dict[str, Any]:
    from factory.events.reader import read_all

    [event] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "hypothesis.registered" and e.payload["hypothesis_id"] == hid
    ]
    return dict(event.payload)


def test_the_registration_records_the_plan(project: Project, human: Any, xw: XW) -> None:
    payload = _registration_payload(project, xw.hid)
    assert (payload["level"], payload["min_seeds"]) == ("0.95", 3)


def test_a_registration_stating_another_plan_does_not_fold(
    project: Project, human: Any, xw: XW, hw: HW
) -> None:
    hid2, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="second"))
    good = _registration_payload(project, xw.hid)
    for over in ({"level": "0.90"}, {"min_seeds": 2}):
        body = {**good, "hypothesis_id": hid2, "h_version": _version(project, hid2), **over}
        body["review_event_id"] = None
        inject(project, raw_event(project, "hypothesis.registered", human, body))
    project.index.rebuild()
    view = hypothesis_view(project, hid2)
    assert view is not None and view.registration is None


def _version(project: Project, hid: str) -> str:
    view = hypothesis_view(project, hid)
    assert view is not None
    return view.h_version


def test_an_old_registration_replays_with_the_plan_of_its_point_in_the_log(
    project: Project, agent: Any, human: Any, xw: XW, tmp_path: Path
) -> None:
    """A log written before these fields existed: the fold pins the plan in force at that event,
    so a later amendment still changes nothing."""
    _amend(project, agent, confidence="0.90")
    changed = 0
    for path in project.paths.events_dir.rglob("*.jsonl"):
        lines = []
        for line in path.read_text("utf-8").splitlines():
            body = json.loads(line)
            if body["type"] == "hypothesis.registered":
                del body["payload"]["level"], body["payload"]["min_seeds"]
                changed += 1
            lines.append(json.dumps(body))
        path.write_text("\n".join(lines) + "\n", "utf-8")
    assert changed == 1
    project.index.rebuild()
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT level, min_seeds FROM hypothesis_registrations WHERE hypothesis_id = :h"),
            {"h": xw.hid},
        ).one()
    assert (row[0], row[1]) == ("0.95", 3)  # the plan at the registration, not the amended one
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, BORDER)
    live = latest_evaluation(project, xw.hid)
    assert live is not None and live.payload.level == "0.95"
