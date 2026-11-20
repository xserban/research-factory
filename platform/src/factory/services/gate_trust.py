"""The trust ledger of agent-closed gates (plan 2026-11-20-tiers-and-autonomy, contract C5).

For each decision gate where an agent closed an act: how many acts, how many a human audited
(`gate.audit_labelled`) and how many of those the human found incorrect (the overturns). The
state follows the overturn rate against named thresholds.

Invariants:
- Read-only: computed from the index on each call; no table, no event.
- Only agent acts count (`gate_acts`, not superseded); a human act is never audited or counted.
- An act sampled by several audits counts once, with its label from the latest audit that
  labelled it.
- `overturn_rate` is None until an act is audited; the state is then `ok`.
- A gate whose acts no audit mechanism records (no `agent_audit` policy ever sampled it) shows
  `audited = 0`: its overturns are unmeasured, not zero (a gap, see the lane report).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.modules.contract import GateKind
from factory.services.context import Project
from factory.services.gates import gate_acts

WATCH_RATE = 0.05
"""Decision D5 (proposed): above this overturn rate, with `WATCH_MIN_AUDITED` acts audited, a gate
is on `watch`."""
WATCH_MIN_AUDITED = 20
PAUSE_RATE = 0.10
"""Decision D5 (proposed): above this overturn rate a gate is on `pause`, whatever the count."""

TrustState = Literal["ok", "watch", "pause"]


@dataclass(frozen=True)
class GateTrust:
    gate_id: str
    closed_by_agent: int
    audited: int
    overturned: int
    overturn_rate: float | None
    state: TrustState
    agent_audited: int = 0
    agent_overturned: int = 0
    """Acts an agent session labelled (the platform-drawn sample); never part of the rate or
    the state, which follow human labels only."""


def trust_state(audited: int, overturned: int) -> TrustState:
    if audited == 0:
        return "ok"
    rate = overturned / audited
    if rate > PAUSE_RATE:
        return "pause"
    if rate > WATCH_RATE and audited >= WATCH_MIN_AUDITED:
        return "watch"
    return "ok"


def labels_of(project: Project, gate_id: str) -> dict[str, bool | None]:
    """Each act sampled at `gate_id` to its human label (True: correct, False: overturned, None:
    not yet labelled), from the latest audit that holds it."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT i.act_event_id, i.correct FROM gate_audit_items i "
                "JOIN gate_audits a ON a.audit_id = i.audit_id "
                "WHERE a.gate_id = :g ORDER BY a.event_id"
            ),
            {"g": gate_id},
        ).all()
    found: dict[str, bool | None] = {}
    for act, correct in rows:
        if correct is not None:
            found[str(act)] = bool(correct)
        else:
            found.setdefault(str(act), None)
    return found


def agent_labels(project: Project, gate_id: str) -> dict[str, bool]:
    """Agent labels at `gate_id` (latest per act), read from the log: the fold keeps human
    labels only."""
    from factory.events.reader import read_typed

    sampled = set(labels_of(project, gate_id))
    found: dict[str, bool] = {}
    for event in read_typed(project.paths.events_dir, project.catalog, ["gate.audit_labelled"]):
        act = str(event.payload.get("act_event_id"))
        if event.actor.kind == "agent" and act in sampled:
            found[act] = bool(event.payload.get("correct"))
    return found


def gate_trust(project: Project, gate_id: str) -> GateTrust:
    agent = {
        a.event_id
        for a in gate_acts(project, gate_id)
        if a.actor_kind == "agent" and not a.superseded
    }
    labels = {act: v for act, v in labels_of(project, gate_id).items() if act in agent}
    audited = sum(1 for v in labels.values() if v is not None)
    overturned = sum(1 for v in labels.values() if v is False)
    return GateTrust(
        gate_id,
        len(agent),
        audited,
        overturned,
        None if audited == 0 else overturned / audited,
        trust_state(audited, overturned),
        sum(1 for a in agent_labels(project, gate_id) if a in agent),
        sum(1 for a, v in agent_labels(project, gate_id).items() if a in agent and not v),
    )


def trust_ledger(project: Project) -> tuple[GateTrust, ...]:
    """One row per decision gate with at least one agent act, in registry order."""
    from factory.services.modules.default import default_modules  # the registry imports services

    rows = (
        gate_trust(project, g.gate_id)
        for g in default_modules().gates()
        if g.kind is GateKind.DECISION
    )
    return tuple(r for r in rows if r.closed_by_agent > 0)
