"""Review requests: `reviews`, one row per request that folded (slice 5 ruling 14).

Invariants:
- Handlers are total: a malformed payload, an unreadable or invalid proposal, or an event that
  fails a guard changes nothing, on rebuild too. A forged request leaves no row.
- The state of a review is computed on read; the row holds only what the events said, and the
  event that consumed it.
- The first decision counts. A requester never approves or rejects their own request, and only
  the requester withdraws one (R-51, plan ruling 4). Compared by user, never by session.
- An approval needs the protocol the request was filed on to be current still (plan ruling 2).
- A protocol event that names a review counts only if it consumes that review: approved, of its
  kind, not consumed, not stale, and carrying the approved proposal. Otherwise, and for a protocol
  event by someone who may not change the protocol at that point of the log, it changes nothing.
  `protocol_guards` wraps the handlers of the events that change the protocol, so the protocol's
  own fold stays as it was.
- The fold cannot know `Settings.user` or the lab: on an unhosted project with no grant in the log
  every person passes the role guards, as `index/members.py` says of the first grant. So a log
  written before slice 5 replays unchanged.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, JsonValue, ValidationError
from sqlalchemy import Column, MetaData, String, Table, insert, select, text, update
from sqlalchemy.engine import Connection, Row

from factory.clock import format_ts
from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Actor, Event
from factory.index.members import MemberTables, holds_here, is_hosted_here
from factory.index.projection import Handler
from factory.model.members import ProjectRole
from factory.model.protocol import (
    ChangeKind,
    DeviationRecorded,
    ProtocolAmended,
    ProtocolRecorded,
    ProtocolStatus,
)
from factory.model.reviews import (
    PROPOSAL_MODELS,
    DeviationProposal,
    Proposal,
    ProtocolAmendProposal,
    ProtocolRecordProposal,
    ReviewDecided,
    ReviewKind,
    ReviewRequested,
)

_CONTRIBUTORS = frozenset({ProjectRole.OWNER, ProjectRole.MAINTAINER, ProjectRole.CONTRIBUTOR})
_DECIDERS = frozenset({ProjectRole.OWNER, ProjectRole.MAINTAINER})


@dataclass(frozen=True)
class ReviewTables:
    reviews: Table


def review_tables(metadata: MetaData) -> ReviewTables:
    return ReviewTables(
        reviews=Table(
            "reviews",
            metadata,
            Column("review_request_id", String, primary_key=True),
            Column("kind", String, nullable=False),
            Column("target", String, nullable=False),
            Column("target_version", String),
            Column("proposal_blob", String, nullable=False),
            Column("required_role", String, nullable=False),
            Column("reason", String, nullable=False),
            Column("requester", String, nullable=False),
            Column("requested_event", String, nullable=False),
            Column("requested_at", String, nullable=False),
            Column("decision", String),
            Column("rationale", String),
            Column("channel", String),
            Column("decided_by", String),
            Column("decided_event", String),
            Column("consumed_event", String),
        )
    )


REVIEW_TABLES = review_tables(MetaData())
"""A handle for the services' reads, as the projection's tables are built per index."""

ReviewRow = Row[Any]


def review_row(conn: Connection, tables: ReviewTables, review_request_id: str) -> ReviewRow | None:
    reviews = tables.reviews
    return conn.execute(
        select(reviews).where(reviews.c.review_request_id == review_request_id)
    ).one_or_none()


def review_rows(conn: Connection, tables: ReviewTables) -> list[ReviewRow]:
    """Every request, in filing order."""
    reviews = tables.reviews
    return list(conn.execute(select(reviews).order_by(reviews.c.requested_event)).all())


def current_protocol_row(conn: Connection) -> tuple[str, str] | None:
    """The id and status of the protocol in force at this point of the log."""
    row = conn.execute(
        text("SELECT protocol_id, status FROM protocols ORDER BY event_id DESC LIMIT 1")
    ).first()
    return None if row is None else (str(row[0]), str(row[1]))


def current_version(conn: Connection) -> str | None:
    current = current_protocol_row(conn)
    return None if current is None else current[0]


def valid_proposal(kind: ReviewKind, data: JsonValue) -> Proposal | None:
    """`data` as `kind`'s proposal, or None when it is not one."""
    try:
        return PROPOSAL_MODELS[kind].model_validate(data)
    except ValidationError:
        return None


