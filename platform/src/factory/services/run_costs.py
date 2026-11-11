"""Run costs (plan restart-and-costs, task C1): what each headless run cost, read from its log.

Each headless run (`factory.services.runner`) records `runner.started` and `runner.finished`; the
finished event holds `log_blob`, the `claude -p --output-format stream-json --verbose` output, one
JSON object per line. This module reads those events and that log and computes the figures. It
writes nothing and calls no model.

Sources of each figure:
- `cost_usd`: `reported-by-cli`, the `total_cost_usd` of the final `result` line. It is the
  API-equivalent price of the tokens the run used, not a subscription charge. None while the log
  has no result line (a killed or truncated run).
- Tokens (per kind, and per turn): summed from the `usage` of the `assistant` lines of the log.
  A message split over several content blocks repeats its usage on each block; consecutive lines
  with the same message id are counted once.
- `units`: `counts_before` total minus `counts_after` total of the run (floor 0), both computed by
  the runner from the queue. No unit counter file is written by the MCP server, so there is no
  second source. An open run has no `counts_after`; its units are 0 with `units_source`
  `unavailable`.

Invariants:
- Read-only: no event is written, no blob is put, no file is changed.
- A malformed log line (not JSON, or JSON that is not an object) is ignored and counted in
  `malformed_lines`; blank lines are skipped. A truncated log therefore yields the figures it
  holds, with `complete` False.
- The log comes from the finished event's blob; when that blob is absent or fails its integrity
  check, from `projects/<slug>/runs/<run_id>/log.jsonl`; when neither exists the log is empty
  (zeros, `complete` False, `log_source` `none`).
- Per-unit figures are None unless units > 0 (and, for cost, a reported cost exists).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Literal

from pydantic import JsonValue

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.events.envelope import Event
from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.runner import RunnerFinished, RunnerStarted
from factory.services.context import Project
from factory.services.runner import MINE_PREFIX

COST_SOURCE = "reported-by-cli"
"""The `cost_source` of a figure taken from the CLI's result line (the API-equivalent price)."""

LogSource = Literal["blob", "file", "none"]
UnitsSource = Literal["counts-before-after", "unavailable"]


