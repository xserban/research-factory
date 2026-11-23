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

import json
from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.index.sheets import sheet_lead_problem
from factory.model.hypotheses import (
    HypothesisAbandoned,
    HypothesisConcluded,
    HypothesisDrafted,
    HypothesisRegistered,
    HypothesisReviewed,
    HypothesisSpec,
    LeadDecided,
    LeadRecorded,
    Level,
    LiteratureTest,
    ModelCutoffDeclared,
    TriggerKind,
)
from factory.model.levels import AutonomyLevel
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolSpec
from factory.modules.autonomy import resolve_policy
from factory.modules.contract import GatePolicy, PolicyKind
from factory.modules.presets import preset

MIN_SEEDS_BY_MODE = {RigorMode.EXPLORATORY: 2, RigorMode.PILOT: 3, RigorMode.SYSTEMATIC: 5}
"""The plan defaults of `services.hypothesis_gates.effective_plan`, spelled once for the fold."""
_STATE = {"promote": "promoted", "park": "parked", "discard": "discarded"}


@dataclass(frozen=True)
class HypothesisTables:
    leads: Table
    lead_triggers: Table
    lead_keys: Table
    hypotheses: Table
    reviews: Table
    registrations: Table
    cutoffs: Table
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
        Column("serves_rq", String),
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
        Column("serves_rq", String),
        Column("event_id", String, nullable=False),
        Column("abandon_reason", String),
        Column("abandoned_event_id", String),
        Column("conclusion_text", String),
        Column("conclusion_event_id", String),
    )
    reviews = Table(
        "hypothesis_reviews",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("hypothesis_id", String, nullable=False),
        Column("h_version", String, nullable=False),
        Column("recommend", String, nullable=False),
        Column("items_json", String, nullable=False),
        Column("notes_json", String, nullable=False),
        Column("critic_session", String, nullable=False),
        Column("critic_model", String),
        Column("task_id", String, nullable=False),
        Column("eligible", Integer, nullable=False),
        Index("ix_hypothesis_reviews_hyp", "hypothesis_id"),
    )
    registrations = Table(
        "hypothesis_registrations",
        metadata,
        Column("hypothesis_id", String, primary_key=True),
        Column("h_version", String, nullable=False),
        Column("review_event_id", String),
        Column("policy", String, nullable=False),
        Column("autonomy", String, nullable=False),
        Column("flags_json", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("level", String, nullable=False),
        Column("min_seeds", Integer, nullable=False),
    )
    cutoffs = Table(
        "model_cutoffs",
        metadata,
        Column("model", String, primary_key=True),
        Column("cutoff", String, nullable=False),
        Column("source", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return HypothesisTables(
        leads, triggers, keys, hypotheses, reviews, registrations, cutoffs, protocols, project
    )


def hypothesis_handlers(t: HypothesisTables) -> dict[str, Handler]:
    return {
        "lead.recorded": _lead_recorded(t),
        "lead.decided": _lead_decided(t),
        "hypothesis.drafted": _drafted(t),
        "hypothesis.abandoned": _abandoned(t),
        "hypothesis.concluded": _concluded(t),
        "hypothesis.reviewed": _reviewed(t),
        "hypothesis.registered": _registered(t),
        "model.cutoff_declared": _cutoff(t),
    }


def plan_in_force(conn: Connection) -> tuple[int, Level]:
    """Minimum seeds and confidence level of the latest protocol recorded so far, with the mode's
    default for a field it leaves open. Read when a hypothesis registers and never again: the
    registration pins them (R-121)."""
    mode_raw = conn.execute(text("SELECT rigor_mode FROM project LIMIT 1")).scalar()
    mode = RigorMode(str(mode_raw)) if mode_raw is not None else RigorMode.PILOT
    row = conn.execute(text("SELECT spec FROM protocols ORDER BY event_id DESC LIMIT 1")).first()
    plan = None if row is None else ProtocolSpec.model_validate_json(str(row[0])).hypothesis_plan
    min_seeds = plan.min_seeds if plan is not None and plan.min_seeds is not None else None
    level: Level = "0.95" if plan is None else plan.confidence
    return (min_seeds if min_seeds is not None else MIN_SEEDS_BY_MODE[mode]), level


def cutoff_flags_of(conn: Connection, hypothesis_id: str) -> tuple[str, ...]:
    """The R-53 flags of a literature hypothesis over the drafter's model and every critic's:
    `cutoff-unknown` when a model has no declared cut-off, `contaminated` when a cut-off is on or
    after the window start. An experiment hypothesis has none (its evidence is generated after
    registration). The service reads it on request, the fold at its point of the log."""
    row = conn.execute(
        text("SELECT spec_json, drafter_model FROM hypotheses WHERE hypothesis_id = :h"),
        {"h": hypothesis_id},
    ).first()
    if row is None:
        return ()
    spec = HypothesisSpec.model_validate(json.loads(str(row[0])))
    if not isinstance(spec.test, LiteratureTest):
        return ()
    models = {str(row[1])} if row[1] is not None else set()
    critics = conn.execute(
        text(
            "SELECT DISTINCT critic_model FROM hypothesis_reviews "
            "WHERE hypothesis_id = :h AND critic_model IS NOT NULL"
        ),
        {"h": hypothesis_id},
    ).scalars()
    models.update(str(m) for m in critics)
    cutoffs = {
        str(m): str(c)
        for m, c in conn.execute(text("SELECT model, cutoff FROM model_cutoffs")).all()
    }
    flags: set[str] = set()
    start = spec.test.window_start.isoformat()
    for model in models:
        if model not in cutoffs:
            flags.add("cutoff-unknown")
        elif cutoffs[model] >= start:
            flags.add("contaminated")
    return tuple(sorted(flags))


def policy_in_force(conn: Connection, t: HypothesisTables, gate_id: str) -> PolicyKind:
    """The effective policy kind of `gate_id` at this point of the log (fold order): the latest
    protocol recorded so far, else the rigor mode's preset (slice M ruling 2, read by the fold)."""
    return policy_of(conn, t.protocols, t.project, gate_id)


LEVEL_READER_KEY = "autonomy_level_reader"
"""Key in `project.info` of the callable that tells the fold the project's autonomy level."""


def autonomy_level_of(project: Table) -> AutonomyLevel:
    """The autonomy level the fold sees: the reader attached to the `project` table (see
    `index.levels.attach_level_reader`), else `attended`. No table or column holds it."""
    reader = project.info.get(LEVEL_READER_KEY)
    return AutonomyLevel.ATTENDED if reader is None else AutonomyLevel(reader())


def policy_of(conn: Connection, protocols: Table, project: Table, gate_id: str) -> PolicyKind:
    """`policy_in_force` over the protocol and project tables, for folds that do not hold
    `HypothesisTables` (the experiment gates use it too). Under `attended` this is the protocol's
    entry, else the rigor preset's, exactly as before the levels; under another level the entry is
    read through the autonomy profile (`modules.autonomy.resolve_policy`)."""
    entry: GatePolicy | None = None
    row = conn.execute(
        select(protocols.c.spec).order_by(protocols.c.event_id.desc()).limit(1)
    ).first()
    if row is not None:
        policies = ProtocolSpec.model_validate_json(str(row[0])).gate_policies
        if policies is not None:
            for candidate in policies.entries:
                if candidate.gate == gate_id:
                    entry = candidate.as_policy()
                    break
    mode_row = conn.execute(select(project.c.rigor_mode).limit(1)).first()
    mode = RigorMode(str(mode_row[0])) if mode_row else RigorMode.PILOT
    level = autonomy_level_of(project)
    if level is AutonomyLevel.ATTENDED:
        return preset(mode, gate_id).kind if entry is None else entry.kind
    return resolve_policy(level, mode, gate_id, entry).kind


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
        if any(
            x.kind is TriggerKind.SHEET and sheet_lead_problem(conn, x.ref) is not None
            for x in p.triggers
        ):
            return  # a sheet that breaks the lead guard (decision 143); no service writes it
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
                serves_rq=p.serves_rq,
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


def _supersede(conn: Connection, t: HypothesisTables, old: str, new: str) -> None:
    conn.execute(
        update(t.hypotheses)
        .where(t.hypotheses.c.hypothesis_id == old, t.hypotheses.c.superseded_by.is_(None))
        .values(superseded_by=new)
    )


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
                serves_rq=p.serves_rq,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["hypothesis_id"])
        )
        if inserted.rowcount and p.supersedes is not None:
            # A draft replaces an unregistered draft at once; a registered hypothesis stays
            # registered until its replacement registers (`_registered`), so that an unreviewed
            # draft cannot undo a registration.
            registered = conn.execute(
                select(t.registrations.c.hypothesis_id).where(
                    t.registrations.c.hypothesis_id == p.supersedes
                )
            ).first()
            if registered is None:
                _supersede(conn, t, p.supersedes, p.hypothesis_id)

    return drafted


def _conclusive_evaluation(conn: Connection, hypothesis_id: str) -> bool:
    """Whether a conclusive evaluation of the hypothesis has been folded."""
    found = conn.execute(
        text(
            "SELECT 1 FROM hypothesis_evaluations WHERE hypothesis_id = :h "
            "AND outcome != 'incomplete' LIMIT 1"
        ),
        {"h": hypothesis_id},
    ).first()
    return found is not None


def _abandoned(t: HypothesisTables) -> Handler:
    def abandoned(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = HypothesisAbandoned.model_validate(event.payload)
        if _conclusive_evaluation(conn, p.hypothesis_id):
            return  # an evaluated outcome stays on record (R-52)
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
        if not _conclusive_evaluation(conn, p.hypothesis_id):
            return  # a conclusion reads an outcome; none exists
        conn.execute(
            update(t.hypotheses)
            .where(t.hypotheses.c.hypothesis_id == p.hypothesis_id)
            .values(conclusion_text=p.text, conclusion_event_id=event.id)
        )

    return concluded


def _reviewed(t: HypothesisTables) -> Handler:
    """A review is kept whoever wrote it; `eligible` says whether its critic was independent of
    the hypothesis by session (R-51): not the drafter's, not the lead author's, and the session the
    payload names is the one that wrote the event. The model rule needs the plan and is applied on
    read."""

    def reviewed(conn: Connection, event: Event) -> None:
        p = HypothesisReviewed.model_validate(event.payload)
        row = conn.execute(
            select(t.hypotheses.c.drafter_session, t.hypotheses.c.lead).where(
                t.hypotheses.c.hypothesis_id == p.hypothesis_id
            )
        ).first()
        if row is None:
            return
        proposers = {str(row[0])}
        if row[1] is not None:
            author = conn.execute(
                select(t.leads.c.author_session).where(t.leads.c.lead_id == str(row[1]))
            ).scalar()
            if author is not None:
                proposers.add(str(author))
        eligible = event.actor.session not in proposers and p.critic_session == event.actor.session
        conn.execute(
            sqlite_insert(t.reviews)
            .values(
                event_id=event.id,
                hypothesis_id=p.hypothesis_id,
                h_version=p.h_version,
                recommend=p.recommend,
                items_json=canonical_json({str(k): v for k, v in p.items.items()}).decode(),
                notes_json=canonical_json({str(k): v for k, v in p.notes.items()}).decode(),
                critic_session=event.actor.session,
                critic_model=event.actor.model,
                task_id=p.task_id,
                eligible=int(eligible),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return reviewed


def _registered(t: HypothesisTables) -> Handler:
    """A registration folds only when it is consistent (see the module docstring): the hypothesis
    and version are the ones drafted, the policy recorded is the one in force and fits the actor,
    the autonomy label is the actor's, and any review it cites is an eligible review of this
    version. The first consistent registration wins."""

    def registered(conn: Connection, event: Event) -> None:
        p = HypothesisRegistered.model_validate(event.payload)
        row = conn.execute(
            select(
                t.hypotheses.c.h_version,
                t.hypotheses.c.drafter_session,
                t.hypotheses.c.lead,
                t.hypotheses.c.abandoned_event_id,
                t.hypotheses.c.superseded_by,
                t.hypotheses.c.supersedes,
            ).where(t.hypotheses.c.hypothesis_id == p.hypothesis_id)
        ).first()
        if row is None or str(row[0]) != p.h_version or row[3] is not None or row[4] is not None:
            return
        proposers = {str(row[1])}
        if row[2] is not None:
            author = conn.execute(
                select(t.leads.c.author_session).where(t.leads.c.lead_id == str(row[2]))
            ).scalar()
            if author is not None:
                proposers.add(str(author))
        if p.autonomy != ("human" if event.actor.kind == "human" else "agent"):
            return
        if not act_is_consistent(conn, t, event, "hypotheses.register", p.policy, proposers):
            return
        if p.review_event_id is not None:
            cited = conn.execute(
                select(t.reviews.c.eligible).where(
                    t.reviews.c.event_id == p.review_event_id,
                    t.reviews.c.hypothesis_id == p.hypothesis_id,
                    t.reviews.c.h_version == p.h_version,
                )
            ).first()
            if cited is None or not cited[0]:
                return
        min_seeds, level = plan_in_force(conn)
        if p.level not in (None, level) or p.min_seeds not in (None, min_seeds):
            return  # the plan a registration states is the one in force
        conn.execute(
            sqlite_insert(t.registrations)
            .values(
                level=level,
                min_seeds=min_seeds,
                hypothesis_id=p.hypothesis_id,
                h_version=p.h_version,
                review_event_id=p.review_event_id,
                policy=p.policy.value,
                autonomy=p.autonomy,
                flags_json=canonical_json(list(p.flags)).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["hypothesis_id"])
        )
        if row[5] is not None:
            _supersede(conn, t, str(row[5]), p.hypothesis_id)

    return registered


def _cutoff(t: HypothesisTables) -> Handler:
    def declared(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = ModelCutoffDeclared.model_validate(event.payload)
        values = {"cutoff": p.cutoff.isoformat(), "source": p.source, "event_id": event.id}
        conn.execute(
            sqlite_insert(t.cutoffs)
            .values(model=p.model, **values)
            .on_conflict_do_update(index_elements=["model"], set_=values)
        )

    return declared
