"""Shared builders for the experiment tests (slice 6, plan XP-A).

`design(...)` builds a valid design dict for one hypothesis; the service-level fixtures (a project
with a registered experiment hypothesis and a final row as baseline) are added below as the plan's
tasks need them.
"""

from __future__ import annotations

from typing import Any

from factory.model.experiments import ExperimentDesign

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
