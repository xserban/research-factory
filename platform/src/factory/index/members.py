"""Project grants: `members` (live, spec) and `member_events` (each grant and revoke that counted).

Invariants:
- Handlers are total: a malformed payload, or an event that fails a guard, changes nothing, on
  rebuild too. `member_events` holds only events that folded, so a forged grant leaves no history.
- Only a person changes grants. With grants in force, that person holds `owner` at that point of
  the log.
- The first grant names an `owner`: once a grant exists only grants count (plan ruling 2), so any
  other first grant would leave the project with no one able to grant.
- The fold cannot know `Settings.user` or the lab registry, since a rebuild reads this log alone.
  Those two checks (the implicit owner, an active grantee) are the service's.
- The last `owner` grant is never revoked (plan ruling 3).
"""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Boolean, Column, MetaData, String, Table, delete, func, insert, select
from sqlalchemy.engine import Connection

from factory.events.envelope import Actor, Event
from factory.index.projection import Handler
from factory.model.members import MemberGranted, MemberRevoked, ProjectRole


@dataclass(frozen=True)
class MemberTables:
    members: Table
    events: Table


def member_tables(metadata: MetaData) -> MemberTables:
    return MemberTables(
        members=Table(
            "members",
            metadata,
            Column("user", String, primary_key=True),
            Column("role", String, primary_key=True),
            Column("event_id", String, nullable=False),
        ),
        events=Table(
            "member_events",
            metadata,
            Column("event_id", String, primary_key=True),
            Column("user", String, nullable=False),
            Column("role", String, nullable=False),
            Column("granted", Boolean, nullable=False),
        ),
    )


MEMBER_TABLES = member_tables(MetaData())
"""A handle for the services' reads, as the projection's tables are built per index."""


def any_grant(conn: Connection, tables: MemberTables) -> bool:
    """Whether a grant ever counted. Once one has, implicit ownership is over for good."""
    return conn.execute(select(tables.events.c.event_id).limit(1)).first() is not None


def live_roles(conn: Connection, tables: MemberTables, user: str) -> frozenset[ProjectRole]:
    members = tables.members
    rows = conn.execute(select(members.c.role).where(members.c.user == user))
    return frozenset(ProjectRole(str(role)) for (role,) in rows)


def roles_at(
    conn: Connection, tables: MemberTables, user: str, event_id: str
) -> frozenset[ProjectRole]:
    """The roles `user` held just after `event_id`: a revoked grant stops counting from its revoke
    event, and a later grant counts from its own."""
    events = tables.events
    rows = conn.execute(
        select(events.c.role, events.c.granted)
        .where(events.c.user == user, events.c.event_id <= event_id)
        .order_by(events.c.event_id)
    )
    held: set[ProjectRole] = set()
    for role, granted in rows:
        if granted:
            held.add(ProjectRole(str(role)))
        else:
            held.discard(ProjectRole(str(role)))
    return frozenset(held)


def any_grant_by(conn: Connection, tables: MemberTables, event_id: str) -> bool:
    events = tables.events
    query = select(events.c.event_id).where(events.c.event_id <= event_id).limit(1)
    return conn.execute(query).first() is not None


def all_members(conn: Connection, tables: MemberTables) -> dict[str, frozenset[ProjectRole]]:
    members = tables.members
    held: dict[str, set[ProjectRole]] = {}
    for user, role in conn.execute(select(members.c.user, members.c.role)):
        held.setdefault(str(user), set()).add(ProjectRole(str(role)))
    return {user: frozenset(roles) for user, roles in sorted(held.items())}


def is_last_owner(conn: Connection, tables: MemberTables, user: str) -> bool:
    members = tables.members
    others = conn.execute(
        select(func.count())
        .select_from(members)
        .where(members.c.role == ProjectRole.OWNER.value, members.c.user != user)
    ).scalar_one()
    return others == 0


def _governs(conn: Connection, tables: MemberTables, actor: Actor) -> bool:
    return (
        actor.kind == "human"
        and actor.id == actor.user
        and ProjectRole.OWNER in live_roles(conn, tables, actor.user)
    )


def _granted(tables: MemberTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = MemberGranted.model_validate(event.payload)
        except ValidationError:
            return
        if any_grant(conn, tables):
            if not _governs(conn, tables, event.actor):
                return
        elif event.actor.kind != "human" or payload.role is not ProjectRole.OWNER:
            return
        if payload.role in live_roles(conn, tables, payload.user):
            return
        conn.execute(
            insert(tables.members).values(
                user=payload.user, role=payload.role.value, event_id=event.id
            )
        )
        conn.execute(
            insert(tables.events).values(
                event_id=event.id, user=payload.user, role=payload.role.value, granted=True
            )
        )

    return fold


def _revoked(tables: MemberTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = MemberRevoked.model_validate(event.payload)
        except ValidationError:
            return
        if not _governs(conn, tables, event.actor):
            return
        if payload.role not in live_roles(conn, tables, payload.user):
            return
        if payload.role is ProjectRole.OWNER and is_last_owner(conn, tables, payload.user):
            return
        members = tables.members
        conn.execute(
            delete(members).where(
                members.c.user == payload.user, members.c.role == payload.role.value
            )
        )
        conn.execute(
            insert(tables.events).values(
                event_id=event.id, user=payload.user, role=payload.role.value, granted=False
            )
        )

    return fold


def member_handlers(tables: MemberTables) -> dict[str, Handler]:
    return {"member.granted": _granted(tables), "member.revoked": _revoked(tables)}
