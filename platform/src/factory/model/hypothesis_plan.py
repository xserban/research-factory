"""The `hypothesis_plan` protocol section (slice 6, plan H-C; ruling 4).

Policy defaults for hypotheses, not the hypotheses: it holds the minimum seeds, the default
confidence level, the test-access limit, the numeric-conflict tolerance, whether a lead is
required and whether the critic must run on another model. A field left `None` takes the default
of the project's rigor mode (`services/hypothesis_gates.effective_plan`).

Invariants:
- Gate policies are not here; they are slice M's `gate_policies` section.
- Absent (`None` on the protocol) it leaves every protocol hash as it was.
- Pure: whether a value is acceptable (`min_seeds >= 2`, `test_access_limit >= 1`) is checked by
  the protocol rules, which report the field that is wrong.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from factory.model.base import StrictModel

DECIMAL_RE = r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"


class HypothesisPlan(StrictModel):
    min_seeds: int | None = None
    confidence: Literal["0.90", "0.95", "0.99"] = "0.95"
    test_access_limit: int = 1
    conflict_tolerance: str = Field(default="0.01", pattern=DECIMAL_RE)
    require_lead: bool | None = None
    critic_distinct_model: bool | None = None
