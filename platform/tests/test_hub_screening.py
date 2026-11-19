"""Hub screening analytics (plan hub-ui, step 4): kappa, curve, stop point, reasons."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest

from factory.events.envelope import Actor
from factory.model.protocol import Criterion
from factory.model.screening import PassLabel, Verdict
from factory.services import hub_screening as hs
from factory.services.context import Project
from factory.services.ranked_queue import stop_status
from factory.services.screening import live_decisions
from tests.helpers import SourcesFor
from tests.screening_helpers import _decide
from tests.test_screening_ranked import _ranked_world

IN, EX = Verdict.INCLUDE, Verdict.EXCLUDE


def dec(
    n: int,
    work: str,
    label: str,
    verdict: str,
    criterion: str | None = None,
    *,
    stage: str = "title-abstract",
    phase: str = "screening",
    rationale: str = "",
) -> hs.Dec:
    return hs.Dec(
        decision_id=f"d{n}",
        work_id=work,
        pass_label=label,
        phase=phase,
        stage=stage,
        verdict=verdict,
        criterion=criterion,
        quote=f"q-{work}-{label}",
        rationale=rationale or f"r-{work}-{label}",
        order=n,
    )


def paired(a: list[str], b: list[str], **kw: str) -> list[hs.Dec]:
    out: list[hs.Dec] = []
    for i, (x, y) in enumerate(zip(a, b, strict=True)):
        crit_a = "EX01" if x == "exclude" else None
        crit_b = "EX01" if y == "exclude" else None
        out.append(dec(2 * i, f"w{i:02d}", "A", x, crit_a, **kw))
        out.append(dec(2 * i + 1, f"w{i:02d}", "B", y, crit_b, **kw))
    return out


def test_kappa_hand_computed() -> None:
    # 2x2: both include 20, A only 5, B only 10, neither 65 (n = 100).
    # observed = 0.85; A includes 25, B includes 30: chance = .25*.30 + .75*.70 = 0.60.
    # kappa = (0.85 - 0.60) / (1 - 0.60) = 0.625
    a = ["include"] * 20 + ["include"] * 5 + ["exclude"] * 10 + ["exclude"] * 65
    b = ["include"] * 20 + ["exclude"] * 5 + ["include"] * 10 + ["exclude"] * 65
    (result,) = hs.two_screeners(paired(a, b))
    assert result.n == 100 and result.agree == 85 and result.agreement == pytest.approx(0.85)
    assert result.table == {
        "both_proceed": 20,
        "only_a_proceeds": 5,
        "only_b_proceeds": 10,
        "neither_proceeds": 65,
    }
    assert result.kappa == pytest.approx(0.625)
    assert len(result.disagreements) == 15


def test_kappa_undefined_when_chance_agreement_is_complete() -> None:
    (result,) = hs.two_screeners(paired(["exclude"] * 4, ["exclude"] * 4))
    assert result.kappa is None and result.agreement == 1.0 and result.disagreements == ()


def test_per_criterion_and_same_criterion_among_both_excluded() -> None:
    rows = [
        dec(0, "w1", "A", "exclude", "EX01"),
        dec(1, "w1", "B", "exclude", "EX01"),
        dec(2, "w2", "A", "exclude", "EX01"),
        dec(3, "w2", "B", "exclude", "EX02"),
        dec(4, "w3", "A", "include"),
        dec(5, "w3", "B", "exclude", "EX02"),
        dec(6, "w4", "A", "include"),
        dec(7, "w4", "B", "include"),
    ]
    (result,) = hs.two_screeners(rows, ["EX03"])
    assert result.both_excluded == 2 and result.same_criterion == 1
    # EX01: A cites it on w1, w2; B on w1: pairs (T,T)(T,F)(F,F)(F,F); kappa = 0.5.
    assert result.kappa_by_criterion["EX01"] == pytest.approx(0.5)
    assert result.kappa_by_criterion["EX03"] is None
    assert set(result.kappa_by_criterion) == {"EX01", "EX02", "EX03"}
    # the 2x2 counts carry their work ids
    assert result.table_works == {
        "both_proceed": ("w4",),
        "only_a_proceeds": ("w3",),
        "only_b_proceeds": (),
        "neither_proceeds": ("w1", "w2"),
    }
    assert {k: len(v) for k, v in result.table_works.items()} == result.table


def test_disagreements_carry_both_sides_sorted_and_calibration_is_separate() -> None:
    rows = [
        dec(0, "w2", "A", "include", rationale="A says in"),
        dec(1, "w2", "B", "exclude", "EX01", rationale="B says out"),
        dec(2, "w1", "A", "unsure"),
        dec(3, "w1", "B", "include"),
        dec(4, "w3", "A", "include", phase="calibration"),
        dec(5, "w3", "B", "include", phase="calibration"),
        dec(6, "w9", "A", "include", stage="full-text"),
    ]
    groups = hs.two_screeners(rows)
    assert [(g.stage, g.phase, g.n) for g in groups] == [
        ("title-abstract", "calibration", 1),
        ("title-abstract", "screening", 2),
    ]
    first, second = groups[1].disagreements
    assert (first.work_id, first.reason) == ("w1", "unsure")
    assert (second.work_id, second.reason) == ("w2", "outcome")
    assert second.a_rationale == "A says in" and second.b_rationale == "B says out"
    assert second.b_criterion == "EX01" and second.a_quote == "q-w2-A"
    assert groups[0].disagreements == ()


def test_curve_is_monotone_ends_at_total_and_shares() -> None:
    order = [f"w{i}" for i in range(10)]
    curve = hs.ranked_curve(order, {"w0", "w1", "w4", "w9"})
    assert curve.points == (1, 2, 2, 2, 3, 3, 3, 3, 3, 4)
    assert all(x <= y for x, y in zip(curve.points, curve.points[1:], strict=False))
    assert curve.points[-1] == curve.included_total == 4
    # 10% = 1 record, 25% = 3 records, 50% = 5 records.
    assert curve.shares == {"10": 0.25, "25": 0.5, "50": 0.75}
    assert curve.stop_at is None


def test_curve_shares_use_all_records_when_screening_stopped_early() -> None:
    curve = hs.ranked_curve(["a", "b"], {"a"}, total_records=20, stop_at=2, stop_rule="r")
    # 50% of 20 = 10 records, but only 2 were screened: all inclusions found by then.
    assert curve.shares["50"] == 1.0 and curve.stop_at == 2 and curve.total_records == 20
    empty = hs.ranked_curve([], set())
    assert empty.points == () and empty.shares["10"] is None


def test_stop_point_matches_the_platform_walk() -> None:
    sequence = ["a", "b", "c", "d", "e"]
    verdicts = {"a": IN, "b": EX, "c": EX}
    assert stop_status(sequence, verdicts, set(), 2).stopped
    assert hs.screened_prefix(sequence, verdicts) == 3
    assert hs.screened_prefix(sequence, {}) == 0
    assert hs.screened_prefix(sequence, dict.fromkeys(sequence, EX)) == 5


def test_order_uses_rank_then_decision_order() -> None:
    rows = [dec(0, "x", "A", "include"), dec(1, "b", "A", "exclude"), dec(2, "a", "A", "exclude")]
    order, mode = hs.order_screened(rows, {"a": 1, "b": 2})
    assert (order, mode) == (["a", "b", "x"], "ranked")
    order, mode = hs.order_screened(rows, None)
    assert (order, mode) == (["x", "b", "a"], "decision-order")


def test_reasons_wall_counts_examples_and_labels() -> None:
    rows = [
        dec(0, "w3", "A", "exclude", "EX01"),
        dec(1, "w3", "B", "exclude", "EX01"),
        dec(2, "w1", "A", "exclude", "EX01"),
        dec(3, "w2", "A", "exclude", "EX01"),
        dec(4, "w4", "B", "exclude", "EX02"),
        dec(5, "w5", "A", "exclude"),
        dec(6, "w6", "A", "include"),
        dec(7, "w7", "A", "exclude", "EX01", phase="calibration"),
    ]
    crit = Criterion(
        id="EX01",
        parent="NG01",
        statement="Off topic",
        rule="Not about X",
        applies_at="either",
        priority=1,
    )
    wall = hs.reasons_wall(rows, {"EX01": crit}, k=2)
    assert [(g.criterion, g.count) for g in wall] == [("EX01", 3), ("EX02", 1), ("unspecified", 1)]
    first = wall[0]
    assert first.label == "Off topic" and first.rule == "Not about X"
    assert [e.work_id for e in first.examples] == ["w1", "w2"]
    assert wall[1].label is None
    assert hs.reasons_wall(rows, k=0)[0].examples == ()
    assert first.works == ("w1", "w2", "w3")  # every excluded work, not only the examples


def test_superseded_decisions_are_ignored(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordered = _ranked_world(project, agent, human, mock_sources, 2)
    w1, w2, w3 = ordered[:3]
    old = _decide(project, agent, w1, "A", "screening", "include", None, protocol_id)
    _decide(project, agent, w1, "A", "screening", "exclude", "EX01", protocol_id, supersedes=old)
    _decide(project, agent, w2, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, w3, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, w1, "B", "screening", "include", None, protocol_id)
    _decide(project, agent, w2, "B", "screening", "exclude", "EX01", protocol_id)
    decisions = hs.load_decisions(project)
    assert old not in {d.decision_id for d in decisions}
    assert len(decisions) == len(live_decisions(project, stage=None))

    curve = hs.load_curve(project, decisions)
    assert curve.mode == "ranked" and curve.screened == 3
    assert curve.included_total == 0 and curve.points == (0, 0, 0)
    assert curve.stop_at == 3 and curve.stop_rule is not None
    assert "consecutive exclusions" in curve.stop_rule

    payload = hs.screening_payload(project)
    json.dumps(payload)
    assert payload["ranked_curve"]["stop_at"] == 3
    (pair,) = [p for p in payload["two_screeners"] if p["phase"] == "screening"]
    assert pair["n"] == 2 and [d["work_id"] for d in pair["disagreements"]] == [w1]
    assert pair["disagreements"][0]["a_verdict"] == "exclude"
    wall = payload["reasons_wall"]
    assert wall and wall[0]["criterion"] == "EX01" and wall[0]["count"] == 3
    assert set(payload["methods"]) == {"ranked_curve", "two_screeners", "reasons_wall"}
    assert PassLabel.A.value == "A"


@pytest.mark.parametrize(
    ("verdict", "proceeds"),
    [("include", True), ("cannot-assess", True), ("exclude", False), ("unsure", False)],
)
def test_promotes_follows_the_platform_rule(verdict: str, proceeds: bool) -> None:
    assert dec(0, "w", "A", verdict).promotes is proceeds


def test_cannot_assess_proceeds_in_the_pair_table() -> None:
    rows = [
        dec(0, "w", "A", "cannot-assess"),
        dec(1, "w", "B", "include"),
        dec(2, "v", "A", "cannot-assess"),
        dec(3, "v", "B", "exclude", "EX01"),
    ]
    (group,) = hs.two_screeners(rows)
    assert group.table["both_proceed"] == 1 and group.table["only_a_proceeds"] == 1
    assert [d.work_id for d in group.disagreements] == ["v"]


def test_shares_round_the_record_count_up() -> None:
    order = [f"w{i}" for i in range(21)]
    curve = hs.ranked_curve(order, set(order))  # every record included: share = records / 21
    # 10% of 21 = 2.1 -> 3 records, 25% = 5.25 -> 6, 50% = 10.5 -> 11
    assert curve.shares == {"10": 3 / 21, "25": 6 / 21, "50": 11 / 21}


def test_reasons_wall_prefers_pass_a_when_both_passes_excluded() -> None:
    rows = [
        dec(0, "w", "B", "exclude", "EX01", rationale="from b"),
        dec(1, "w", "A", "exclude", "EX01", rationale="from a"),
    ]
    (group,) = hs.reasons_wall(rows)
    assert group.count == 1
    assert [(e.pass_label, e.rationale) for e in group.examples] == [("A", "from a")]


def test_per_criterion_kappa_counts_only_exclude_verdicts() -> None:
    rows = [
        dec(0, "w1", "A", "include", "IN01"),
        dec(1, "w1", "B", "include", "IN01"),
        dec(2, "w2", "A", "exclude", "EX01"),
        dec(3, "w2", "B", "exclude", "EX01"),
    ]
    (group,) = hs.two_screeners(rows)
    assert set(group.kappa_by_criterion) == {"EX01"}


def test_disagreement_reason_splits_unsure_from_outcome() -> None:
    rows = [
        dec(0, "a", "A", "include"),
        dec(1, "a", "B", "unsure"),
        dec(2, "b", "A", "include"),
        dec(3, "b", "B", "exclude", "EX01"),
        dec(4, "c", "A", "unsure"),
        dec(5, "c", "B", "unsure"),
        dec(6, "d", "A", "include"),
        dec(7, "d", "B", "cannot-assess"),
        dec(8, "e", "A", "exclude", "EX01"),
        dec(9, "e", "B", "exclude", "EX02"),
    ]
    (group,) = hs.two_screeners(rows)
    assert {d.work_id: d.reason for d in group.disagreements} == {
        "a": "unsure",
        "b": "outcome",
        "c": "unsure",
    }


def test_load_curve_and_stop_walk_both_leave_out_stale_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [dec(0, "a", "A", "exclude", "EX01"), dec(1, "b", "A", "include")]
    monkeypatch.setattr(hs, "stale_screening_decisions", lambda _p, stage: {"d1"})
    monkeypatch.setattr(hs, "ranking_positions", lambda _p: {"a": 1, "b": 2, "c": 3})
    monkeypatch.setattr(hs, "stage_population", lambda _p, _s: {"a", "b", "c"})
    monkeypatch.setattr(hs, "calibration_items", lambda _p, stage: set())
    stop = type("S", (), {"stopped": True})()
    monkeypatch.setattr(hs, "screening_stops", lambda _p, _s: [stop])
    monkeypatch.setattr(hs, "stop_rules_text", lambda _s: "rule")
    curve = hs.load_curve(cast(Project, None), rows)
    # the stale include of b is in neither: the curve has one record, the walk stops after it
    assert curve.screened == 1 and curve.included_total == 0
    assert curve.stop_at == 1 and curve.total_records == 3


def test_criteria_table_joins_protocol_statements_with_flow_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = SimpleNamespace(
        excluded={"EX01": 5},
        background={"EX01": 2},
        full_text=SimpleNamespace(excluded={"EX02": 3}, background={}),
    )
    crit = {c: SimpleNamespace(id=c, statement=f"s {c}") for c in ("EX01", "EX02", "EX03", "IN01")}
    protocol = SimpleNamespace(spec=SimpleNamespace(criteria=list(crit.values())))
    monkeypatch.setattr(hs, "prisma_flow", lambda _p: flow)
    monkeypatch.setattr(hs, "current_protocol", lambda _p: protocol)
    got = {r["id"]: r for r in hs.criteria_table(cast(Project, None))}
    assert list(got) == ["EX01", "EX02", "EX03"]  # inclusion criteria are not listed
    assert (got["EX01"]["ta_excluded"], got["EX01"]["ta_background"]) == (5, 2)
    assert (got["EX02"]["ft_excluded"], got["EX02"]["ta_excluded"]) == (3, 0)
    assert got["EX03"]["statement"] == "s EX03" and got["EX03"]["ft_background"] == 0


def test_screening_panel_reads_the_services_and_is_json_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress = SimpleNamespace(
        model_dump=lambda mode="json": {"queued": 4, "decided": 3, "remaining": 1}
    )
    status = SimpleNamespace(
        passes={"A": progress},
        full_text_passes=None,
        stale_decisions=2,
        calibration=SimpleNamespace(drawn=10, labelled=9, required=True, passed={"A": True}),
    )
    monkeypatch.setattr(hs, "screening_status", lambda _p: status)
    monkeypatch.setattr(
        hs,
        "latest_ranking",
        lambda _p, top: SimpleNamespace(
            ranking_id="r1", model_id="m", weights_hash="h", software="s", count=7
        ),
    )
    monkeypatch.setattr(hs, "check_list", lambda _p: [])
    monkeypatch.setattr(hs, "current_protocol", lambda _p: None)
    monkeypatch.setattr(hs, "screening_stops", lambda _p: [])
    monkeypatch.setattr(hs, "list_deviations", lambda _p: [1, 2, 3])
    monkeypatch.setattr(hs, "criteria_table", lambda _p: [])
    out = hs.screening_panel(cast(Project, None))
    assert out["ranking"]["weights_hash"] == "h" and out["records_left"] == 1
    assert out["passes"]["A"]["decided"] == 3 and out["full_text_passes"] is None
    assert out["calibration"] == {
        "drawn": 10,
        "labelled": 9,
        "required": True,
        "passed": {"A": True},
    }
    assert out["stale_decisions"] == 2 and out["deviations"] == 3
    assert out["cannot_assess"] == [] and out["checks"] == []
    assert {"ranking", "passes", "stops", "checks", "cannot_assess", "criteria"} <= set(hs.METHODS)
