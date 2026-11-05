"""A hand-written literature evaluation changes nothing (review I1; acceptance 18, R-121). Each
variant is the exact payload with one field changed and a correct hash for what it now says, so
only the guard under test can refuse it."""

# ruff: noqa: F401

from __future__ import annotations

from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.hypotheses.literature import literature_hash
from factory.model.hypotheses import HypothesisEvaluated, LiteratureComparison
from factory.services.context import Project
from factory.services.directions import registry_query
from factory.services.evaluation import evaluations_of, recompute
from factory.services.hypotheses import conclude_hypothesis, hypothesis_view
from tests.card_helpers import cw
from tests.experiment_helpers import inject, raw_event
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.literature_helpers import literature_hypothesis, literature_world


@pytest.fixture
def lit(
    project: Project, agent: Any, agent_other: Any, human: Any, mock_sources: Any
) -> tuple[str, HypothesisEvaluated, list[str]]:
    works = literature_world(project, agent, agent_other, human, mock_sources, ["t", "t", "t", "b"])
    hid = literature_hypothesis(project, human, works)
    exact = recompute(project, hid)
    assert exact is not None and exact.outcome == "supported" and exact.comparisons
    return hid, exact, works


def _hashed(project: Project, hid: str, body: dict[str, Any]) -> dict[str, Any]:
    view = hypothesis_view(project, hid)
    assert view is not None
    comparisons = tuple(LiteratureComparison.model_validate(c) for c in body["comparisons"])
    body["inputs_hash"] = literature_hash(
        view.spec, view.h_version, comparisons, tuple(body["flags"])
    )
    return body


def _refused(project: Project, hid: str, body: dict[str, Any]) -> None:
    inject(project, raw_event(project, "hypothesis.evaluated", project.system_actor(), body))
    assert evaluations_of(project, hid) == []
    project.index.rebuild()
    assert evaluations_of(project, hid) == []
    assert registry_query(project).total == 0


def test_the_exact_payload_folds(project: Project, lit: Any) -> None:
    hid, exact, _ = lit
    good = _hashed(project, hid, exact.model_dump(mode="json"))
    assert good["inputs_hash"] == exact.inputs_hash
    inject(project, raw_event(project, "hypothesis.evaluated", project.system_actor(), good))
    assert [e.payload for e in evaluations_of(project, hid)] == [exact]


def test_the_review_forgery_changes_nothing(project: Project, human: Any, lit: Any) -> None:
    hid, exact, _ = lit
    forged = {
        "hypothesis_id": hid,
        "h_version": exact.h_version,
        "outcome": "refuted",
        "n": 2,
        "level": "0.95",
        "counts": {"n": 2, "favour_treatment": 0, "favour_baseline": 2, "ties": 0},
        "flags": [],
        "runs": [],
        "works": ["rf:not-a-work-1", "rf:not-a-work-2"],
        "inputs_hash": "a" * 16,
        "evaluator_version": "1",
    }
    _refused(project, hid, forged)
    with pytest.raises(FactoryValidationError):
        conclude_hypothesis(project, human, hid, "forged outcome concluded")


def _body(exact: HypothesisEvaluated, **over: Any) -> dict[str, Any]:
    return {**exact.model_dump(mode="json"), **over}


def test_a_work_that_does_not_exist(project: Project, lit: Any) -> None:
    hid, exact, _ = lit
    body = _body(exact)
    body["comparisons"][0]["work_id"] = "rf:zhou2020-unknown-1-00000000"
    body["works"] = sorted(c["work_id"] for c in body["comparisons"])
    _refused(project, hid, _hashed(project, hid, body))


def test_a_row_of_another_work(project: Project, lit: Any) -> None:
    hid, exact, _ = lit
    body = _body(exact)
    body["comparisons"][0]["treatment_row"] = body["comparisons"][1]["baseline_row"][:-1] + "0"
    _refused(project, hid, _hashed(project, hid, body))


def test_a_favour_the_rows_do_not_give(project: Project, lit: Any) -> None:
    hid, exact, _ = lit
    body = _body(exact)
    flipped = next(c for c in body["comparisons"] if c["favour"] == "baseline")
    flipped["favour"] = "treatment"
    body["counts"] = {"n": 4, "favour_treatment": 4, "favour_baseline": 0, "ties": 0}
    _refused(project, hid, _hashed(project, hid, body))


def test_a_work_before_the_window(
    project: Project, agent: Any, agent_other: Any, human: Any, mock_sources: Any
) -> None:
    works = literature_world(project, agent, agent_other, human, mock_sources, ["t", "t", "t", "t"])
    early = literature_hypothesis(project, human, works)
    late = literature_hypothesis(
        project,
        human,
        works,
        rationale="late",
        test={"kind": "literature", "window_start": "2099-01-01"},
    )
    exact = recompute(project, early)
    assert exact is not None
    view = hypothesis_view(project, late)
    assert view is not None
    body = _body(exact, hypothesis_id=late, h_version=view.h_version)
    _refused(project, late, _hashed(project, late, body))


@pytest.mark.parametrize(
    "over",
    [
        {"works": []},  # lit-works-count: the works do not match the comparisons
        {"n": 3},  # lit-pn: the count does not match
        {"flags": []},  # lit-flags: the cut-off flags left out
        {"flags": ["cutoff-unknown", "extra-flag"]},
        {"runs": ["xrn_01JZ9Q3K5M7N8P0R2S4T6V8W99"]},
        {"experiment_id": "exp_01JZ9Q3K5M7N8P0R2S4T6V8W99"},  # lit-runs-exp
        {"mean": "1"},
        {"level": "0.90"},
        {"outcome": "refuted"},
        {"counts": {"n": 4, "favour_treatment": 4, "favour_baseline": 0, "ties": 0}},
        {"h_version": "H@00000000"},  # fold-hversion
    ],
    ids=lambda o: next(iter(o)),
)
def test_one_field_changed(project: Project, lit: Any, over: dict[str, Any]) -> None:
    hid, exact, _ = lit
    _refused(project, hid, _hashed(project, hid, _body(exact, **over)))


def test_a_stale_hash(project: Project, lit: Any) -> None:
    hid, exact, _ = lit
    _refused(project, hid, _body(exact, inputs_hash="b" * 16))
