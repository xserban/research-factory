"""Projection of leads, hypotheses, reviews, registrations and model cut-offs (slice 6, plan H-C).

`leads` keeps one row per lead with the latest binding decision; `lead_triggers` and `lead_keys`
are lookup tables (`lead_keys.key` is how a later lead finds the failures that share a key).

A decision or registration is folded only when it is consistent with the gate policy in force
when it was written: the recorded policy kind must equal the effective one (the protocol's
`gate_policies` entry current at that point of the log, else the preset of the project's rigor
mode), a `human` policy needs a human actor, and any other policy needs a session that is not a
proposer's (the lead author's; for a registration also the drafter's). An event that fails this
stays in the log, visibly unfolded, and changes nothing else: no service writes one, so it was
written by hand (R-51). Cut-off declarations, abandonment and conclusions are human acts and are
folded only from a human actor.

Handlers are total: an event naming an unknown lead or hypothesis changes nothing, never raises.
Rows are first-write-wins per id.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.hypotheses import (
    HypothesisAbandoned,
    HypothesisConcluded,
    HypothesisDrafted,
    LeadDecided,
    LeadRecorded,
)
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolSpec
from factory.modules.contract import PolicyKind
from factory.modules.presets import preset

_STATE = {"promote": "promoted", "park": "parked", "discard": "discarded"}


@dataclass(frozen=True)
class HypothesisTables:
    leads: Table
    lead_triggers: Table
    lead_keys: Table
    hypotheses: Table
    protocols: Table
    project: Table
    """The protocol and project tables the fold reads to know the policy in force."""


def hypothesis_tables(metadata: MetaData, protocols: Table, project: Table) -> HypothesisTables:
    leads = Table(
        "leads",
        metadata,
        Column("lead_id", String, primary_key=True),
        Column("text", String, nullable=False),
        Column("framework", String),
        Column("triggers_json", String, nullable=False),
        Column("prior_json", String, nullable=False),
        Column("prior_total", Integer, nullable=False),
        Column("author_session", String, nullable=False),
        Column("state", String, nullable=False),
        Column("decision", String),
        Column("reason", String),
        Column("note", String),
        Column("decision_event_id", String),
        Column("event_id", String, nullable=False),
    )
    triggers = Table(
        "lead_triggers",
        metadata,
        Column("lead_id", String, primary_key=True),
        Column("kind", String, primary_key=True),
        Column("ref", String, primary_key=True),
    )
    keys = Table(
        "lead_keys",
        metadata,
        Column("lead_id", String, primary_key=True),
        Column("key", String, primary_key=True),
        Index("ix_lead_keys_key", "key"),
    )
    hypotheses = Table(
        "hypotheses",
        metadata,
        Column("hypothesis_id", String, primary_key=True),
        Column("h_version", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("lead", String),
        Column("spec_json", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("drafter_session", String, nullable=False),
        Column("drafter_model", String),
        Column("event_id", String, nullable=False),
        Column("abandon_reason", String),
        Column("abandoned_event_id", String),
        Column("conclusion_text", String),
        Column("conclusion_event_id", String),
    )
    return HypothesisTables(leads, triggers, keys, hypotheses, protocols, project)


def hypothesis_handlers(t: HypothesisTables) -> dict[str, Handler]:
    return {
        "lead.recorded": _lead_recorded(t),
        "lead.decided": _lead_decided(t),
        "hypothesis.drafted": _drafted(t),
        "hypothesis.abandoned": _abandoned(t),
        "hypothesis.concluded": _concluded(t),
    }


def policy_in_force(conn: Connection, t: HypothesisTables, gate_id: str) -> PolicyKind:
    """The effective policy kind of `gate_id` at this point of the log (fold order): the latest
    protocol recorded so far, else the rigor mode's preset (slice M ruling 2, read by the fold)."""
    row = conn.execute(
        select(t.protocols.c.spec).order_by(t.protocols.c.event_id.desc()).limit(1)
    ).first()
    if row is not None:
        policies = ProtocolSpec.model_validate_json(str(row[0])).gate_policies
        if policies is not None:
            for entry in policies.entries:
                if entry.gate == gate_id:
                    return entry.policy
    mode = conn.execute(select(t.project.c.rigor_mode).limit(1)).first()
    return preset(RigorMode(str(mode[0])) if mode else RigorMode.PILOT, gate_id).kind


