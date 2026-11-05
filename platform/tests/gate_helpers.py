"""Builders shared by the gate-policy tests (slice M, M-B)."""

from factory.events.envelope import Actor
from factory.model.gates import GatePolicies, GatePolicyEntry
from factory.modules.contract import PolicyKind
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol


def entry(
    gate: str, policy: PolicyKind, fraction: float | None = None, minimum: int | None = None
) -> GatePolicyEntry:
    return GatePolicyEntry(gate=gate, policy=policy, fraction=fraction, minimum=minimum)


def amend_gate_policies(project: Project, actor: Actor, *entries: GatePolicyEntry) -> str:
    """Amend the current protocol so it declares `entries`; returns the new protocol id."""
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_copy(update={"gate_policies": GatePolicies(entries=entries)})
    return amend_protocol(
        project, actor, spec, reason="set the gate policies", semantic=True, effects={}
    ).to_version
