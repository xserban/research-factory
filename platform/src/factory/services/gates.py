"""Who may pass each decision gate, and what was passed by whom (slice M, M-B; rulings 6-10).

The effective policy of a gate is the protocol's `gate_policies` entry, else the preset of the
project's rigor mode. `gate_issues` and `require_gate` are the one check every decision-gate
service makes before its own; `gate_acts`, `autonomy_of` and `below_policy` read the log's acts
back with the policy that was in force when each was written.

Invariants:
- Everything here reads the index (after a sync); only the gate audit functions write events.
- An act's effective policy is the one in force under the protocol version current when its
  event was written (the latest `protocol.recorded` or `protocol.amended` before it in ULID
  order); an act before any protocol falls under the preset.
- A refusal names the gate id and the policy kind only: never a fraction, a minimum, a ceiling
  or a label (decision 37 item 14).
- A gate with an entry in a service's own refusal text keeps that text: `agent_text` replaces
  the generic actor message, so pinned messages survive (ruling 3).
- Acts at the two link gates are the live binding decisions; a superseded decision no longer
  binds and is not listed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.gate_audit import GateAuditLabelled, GateAuditSampled
from factory.model.gates import GatePolicies
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolSpec
from factory.model.screening import Channel
from factory.modules.contract import (
    Autonomy,
    AutonomyAct,
    CheckHit,
    GateKind,
    GatePolicy,
    PolicyKind,
)
from factory.modules.presets import Enforcement, enforcement, preset
from factory.quality.stats import audit_size, draw_uniform
from factory.services import audit_core, passes
from factory.services.context import Project

_LIVE_DECISIONS = {
    "reference.link_confirm": "reference_decisions",
    "import.resolution_confirm": "import_decisions",
}
"""Gates whose acts are the live `binding` rows of a decisions table."""


@dataclass(frozen=True)
class GateAct:
    gate_id: str
    event_id: str
    actor_kind: str
    session: str
    protocol_id: str | None
    superseded: bool = False


def _rigor_mode(project: Project) -> RigorMode:
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT rigor_mode FROM project WHERE slug = :slug"),
            {"slug": project.paths.slug},
        ).scalar_one()
    return RigorMode(str(value))


def _policies_of(project: Project, protocol_id: str | None) -> GatePolicies | None:
    """The `gate_policies` of `protocol_id`'s latest recording, or of the latest protocol."""
    with project.index.connect() as conn:
        if protocol_id is None:
            row = conn.execute(
                text("SELECT spec FROM protocols ORDER BY event_id DESC LIMIT 1")
            ).one_or_none()
        else:
            row = conn.execute(
                text(
                    "SELECT spec FROM protocols WHERE protocol_id = :p "
                    "ORDER BY event_id DESC LIMIT 1"
                ),
                {"p": protocol_id},
            ).one_or_none()
    if row is None:
        return None
    return ProtocolSpec.model_validate_json(str(row[0])).gate_policies


def effective_policy(
    project: Project,
    gate_id: str,
    *,
    protocol_id: str | None = None,
    mode: RigorMode | None = None,
) -> GatePolicy:
    """The protocol's entry for `gate_id` (the current protocol's when `protocol_id` is None),
    else the preset of `mode` (the project's rigor mode unless a caller names it)."""
    project.index.sync()
    policies = _policies_of(project, protocol_id)
    if policies is not None:
        for entry in policies.entries:
            if entry.gate == gate_id:
                return entry.as_policy()
    return preset(mode or _rigor_mode(project), gate_id)


