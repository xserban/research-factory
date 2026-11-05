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
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.hypothesis_plan import HypothesisPlan
from factory.model.project import RigorMode
from factory.modules.contract import GatePolicy, PolicyKind
from factory.services.context import Project
from factory.services.gates import effective_policy
from factory.services.protocol import current_protocol

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


_MIN_SEEDS = {RigorMode.EXPLORATORY: 2, RigorMode.PILOT: 3, RigorMode.SYSTEMATIC: 5}


def project_mode(project: Project) -> RigorMode:
    project.index.sync()
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT rigor_mode FROM project WHERE slug = :slug"),
            {"slug": project.paths.slug},
        ).scalar_one()
    return RigorMode(str(value))


def effective_plan(project: Project) -> HypothesisPlan:
    """The protocol's `hypothesis_plan` with every default filled for the project's mode: the
    minimum seeds (2, 3, 5), a required lead outside exploratory mode and a distinct critic model
    in systematic mode only. A field the protocol states is kept."""
    mode = project_mode(project)
    protocol = current_protocol(project)
    plan = HypothesisPlan() if protocol is None else protocol.spec.hypothesis_plan
    plan = plan or HypothesisPlan()
    return plan.model_copy(
        update={
            "min_seeds": plan.min_seeds if plan.min_seeds is not None else _MIN_SEEDS[mode],
            "require_lead": (
                plan.require_lead
                if plan.require_lead is not None
                else mode is not RigorMode.EXPLORATORY
            ),
            "critic_distinct_model": (
                plan.critic_distinct_model
                if plan.critic_distinct_model is not None
                else mode is RigorMode.SYSTEMATIC
            ),
        }
    )


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
