"""Projection of chat requests (plan spar-night N3).

Table `chat_requests`: one row per folded request, with who took it (the run and the session). The
state is not a column: it is derived at read time from this row, the runs (`runner_runs`) and the
results that name the request (`sheets.request_id`, `sheets.for_request_id`,
`answers.request_id`), see `services/chat_requests.py`.

An event is folded only when it is consistent with what `services/chat_requests.py` enforces; one
that fails stays in the log and changes nothing (no service writes one, so it was written by hand):
- a request needs a human actor and a parent that is a folded sheet or answer when one is named
  (a re-spar names a sheet);
- a taking needs an agent actor, a folded request not taken before and, when the run is known, a
  run of the request's stage (`spar` or `ask`).

Handlers are total: a failure at any point folds nothing and never raises, on rebuild too.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.errors import FactoryError
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.chat_requests import ChatRequested, ChatRequestTaken


class ChatRequestTables:
    def __init__(self, requests: Table) -> None:
        self.requests = requests


def chat_request_tables(metadata: MetaData) -> ChatRequestTables:
    requests = Table(
        "chat_requests",
        metadata,
        Column("request_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("selection", String, nullable=False),
        Column("hypothesis", String),
        Column("question", String),
        Column("mode", String),
        Column("parent", String),
        Column("note", String),
        Column("respar", Boolean, nullable=False, server_default="0"),
        Column("actor", String, nullable=False),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("taken_run", String),
        Column("taken_session", String),
        Column("taken_event_id", String),
    )
    return ChatRequestTables(requests)


def chat_request_handlers(tables: ChatRequestTables) -> dict[str, Handler]:
    def requested(conn: Connection, event: Event) -> None:
        payload = ChatRequested.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        if payload.parent is not None:
            table, column = (
                ("answers", "answer_id")
                if payload.parent.startswith("ans_")
                else ("sheets", "sheet_id")
            )
            found = conn.execute(
                text(f"SELECT 1 FROM {table} WHERE {column} = :p"), {"p": payload.parent}
            ).first()
            if found is None:
                return
        if payload.respar and not payload.parent:
            return
        conn.execute(
            sqlite_insert(tables.requests)
            .values(
                request_id=payload.request_id,
                kind=payload.kind,
                selection=canonical_json(payload.selection).decode(),
                hypothesis=payload.hypothesis,
                question=payload.question,
                mode=payload.mode,
                parent=payload.parent,
                note=payload.note,
                respar=payload.respar,
                actor=event.actor.id,
                ts=format_ts(event.ts),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["request_id"])
        )

    def taken(conn: Connection, event: Event) -> None:
        payload = ChatRequestTaken.model_validate(event.payload)
        if event.actor.kind != "agent":
            return
        row = conn.execute(
            text("SELECT kind, taken_run FROM chat_requests WHERE request_id = :r"),
            {"r": payload.request_id},
        ).first()
        if row is None or row[1] is not None:
            return
        stage = conn.execute(
            text("SELECT stage FROM runner_runs WHERE run_id = :r"), {"r": payload.run_id}
        ).first()
        if stage is not None and str(stage[0]) != str(row[0]):
            return
        conn.execute(
            text(
                "UPDATE chat_requests SET taken_run = :run, taken_session = :s, "
                "taken_event_id = :e WHERE request_id = :r"
            ),
            {
                "run": payload.run_id,
                "s": event.actor.session,
                "e": event.id,
                "r": payload.request_id,
            },
        )

    def total(fold: Handler) -> Handler:
        def run(conn: Connection, event: Event) -> None:
            try:
                with conn.begin_nested():
                    fold(conn, event)
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                FactoryError,
                SQLAlchemyError,
            ):
                return

        return run

    return {
        "chat.requested": total(requested),
        "chat.request_taken": total(taken),
    }
