"""Projection of merges and the pairs a human has ruled apart.

Handlers are total: a revert of an unknown or already reverted merge changes nothing. A manual
revert blocks every pair among the merge's members (stored with `a < b`), so the cascade does
not rebuild any part of a merge a person has undone.
"""

import json
from dataclasses import dataclass
from itertools import combinations

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.dedup import DedupMerged, DedupReverted, MergeStatus


@dataclass(frozen=True)
class DedupTables:
    merges: Table
    blocked: Table
    members: Table


def dedup_tables(metadata: MetaData) -> DedupTables:
    merges = Table(
        "merges",
        metadata,
        Column("merge_id", String, primary_key=True),
        Column("primary", String, nullable=False),
        Column("absorbed", String, nullable=False),
        Column("rule", String, nullable=False),
        Column("records", Integer, nullable=False),
        Column("status", String, nullable=False),
        Column("reverted_reason", String),
        Column("manual", Boolean),
    )
    blocked = Table(
        "blocked_pairs",
        metadata,
        Column("a", String, primary_key=True),
        Column("b", String, primary_key=True),
    )
    # Every work of a merge (primary and absorbed), so incremental deduplication finds the
    # merges that touch a candidate by work id. Status lives on `merges`.
    members = Table(
        "merge_members",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("merge_id", String, primary_key=True),
    )
    return DedupTables(merges, blocked, members)


def dedup_handlers(t: DedupTables) -> dict[str, Handler]:
    return {"dedup.merged": _merged(t), "dedup.reverted": _reverted(t)}


def _merged(t: DedupTables) -> Handler:
    def merged(conn: Connection, event: Event) -> None:
        payload = DedupMerged.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.merges)
            .values(
                merge_id=payload.merge_id,
                primary=payload.primary,
                absorbed=canonical_json(list(payload.absorbed)).decode(),
                rule=payload.rule,
                records=payload.records,
                status=MergeStatus.ACTIVE.value,
                reverted_reason=None,
                manual=None,
            )
            .on_conflict_do_nothing(index_elements=["merge_id"])
        )
        for member in (payload.primary, *payload.absorbed):
            conn.execute(
                sqlite_insert(t.members)
                .values(work_id=member, merge_id=payload.merge_id)
                .on_conflict_do_nothing(index_elements=["work_id", "merge_id"])
            )

    return merged


def _reverted(t: DedupTables) -> Handler:
    def reverted(conn: Connection, event: Event) -> None:
        payload = DedupReverted.model_validate(event.payload)
        row = conn.execute(
            select(t.merges.c.primary, t.merges.c.absorbed, t.merges.c.status).where(
                t.merges.c.merge_id == payload.merge_id
            )
        ).one_or_none()
        # Only an active merge can be reverted: an unknown or repeated reversal changes nothing.
        if row is None or row.status != MergeStatus.ACTIVE.value:
            return
        conn.execute(
            update(t.merges)
            .where(t.merges.c.merge_id == payload.merge_id)
            .values(
                status=MergeStatus.REVERTED.value,
                reverted_reason=payload.reason,
                manual=payload.manual,
            )
        )
        if not payload.manual:
            return
        members = sorted({str(row.primary), *(str(m) for m in json.loads(str(row.absorbed)))})
        for first, second in combinations(members, 2):
            conn.execute(
                sqlite_insert(t.blocked)
                .values(a=first, b=second)
                .on_conflict_do_nothing(index_elements=["a", "b"])
            )

    return reverted
