from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
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
