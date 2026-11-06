"""Projection of regions (slice 3d, plan Regions-A).

`region_definitions` keeps every `region.defined` (the live definition of a region is its row with
the greatest `event_id`); `regions` has one row per region id. `region_snapshots` keeps every
snapshot event; the latest of a region is the row with the greatest `event_id`. `region_members`
holds the members of the latest snapshot of each region only (older sets are read from their
blobs on demand) and is replaced as a whole when a newer snapshot is folded. `region_reviews` and
`region_member_decisions` keep every human act; the latest per version, or per member, binds.
`region_member_proposals` keeps every proposal (open or not is read against the later decisions)
and `region_links` every declared link (human only, like a review).

Only a review or a member decision whose actor is a human is folded (defence in depth: no service
writes one for another actor, R-51). Handlers are total in the sense that a repeated event id
changes nothing. The projector reads the member and basis blobs from `blobs/`; folding a snapshot
without a blob store raises.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.regions import (
    RegionAdopted,
    RegionDefined,
    RegionLinked,
    RegionMemberDecided,
    RegionMemberProposed,
    RegionReviewed,
)
from factory.model.regions import RegionSnapshotTaken as Snapshot
from factory.regions.rules import MemberType
from factory.regions.version import canonical_rules, member_lines, members_hash


@dataclass(frozen=True)
class RegionTables:
    regions: Table
    definitions: Table
    snapshots: Table
    members: Table
    reviews: Table
    decisions: Table
    proposals: Table
    links: Table
    adoptions: Table


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
        Column("proposal_id", String),
        Index(
            "ix_region_member_decisions_member", "region_id", "member_type", "member", "event_id"
        ),
    )
    proposals = Table(
        "region_member_proposals",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("proposal_id", String, nullable=False),
        Column("region_id", String, nullable=False),
        Column("member_type", String, nullable=False),
        Column("member", String, nullable=False),
        Column("basis", String, nullable=False),
        Column("note", String),
        Column("proposer_kind", String, nullable=False),
        Column("proposer_session", String, nullable=False),
        Index("ix_region_member_proposals_region", "region_id", "event_id"),
        Index("ix_region_member_proposals_id", "proposal_id"),
    )
    links = Table(
        "region_links",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("link_type", String, nullable=False),
        Column("source", String, nullable=False),
        Column("target", String, nullable=False),
        Column("note", String),
        Column("linker_user", String, nullable=False),
        Index("ix_region_links_source", "source"),
        Index("ix_region_links_target", "target"),
    )
    adoptions = Table(
        "region_adoptions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("source_project", String, nullable=False),
        Column("source_region", String, nullable=False),
        Column("version", String, nullable=False),
        Column("members_blob", String, nullable=False),
        Column("members_hash", String, nullable=False),
        Column("counts", String, nullable=False),
        Column("adopter_user", String, nullable=False),
        Index("ix_region_adoptions_source", "source_project", "source_region", "event_id"),
    )
    return RegionTables(
        regions, definitions, snapshots, members, reviews, decisions, proposals, links, adoptions
    )


def region_handlers(t: RegionTables, blobs: BlobStore | None) -> dict[str, Handler]:
    return {
        "region.defined": _defined(t),
        "region.snapshot_taken": _snapshot(t, blobs),
        "region.reviewed": _reviewed(t),
        "region.member_decided": _member_decided(t),
        "region.member_proposed": _member_proposed(t),
        "region.linked": _linked(t),
        "region.adopted": _adopted(t, blobs),
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


def _member_rows(blobs: BlobStore, p: Snapshot) -> list[tuple[str, str, str]] | None:
    """The `(member_type, member, basis)` rows of a snapshot's blobs, or None when a blob is
    missing or corrupt, a line has no type, a member repeats or the basis is not an object (the
    event is then unfolded: a logged event can never be removed, so the fold must not raise)."""
    try:
        lines = member_lines(blobs.get(p.members_blob))
        basis = blobs.get_json(p.basis_blob)
    except (FactoryError, OSError, EOFError, ValueError, zlib.error):
        return None
    if not isinstance(basis, dict) or len(set(lines)) != len(lines):
        return None
    rows: list[tuple[str, str, str]] = []
    for line in lines:
        member_type, tab, member = line.partition("\t")
        if not tab:
            return None
        rows.append(
            (
                member_type,
                member,
                json.dumps(basis.get(line), sort_keys=True, separators=(",", ":")),
            )
        )
    return rows


def _snapshot(t: RegionTables, blobs: BlobStore | None) -> Handler:
    def taken(conn: Connection, event: Event) -> None:
        if blobs is None:
            raise RuntimeError("the regions projection needs the project's blob store")
        p = Snapshot.model_validate(event.payload)
        members = _member_rows(blobs, p)
        if members is None:
            return  # a snapshot whose blobs cannot be read stays in the log, unfolded
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
        conn.execute(delete(t.members).where(t.members.c.region_id == p.region_id))
        rows = [
            {
                "region_id": p.region_id,
                "member_type": mt,
                "member": m,
                "version": p.version,
                "basis": b,
            }
            for mt, m, b in members
        ]
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
                proposal_id=p.proposal_id,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return decided


def _member_proposed(t: RegionTables) -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = RegionMemberProposed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.proposals)
            .values(
                event_id=event.id,
                proposal_id=p.proposal_id,
                region_id=p.region_id,
                member_type=p.member_type.value,
                member=p.member,
                basis=canonical_json(p.basis.model_dump(mode="json")).decode(),
                note=p.note,
                proposer_kind=event.actor.kind,
                proposer_session=event.actor.session,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return proposed


def _linked(t: RegionTables) -> Handler:
    def linked(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = RegionLinked.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.links)
            .values(
                event_id=event.id,
                link_type=p.link_type,
                source=p.source,
                target=p.target,
                note=p.note,
                linker_user=event.actor.user,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return linked


def _adopted(t: RegionTables, blobs: BlobStore | None) -> Handler:
    """Fold a human adoption whose copied member list is present and matches its hash; any other
    (an agent's, a missing or altered blob) stays in the log, unfolded."""

    def adopted(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        if blobs is None:
            raise RuntimeError("the regions projection needs the project's blob store")
        p = RegionAdopted.model_validate(event.payload)
        try:
            lines = member_lines(blobs.get(p.members_blob))
        except (FactoryError, OSError, EOFError, ValueError, zlib.error):
            return
        kinds = {m.value for m in MemberType}
        if any(line.partition("\t")[0] not in kinds or "\t" not in line for line in lines):
            return
        text_bytes = "".join(f"{line}\n" for line in lines).encode()
        if members_hash(text_bytes) != p.members_hash:
            return
        conn.execute(
            sqlite_insert(t.adoptions)
            .values(
                event_id=event.id,
                source_project=p.source_project,
                source_region=p.source_region,
                version=p.version,
                members_blob=p.members_blob,
                members_hash=p.members_hash,
                counts=canonical_json({k.value: v for k, v in sorted(p.counts.items())}).decode(),
                adopter_user=event.actor.user,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return adopted
