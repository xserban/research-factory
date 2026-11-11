"""Projection of the headless runner (plan feed-hub H5, decision 118 item 4): `runner_runs`.

One row per run, created by `runner.started` and closed by the first `runner.finished`; one row
per pipeline (`runner_pipelines`), created by `runner.pipeline_started` and closed by the first
`runner.pipeline_finished`.

Folded only if (a hand-written event failing a guard changes nothing on rebuild):
- `runner.started`: the actor is the system (a human or an agent never starts a run) and the run
  is not already known.
- `runner.finished`: the actor is the system, the run is known and still open (the first finish
  stands).
- `runner.pipeline_started` and `runner.pipeline_finished`: the same two guards for a pipeline.
- `adopted` (optional, R4; False when absent) marks a driver recorded after the fact.
- `resumes` (optional, R2) is stored only if it names a run (pipeline) already folded; otherwise
  the run (pipeline) is kept with `resumes` NULL. The index is per project, so "known" means
  known to this project.

Handlers are total: an event that does not validate changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue, ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.runner import PipelineFinished, PipelineStarted, RunnerFinished, RunnerStarted


@dataclass(frozen=True)
class RunnerTables:
    runs: Table
    pipelines: Table


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
        Column("resumes", String),
        Column("adopted", Integer, nullable=False, default=0),
    )
    pipelines = Table(
        "runner_pipelines",
        metadata,
        Column("pipeline_id", String, primary_key=True),
        Column("stages", String, nullable=False),
        Column("unit_cap", Integer, nullable=False),
        Column("counts_before", String, nullable=False),
        Column("started_event_id", String, nullable=False),
        Column("outcome", String),
        Column("run_ids", String),
        Column("stopped_at", String),
        Column("reason", String),
        Column("finished_event_id", String),
        Column("resumes", String),
    )
    return RunnerTables(runs, pipelines)


def _counts(value: dict[str, int]) -> dict[str, JsonValue]:
    return {key: count for key, count in value.items()}


def _total(handler: Handler) -> Handler:
    def run(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (ValidationError, ValueError, TypeError, KeyError):
            return

    return run


def _known(conn: Connection, table: Table, key: str, value: str | None) -> str | None:
    """`value` if it is the id of a row of `table`, else None (an unknown reference is dropped)."""
    if value is None:
        return None
    found = conn.execute(select(table.c[key]).where(table.c[key] == value)).first()
    return value if found is not None else None


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
                resumes=_known(conn, t.runs, "run_id", p.resumes),
                adopted=int(p.adopted),
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

    def pipeline_started(conn: Connection, event: Event) -> None:
        p = PipelineStarted.model_validate(event.payload)
        if event.actor.kind != "system":
            return
        conn.execute(
            sqlite_insert(t.pipelines)
            .values(
                pipeline_id=p.pipeline_id,
                stages=canonical_json(list(p.stages)).decode(),
                unit_cap=p.unit_cap,
                counts_before=canonical_json(_counts(p.counts_before)).decode(),
                started_event_id=event.id,
                resumes=_known(conn, t.pipelines, "pipeline_id", p.resumes),
            )
            .on_conflict_do_nothing(index_elements=["pipeline_id"])
        )

    def pipeline_finished(conn: Connection, event: Event) -> None:
        p = PipelineFinished.model_validate(event.payload)
        if event.actor.kind != "system":
            return
        conn.execute(
            update(t.pipelines)
            .where(t.pipelines.c.pipeline_id == p.pipeline_id, t.pipelines.c.outcome.is_(None))
            .values(
                outcome=p.outcome,
                run_ids=canonical_json(list(p.run_ids)).decode(),
                stopped_at=p.stopped_at,
                reason=p.reason,
                finished_event_id=event.id,
            )
        )

    return {
        "runner.started": _total(started),
        "runner.finished": _total(finished),
        "runner.pipeline_started": _total(pipeline_started),
        "runner.pipeline_finished": _total(pipeline_finished),
    }
