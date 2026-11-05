"""Shared builders for the experiment tests (slice 6, plan XP-A).

`design(...)` builds a valid design dict for one hypothesis; the service-level fixtures (a project
with a registered experiment hypothesis and a final row as baseline) are added below as the plan's
tasks need them.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from factory.events.envelope import Actor
from factory.model.experiments import Cell, ExperimentDesign
from factory.services.context import Project
from factory.services.experiments import design_experiment, freeze_experiment
from factory.services.extraction_agreement import final_rows
from factory.services.hypotheses import draft_hypothesis, register_hypothesis
from factory.services.hypothesis_review import record_review, review_next
from tests.hypothesis_helpers import CRITIC, DRAFTER, HW, OTHER, gw, hw, make_spec
from tests.test_hypothesis_review import verdict

HYP = "hyp_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
ROW = "rk_0123456789ab"
ROW2 = "rk_ba9876543210"
COMMIT = "9f2c1ab"
ENV = "sha256:lockfile-1"


def design_body(hypothesis: str = HYP, **over: Any) -> dict[str, Any]:
    """A valid design: one factor (`attention`), three seeds, two axes, one ablation, one positive
    and one negative control, one baseline, a small budget."""
    body: dict[str, Any] = {
        "hypothesis": hypothesis,
        "factor": {"attention": ["softmax", "linear"]},
        "base_config": {"attention": "softmax", "depth": 12, "lr": "0.001", "use_norm": True},
        "code": {"uri": "https://example.org/repo.git", "commit": COMMIT},
        "environment": ENV,
        "datasets": [
            {"name": "imagenet-dev", "version": "1", "sha256": "a" * 64, "role": "dev"},
            {"name": "imagenet-test", "version": "1", "sha256": "b" * 64, "role": "confirmatory"},
        ],
        "metrics": [
            {
                "name": "top-1 accuracy",
                "direction": "higher",
                "unit_family": "score",
                "unit": "%",
                "primary": True,
            }
        ],
        "seeds": [1, 2, 3],
        "axes": {"resolution": ["224", "384"]},
        "primary_universe": {"resolution": "224"},
        "ablations": [{"name": "no-norm", "key": "use_norm", "value": False}],
        "controls": [
            {
                "name": "shuffled",
                "kind": "negative",
                "overrides": {"labels": "shuffled"},
                "expect": "no-effect",
            },
            {
                "name": "planted",
                "kind": "positive",
                "overrides": {"labels": "planted"},
                "expect": "effect",
            },
        ],
        "baselines": [{"row_key": ROW, "tolerance": "0.01", "tolerance_kind": "relative"}],
        "budget": {"gpu_hours": "100", "per_run_gpu_hours": "10", "max_runs": 40},
    }
    body.update(over)
    return body


def design(hypothesis: str = HYP, **over: Any) -> ExperimentDesign:
    return ExperimentDesign.model_validate(design_body(hypothesis, **over))


METRIC = {"name": "top-1 accuracy", "direction": "higher", "unit_family": "score", "unit": "%"}
"""The hypothesis metric of these tests, with a unit the evidence schema's score family accepts."""


@dataclass
class XW:
    """A project with a registered experiment hypothesis (`hid`); `rows` are the final evidence
    row keys of its evidence world, in work order (none in the exploratory project)."""

    hid: str
    rows: list[str]

    def design(self, **over: Any) -> ExperimentDesign:
        baselines = [{"row_key": self.rows[0], "tolerance": "0.01"}] if self.rows else []
        body: dict[str, Any] = {"baselines": baselines}
        body.update(over)
        return design(self.hid, **body)


def register_with_review(project: Project, human: Actor, hid: str) -> None:
    served = review_next(project, CRITIC)
    assert served is not None
    record_review(project, CRITIC, served.task_id, verdict("register"))
    register_hypothesis(project, human, hid)


def cell(
    arm: str = "treatment", seed: int = 1, split: str = "confirmatory", resolution: str = "224"
) -> Cell:
    return Cell(universe=(("resolution", resolution),), seed=seed, arm=arm, split=split)  # type: ignore[arg-type]


def frozen_design(project: Project, human: Actor, w: XW, **over: Any) -> str:
    """A design of `w` recorded by the drafter and frozen by the human."""
    exp, _ = design_experiment(project, DRAFTER, w.design(**over))
    freeze_experiment(project, human, exp)
    return exp


@pytest.fixture
def xw(project: Project, human: Actor, hw: HW) -> XW:
    """A pilot project: the hypothesis of `hw` after a critic's review and a human registration."""
    register_with_review(project, human, hw.hid)
    return XW(hw.hid, [r.row_key for r in final_rows(project)])


@pytest.fixture
def xe(explore_project: Project) -> XW:
    """An exploratory project: a hypothesis registered by an agent session other than the
    drafter's; no evidence world, so a design has no baselines."""
    hid, _ = draft_hypothesis(explore_project, DRAFTER, make_spec(metric=METRIC))
    register_hypothesis(explore_project, OTHER, hid)
    return XW(hid, [])
