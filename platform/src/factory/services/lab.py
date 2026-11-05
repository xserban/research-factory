"""The lab registry: who the people of this server are (slice 5 rulings 6 and 9).

A second event log at `<root>/lab/`, with its own catalog and projection, on the same `EventWriter`,
`Index` and `EventFactory` as a project. Its envelope `project` is the reserved slug `lab`.

Invariants:
- Every mint and record happens under the lab write lock, and each check reads the state the lock
  holds still, so two admins cannot both pass a check and both write.
- A refusal writes nothing. The services refuse what the fold would ignore, so an event the
  platform writes always counts; `index/lab.py` holds the rules for both.
- A user id is never reused: deactivation never deletes, so a deactivated user's id stays taken.
- No email address reaches the log, only its SHA-256.
"""

import hashlib
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError
from sqlalchemy import Table, select
from sqlalchemy.engine import Connection

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobStore
from factory.events.envelope import Actor, Event
from factory.events.factory import EventFactory
from factory.events.writer import EventWriter
from factory.index import lab as lab_index
from factory.index.index import Index
from factory.model.base import StrictModel
from factory.model.identity import IdGenerator
from factory.model.lab import (
    LAB_SLUG,
    IdentityLinked,
    LabRole,
    LabRoleSet,
    UserDeactivated,
    UserReactivated,
    UserRegistered,
)
from factory.services.context import future_dated

_M = TypeVar("_M", bound=StrictModel)
_T = TypeVar("_T")
_PRIVATE_DIR_MODE = 0o700


@dataclass(frozen=True)
class LabPaths:
    root: Path

    @property
    def dir(self) -> Path:
        return self.root / "lab"

    @property
    def events_dir(self) -> Path:
        return self.dir / "events"

    @property
    def blobs_dir(self) -> Path:
        return self.dir / "blobs"

    @property
    def index_path(self) -> Path:
        return self.dir / ".index" / "lab.sqlite"


@dataclass
class Lab:
    """Everything a service needs to work on the lab registry."""

    paths: LabPaths
    settings: Settings
    session: str
    clock: Clock
    ids: IdGenerator
    events: EventFactory
    writer: EventWriter
    index: Index
    tables: dict[str, Table]

    def writing(self) -> AbstractContextManager[None]:
        """The lab write context, as `Project.writing()`: lock, sync, and IDs above the log."""
        return self.index.exclusive()

    def record(self, events: Sequence[Event]) -> None:
        with self.writing():
            self.writer.append(events)
            self.index.sync()

    def human_actor(self) -> Actor:
        return Actor(
            kind="human", id=self.settings.user, user=self.settings.user, session=self.session
        )


@dataclass(frozen=True)
class UserRecord:
    user: str
    display_name: str
    active: bool
    lab_roles: tuple[LabRole, ...]


