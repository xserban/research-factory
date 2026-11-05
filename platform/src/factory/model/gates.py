"""Gate policies as a protocol section (slice M, M-B).

`GatePolicies` is the optional, amendable, hashed protocol section that says who may pass each
decision gate.

Invariants:
- An entry carries `fraction` and `minimum` if and only if its policy is `agent_audit`.
- Entries name each gate once. Their order never reaches a hash (the protocol sorts them by gate).
- Pure: no registry lookup here; whether a gate exists and what its floor is are checked by the
  protocol rules, which see the module registry.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.modules.contract import GatePolicy, PolicyKind

GATE_ID_RE = r"^[a-z]+\.[a-z_]+$"


class GatePolicyEntry(StrictModel):
    gate: str = Field(pattern=GATE_ID_RE)
    policy: PolicyKind
    fraction: float | None = Field(default=None, gt=0, le=1)
    minimum: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _audit_parameters(self) -> Self:
        audited = self.policy is PolicyKind.AGENT_AUDIT
        if audited and (self.fraction is None or self.minimum is None):
            raise ValueError("agent_audit needs a fraction and a minimum")
        if not audited and (self.fraction is not None or self.minimum is not None):
            raise ValueError("only agent_audit takes a fraction and a minimum")
        return self

    def as_policy(self) -> GatePolicy:
        return GatePolicy(self.policy, self.fraction, self.minimum)


class GatePolicies(StrictModel):
    entries: tuple[GatePolicyEntry, ...]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        gates = [e.gate for e in self.entries]
        if len(set(gates)) != len(gates):
            raise ValueError("gate_policies must not repeat a gate")
        return self
