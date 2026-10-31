from sqlalchemy import Column, MetaData, String, Table, insert
from sqlalchemy.engine import Connection

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
        created_at = str(event.model_dump(mode="json", by_alias=True)["ts"])
        conn.execute(
            insert(table).values(
                slug=payload.slug,
                rigor_mode=payload.rigor_mode.value,
                created_at=created_at,
                created_by=event.actor.id,
            )
        )

    return project_created
