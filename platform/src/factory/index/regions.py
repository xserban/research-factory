"""Projection of regions (slice 3d, plan Regions-A).

`region_definitions` keeps every `region.defined` (the live definition of a region is its row with
the greatest `event_id`); `regions` has one row per region id. `region_snapshots` keeps every
snapshot event; the latest of a region is the row with the greatest `event_id`. `region_members`
holds the members of the latest snapshot of each region only (older sets are read from their
blobs on demand) and is replaced as a whole when a newer snapshot is folded. `region_reviews` and
`region_member_decisions` keep every human act; the latest per version, or per member, binds.

Only a review or a member decision whose actor is a human is folded (defence in depth: no service
writes one for another actor, R-51). Handlers are total in the sense that a repeated event id
changes nothing. The projector reads the member and basis blobs from `blobs/`; folding a snapshot
without a blob store raises.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.regions import RegionDefined, RegionMemberDecided, RegionReviewed
from factory.model.regions import RegionSnapshotTaken as Snapshot
from factory.regions.version import canonical_rules


@dataclass(frozen=True)
class RegionTables:
    regions: Table
    definitions: Table
    snapshots: Table
    members: Table
    reviews: Table
    decisions: Table


def region_tables(metadata: MetaData) -> RegionTables:
    regions = Table(
        "regions",
        metadata,
        Column("region_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("facet_question", String),
        Column("facet_slot", String),
        Column("event_id", String, nullable=False),
        Index("ix_regions_facet", "facet_question", "facet_slot"),
    )
    definitions = Table(
        "region_definitions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("region_id", String, nullable=False),
        Column("name", String, nullable=False),
        Column("definition", String, nullable=False),
        Column("rules", String, nullable=False),
        Column("supersedes", String),
        Column("author", String, nullable=False),
        Column("author_user", String, nullable=False),
        Column("writer_session", String, nullable=False),
        Column("input_blob", String),
        Index("ix_region_definitions_region", "region_id", "event_id"),
    )
    snapshots = Table(
        "region_snapshots",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("region_id", String, nullable=False),
        Column("version", String, nullable=False),
        Column("definition_event", String, nullable=False),
        Column("rules_hash", String, nullable=False),
        Column("decisions", String, nullable=False),
        Column("members_blob", String, nullable=False),
        Column("members_hash", String, nullable=False),
        Column("basis_blob", String, nullable=False),
        Column("counts", String, nullable=False),
        Column("as_of", String, nullable=False),
        Index("ix_region_snapshots_region", "region_id", "event_id"),
        Index("ix_region_snapshots_version", "version"),
    )
    members = Table(
        "region_members",
        metadata,
        Column("region_id", String, primary_key=True),
        Column("member_type", String, primary_key=True),
        Column("member", String, primary_key=True),
        Column("version", String, nullable=False),
        Column("basis", String, nullable=False),
        Index("ix_region_members_member", "member"),
    )
    reviews = Table(
        "region_reviews",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("version", String, nullable=False),
        Column("state", String, nullable=False),
        Column("note", String),
        Column("reviewer_user", String, nullable=False),
        Column("self_reviewed", Integer, nullable=False),
        Index("ix_region_reviews_version", "version", "event_id"),
    )
    decisions = Table(
        "region_member_decisions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("region_id", String, nullable=False),
        Column("member_type", String, nullable=False),
        Column("member", String, nullable=False),
        Column("decision", String, nullable=False),
        Column("decider_user", String, nullable=False),
        Index(
            "ix_region_member_decisions_member", "region_id", "member_type", "member", "event_id"
        ),
    )
    return RegionTables(regions, definitions, snapshots, members, reviews, decisions)


def region_handlers(t: RegionTables, blobs: BlobStore | None) -> dict[str, Handler]:
    return {
        "region.defined": _defined(t),
        "region.snapshot_taken": _snapshot(t, blobs),
        "region.reviewed": _reviewed(t),
        "region.member_decided": _member_decided(t),
    }


def _defined(t: RegionTables) -> Handler:
    def defined(conn: Connection, event: Event) -> None:
        p = RegionDefined.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.regions)
            .values(
                region_id=p.region_id,
                kind=p.kind.value,
                facet_question=None if p.facet is None else p.facet.question_id,
                facet_slot=None if p.facet is None else p.facet.slot,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["region_id"])
        )
        conn.execute(
            sqlite_insert(t.definitions)
            .values(
                event_id=event.id,
                region_id=p.region_id,
                name=p.name,
                definition=p.definition,
                rules=canonical_json(canonical_rules(p.rules)).decode(),
                supersedes=p.supersedes,
                author=p.author,
                author_user=event.actor.user,
                writer_session=event.actor.session,
                input_blob=event.input_blob,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return defined


def _snapshot(t: RegionTables, blobs: BlobStore | None) -> Handler:
    def taken(conn: Connection, event: Event) -> None:
        if blobs is None:
            raise RuntimeError("the regions projection needs the project's blob store")
        p = Snapshot.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.snapshots)
            .values(
                event_id=event.id,
                region_id=p.region_id,
                version=p.version,
                definition_event=p.definition_event,
                rules_hash=p.rules_hash,
                decisions=canonical_json(list(p.decisions)).decode(),
                members_blob=p.members_blob,
                members_hash=p.members_hash,
                basis_blob=p.basis_blob,
                counts=canonical_json({k.value: v for k, v in sorted(p.counts.items())}).decode(),
                as_of=p.as_of,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        if not inserted.rowcount:
            return
        lines = gzip.decompress(blobs.get(p.members_blob)).decode().splitlines()
        basis = blobs.get_json(p.basis_blob)
        assert isinstance(basis, dict)
        conn.execute(delete(t.members).where(t.members.c.region_id == p.region_id))
        rows = []
        for line in lines:
            member_type, member = line.split("\t", 1)
            rows.append(
                {
                    "region_id": p.region_id,
                    "member_type": member_type,
                    "member": member,
                    "version": p.version,
                    "basis": json.dumps(basis.get(line), sort_keys=True, separators=(",", ":")),
                }
            )
        for start in range(0, len(rows), 5000):
            conn.execute(sqlite_insert(t.members), rows[start : start + 5000])

    return taken


def _reviewed(t: RegionTables) -> Handler:
    def reviewed(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = RegionReviewed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.reviews)
            .values(
                event_id=event.id,
                version=p.version,
                state=p.state,
                note=p.note,
                reviewer_user=event.actor.user,
                self_reviewed=int(p.self_reviewed),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return reviewed


def _member_decided(t: RegionTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = RegionMemberDecided.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.decisions)
            .values(
                event_id=event.id,
                region_id=p.region_id,
                member_type=p.member_type.value,
                member=p.member,
                decision=p.decision,
                decider_user=event.actor.user,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return decided
