"""One row per decision gate: policy, who passed its acts, its audit (slice M, M-B Task 6).

Invariants:
- Read-only; every figure is computed from the log and the registry (R-05).
- Rows follow the registry's declaration order.
- `agent_view` is the row an agent may read: no fraction, minimum, sample size, label count or
  error rate (decision 37 item 14); only that an audit was drawn.
"""

from __future__ import annotations

from typing import Literal

from factory.model.base import StrictModel
from factory.modules.contract import Autonomy, GateKind, PolicyKind
from factory.services.context import Project
from factory.services.gates import (
    autonomy_counts,
    below_policy,
    effective_policy,
    gate_audit_report,
)


class GateAuditView(StrictModel):
    """The latest audit of a gate. The figures are None in the agent view."""

    audit_id: str
    sample_size: int | None
    labelled: int | None
    incorrect: int | None
    error_rate: float | None
    above_ceiling: bool | None
    enforced: bool | None


class GateStatusRow(StrictModel):
    gate_id: str
    floor: str
    policy: str
    fraction: float | None
    minimum: int | None
    source: Literal["preset", "protocol"]
    counts: dict[str, int]
    """Acts per autonomy level (`human`, `audited-agent`, `agent`)."""
    audit: GateAuditView | None
    below_policy: int

    def agent_view(self) -> GateStatusRow:
        audit = self.audit
        hidden = (
            None
            if audit is None
            else GateAuditView(
                audit_id=audit.audit_id,
                sample_size=None,
                labelled=None,
                incorrect=None,
                error_rate=None,
                above_ceiling=None,
                enforced=None,
            )
        )
        return self.model_copy(update={"fraction": None, "minimum": None, "audit": hidden})

    def notable(self) -> bool:
        """Whether a methods statement says something about this gate: an agent passed acts under
        a policy that is not `human`, the protocol declares such a policy, or acts fall below it."""
        agent_acts = self.counts[Autonomy.AGENT.value] + self.counts[Autonomy.AUDITED_AGENT.value]
        loose = self.policy != PolicyKind.HUMAN.value
        return (loose and (agent_acts > 0 or self.source == "protocol")) or self.below_policy > 0


def gates_status(project: Project) -> list[GateStatusRow]:
    """One row per decision gate of the registry."""
    from factory.services.modules.default import default_modules  # the registry imports services

    below: dict[str, int] = {}
    for act in below_policy(project):
        below[act.gate_id] = below.get(act.gate_id, 0) + 1
    declared = _declared(project)
    rows: list[GateStatusRow] = []
    for gate in default_modules().gates():
        if gate.kind is not GateKind.DECISION:
            continue
        policy = effective_policy(project, gate.gate_id)
        report = gate_audit_report(project, gate.gate_id)
        counts = autonomy_counts(project, gate.gate_id)
        rows.append(
            GateStatusRow(
                gate_id=gate.gate_id,
                floor=gate.floor.value,
                policy=policy.kind.value,
                fraction=policy.fraction,
                minimum=policy.minimum,
                source="protocol" if gate.gate_id in declared else "preset",
                counts={level.value: counts[level] for level in Autonomy},
                audit=None
                if report is None
                else GateAuditView(
                    audit_id=report.audit_id,
                    sample_size=report.sample_size,
                    labelled=report.labelled,
                    incorrect=report.incorrect,
                    error_rate=report.verdict.rate,
                    above_ceiling=report.verdict.above,
                    enforced=report.verdict.enforced,
                ),
                below_policy=below.get(gate.gate_id, 0),
            )
        )
    return rows


def notable_rows(project: Project) -> list[GateStatusRow]:
    """The rows a methods statement reports (see `GateStatusRow.notable`)."""
    return [row for row in gates_status(project) if row.notable()]


def _declared(project: Project) -> set[str]:
    from factory.services.protocol import current_protocol

    protocol = current_protocol(project)
    if protocol is None or protocol.spec.gate_policies is None:
        return set()
    return {e.gate for e in protocol.spec.gate_policies.entries}