def act_is_consistent(
    conn: Connection,
    t: HypothesisTables,
    event: Event,
    gate_id: str,
    recorded: PolicyKind,
    proposers: set[str],
) -> bool:
    """Whether the actor of `event` may have passed `gate_id` under the policy in force: the
    recorded policy equals it, a `human` policy needs a human and any other needs a session
    outside `proposers`."""
    if recorded is not policy_in_force(conn, t, gate_id):
        return False
    if recorded is PolicyKind.HUMAN:
        return event.actor.kind == "human"
    return event.actor.session not in proposers


def _lead_recorded(t: HypothesisTables) -> Handler:
    def recorded(conn: Connection, event: Event) -> None:
        p = LeadRecorded.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.leads)
            .values(
                lead_id=p.lead_id,
                text=p.text,
                framework=p.framework,
                triggers_json=canonical_json(
                    [x.model_dump(mode="json") for x in p.triggers]
                ).decode(),
                prior_json=canonical_json(list(p.prior)).decode(),
                prior_total=p.prior_total,
                author_session=event.actor.session,
                state="open",
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["lead_id"])
        )
        if not inserted.rowcount:
            return
        for trigger in p.triggers:
            conn.execute(
                sqlite_insert(t.lead_triggers)
                .values(lead_id=p.lead_id, kind=trigger.kind.value, ref=trigger.ref)
                .on_conflict_do_nothing()
            )
        for key in p.keys:
            conn.execute(
                sqlite_insert(t.lead_keys)
                .values(lead_id=p.lead_id, key=key)
                .on_conflict_do_nothing()
            )

    return recorded


def _lead_decided(t: HypothesisTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        p = LeadDecided.model_validate(event.payload)
        row = conn.execute(
            select(t.leads.c.author_session).where(t.leads.c.lead_id == p.lead_id)
        ).first()
        if row is None:
            return
        if not act_is_consistent(conn, t, event, "hypotheses.lead_decide", p.policy, {str(row[0])}):
            return
        conn.execute(
            update(t.leads)
            .where(t.leads.c.lead_id == p.lead_id)
            .values(
                state=_STATE[p.decision],
                decision=p.decision,
                reason=None if p.reason is None else p.reason.value,
                note=p.note,
                decision_event_id=event.id,
            )
        )

    return decided


def _drafted(t: HypothesisTables) -> Handler:
    def drafted(conn: Connection, event: Event) -> None:
        p = HypothesisDrafted.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.hypotheses)
            .values(
                hypothesis_id=p.hypothesis_id,
                h_version=p.h_version,
                kind=p.spec.kind,
                lead=p.spec.lead,
                spec_json=canonical_json(p.spec.model_dump(mode="json")).decode(),
                supersedes=p.supersedes,
                drafter_session=event.actor.session,
                drafter_model=event.actor.model,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["hypothesis_id"])
        )
        if inserted.rowcount and p.supersedes is not None:
            conn.execute(
                update(t.hypotheses)
                .where(
                    t.hypotheses.c.hypothesis_id == p.supersedes,
                    t.hypotheses.c.superseded_by.is_(None),
                )
                .values(superseded_by=p.hypothesis_id)
            )

    return drafted


def _abandoned(t: HypothesisTables) -> Handler:
    def abandoned(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = HypothesisAbandoned.model_validate(event.payload)
        conn.execute(
            update(t.hypotheses)
            .where(
                t.hypotheses.c.hypothesis_id == p.hypothesis_id,
                t.hypotheses.c.abandoned_event_id.is_(None),
            )
            .values(abandon_reason=p.reason.value, abandoned_event_id=event.id)
        )

    return abandoned


def _concluded(t: HypothesisTables) -> Handler:
    def concluded(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = HypothesisConcluded.model_validate(event.payload)
        conn.execute(
            update(t.hypotheses)
            .where(t.hypotheses.c.hypothesis_id == p.hypothesis_id)
            .values(conclusion_text=p.text, conclusion_event_id=event.id)
        )

    return concluded
