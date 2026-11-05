"""Projection of free labels, terms and consolidation (slice 3d, plan Regions-C).

Organisation class: none of these tables is read by an evidence module, and none of them is a
graph or layer table.

- `labels` holds one row per application; `live_key` is the end of the merge chain of `key`,
  recomputed for the affected keys whenever a merge or an unmerge is folded. `decision` is a
  human's confirm or reject of the application and `withdrawn` a withdrawal.
- `label_merges` keeps every `label.merged` (`active` until a `label.unmerged` names it). A key is
  merged into at most one key at a time; the services refuse a second merge and a cycle.
- `terms` holds the latest version of each term, `term_aliases` the keys (name and aliases) of that
  version.
- `consolidation_passes`, `consolidation_proposals` and `consolidation_decisions` keep every pass,
  proposal and human decision.

A decision, a promotion, a revision, a retirement and a merge are folded only when their actor is a
human (defence in depth: no service writes one for another actor, R-51). Handlers are total.
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
from factory.model.labels import (
    ConsolidationDecided,
    ConsolidationPassCompleted,
    ConsolidationPassStarted,
    ConsolidationProposed,
    LabelApplicationDecided,
    LabelApplied,
    LabelMerged,
    LabelUnmerged,
    LabelWithdrawn,
    TermPromoted,
    TermRetired,
    TermRevised,
    label_key,
)


@dataclass(frozen=True)
class LabelTables:
    labels: Table
    merges: Table
    terms: Table
    term_aliases: Table
    passes: Table
    proposals: Table
    decisions: Table


def label_tables(metadata: MetaData) -> LabelTables:
    labels = Table(
        "labels",
        metadata,
        Column("application_id", String, primary_key=True),
        Column("target_type", String, nullable=False),
        Column("target", String, nullable=False),
        Column("text", String, nullable=False),
        Column("key", String, nullable=False),
        Column("live_key", String, nullable=False),
        Column("quote", String),
        Column("quote_text", String),
        Column("status", String, nullable=False),
        Column("origin", String, nullable=False),
        Column("import_ref", String),
        Column("applier_kind", String, nullable=False),
        Column("applier_session", String, nullable=False),
        Column("decision", String),
        Column("withdrawn", Integer, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_labels_key", "key"),
        Index("ix_labels_live_key", "live_key"),
        Index("ix_labels_target", "target"),
    )
    merges = Table(
        "label_merges",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("into_key", String, nullable=False),
        Column("from_key", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("proposal_id", String),
        Column("active", Integer, nullable=False),
        Index("ix_label_merges_from", "from_key", "active"),
        Index("ix_label_merges_into", "into_key", "active"),
    )
    terms = Table(
        "terms",
        metadata,
        Column("term_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("name", String, nullable=False),
        Column("name_key", String, nullable=False),
        Column("aliases", String, nullable=False),
        Column("definition", String, nullable=False),
        Column("applies_to", String, nullable=False),
        Column("refers_to", String),
        Column("from_keys", String, nullable=False),
        Column("retired", Integer, nullable=False),
        Column("version", Integer, nullable=False),
    )
    term_aliases = Table(
        "term_aliases",
        metadata,
        Column("term_id", String, primary_key=True),
        Column("key", String, primary_key=True),
        Index("ix_term_aliases_key", "key"),
    )
    passes = Table(
        "consolidation_passes",
        metadata,
        Column("pass_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("clusters_blob", String, nullable=False),
        Column("constants", String, nullable=False),
        Column("counts", String, nullable=False),
        Column("completed_event", String),
    )
    proposals = Table(
        "consolidation_proposals",
        metadata,
        Column("proposal_id", String, primary_key=True),
        Column("pass_id", String, nullable=False),
        Column("cluster_index", Integer, nullable=False),
        Column("action", String, nullable=False),
        Column("into", String),
        Column("members", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("quotes", String, nullable=False),
        Column("proposer_session", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_consolidation_proposals_cluster", "pass_id", "cluster_index"),
    )
    decisions = Table(
        "consolidation_decisions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("pass_id", String, nullable=False),
        Column("cluster_index", Integer, nullable=False),
        Column("decision", String, nullable=False),
        Column("merge_events", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("proposal_id", String),
        Column("decider_user", String, nullable=False),
        Index("ix_consolidation_decisions_cluster", "pass_id", "cluster_index"),
    )
    return LabelTables(labels, merges, terms, term_aliases, passes, proposals, decisions)


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def label_handlers(t: LabelTables) -> dict[str, Handler]:
    return {
        "label.applied": _applied(t),
        "label.withdrawn": _withdrawn(t),
        "label.application_decided": _application_decided(t),
        "label.merged": _merged(t),
        "label.unmerged": _unmerged(t),
        "term.promoted": _promoted(t),
        "term.revised": _revised(t),
        "term.retired": _retired(t),
        "consolidation.pass_started": _pass_started(t),
        "consolidation.proposed": _proposed(t),
        "consolidation.decided": _decided(t),
        "consolidation.pass_completed": _pass_completed(t),
    }


# --- Merge chains ---


def live_key_of(conn: Connection, key: str) -> str:
    """The end of the active merge chain of `key` (itself when unmerged); cycle-safe."""
    current, seen = key, set()
    while current not in seen:
        seen.add(current)
        into = conn.execute(
            text("SELECT into_key FROM label_merges WHERE from_key = :k AND active = 1"),
            {"k": current},
        ).scalar_one_or_none()
        if into is None:
            break
        current = str(into)
    return current


def _keys_through(conn: Connection, key: str) -> set[str]:
    """`key` and every key whose merge chain passes through it."""
    found, frontier = {key}, [key]
    while frontier:
        rows = conn.execute(
            text(
                "SELECT from_key FROM label_merges WHERE active = 1 AND into_key IN "
                "(SELECT value FROM json_each(:ks))"
            ),
            {"ks": json.dumps(frontier)},
        ).all()
        frontier = [str(r[0]) for r in rows if str(r[0]) not in found]
        found.update(frontier)
    return found


def _refresh(t: LabelTables, conn: Connection, key: str) -> None:
    for affected in sorted(_keys_through(conn, key)):
        conn.execute(
            update(t.labels)
            .where(t.labels.c.key == affected)
            .values(live_key=live_key_of(conn, affected))
        )


# --- Handlers ---


def _applied(t: LabelTables) -> Handler:
    def applied(conn: Connection, event: Event) -> None:
        p = LabelApplied.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.labels)
            .values(
                application_id=p.application_id,
                target_type=p.target_type.value,
                target=p.target,
                text=p.text,
                key=p.key,
                live_key=live_key_of(conn, p.key),
                quote=None if p.quote is None else p.quote.model_dump_json(),
                quote_text=None if p.quote is None else p.quote.quote,
                status=p.status,
                origin=p.origin,
                import_ref=p.import_ref,
                applier_kind=event.actor.kind,
                applier_session=event.actor.session,
                decision=None,
                withdrawn=0,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["application_id"])
        )

    return applied


def _withdrawn(t: LabelTables) -> Handler:
    def withdrawn(conn: Connection, event: Event) -> None:
        p = LabelWithdrawn.model_validate(event.payload)
        conn.execute(
            update(t.labels)
            .where(t.labels.c.application_id == p.application_id)
            .values(withdrawn=1)
        )

    return withdrawn


def _application_decided(t: LabelTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = LabelApplicationDecided.model_validate(event.payload)
        conn.execute(
            update(t.labels)
            .where(t.labels.c.application_id == p.application_id)
            .values(decision=p.decision)
        )

    return decided


def _merged(t: LabelTables) -> Handler:
    def merged(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = LabelMerged.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.merges)
            .values(
                event_id=event.id,
                into_key=p.into_key,
                from_key=p.from_key,
                reason=p.reason,
                proposal_id=p.proposal_id,
                active=1,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        _refresh(t, conn, p.from_key)

    return merged


def _unmerged(t: LabelTables) -> Handler:
    def unmerged(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = LabelUnmerged.model_validate(event.payload)
        row = conn.execute(
            select(t.merges.c.from_key).where(t.merges.c.event_id == p.merge_event)
        ).scalar_one_or_none()
        if row is None:
            return
        conn.execute(update(t.merges).where(t.merges.c.event_id == p.merge_event).values(active=0))
        _refresh(t, conn, str(row))

    return unmerged


def _term_values(p: TermPromoted, event: Event, version: int) -> dict[str, object]:
    return {
        "event_id": event.id,
        "name": p.name,
        "name_key": label_key(p.name),
        "aliases": canonical_json(list(p.aliases)).decode(),
        "definition": p.definition,
        "applies_to": canonical_json([a.value for a in p.applies_to]).decode(),
        "refers_to": p.refers_to,
        "from_keys": canonical_json(list(p.from_keys)).decode(),
        "version": version,
    }


def _set_aliases(t: LabelTables, conn: Connection, p: TermPromoted) -> None:
    conn.execute(text("DELETE FROM term_aliases WHERE term_id = :t"), {"t": p.term_id})
    keys = sorted({label_key(p.name), *(label_key(a) for a in p.aliases)})
    conn.execute(
        sqlite_insert(t.term_aliases).on_conflict_do_nothing(),
        [{"term_id": p.term_id, "key": k} for k in keys],
    )


def _promoted(t: LabelTables) -> Handler:
    def promoted(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = TermPromoted.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.terms)
            .values(term_id=p.term_id, retired=0, **_term_values(p, event, 1))
            .on_conflict_do_nothing(index_elements=["term_id"])
        )
        if inserted.rowcount:
            _set_aliases(t, conn, p)

    return promoted


def _revised(t: LabelTables) -> Handler:
    def revised(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = TermRevised.model_validate(event.payload)
        row = conn.execute(
            select(t.terms.c.event_id, t.terms.c.version).where(t.terms.c.term_id == p.term_id)
        ).first()
        if row is None or str(row[0]) != p.supersedes:
            return
        conn.execute(
            update(t.terms)
            .where(t.terms.c.term_id == p.term_id)
            .values(**_term_values(p, event, int(row[1]) + 1))
        )
        _set_aliases(t, conn, p)

    return revised


def _retired(t: LabelTables) -> Handler:
    def retired(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = TermRetired.model_validate(event.payload)
        conn.execute(update(t.terms).where(t.terms.c.term_id == p.term_id).values(retired=1))

    return retired


def _pass_started(t: LabelTables) -> Handler:
    def started(conn: Connection, event: Event) -> None:
        p = ConsolidationPassStarted.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.passes)
            .values(
                pass_id=p.pass_id,
                event_id=event.id,
                clusters_blob=p.clusters_blob,
                constants=_dumps(p.constants),
                counts=_dumps(p.counts),
                completed_event=None,
            )
            .on_conflict_do_nothing(index_elements=["pass_id"])
        )

    return started


def _proposed(t: LabelTables) -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = ConsolidationProposed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.proposals)
            .values(
                proposal_id=p.proposal_id,
                pass_id=p.pass_id,
                cluster_index=p.cluster_index,
                action=p.action,
                into=p.into,
                members=canonical_json(list(p.members)).decode(),
                reason=p.reason,
                quotes=canonical_json([q.model_dump(mode="json") for q in p.quotes]).decode(),
                proposer_session=event.actor.session,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["proposal_id"])
        )

    return proposed


def _decided(t: LabelTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = ConsolidationDecided.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.decisions)
            .values(
                event_id=event.id,
                pass_id=p.pass_id,
                cluster_index=p.cluster_index,
                decision=p.decision,
                merge_events=canonical_json(list(p.merge_events)).decode(),
                reason=p.reason,
                proposal_id=p.proposal_id,
                decider_user=event.actor.user,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return decided


def _pass_completed(t: LabelTables) -> Handler:
    def completed(conn: Connection, event: Event) -> None:
        p = ConsolidationPassCompleted.model_validate(event.payload)
        conn.execute(
            update(t.passes)
            .where(t.passes.c.pass_id == p.pass_id, t.passes.c.completed_event.is_(None))
            .values(completed_event=event.id)
        )

    return completed
