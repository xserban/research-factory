"""Projection of taxonomies, change proposals, mining requests and work layer moves (IDEA-50).

`taxonomies` holds the first registration of each `(name, version)`: a later event naming the same
pair changes nothing (first write wins). Only a human actor's `taxonomy.registered` is folded.
`taxonomy_proposals` holds an agent's `taxonomy.change_proposed` per `proposal_id` (first write
wins; only an agent actor's event is folded); list fields are canonical JSON. `mining_requests`
holds one row per `mining.requested` (human actor only) and `mining_request_works` its work ids.
`work_layer_moves` keeps every human `work.layer_set`, in event order: the latest move of a work
(highest `ts`, then `event_id`) is its effective layer, which readers compute from this table.

An event that fails the actor guard or its payload validation changes nothing. Handlers are total:
an event naming an unknown taxonomy, scheme or work is stored; the services refuse those at the
boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue, ValidationError
from sqlalchemy import Column, Index, Integer, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.taxonomies import (
    MiningRequested,
    TaxonomyChangeProposed,
    TaxonomyRegistered,
    WorkLayerSet,
)


@dataclass(frozen=True)
class TaxonomyTables:
    taxonomies: Table
    proposals: Table
    mining_requests: Table
    mining_request_works: Table
    layer_moves: Table


def taxonomy_tables(metadata: MetaData) -> TaxonomyTables:
    taxonomies = Table(
        "taxonomies",
        metadata,
        Column("name", String, primary_key=True),
        Column("version", Integer, primary_key=True),
        Column("digest", String, nullable=False),
        Column("spec_blob", String, nullable=False),
        Column("accepts", String, nullable=False),
        Column("rejects", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    proposals = Table(
        "taxonomy_proposals",
        metadata,
        Column("proposal_id", String, primary_key=True),
        Column("taxonomy", String, nullable=False),
        Column("base_version", Integer, nullable=False),
        Column("kind", String, nullable=False),
        Column("targets", String, nullable=False),
        Column("draft_blob", String),
        Column("works", String, nullable=False),
        Column("rows", String, nullable=False),
        Column("cluster_id", String),
        Column("rationale", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_taxonomy_proposals_taxonomy", "taxonomy", "base_version"),
    )
    requests = Table(
        "mining_requests",
        metadata,
        Column("request_id", String, primary_key=True),
        Column("target", String, nullable=False),
        Column("layer", String),
        Column("layer_scheme", Integer),
        Column("miners", String, nullable=False),
        Column("reason", String),
        Column("event_id", String, nullable=False),
    )
    request_works = Table(
        "mining_request_works",
        metadata,
        Column("request_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Index("ix_mining_request_works_work", "work_id"),
    )
    moves = Table(
        "work_layer_moves",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("ts", String, nullable=False),
        Column("work_id", String, nullable=False),
        Column("scheme_version", Integer, nullable=False),
        Column("layer", String, nullable=False),
        Column("reason", String, nullable=False),
        Index("ix_work_layer_moves_work", "work_id", "ts", "event_id"),
    )
    return TaxonomyTables(taxonomies, proposals, requests, request_works, moves)


def taxonomy_handlers(t: TaxonomyTables) -> dict[str, Handler]:
    return {
        "taxonomy.registered": _registered(t),
        "taxonomy.change_proposed": _proposed(t),
        "mining.requested": _requested(t),
        "work.layer_set": _layer_set(t),
    }


def _json(value: JsonValue) -> str:
    return canonical_json(value).decode()


def _registered(t: TaxonomyTables) -> Handler:
    def registered(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        try:
            p = TaxonomyRegistered.model_validate(event.payload)
        except ValidationError:
            return
        conn.execute(
            sqlite_insert(t.taxonomies)
            .values(
                name=p.name,
                version=p.version,
                digest=p.digest,
                spec_blob=p.spec_blob,
                accepts=_json(list(p.accepts)),
                rejects=_json([r.model_dump(mode="json") for r in p.rejects]),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["name", "version"])
        )

    return registered


def _proposed(t: TaxonomyTables) -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        if event.actor.kind != "agent":
            return
        try:
            p = TaxonomyChangeProposed.model_validate(event.payload)
        except ValidationError:
            return
        conn.execute(
            sqlite_insert(t.proposals)
            .values(
                proposal_id=p.proposal_id,
                taxonomy=p.taxonomy,
                base_version=p.base_version,
                kind=p.kind,
                targets=_json(list(p.targets)),
                draft_blob=p.draft_blob,
                works=_json(list(p.works)),
                rows=_json(list(p.rows)),
                cluster_id=p.cluster_id,
                rationale=p.rationale,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["proposal_id"])
        )

    return proposed


def _requested(t: TaxonomyTables) -> Handler:
    def requested(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        try:
            p = MiningRequested.model_validate(event.payload)
        except ValidationError:
            return
        inserted = conn.execute(
            sqlite_insert(t.mining_requests)
            .values(
                request_id=p.request_id,
                target=p.target,
                layer=p.layer,
                layer_scheme=p.layer_scheme,
                miners=_json(list(p.miners)),
                reason=p.reason,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["request_id"])
        )
        if inserted.rowcount == 0:
            return
        for work_id in dict.fromkeys(p.works):
            conn.execute(
                sqlite_insert(t.mining_request_works)
                .values(request_id=p.request_id, work_id=work_id)
                .on_conflict_do_nothing(index_elements=["request_id", "work_id"])
            )

    return requested


def _layer_set(t: TaxonomyTables) -> Handler:
    def layer_set(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        try:
            p = WorkLayerSet.model_validate(event.payload)
        except ValidationError:
            return
        conn.execute(
            sqlite_insert(t.layer_moves)
            .values(
                event_id=event.id,
                ts=event.ts.isoformat(),
                work_id=p.work_id,
                scheme_version=p.scheme_version,
                layer=p.layer,
                reason=p.reason,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return layer_set
