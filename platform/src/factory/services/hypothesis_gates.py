"""Who may pass the hypothesis gates (slice 6, plan H-C; slice M ruling 2).

The gates are slice M's decision gates; their policy is the protocol's `gate_policies` entry, else
the rigor-mode preset (`services/gates.py`, `modules/presets.py`). This module adds the proposer
exclusion the hypothesis gates share and the plan defaults of a mode.

Invariants:
- Read-only: nothing here writes an event.
- Under a `human` policy only a human passes, whatever session; under `agent` and `agent_audit`
  any actor whose session is not a proposer's passes (the proposer cannot pass its own work).
- A refusal names the gate id and the policy kind only, never a fraction or a minimum.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.modules.contract import GatePolicy, PolicyKind
from factory.services.context import Project
from factory.services.gates import effective_policy

GateName = Literal[
    "hypotheses.lead_decide",
    "hypotheses.register",
    "experiments.freeze_unlock",
    "experiments.accept_baseline",
]
"""The slice-M gate ids of this slice's draft gate names (`lead-promotion`,
`hypothesis-registration`, `design-freeze` and `confirmatory-unlock`, `baseline-acceptance`)."""

Autonomy = Literal["human", "agent"]


@dataclass(frozen=True)
class GateVerdict:
    ok: bool
    reason: str | None
    policy: GatePolicy
    autonomy: Autonomy
    field: str | None = None
    """The input field a refusal names (`actor` or `session`)."""

    def raise_if_refused(self) -> None:
        if not self.ok:
            raise FactoryValidationError(
                [ValidationIssue(self.field or "actor", self.reason or "refused")]
            )


def gate_policy(project: Project, gate: GateName) -> GatePolicy:
    """The policy in force at `gate` (M-B `effective_policy`)."""
    return effective_policy(project, gate)


def may_pass(
    project: Project, actor: Actor, gate: GateName, *, proposer_sessions: Collection[str]
) -> GateVerdict:
    """Whether `actor` may pass `gate` now, with the policy in force and the autonomy label the
    act will carry (`human`, or `agent` for any agent act, audited or not)."""
    policy = gate_policy(project, gate)
    autonomy: Autonomy = "human" if actor.kind == "human" else "agent"
    if actor.kind not in ("human", "agent"):
        return GateVerdict(False, "only an agent or a human passes a gate", policy, autonomy)
    if policy.kind is PolicyKind.HUMAN:
        if actor.kind != "human":
            return GateVerdict(
                False, f"gate {gate} is human: an agent cannot pass it", policy, autonomy
            )
        return GateVerdict(True, None, policy, autonomy)
    if actor.session in set(proposer_sessions):
        return GateVerdict(
            False, f"the proposer cannot pass gate {gate}", policy, autonomy, "session"
        )
    return GateVerdict(True, None, policy, autonomy)
