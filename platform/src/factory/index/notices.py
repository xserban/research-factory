"""Projection of notices and versions (living-C): observations and human acts, never states.

`notices` keeps one row per notice identity (the first observation wins; a repeat changes nothing).
Whether a work is retracted or a correction is pending is computed at read time from these rows
by `model.notices.notice_state`; nothing derived is stored here.

`version_observations` keeps one row per (work, route, version) a source called newer.
`version_links` keeps one row per (work, published identifier) link, including a refused one
(`conflicts_with` set); only an applied link writes `work_aliases` rows (identifier -> work) and
the matching `work_keys` rows, which incremental deduplication reads to find the work by the
published identifier.

Handlers are total: an event naming a repeated identity changes nothing. Every table is empty for
a log without the events, so each is left out of the state hash then.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.dedup_keys import identifier_keys
from factory.model.notices import NoticeAssessed, NoticeObserved
from factory.model.screening import Channel
from factory.model.versions import DocumentPreferred, VersionLinked, VersionObserved


@dataclass(frozen=True)
class NoticeTables:
    notices: Table
    version_observations: Table
    version_links: Table
    work_aliases: Table
    notice_assessments: Table
    document_preferences: Table
    work_keys: Table
    label_sessions: Table
    """The search projection's lookup table, which an applied link adds its identifiers to."""


def notice_tables(metadata: MetaData, work_keys: Table, label_sessions: Table) -> NoticeTables:
    notices = Table(
        "notices",
        metadata,
        Column("notice_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("identity", String, nullable=False),
        Column("notice_date", String),
        Column("notice_doi", String),
        Column("source", String, nullable=False),
        Column("run_id", String, nullable=False),
        Column("raw_blob", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("observed_at", String, nullable=False),
        Index("ix_notices_work", "work_id"),
        Index("uq_notices_identity", "work_id", "kind", "identity", unique=True),
    )
    observations = Table(
        "version_observations",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("route", String, primary_key=True),
        Column("source_version", String, primary_key=True),
        Column("run_id", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("observed_at", String, nullable=False),
    )
    links = Table(
        "version_links",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("link_key", String, primary_key=True),
        Column("identifiers", String, nullable=False),
        Column("venue", String),
        Column("source", String, nullable=False),
        Column("run_id", String, nullable=False),
        Column("conflicts_with", String),
        Column("event_id", String, nullable=False),
        Column("linked_at", String, nullable=False),
    )
    aliases = Table(
        "work_aliases",
        metadata,
        Column("kind", String, primary_key=True),
        Column("value", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Index("ix_work_aliases_work", "work_id"),
    )
    assessments = Table(
        "notice_assessments",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("notice_id", String, nullable=False),
        Column("decision", String, nullable=False),
        Column("fields", String, nullable=False),
        Column("rationale", String, nullable=False),
        Column("actor_id", String, nullable=False),
        Column("channel", String, nullable=False, server_default="cli"),
        Column("assessed_at", String, nullable=False),
        Index("ix_notice_assessments_notice", "notice_id"),
    )
    preferences = Table(
        "document_preferences",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("document_id", String, nullable=False),
        Column("rationale", String, nullable=False),
        Column("automatic", Integer, nullable=False),
        Column("actor_id", String, nullable=False),
        Column("preferred_at", String, nullable=False),
        Index("ix_document_preferences_work", "work_id"),
    )
    return NoticeTables(
        notices,
        observations,
        links,
        aliases,
        assessments,
        preferences,
        work_keys,
        label_sessions,
    )


def notice_handlers(t: NoticeTables) -> dict[str, Handler]:
    def observed(conn: Connection, event: Event) -> None:
        payload = NoticeObserved.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.notices)
            .values(
                notice_id=payload.notice_id,
                work_id=payload.work_id,
                kind=payload.kind.value,
                identity=payload.identity,
                notice_date=None
                if payload.notice_date is None
                else payload.notice_date.isoformat(),
                notice_doi=payload.notice_doi,
                source=payload.source,
                run_id=payload.run_id,
                raw_blob=payload.raw_blob,
                event_id=event.id,
                observed_at=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        )

    def version_observed(conn: Connection, event: Event) -> None:
        payload = VersionObserved.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.version_observations)
            .values(
                work_id=payload.work_id,
                route=payload.route.value,
                source_version=payload.source_version,
                run_id=payload.run_id,
                event_id=event.id,
                observed_at=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        )

    def version_linked(conn: Connection, event: Event) -> None:
        payload = VersionLinked.model_validate(event.payload)
        keys = identifier_keys(payload.identifiers)
        inserted = conn.execute(
            sqlite_insert(t.version_links)
            .values(
                work_id=payload.work_id,
                link_key=":".join(keys[0]) if keys else "",
                identifiers=canonical_json(payload.identifiers.model_dump(mode="json")).decode(),
                venue=payload.venue,
                source=payload.source,
                run_id=payload.run_id,
                conflicts_with=payload.conflicts_with,
                event_id=event.id,
                linked_at=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        ).rowcount
        if not inserted or payload.conflicts_with is not None:
            return
        for kind, value in keys:
            conn.execute(
                sqlite_insert(t.work_aliases)
                .values(kind=kind, value=value, work_id=payload.work_id, event_id=event.id)
                .on_conflict_do_nothing()
            )
            conn.execute(
                sqlite_insert(t.work_keys)
                .values(kind=kind, value=value, work_id=payload.work_id)
                .on_conflict_do_nothing()
            )

    def assessed(conn: Connection, event: Event) -> None:
        payload = NoticeAssessed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.notice_assessments)
            .values(
                event_id=event.id,
                notice_id=payload.notice_id,
                decision=payload.decision.value,
                fields=canonical_json(list(payload.fields)).decode(),
                rationale=payload.rationale,
                actor_id=event.actor.id,
                channel=payload.channel.value,
                assessed_at=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        )
        if payload.channel is Channel.MCP:  # a relaying session cannot join a pass (37.6)
            conn.execute(
                sqlite_insert(t.label_sessions)
                .values(session=event.actor.session)
                .on_conflict_do_nothing(index_elements=["session"])
            )

    def preferred(conn: Connection, event: Event) -> None:
        payload = DocumentPreferred.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.document_preferences)
            .values(
                event_id=event.id,
                work_id=payload.work_id,
                document_id=payload.document_id,
                rationale=payload.rationale,
                automatic=int(payload.automatic),
                actor_id=event.actor.id,
                preferred_at=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        )

    return {
        "notice.assessed": assessed,
        "document.preferred": preferred,
        "notice.observed": observed,
        "version.observed": version_observed,
        "version.linked": version_linked,
    }
