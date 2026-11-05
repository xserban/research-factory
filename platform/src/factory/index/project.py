from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.hosting import ProjectHosted
from factory.model.project import ProjectCreated


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
    )


def latest_host(conn: Connection) -> str | None:
    """The host of the last folded `project.hosted`; None for an unhosted project."""
    row = conn.execute(
        text("SELECT host_id FROM project_hosts ORDER BY event_id DESC LIMIT 1")
    ).first()
    return None if row is None else str(row[0])


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
                event_id=event.id, host_id=payload.host_id, previous_host=payload.previous_host
            )
        )

    return project_hosted