def _proposal(blobs: BlobStore | None, kind: ReviewKind, ref: str) -> Proposal | None:
    if blobs is None:
        return None
    try:
        return valid_proposal(kind, blobs.get_json(ref))
    except (FactoryError, ValueError):
        return None


def _in_own_name(actor: Actor) -> bool:
    return actor.kind == "human" and actor.id == actor.user


def _requested_validly(conn: Connection, event: Event, payload: ReviewRequested) -> bool:
    """A request names the protocol in force, and an amendment asks to change a ready one."""
    current = current_protocol_row(conn)
    version = None if current is None else current[0]
    if payload.target_version != version:
        return False
    if payload.kind is ReviewKind.PROTOCOL_RECORD:
        return payload.target == event.project
    if current is None or payload.target != version:
        return False
    return payload.kind is not ReviewKind.PROTOCOL_AMEND or current[1] == ProtocolStatus.READY.value


def _requested(t: ReviewTables, members: MemberTables, blobs: BlobStore | None) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = ReviewRequested.model_validate(event.payload)
        except ValidationError:
            return
        actor = event.actor
        if actor.kind == "system" or (actor.kind == "human" and actor.id != actor.user):
            return
        if not holds_here(conn, members, actor.user, _CONTRIBUTORS):
            return
        if review_row(conn, t, payload.review_request_id) is not None:
            return
        if not _requested_validly(conn, event, payload):
            return
        if _proposal(blobs, payload.kind, payload.proposal_blob) is None:
            return
        conn.execute(
            insert(t.reviews).values(
                review_request_id=payload.review_request_id,
                kind=payload.kind.value,
                target=payload.target,
                target_version=payload.target_version,
                proposal_blob=payload.proposal_blob,
                required_role=payload.required_role.value,
                reason=payload.reason,
                requester=actor.user,
                requested_event=event.id,
                requested_at=format_ts(event.ts),
            )
        )

    return fold


def _may_decide(
    conn: Connection, members: MemberTables, event: Event, row: ReviewRow, decision: str
) -> bool:
    user = event.actor.user
    if decision == "withdraw":
        return bool(row.requester == user)
    if row.requester == user:
        return False
    required = ProjectRole(str(row.required_role))
    if not holds_here(conn, members, user, frozenset({required, ProjectRole.OWNER})):
        return False
    return decision != "approve" or row.target_version == current_version(conn)


