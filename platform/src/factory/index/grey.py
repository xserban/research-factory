"""Projection of reported grey searches and expert contacts (plan SG, Task 6).

`grey_searches` keeps one row per `grey.search_reported`, `grey_contacts` one per
`grey.contact_logged`. Neither enrols a work: a reported search's URLs are offered to the inbox
by the service, and the platform cannot verify what the agent says it ran.

Handlers are total and atomic: a payload that fails validation, and a second event under an
existing id, change nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.grey import GreyContactLogged, GreySearchReported


@dataclass(frozen=True)
class GreyTables:
    searches: Table
    contacts: Table


def grey_tables(metadata: MetaData) -> GreyTables:
    searches = Table(
        "grey_searches",
        metadata,
        Column("report_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("actor_kind", String, nullable=False),
        Column("target", String, nullable=False),
        Column("engine", String, nullable=False),
        Column("query", String, nullable=False),
        Column("searched_at", String, nullable=False),
        Column("stopping_rule", String, nullable=False),
        Column("url_count", Integer, nullable=False),
    )
    contacts = Table(
        "grey_contacts",
        metadata,
        Column("contact_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("actor_kind", String, nullable=False),
        Column("target", String, nullable=False),
        Column("contacted_on", String, nullable=False),
        Column("summary", String, nullable=False),
        Column("url_count", Integer, nullable=False),
    )
    return GreyTables(searches, contacts)


def grey_handlers(t: GreyTables) -> dict[str, Handler]:
    return {
        "grey.search_reported": _search(t),
        "grey.contact_logged": _contact(t),
    }


def _search(t: GreyTables) -> Handler:
    def reported(conn: Connection, event: Event) -> None:
        try:
            payload = GreySearchReported.model_validate(event.payload)
        except ValidationError:
            return
        conn.execute(
            sqlite_insert(t.searches)
            .values(
                report_id=payload.report_id,
                event_id=event.id,
                actor_kind=event.actor.kind,
                target=payload.target,
                engine=payload.engine,
                query=payload.query,
                searched_at=payload.timestamp.isoformat(),
                stopping_rule=payload.stopping_rule,
                url_count=len(payload.urls),
            )
            .on_conflict_do_nothing(index_elements=["report_id"])
        )

    return reported


def _contact(t: GreyTables) -> Handler:
    def logged(conn: Connection, event: Event) -> None:
        try:
            payload = GreyContactLogged.model_validate(event.payload)
        except ValidationError:
            return
        conn.execute(
            sqlite_insert(t.contacts)
            .values(
                contact_id=payload.contact_id,
                event_id=event.id,
                actor_kind=event.actor.kind,
                target=payload.target,
                contacted_on=payload.contacted_on.isoformat(),
                summary=payload.summary,
                url_count=len(payload.urls),
            )
            .on_conflict_do_nothing(index_elements=["contact_id"])
        )

    return logged