def private_server_dir(root: Path) -> Path:
    """`<root>/.server/`, created if need be and always mode 0700: it holds secrets and logs."""
    path = root / ".server"
    path.mkdir(mode=_PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    path.chmod(_PRIVATE_DIR_MODE)
    return path


def lab_exists(settings: Settings) -> bool:
    return LabPaths(settings.root).events_dir.is_dir()


def _build_lab(settings: Settings, *, session: str, clock: Clock) -> Lab:
    paths = LabPaths(settings.root)
    catalog = lab_index.lab_catalog()
    ids = IdGenerator(clock)
    blobs = BlobStore(paths.blobs_dir)
    projection, tables = lab_index.lab_projection()

    def floor(last_event_id: str | None) -> None:
        """As a hosted project: the lab has one writer, and a far-future event sets no floor."""
        if last_event_id is not None and not future_dated(last_event_id, clock.now()):
            ids.floor(last_event_id.removeprefix("ev_"))

    return Lab(
        paths=paths,
        settings=settings,
        session=session,
        clock=clock,
        ids=ids,
        events=EventFactory(LAB_SLUG, catalog, ids),
        writer=EventWriter(paths.events_dir, project=LAB_SLUG, catalog=catalog, blobs=blobs),
        index=Index(paths.index_path, paths.events_dir, catalog, projection, on_exclusive=floor),
        tables=tables,
    )


def init_lab(settings: Settings, *, session: str, clock: Clock) -> Lab:
    """Create `<root>/lab/events` if need be and open the registry. Registers nobody."""
    LabPaths(settings.root).events_dir.mkdir(parents=True, exist_ok=True)
    return _build_lab(settings, session=session, clock=clock)


def open_lab(settings: Settings, *, session: str, clock: Clock) -> Lab:
    if not lab_exists(settings):
        raise refuse("lab", "no lab registry; run factory server init")
    return _build_lab(settings, session=session, clock=clock)


def read_lab(lab: Lab, read: Callable[[Connection], _T]) -> _T:
    """`read` on a connection to the synced lab index."""
    lab.index.sync()
    with lab.index.connect() as conn:
        return read(conn)


def payload_of(model: type[_M], **fields: object) -> _M:
    """The payload, or the structured refusal naming each bad field."""
    try:
        return model.model_validate(fields)
    except ValidationError as exc:
        raise FactoryValidationError(
            [ValidationIssue(".".join(str(p) for p in e["loc"]), e["msg"]) for e in exc.errors()]
        ) from exc


def refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def require_admin(lab: Lab, conn: Connection, actor: Actor) -> None:
    if not lab_index.actor_is_admin(conn, lab.tables, actor):
        raise refuse("permission", "lab:admin not held")


def require_user(lab: Lab, conn: Connection, user: str) -> None:
    if not lab_index.user_exists(conn, lab.tables, user):
        raise refuse("user", f"no user {user!r}")


def email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _ordered(lab_roles: Iterable[LabRole]) -> list[str]:
    """The roles in one order, so that the same set writes the same payload. A repeat is kept for
    the model to refuse."""
    return sorted(str(role) for role in lab_roles)


def register_user(
    lab: Lab,
    actor: Actor,
    user: str,
    display_name: str,
    email: str | None,
    lab_roles: Iterable[LabRole],
) -> None:
    """Add a person. Refused when the user exists or ever existed, and to anyone but an active
    admin; on an empty registry, to anyone but a person registering themselves as `admin`."""
    if email is not None and not email:
        raise refuse("email", "must not be empty")
    payload = payload_of(
        UserRegistered,
        user=user,
        display_name=display_name,
        email_hash=None if email is None else email_hash(email),
        lab_roles=_ordered(lab_roles),
    )
    with lab.writing():
        with lab.index.connect() as conn:
            if not lab_index.may_register(conn, lab.tables, actor, user, payload.lab_roles):
                raise refuse("permission", "lab:admin not held")
            if lab_index.user_exists(conn, lab.tables, user):
                raise refuse("user", f"user {user!r} exists; a user id is never reused")
        lab.record([lab.events.make("user.registered", payload, actor)])


def deactivate_user(lab: Lab, actor: Actor, user: str, reason: str) -> None:
    """Stop a person acting; their events stay attributed. The last active admin is refused."""
    payload = payload_of(UserDeactivated, user=user, reason=reason)
    with lab.writing():
        with lab.index.connect() as conn:
            require_admin(lab, conn, actor)
            require_user(lab, conn, user)
            if not lab_index.is_active(conn, lab.tables, user):
                raise refuse("user", f"user {user!r} is not active")
            if lab_index.is_last_admin(conn, lab.tables, user):
                raise refuse("user", "the last active admin cannot be deactivated")
        lab.record([lab.events.make("user.deactivated", payload, actor)])


def reactivate_user(lab: Lab, actor: Actor, user: str, reason: str) -> None:
    payload = payload_of(UserReactivated, user=user, reason=reason)
    with lab.writing():
        with lab.index.connect() as conn:
            require_admin(lab, conn, actor)
            require_user(lab, conn, user)
            if lab_index.is_active(conn, lab.tables, user):
                raise refuse("user", f"user {user!r} is active")
        lab.record([lab.events.make("user.reactivated", payload, actor)])


def set_lab_roles(lab: Lab, actor: Actor, user: str, lab_roles: Iterable[LabRole]) -> None:
    """Replace a person's lab roles. Taking `admin` from the last active admin is refused."""
    payload = payload_of(LabRoleSet, user=user, lab_roles=_ordered(lab_roles))
    with lab.writing():
        with lab.index.connect() as conn:
            require_admin(lab, conn, actor)
            require_user(lab, conn, user)
            if LabRole.ADMIN not in payload.lab_roles and lab_index.is_last_admin(
                conn, lab.tables, user
            ):
                raise refuse("lab_roles", "the last active admin must keep the admin role")
        lab.record([lab.events.make("user.lab_role_set", payload, actor)])


def link_identity(lab: Lab, actor: Actor, user: str, issuer: str, subject: str) -> None:
    """Link a provider's subject to a person. Refused when the pair is linked already: to another
    user, because it names one person for good; to this one, because there is nothing to record."""
    payload = payload_of(IdentityLinked, user=user, issuer=issuer, subject=subject)
    with lab.writing():
        with lab.index.connect() as conn:
            require_admin(lab, conn, actor)
            require_user(lab, conn, user)
            if lab_index.linked_user(conn, lab.tables, issuer, subject) is not None:
                raise refuse("subject", "this identity is already linked")
        lab.record([lab.events.make("user.identity_linked", payload, actor)])


def user_record(lab: Lab, user: str) -> UserRecord | None:
    """A person as the registry stands; None when the id was never registered."""

    def read(conn: Connection) -> UserRecord | None:
        users = lab.tables["users"]
        row = conn.execute(
            select(users.c.display_name, users.c.active).where(users.c.user == user)
        ).first()
        if row is None:
            return None
        roles = lab_index.roles_of_user(conn, lab.tables, user)
        return UserRecord(user, str(row.display_name), bool(row.active), roles)

    return read_lab(lab, read)


def list_users(lab: Lab) -> list[UserRecord]:
    """Every person ever registered, deactivated ones included, by id."""

    def read(conn: Connection) -> list[UserRecord]:
        users = lab.tables["users"]
        rows = conn.execute(
            select(users.c.user, users.c.display_name, users.c.active).order_by(users.c.user)
        ).all()
        return [
            UserRecord(
                str(row.user),
                str(row.display_name),
                bool(row.active),
                lab_index.roles_of_user(conn, lab.tables, str(row.user)),
            )
            for row in rows
        ]

    return read_lab(lab, read)


def user_for_subject(lab: Lab, issuer: str, subject: str) -> str | None:
    """The user a provider's subject is linked to, active or not; the caller reads `active`."""
    return read_lab(lab, lambda conn: lab_index.linked_user(conn, lab.tables, issuer, subject))