def protocol_at(project: Project, event_id: str) -> str | None:
    """The protocol version current when `event_id` was written (ruling 2), or None."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT protocol_id FROM protocols WHERE event_id < :e "
                "ORDER BY event_id DESC LIMIT 1"
            ),
            {"e": event_id},
        ).one_or_none()
    return None if row is None else str(row[0])


def gate_issues(
    project: Project,
    actor: Actor,
    gate_id: str,
    *,
    channel: Channel | None = None,
    proposer_session: str | None = None,
    agent_text: str | None = None,
) -> list[ValidationIssue]:
    """Why `actor` may not pass `gate_id` now; empty when the policy permits.

    An agent is refused (field `actor`) at a `human` gate; the proposer's own session is refused
    (field `session`); a human act relayed over MCP (`channel`) from a session in a pass is
    refused (field `channel`). `agent_text` replaces the generic text of the actor refusal."""
    policy = effective_policy(project, gate_id)
    issues: list[ValidationIssue] = []
    if actor.kind != "human" and policy.kind is PolicyKind.HUMAN:
        issues.append(
            ValidationIssue(
                "actor",
                agent_text or f"gate {gate_id} is {policy.kind.value}: an agent cannot pass it",
            )
        )
    if proposer_session is not None and actor.session == proposer_session:
        issues.append(ValidationIssue("session", f"the proposer cannot pass gate {gate_id}"))
    if channel is not None:
        issues.extend(passes.require_not_pass_session(project, actor, channel))
    return issues


def require_gate(
    project: Project,
    actor: Actor,
    gate_id: str,
    *,
    channel: Channel | None = None,
    proposer_session: str | None = None,
) -> GatePolicy:
    """`gate_issues`, raised as one `FactoryValidationError`; else the policy in force."""
    issues = gate_issues(
        project, actor, gate_id, channel=channel, proposer_session=proposer_session
    )
    if issues:
        raise FactoryValidationError(issues)
    return effective_policy(project, gate_id)


# --- Acts, autonomy -----------------------------------------------------------------------


def gate_acts(project: Project, gate_id: str) -> Iterator[GateAct]:
    """The acts recorded at `gate_id`, in ULID order (see the module invariants)."""
    from factory.services.modules.default import default_modules  # the registry imports services

    project.index.sync()
    live = _LIVE_DECISIONS.get(gate_id)
    with project.index.connect() as conn:
        if live is not None:
            rows = conn.execute(
                text(
                    f"SELECT e.id, e.actor_kind, e.session FROM {live} d "
                    "JOIN events e ON e.id = d.event_id WHERE d.kind = 'binding' ORDER BY e.id"
                )
            ).all()
        else:
            types = default_modules().gate(gate_id).act_events
            marks = ", ".join(f":t{i}" for i in range(len(types)))
            rows = conn.execute(
                text(
                    f"SELECT id, actor_kind, session FROM events "
                    f"WHERE type IN ({marks}) ORDER BY id"
                ),
                {f"t{i}": t for i, t in enumerate(types)},
            ).all()
    for event_id, kind, session in rows:
        yield GateAct(
            gate_id, str(event_id), str(kind), str(session), protocol_at(project, str(event_id))
        )


def as_autonomy_acts(project: Project, gate_ids: tuple[str, ...]) -> Iterator[AutonomyAct]:
    """`gate_acts` of each gate as the `autonomy_acts` hook of a module yields them."""
    for gate_id in gate_ids:
        for act in gate_acts(project, gate_id):
            yield AutonomyAct(gate_id, act.event_id, act.actor_kind, act.protocol_id)


def _audited(project: Project, act: GateAct) -> bool:
    """Whether a gate audit of the act's gate was drawn after the act: its population was every
    agent act then recorded at the gate, so it contains the act."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM gate_audits WHERE gate_id = :g AND event_id > :e LIMIT 1"),
            {"g": act.gate_id, "e": act.event_id},
        ).first()
    return row is not None


def autonomy_of(project: Project, act: GateAct) -> Autonomy:
    """Ruling 10: `human` for a human act, `audited-agent` for an agent act at a gate whose
    policy then was `agent_audit` and whose audit sample contains the act, else `agent`."""
    if act.actor_kind != "agent":
        return Autonomy.HUMAN
    policy = effective_policy(project, act.gate_id, protocol_id=act.protocol_id)
    if policy.kind is PolicyKind.AGENT_AUDIT and _audited(project, act):
        return Autonomy.AUDITED_AGENT
    return Autonomy.AGENT


def autonomy_counts(project: Project, gate_id: str) -> dict[Autonomy, int]:
    counts = {level: 0 for level in Autonomy}
    for act in gate_acts(project, gate_id):
        counts[autonomy_of(project, act)] += 1
    return counts


def weakest(levels: list[Autonomy]) -> Autonomy:
    """The weakest autonomy of a basis: agent < audited-agent < human (ruling 10)."""
    order = [Autonomy.AGENT, Autonomy.AUDITED_AGENT, Autonomy.HUMAN]
    return min(levels, key=order.index, default=Autonomy.HUMAN)


# --- Tightening blast radius (ruling 7) -------------------------------------------------


