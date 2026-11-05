from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.members import MemberTables, holds_here
from factory.index.projection import Handler
from factory.model.hosting import ProjectHosted
from factory.model.members import ProjectRole
from factory.model.project import ProjectCreated, ProjectVisibilitySet, Visibility


def project_table(metadata: MetaData) -> Table:
    return Table(
        "project",
        metadata,
        Column("slug", String, primary_key=True),
        Column("rigor_mode", String, nullable=False),
        Column("created_at", String, nullable=False),
        Column("created_by", String, nullable=False),
    )


def project_created_handler(table: Table) -> Handler:
    def project_created(conn: Connection, event: Event) -> None:
        payload = ProjectCreated.model_validate(event.payload)
        # First event wins: a merge of two inits of one project must not break the index.
        conn.execute(
            insert(table)
            .values(
                slug=event.project,
                rigor_mode=payload.rigor_mode.value,
                created_at=format_ts(event.ts),
                created_by=event.actor.id,
            )
            .on_conflict_do_nothing(index_elements=["slug"])
        )

    return project_created


def project_hosts_table(metadata: MetaData) -> Table:
    return Table(
        "project_hosts",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("host_id", String, nullable=False),
        Column("previous_host", String),
        Column("hosted_by", String, nullable=False),
    )


def latest_host(conn: Connection) -> str | None:
    """The host of the last folded `project.hosted`; None for an unhosted project."""
    row = conn.execute(
        text("SELECT host_id FROM project_hosts ORDER BY event_id DESC LIMIT 1")
    ).first()
    return None if row is None else str(row[0])


def latest_hoster(conn: Connection) -> str | None:
    """The person who wrote the last folded `project.hosted`; None for an unhosted project."""
    row = conn.execute(
        text("SELECT hosted_by FROM project_hosts ORDER BY event_id DESC LIMIT 1")
    ).first()
    return None if row is None else str(row[0])


def project_creator(conn: Connection) -> str | None:
    """Who wrote the `project.created` that folded; None before it."""
    row = conn.execute(text("SELECT created_by FROM project LIMIT 1")).first()
    return None if row is None else str(row[0])


def project_visibility_table(metadata: MetaData) -> Table:
    return Table(
        "project_visibility",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("visibility", String, nullable=False),
    )


def latest_visibility(conn: Connection) -> Visibility:
    """The visibility of the last folded `project.visibility_set`; `lab` before any."""
    row = conn.execute(
        text("SELECT visibility FROM project_visibility ORDER BY event_id DESC LIMIT 1")
    ).first()
    return "private" if row is not None and row[0] == "private" else "lab"


def project_visibility_handler(table: Table, members: MemberTables) -> Handler:
    def visibility_set(conn: Connection, event: Event) -> None:
        """Folds an owner's act in their own name that changes the visibility. Anything else (an
        agent, another role, no change, a malformed payload) changes nothing."""
        if event.actor.kind != "human" or event.actor.id != event.actor.user:
            return
        try:
            payload = ProjectVisibilitySet.model_validate(event.payload)
        except ValidationError:
            return
        if not holds_here(conn, members, event.actor.user, frozenset({ProjectRole.OWNER})):
            return
        if payload.visibility == latest_visibility(conn):
            return
        conn.execute(insert(table).values(event_id=event.id, visibility=payload.visibility))

    return visibility_set


def project_hosted_handler(table: Table) -> Handler:
    def project_hosted(conn: Connection, event: Event) -> None:
        """Folds a person's move from the host in force to another. Anything else (another actor,
        a misstated `previous_host`, no change of host, a malformed payload) changes nothing."""
        if event.actor.kind != "human":
            return
        try:
            payload = ProjectHosted.model_validate(event.payload)
        except ValidationError:
            return
        current = latest_host(conn)
        if payload.previous_host != current or payload.host_id == current:
            return
        conn.execute(
            insert(table).values(
                event_id=event.id,
                host_id=payload.host_id,
                previous_host=payload.previous_host,
                hosted_by=event.actor.id,
            )
        )

    return project_hosted
