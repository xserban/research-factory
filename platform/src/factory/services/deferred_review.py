"""The deferred human review of agent-closed acts (contract C6).

An item is an agent act at a decision gate that a gate audit sampled and no human has labelled
yet; the gate's trust state (`gate_trust`) rides along. A human decides it with the existing
`gate.audit_labelled` event (`gates.gate_audit_record`): `correct`, or `overturn` (label
`correct = false`), so the ledger counts the overturn with no new event type.

Invariants:
- Read-only except `decide_deferred`, which refuses any actor but a human (field `actor`) and
  writes nothing then.
- Items exist only for a project whose autonomy level is not `attended`; under `attended` the
  list is empty, so existing queues, digests and counts do not change.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.levels import AutonomyLevel
from factory.model.screening import Channel
from factory.modules.contract import GateKind
from factory.services.context import Project
from factory.services.gate_trust import TrustState, gate_trust
from factory.services.gates import autonomy_level, gate_acts, gate_audit_record


@dataclass(frozen=True)
class DeferredItem:
    gate_id: str
    audit_id: str
    act_event_id: str
    trust_state: TrustState


def deferred_items(project: Project) -> tuple[DeferredItem, ...]:
    """The unlabelled sampled agent acts, by gate in registry order, then act id."""
    from factory.services.modules.default import default_modules  # the registry imports services

    if autonomy_level(project) is AutonomyLevel.ATTENDED:
        return ()
    project.index.sync()
    found: list[DeferredItem] = []
    for gate in default_modules().gates():
        if gate.kind is not GateKind.DECISION:
            continue
        agent = {a.event_id for a in gate_acts(project, gate.gate_id) if a.actor_kind == "agent"}
        if not agent:
            continue
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT i.audit_id, i.act_event_id FROM gate_audit_items i "
                    "JOIN gate_audits a ON a.audit_id = i.audit_id "
                    "WHERE a.gate_id = :g AND i.correct IS NULL "
                    "ORDER BY i.act_event_id, i.audit_id"
                ),
                {"g": gate.gate_id},
            ).all()
        mine = [(str(a), str(e)) for a, e in rows if str(e) in agent]
        if not mine:
            continue
        state = gate_trust(project, gate.gate_id).state
        found.extend(DeferredItem(gate.gate_id, a, e, state) for a, e in mine)
    return tuple(found)


def deferred_count(project: Project) -> int:
    return len(deferred_items(project))


def decide_deferred(
    project: Project,
    actor: Actor,
    audit_id: str,
    act_event_id: str,
    verdict: str,
    note: str | None,
    channel: Channel,
) -> str:
    """A human's decision on one deferred item (`correct` or `overturn`); the event id. Refused,
    nothing written, for a non-human actor, another verdict, or an act outside the audit."""
    from factory.errors import FactoryValidationError, ValidationIssue

    if verdict not in ("correct", "overturn"):
        raise FactoryValidationError([ValidationIssue("verdict", "must be correct or overturn")])
    return gate_audit_record(
        project, actor, audit_id, act_event_id, verdict == "correct", note, channel
    )
