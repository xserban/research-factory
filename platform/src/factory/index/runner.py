"""Projection of the headless runner (plan feed-hub H5, decision 118 item 4): `runner_runs`.

One row per run, created by `runner.started` and closed by the first `runner.finished`.

Folded only if (a hand-written event failing a guard changes nothing on rebuild):
- `runner.started`: the actor is the system (a human or an agent never starts a run) and the run
  is not already known.
- `runner.finished`: the actor is the system, the run is known and still open (the first finish
  stands).

Handlers are total: an event that does not validate changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue, ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.runner import RunnerFinished, RunnerStarted


@dataclass(frozen=True)
class RunnerTables:
    runs: Table


def runner_tables(metadata: MetaData) -> RunnerTables:
    runs = Table(
        "runner_runs",
        metadata,
        Column("run_id", String, primary_key=True),
        Column("stage", String, nullable=False),
        Column("model", String, nullable=False),
        Column("unit_cap", Integer, nullable=False),
        Column("allowed_tools", String, nullable=False),
        Column("command", String, nullable=False),
        Column("prompt_blob", String, nullable=False),
        Column("counts_before", String, nullable=False),
        Column("started_event_id", String, nullable=False),
        Column("outcome", String),
        Column("exit_status", Integer),
        Column("log_blob", String),
        Column("counts_after", String),
        Column("finished_event_id", String),
    )
    return RunnerTables(runs)


def _counts(value: dict[str, int]) -> dict[str, JsonValue]:
    return {key: count for key, count in value.items()}


def _total(handler: Handler) -> Handler:
    def run(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (ValidationError, ValueError, TypeError, KeyError):
            return

    return run


def runner_handlers(t: RunnerTables) -> dict[str, Handler]:
    def started(conn: Connection, event: Event) -> None:
        p = RunnerStarted.model_validate(event.payload)
        if event.actor.kind != "system":
            return
        conn.execute(
            sqlite_insert(t.runs)
            .values(
                run_id=p.run_id,
                stage=p.stage,
                model=p.model,
                unit_cap=p.unit_cap,
                allowed_tools=canonical_json(list(p.allowed_tools)).decode(),
                command=canonical_json(list(p.command)).decode(),
                prompt_blob=p.prompt_blob,
                counts_before=canonical_json(_counts(p.counts_before)).decode(),
                started_event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["run_id"])
        )

    def finished(conn: Connection, event: Event) -> None:
        p = RunnerFinished.model_validate(event.payload)
        if event.actor.kind != "system":
            return
        conn.execute(
            update(t.runs)
            .where(t.runs.c.run_id == p.run_id, t.runs.c.outcome.is_(None))
            .values(
                outcome=p.outcome,
                exit_status=p.exit_status,
                log_blob=p.log_blob,
                counts_after=canonical_json(_counts(p.counts_after)).decode(),
                finished_event_id=event.id,
            )
        )

    return {"runner.started": _total(started), "runner.finished": _total(finished)}