def below_policy(project: Project) -> list[GateAct]:
    """Agent acts at a gate whose *current* effective policy is `human`: earlier acts that a
    tightening amendment would no longer accept. Computed on read; nothing is staled (decision
    50). An agent act at a gate now `agent_audit` is not below policy; it enters the audit
    population. Loosening lists nothing."""
    from factory.services.modules.default import default_modules  # the registry imports services

    found: list[GateAct] = []
    for gate in default_modules().gates():
        if gate.kind is not GateKind.DECISION:
            continue
        if effective_policy(project, gate.gate_id).kind is not PolicyKind.HUMAN:
            continue
        found.extend(a for a in gate_acts(project, gate.gate_id) if a.actor_kind == "agent")
    return found


def gate_hits(project: Project) -> list[CheckHit]:
    """The `gate-*` findings, one hit per gate; none for a project whose acts all meet policy."""
    hits: list[CheckHit] = []
    by_gate: dict[str, list[str]] = {}
    for act in below_policy(project):
        by_gate.setdefault(act.gate_id, []).append(act.event_id)
    for gate_id, refs in by_gate.items():
        hits.append(
            CheckHit(
                "gate-below-policy",
                tuple(refs),
                f"{len(refs)} act(s) at gate {gate_id} were passed by an agent before the "
                "policy became human",
            )
        )
    return hits


# --- Gate audit (ruling 9) ----------------------------------------------------------------

GATE_AUDIT_ERROR_CEILING = 0.05
"""The error rate of a gate audit above which `gate-audit-error-high` is raised (ruling 9)."""


@dataclass(frozen=True)
class GateAuditReport:
    audit_id: str
    gate_id: str
    sample_size: int
    labelled: int
    incorrect: int
    verdict: audit_core.CeilingVerdict


def _population(project: Project, gate_id: str) -> audit_core.AuditPopulation:
    """The agent acts at the gate, not superseded (ruling 4): human acts are never sampled."""
    return audit_core.AuditPopulation.of(
        (a.event_id, a.actor_kind)
        for a in gate_acts(project, gate_id)
        if a.actor_kind == "agent" and not a.superseded
    )


def _last_digest(project: Project, gate_id: str) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT population_digest FROM gate_audits WHERE gate_id = :g "
                "ORDER BY event_id DESC LIMIT 1"
            ),
            {"g": gate_id},
        ).one_or_none()
    return None if row is None else str(row[0])


def _latest_protocol(project: Project) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT protocol_id FROM protocols ORDER BY event_id DESC LIMIT 1")
        ).one_or_none()
    return None if row is None else str(row[0])


def gate_audit_sample(
    project: Project, actor: Actor, gate_id: str, *, random_seed: int | None = None
) -> GateAuditSampled:
    """Draw and record a human audit sample of the agent acts at an `agent_audit` gate.

    The size is `audit_size(N, fraction, minimum)` of the gate's current policy over the `N` agent
    acts (capped at `N`); the draw is uniform from the recorded seed. Refused, with nothing
    written: for a non-human actor (`actor`), a seed out of range (`random_seed`), a gate that is
    not a decision gate or is not `agent_audit` now (`gate_id`), no agent act to audit
    (`gate_id`), or a new draw over the very population of the latest audit (`passes`)."""
    from factory.services.modules.default import default_modules  # the registry imports services

    seed, seed_issues = audit_core.validate_seed(random_seed)
    with project.index.exclusive():
        project.index.sync()
        issues = audit_core.human_gate(project, actor, Channel.CLI, noun="sample")
        issues.extend(seed_issues)
        known = {g.gate_id for g in default_modules().gates() if g.kind is GateKind.DECISION}
        policy = effective_policy(project, gate_id) if gate_id in known else None
        if policy is None or policy.kind is not PolicyKind.AGENT_AUDIT:
            issues.append(ValidationIssue("gate_id", f"gate {gate_id} is not an agent_audit gate"))
        if issues or policy is None:
            raise FactoryValidationError(issues)
        population = _population(project, gate_id)
        if not len(population):
            raise FactoryValidationError(
                [ValidationIssue("gate_id", f"no agent act at gate {gate_id} to audit")]
            )
        audit_core.refuse_reopen(_last_digest(project, gate_id), population)
        size = audit_size(len(population), policy.fraction or 0.0, policy.minimum or 0)
        drawn = draw_uniform(population.keys, size, seed, key=str)
        payload = GateAuditSampled(
            audit_id=project.ids.new("gau"),
            gate_id=gate_id,
            act_event_ids=tuple(drawn),
            random_seed=seed,
            population=len(population),
            population_digest=population.digest,
            protocol_id=_latest_protocol(project),
        )
        project.record([project.events.make("gate.audit_sampled", payload, actor)])
    return payload