class TurnUsage(StrictModel):
    """The token usage of one assistant message of the log."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


class LogCost(StrictModel):
    """The figures read from one stream-json log. `reported_cost_usd` and the duration fields are
    None when the result line is absent; the token totals are the sums of `turns`."""

    complete: bool
    reported_cost_usd: float | None
    num_turns: int | None
    duration_ms: int | None
    duration_api_ms: int | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    turns: list[TurnUsage]
    malformed_lines: int


class RunCost(StrictModel):
    """The cost of one headless run. Every figure is computed from the run's events and log; the
    `*_source` fields name where each figure comes from."""

    run_id: str
    stage: str
    model: str
    miner: str | None
    started_at: str
    outcome: str | None
    exit_status: int | None
    units: int
    units_source: UnitsSource
    cost_usd: float | None
    cost_source: str | None
    cost_per_unit_usd: float | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    tokens_per_unit: float | None
    turns: int
    duration_ms: int | None
    complete: bool
    malformed_lines: int
    log_source: LogSource


def _count(value: JsonValue | None) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_int(value: JsonValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: JsonValue | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _turn(usage: dict[str, JsonValue]) -> TurnUsage:
    return TurnUsage(
        input_tokens=_count(usage.get("input_tokens")),
        output_tokens=_count(usage.get("output_tokens")),
        cache_read_tokens=_count(usage.get("cache_read_input_tokens")),
        cache_write_tokens=_count(usage.get("cache_creation_input_tokens")),
    )


def parse_log(lines: Iterable[str]) -> LogCost:
    """Read a stream-json log. Assistant lines give the per-turn usage in order; the last `result`
    line gives the reported cost, turn count and durations. `complete` is True when a result line
    was seen. Malformed lines are ignored and counted."""
    turns: list[TurnUsage] = []
    malformed = 0
    result: dict[str, JsonValue] | None = None
    last_id: str | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            obj: JsonValue = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(obj, dict):
            malformed += 1
            continue
        kind = obj.get("type")
        if kind == "assistant":
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            msg_id = message.get("id")
            message_id = msg_id if isinstance(msg_id, str) else None
            if message_id is not None and message_id == last_id:
                continue
            last_id = message_id
            turns.append(_turn(usage))
        elif kind == "result":
            result = obj
    return LogCost(
        complete=result is not None,
        reported_cost_usd=None if result is None else _optional_float(result.get("total_cost_usd")),
        num_turns=None if result is None else _optional_int(result.get("num_turns")),
        duration_ms=None if result is None else _optional_int(result.get("duration_ms")),
        duration_api_ms=None if result is None else _optional_int(result.get("duration_api_ms")),
        input_tokens=sum(t.input_tokens for t in turns),
        output_tokens=sum(t.output_tokens for t in turns),
        cache_read_tokens=sum(t.cache_read_tokens for t in turns),
        cache_write_tokens=sum(t.cache_write_tokens for t in turns),
        turns=turns,
        malformed_lines=malformed,
    )


def _index_runs(
    project: Project,
) -> tuple[dict[str, tuple[Event, RunnerStarted]], dict[str, RunnerFinished]]:
    """The started events (with their event, in log order) and the finished payloads by run id."""
    started: dict[str, tuple[Event, RunnerStarted]] = {}
    finished: dict[str, RunnerFinished] = {}
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type == "runner.started":
            payload = RunnerStarted.model_validate(event.payload)
            started[payload.run_id] = (event, payload)
        elif event.type == "runner.finished":
            done = RunnerFinished.model_validate(event.payload)
            finished[done.run_id] = done
    return started, finished


def _log_text(
    project: Project, run_id: str, finished: RunnerFinished | None
) -> tuple[str, LogSource]:
    if finished is not None:
        try:
            return project.blobs.get(finished.log_blob).decode("utf-8", "replace"), "blob"
        except (BlobNotFoundError, BlobIntegrityError):
            pass
    path = project.paths.dir / "runs" / run_id / "log.jsonl"
    try:
        return path.read_text(encoding="utf-8", errors="replace"), "file"
    except OSError:
        return "", "none"


def _cost(
    project: Project,
    run_id: str,
    started: RunnerStarted,
    started_at: str,
    finished: RunnerFinished | None,
) -> RunCost:
    text, log_source = _log_text(project, run_id, finished)
    log = parse_log(text.splitlines())
    before = sum(started.counts_before.values())
    if finished is None:
        units, units_source = 0, "unavailable"
    else:
        units = max(before - sum(finished.counts_after.values()), 0)
        units_source = "counts-before-after"
    cost = log.reported_cost_usd
    tokens = log.input_tokens + log.output_tokens + log.cache_read_tokens + log.cache_write_tokens
    miner = started.stage[len(MINE_PREFIX) :] if started.stage.startswith(MINE_PREFIX) else None
    return RunCost(
        run_id=run_id,
        stage=started.stage,
        model=started.model,
        miner=miner,
        started_at=started_at,
        outcome=None if finished is None else finished.outcome,
        exit_status=None if finished is None else finished.exit_status,
        units=units,
        units_source=units_source,
        cost_usd=cost,
        cost_source=None if cost is None else COST_SOURCE,
        cost_per_unit_usd=cost / units if cost is not None and units > 0 else None,
        input_tokens=log.input_tokens,
        output_tokens=log.output_tokens,
        cache_read_tokens=log.cache_read_tokens,
        cache_write_tokens=log.cache_write_tokens,
        tokens_per_unit=tokens / units if units > 0 else None,
        turns=len(log.turns),
        duration_ms=log.duration_ms,
        complete=log.complete,
        malformed_lines=log.malformed_lines,
        log_source=log_source,
    )


def run_cost(project: Project, run_id: str) -> RunCost:
    """The cost of run `run_id`. Refuses with one `FactoryValidationError` when the project has no
    `runner.started` event for it."""
    started, finished = _index_runs(project)
    if run_id not in started:
        raise FactoryValidationError(
            [ValidationIssue("run_id", f"no runner.started event for run {run_id}")]
        )
    event, payload = started[run_id]
    return _cost(project, run_id, payload, event.ts.isoformat(), finished.get(run_id))


def all_run_costs(project: Project) -> list[RunCost]:
    """The costs of every run of the project, in the order their `runner.started` events were
    recorded."""
    started, finished = _index_runs(project)
    return [
        _cost(project, run_id, payload, event.ts.isoformat(), finished.get(run_id))
        for run_id, (event, payload) in started.items()
    ]
