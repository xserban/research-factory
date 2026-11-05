"""Literature evaluation through the real evidence report (review C2, I5; ruling 16, R-121)."""

# ruff: noqa: F401

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from factory.services.benchmark_ledger import ledger
from factory.services.context import Project
from factory.services.evaluation import evaluate_hypothesis, latest_evaluation, recompute
from factory.services.hypotheses import declare_cutoff
from tests.card_helpers import cw
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.literature_helpers import LOW, literature_hypothesis, literature_world

TOP1 = {"name": "top-1 accuracy", "direction": "higher", "unit_family": "score", "unit": "points"}


@pytest.fixture
def lw(project: Project, agent: Any, agent_other: Any, human: Any, mock_sources: Any) -> list[str]:
    return literature_world(project, agent, agent_other, human, mock_sources, ["t", "t", "t", "b"])


def _live(project: Project, hid: str) -> Any:
    live = latest_evaluation(project, hid)
    assert live is not None
    return live.payload


def test_supported_through_the_evidence_report(project: Project, human: Any, lw: list[str]) -> None:
    hid = literature_hypothesis(project, human, lw)
    evaluate_hypothesis(project, hid)
    p = _live(project, hid)
    assert (p.outcome, p.n) == ("supported", 4)
    assert p.counts["favour_treatment"] == 3 and p.counts["favour_baseline"] == 1
    assert recompute(project, hid) == p
    project.index.rebuild()
    assert _live(project, hid) == p


def test_refuted_through_the_evidence_report(
    project: Project, agent: Any, agent_other: Any, human: Any, mock_sources: Any
) -> None:
    works = literature_world(project, agent, agent_other, human, mock_sources, ["b", "b", "b", "t"])
    hid = literature_hypothesis(project, human, works)
    evaluate_hypothesis(project, hid)
    assert _live(project, hid).outcome == "refuted"


def test_contaminated_flag_on_the_payload(project: Project, human: Any, lw: list[str]) -> None:
    hid = literature_hypothesis(project, human, lw)
    for model in ("model-drafter", "model-critic"):
        declare_cutoff(project, human, model, date(2024, 1, 1), "vendor note")
    evaluate_hypothesis(project, hid)
    flags = _live(project, hid).flags
    assert "contaminated" in flags and "cutoff-unknown" not in flags


def test_the_window_excludes_earlier_works(project: Project, human: Any, lw: list[str]) -> None:
    hid = literature_hypothesis(
        project, human, lw, test={"kind": "literature", "window_start": "2099-01-01"}
    )
    evaluate_hypothesis(project, hid)
    assert _live(project, hid).n == 0


def test_a_group_of_another_metric_does_not_count(
    project: Project, human: Any, lw: list[str]
) -> None:
    """The review's case: a group keyed metric=low counted for a top-1 accuracy hypothesis."""
    hid = literature_hypothesis(project, human, lw, metric=TOP1)
    evaluate_hypothesis(project, hid)
    p = _live(project, hid)
    assert (p.outcome, p.n, p.works) == ("inconclusive", 0, ())
    assert "insufficient-evidence" in p.flags


def test_own_results_attach_only_to_groups_of_their_metric(
    project: Project, human: Any, lw: list[str]
) -> None:
    same = literature_hypothesis(project, human, lw)
    other = literature_hypothesis(project, human, lw, metric=TOP1, rationale="other metric")
    evaluate_hypothesis(project, same)
    evaluate_hypothesis(project, other)
    attached = {o.hypothesis_id for g in ledger(project) for o in g.own_results}
    assert attached == {same}