def gate_audit_record(
    project: Project,
    actor: Actor,
    audit_id: str,
    act_event_id: str,
    correct: bool,
    note: str | None,
    channel: Channel,
) -> str:
    """Record a human's label on one sampled act (`correct`: the agent's act was right) and
    return the event id. Refused, with nothing written: for a non-human actor (`actor`), an MCP
    relay from a session in a pass (`channel`), an unknown audit (`audit_id`) or an act outside
    its sample (`act_event_id`). A later label of the same act replaces the earlier."""
    with project.index.exclusive():
        project.index.sync()
        issues = audit_core.human_gate(project, actor, channel, noun="gate-label")
        with project.index.connect() as conn:
            known = conn.execute(
                text("SELECT 1 FROM gate_audits WHERE audit_id = :a"), {"a": audit_id}
            ).first()
            sampled = conn.execute(
                text("SELECT 1 FROM gate_audit_items WHERE audit_id = :a AND act_event_id = :e"),
                {"a": audit_id, "e": act_event_id},
            ).first()
        if known is None:
            issues.append(ValidationIssue("audit_id", "unknown gate audit"))
        elif sampled is None:
            issues.append(ValidationIssue("act_event_id", "not in this audit sample"))
        if issues:
            raise FactoryValidationError(issues)
        payload = GateAuditLabelled(
            audit_id=audit_id,
            act_event_id=act_event_id,
            correct=correct,
            note=note or None,
            channel=channel,
        )
        event = project.events.make("gate.audit_labelled", payload, actor)
        project.record([event])
    return event.id


def gate_audit_report(project: Project, gate_id: str) -> GateAuditReport | None:
    """The latest audit of `gate_id` with its error rate against the ceiling; None when none was
    drawn. The rate is undefined (no verdict above) until a sampled act is labelled."""
    project.index.sync()
    with project.index.connect() as conn:
        audit = conn.execute(
            text("SELECT audit_id FROM gate_audits WHERE gate_id = :g ORDER BY event_id DESC"),
            {"g": gate_id},
        ).first()
        if audit is None:
            return None
        rows = conn.execute(
            text("SELECT correct FROM gate_audit_items WHERE audit_id = :a"),
            {"a": str(audit[0])},
        ).all()
    labelled = [bool(c) for (c,) in rows if c is not None]
    incorrect = sum(1 for c in labelled if not c)
    rate = incorrect / len(labelled) if labelled else None
    verdict = audit_core.ceiling_verdict(
        rate,
        GATE_AUDIT_ERROR_CEILING,
        enforced=enforcement(_rigor_mode(project), "gate.audit_ceiling") is Enforcement.ENFORCED,
    )
    return GateAuditReport(str(audit[0]), gate_id, len(rows), len(labelled), incorrect, verdict)


def audit_hits(project: Project) -> list[CheckHit]:
    """`gate-audit-missing` for an `agent_audit` gate with agent acts and no audit drawn, and
    `gate-audit-error-high` for a latest audit above the ceiling. Messages carry counts, never a
    rate."""
    from factory.services.modules.default import default_modules  # the registry imports services

    hits: list[CheckHit] = []
    for gate in default_modules().gates():
        if gate.kind is not GateKind.DECISION:
            continue
        if effective_policy(project, gate.gate_id).kind is not PolicyKind.AGENT_AUDIT:
            continue
        report = gate_audit_report(project, gate.gate_id)
        if report is None:
            keys = _population(project, gate.gate_id).keys
            if keys:
                hits.append(
                    CheckHit(
                        "gate-audit-missing",
                        keys,
                        f"{len(keys)} agent act(s) at gate {gate.gate_id} have no human audit",
                    )
                )
        elif report.verdict.above:
            hits.append(
                CheckHit(
                    "gate-audit-error-high",
                    (report.audit_id,),
                    f"the human audit of gate {gate.gate_id} found errors above the declared "
                    "ceiling",
                )
            )
    return hits
