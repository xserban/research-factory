"""The lab registry's catalog and projection: `<root>/lab/.index/lab.sqlite`.

The lab index is versioned on its own (`LAB_PROJECTION_VERSION`), apart from the project index.

Invariants:
- Every handler is total: a malformed payload, or an event that fails a guard, changes nothing, on
  rebuild too. A hand-written event stays in the log and counts for nothing.
- The first user is the person who registers themselves as `admin`; from then on only a person who
  is an active admin at that point of the log changes the registry.
- A user id is never reused, and an `(issuer, subject)` pair names one user for good.
- A change that would leave the lab with no active admin does not fold, since nothing could then
  repair the registry.
"""

from collections.abc import Mapping, Sequence
from typing import TypeVar

from pydantic import ValidationError
from sqlalchemy import (
    Boolean,
    Column,
    MetaData,
    String,
    Table,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.catalog import EventCatalog, EventType
from factory.events.envelope import Actor, Event
from factory.index.projection import Handler, Projection, core_tables
from factory.model.base import StrictModel
from factory.model.lab import (
    IdentityLinked,
    LabRole,
    LabRoleSet,
    UserDeactivated,
    UserReactivated,
    UserRegistered,
)

# Bump on any change to the tables or handlers below; the lab index is then rebuilt.
LAB_PROJECTION_VERSION = "1"

_M = TypeVar("_M", bound=StrictModel)


def lab_catalog() -> EventCatalog:
    """The event types of the lab log; they are not project events."""
    catalog = EventCatalog()
    catalog.register(EventType("user.registered", UserRegistered, 1))
    catalog.register(EventType("user.identity_linked", IdentityLinked, 1))
    catalog.register(EventType("user.deactivated", UserDeactivated, 1))
    catalog.register(EventType("user.reactivated", UserReactivated, 1))
    catalog.register(EventType("user.lab_role_set", LabRoleSet, 1))
    return catalog


def lab_tables(metadata: MetaData) -> dict[str, Table]:
    return {
        "users": Table(
            "users",
            metadata,
            Column("user", String, primary_key=True),
            Column("display_name", String, nullable=False),
            Column("email_hash", String),
            Column("active", Boolean, nullable=False),
            Column("registered_at", String, nullable=False),
        ),
        "identities": Table(
            "identities",
            metadata,
            Column("issuer", String, primary_key=True),
            Column("subject", String, primary_key=True),
            Column("user", String, nullable=False),
        ),
        "lab_roles": Table(
            "lab_roles",
            metadata,
            Column("user", String, primary_key=True),
            Column("role", String, primary_key=True),
        ),
    }


def _parsed(model: type[_M], event: Event) -> _M | None:
    try:
        return model.model_validate(event.payload)
    except ValidationError:
        return None


def user_exists(conn: Connection, tables: Mapping[str, Table], user: str) -> bool:
    users = tables["users"]
    return conn.execute(select(users.c.user).where(users.c.user == user)).first() is not None


def is_active(conn: Connection, tables: Mapping[str, Table], user: str) -> bool:
    users = tables["users"]
    return conn.execute(select(users.c.active).where(users.c.user == user)).scalar() is True


def roles_of_user(conn: Connection, tables: Mapping[str, Table], user: str) -> tuple[LabRole, ...]:
    roles = tables["lab_roles"]
    rows = conn.execute(select(roles.c.role).where(roles.c.user == user).order_by(roles.c.role))
    return tuple(LabRole(str(role)) for (role,) in rows)


def is_active_admin(conn: Connection, tables: Mapping[str, Table], user: str) -> bool:
    return is_active(conn, tables, user) and LabRole.ADMIN in roles_of_user(conn, tables, user)


def actor_is_admin(conn: Connection, tables: Mapping[str, Table], actor: Actor) -> bool:
    """Only a person in their own name, an active admin now, changes the registry."""
    return (
        actor.kind == "human"
        and actor.id == actor.user
        and is_active_admin(conn, tables, actor.user)
    )


def registry_is_empty(conn: Connection, tables: Mapping[str, Table]) -> bool:
    return conn.execute(select(func.count()).select_from(tables["users"])).scalar_one() == 0


def is_last_admin(conn: Connection, tables: Mapping[str, Table], user: str) -> bool:
    """`user` is the only active admin, so losing them would leave the registry unrepairable."""
    users, roles = tables["users"], tables["lab_roles"]
    others = conn.execute(
        select(func.count())
        .select_from(users.join(roles, users.c.user == roles.c.user))
        .where(users.c.active.is_(True), roles.c.role == LabRole.ADMIN.value, users.c.user != user)
    ).scalar_one()
    return others == 0 and is_active_admin(conn, tables, user)


def may_register(
    conn: Connection,
    tables: Mapping[str, Table],
    actor: Actor,
    user: str,
    lab_roles: Sequence[LabRole],
) -> bool:
    """Who may add a person: an active admin, or, on an empty registry, a person registering
    themselves as admin (`factory server init`)."""
    if registry_is_empty(conn, tables):
        return (
            actor.kind == "human"
            and actor.id == actor.user == user
            and (LabRole.ADMIN in lab_roles)
        )
    return actor_is_admin(conn, tables, actor)


def linked_user(
    conn: Connection, tables: Mapping[str, Table], issuer: str, subject: str
) -> str | None:
    identities = tables["identities"]
    user = conn.execute(
        select(identities.c.user).where(
            identities.c.issuer == issuer, identities.c.subject == subject
        )
    ).scalar()
    return None if user is None else str(user)


def _write_roles(
    conn: Connection, tables: Mapping[str, Table], user: str, lab_roles: Sequence[LabRole]
) -> None:
    roles = tables["lab_roles"]
    conn.execute(delete(roles).where(roles.c.user == user))
    conn.execute(insert(roles), [{"user": user, "role": role.value} for role in lab_roles])


def _set_active(conn: Connection, tables: Mapping[str, Table], user: str, active: bool) -> None:
    users = tables["users"]
    conn.execute(update(users).where(users.c.user == user).values(active=active))


def _user_registered(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(UserRegistered, event)
        if payload is None or user_exists(conn, tables, payload.user):
            return
        if not may_register(conn, tables, event.actor, payload.user, payload.lab_roles):
            return
        conn.execute(
            insert(tables["users"]).values(
                user=payload.user,
                display_name=payload.display_name,
                email_hash=payload.email_hash,
                active=True,
                registered_at=format_ts(event.ts),
            )
        )
        _write_roles(conn, tables, payload.user, payload.lab_roles)

    return fold


def _identity_linked(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(IdentityLinked, event)
        if payload is None or not actor_is_admin(conn, tables, event.actor):
            return
        if not user_exists(conn, tables, payload.user):
            return
        if linked_user(conn, tables, payload.issuer, payload.subject) is not None:
            return
        conn.execute(
            insert(tables["identities"]).values(
                issuer=payload.issuer, subject=payload.subject, user=payload.user
            )
        )

    return fold


def _user_deactivated(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(UserDeactivated, event)
        if payload is None or not actor_is_admin(conn, tables, event.actor):
            return
        if is_active(conn, tables, payload.user) and not is_last_admin(conn, tables, payload.user):
            _set_active(conn, tables, payload.user, False)

    return fold


def _user_reactivated(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(UserReactivated, event)
        if payload is None or not actor_is_admin(conn, tables, event.actor):
            return
        if user_exists(conn, tables, payload.user) and not is_active(conn, tables, payload.user):
            _set_active(conn, tables, payload.user, True)

    return fold


def _lab_role_set(tables: Mapping[str, Table]) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        payload = _parsed(LabRoleSet, event)
        if payload is None or not actor_is_admin(conn, tables, event.actor):
            return
        if not user_exists(conn, tables, payload.user):
            return
        if LabRole.ADMIN not in payload.lab_roles and is_last_admin(conn, tables, payload.user):
            return
        _write_roles(conn, tables, payload.user, payload.lab_roles)

    return fold


def lab_projection() -> tuple[Projection, dict[str, Table]]:
    """The lab projection and its tables by name, which the services read through."""
    metadata = MetaData()
    core_tables(metadata)
    tables = lab_tables(metadata)
    handlers: dict[str, Handler] = {
        "user.registered": _user_registered(tables),
        "user.identity_linked": _identity_linked(tables),
        "user.deactivated": _user_deactivated(tables),
        "user.reactivated": _user_reactivated(tables),
        "user.lab_role_set": _lab_role_set(tables),
    }
    projection = Projection(version=LAB_PROJECTION_VERSION, metadata=metadata, handlers=handlers)
    return projection, tables