def _decided(t: ReviewTables, members: MemberTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = ReviewDecided.model_validate(event.payload)
        except ValidationError:
            return
        if not _in_own_name(event.actor):
            return
        row = review_row(conn, t, payload.review_request_id)
        if row is None or row.decision is not None:
            return
        if not _may_decide(conn, members, event, row, payload.decision):
            return
        conn.execute(
            update(t.reviews)
            .where(t.reviews.c.review_request_id == payload.review_request_id)
            .values(
                decision=payload.decision,
                rationale=payload.rationale,
                channel=payload.channel.value,
                decided_by=event.actor.user,
                decided_event=event.id,
            )
        )

    return fold


def review_handlers(
    tables: ReviewTables, members: MemberTables, blobs: BlobStore | None
) -> dict[str, Handler]:
    return {
        "review.requested": _requested(tables, members, blobs),
        "review.decided": _decided(tables, members),
    }


# --- Consumption ---------------------------------------------------------------------------------


def _amend_matches(payload: BaseModel, proposal: Proposal) -> bool:
    if not isinstance(payload, ProtocolAmended) or not isinstance(proposal, ProtocolAmendProposal):
        return False
    effects = {c.cid: c.effect for c in payload.changes if c.change is ChangeKind.CHANGED}
    return (
        payload.spec == proposal.spec
        and payload.reason == proposal.reason.strip()
        and payload.semantic == proposal.semantic
        and effects == proposal.effects
    )


def _record_matches(payload: BaseModel, proposal: Proposal) -> bool:
    if not isinstance(payload, ProtocolRecorded) or not isinstance(
        proposal, ProtocolRecordProposal
    ):
        return False
    status = ProtocolStatus.READY if proposal.ready else ProtocolStatus.DRAFT
    return payload.spec == proposal.spec and payload.status is status


def _deviation_matches(payload: BaseModel, proposal: Proposal) -> bool:
    if not isinstance(payload, DeviationRecorded) or not isinstance(proposal, DeviationProposal):
        return False
    return (
        payload.description == proposal.description
        and payload.reason == proposal.reason
        and payload.affects == proposal.affects
    )


_MATCHERS = {
    ReviewKind.PROTOCOL_AMEND: _amend_matches,
    ReviewKind.PROTOCOL_RECORD: _record_matches,
    ReviewKind.DEVIATION: _deviation_matches,
}


def _consumable(
    conn: Connection,
    t: ReviewTables,
    blobs: BlobStore | None,
    kind: ReviewKind,
    review_request_id: str,
    payload: BaseModel,
) -> bool:
    row = review_row(conn, t, review_request_id)
    if row is None or row.kind != kind.value or row.decision != "approve":
        return False
    if row.consumed_event is not None or row.target_version != current_version(conn):
        return False
    proposal = _proposal(blobs, kind, str(row.proposal_blob))
    return proposal is not None and _MATCHERS[kind](payload, proposal)


def _may_change_protocol(conn: Connection, members: MemberTables, actor: Actor) -> bool:
    """A person or agent holding the role here. On a hosted project an agent proposes only."""
    if actor.kind != "human" and is_hosted_here(conn):
        return False
    return holds_here(conn, members, actor.user, _DECIDERS)


def _guarded(
    t: ReviewTables,
    members: MemberTables,
    blobs: BlobStore | None,
    kind: ReviewKind,
    model: type[ProtocolAmended | ProtocolRecorded | DeviationRecorded],
    handler: Handler,
) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = model.model_validate(event.payload)
        except ValidationError:
            return
        if not _may_change_protocol(conn, members, event.actor):
            return
        request = payload.review_request_id
        if request is None:
            handler(conn, event)
            return
        if not _consumable(conn, t, blobs, kind, request, payload):
            return
        handler(conn, event)
        conn.execute(
            update(t.reviews)
            .where(t.reviews.c.review_request_id == request)
            .values(consumed_event=event.id)
        )

    return fold


def protocol_guards(
    t: ReviewTables,
    members: MemberTables,
    blobs: BlobStore | None,
    handlers: Mapping[str, Handler],
) -> dict[str, Handler]:
    """The handlers of the three events that change the protocol, behind the guards above. Applied
    last, so a refused event reaches nothing that is chained after the protocol's own fold."""
    return {
        "protocol.recorded": _guarded(
            t,
            members,
            blobs,
            ReviewKind.PROTOCOL_RECORD,
            ProtocolRecorded,
            handlers["protocol.recorded"],
        ),
        "protocol.amended": _guarded(
            t,
            members,
            blobs,
            ReviewKind.PROTOCOL_AMEND,
            ProtocolAmended,
            handlers["protocol.amended"],
        ),
        "protocol.deviation_recorded": _guarded(
            t,
            members,
            blobs,
            ReviewKind.DEVIATION,
            DeviationRecorded,
            handlers["protocol.deviation_recorded"],
        ),
    }
