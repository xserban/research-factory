"""Watch cycles: re-run a protocol's planned queries on a declared cadence (slice 4b, living-A).

A cycle is a grouping of ordinary search runs, not a new kind of retrieval: every planned query of
every due source is run through `register_query`/`run_query`, so raw archiving, PRISMA-S fields,
shortfall handling and the protocol gate apply unchanged. New records are then deduplicated
incrementally and the cycle is closed with counts recomputed from the run events.

The whole of `watch_run` runs under a per-project file lock, so two callers (a scheduler and an
MCP session, say) cannot both open a cycle or both run its queries; the second waits, then finds
nothing due. The index's exclusive lock is held only to decide and to write the start of a cycle,
not during fetches. There is no daemon, thread or timer here: an external scheduler calls this.

Module kind (slice M): `retrieval`. Until the module contract exists the cycle is this plain
service; its events do not change when it moves behind the contract.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import text

from factory.canonical import canonical_json
from factory.clock import parse_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.living.counts import cycle_run_ids, cycle_work_ids, new_work_ids, source_counts
from factory.living.due import CycleView, consecutive_failures, due_sources, next_due
from factory.living.window import is_full_replay, window_spec, window_start
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_SEARCH
from factory.model.protocol import PlannedQuery, ProtocolStatus
from factory.model.search import QueryPurpose, QuerySpec
from factory.model.watch import (
    CycleSource,
    CycleStatus,
    CycleTrigger,
    SourceCounts,
    WatchCycleFinished,
    WatchCycleStarted,
    WatchSource,
)
from factory.services.budgets import require_for
from factory.services.context import Project
from factory.services.dedup_incremental import dedup_new
from factory.services.protocol import (
    current_protocol,
    registered_cycle,
    search_authorization,
)
from factory.services.search import register_query, run_query
from factory.sources.registry import SourceFactory

CYCLE_STALE_AFTER = timedelta(hours=24)
"""An open cycle older than this is closed `partial` (note `abandoned`) before a new one opens."""

CycleHook = Callable[[Project, str, tuple[str, ...]], tuple[str, ...]]
"""Called once per cycle as `(project, cycle_id, new_work_ids)`; returns the ids of the runs it
started, which the cycle records as `status_run_ids`. Plans living-B and living-C attach here."""


class CycleSummary(StrictModel):
    cycle_id: str
    status: CycleStatus
    counts: tuple[SourceCounts, ...]
    run_ids: tuple[str, ...]
    new_work_ids: tuple[str, ...]


class SourceStatus(StrictModel):
    source: str
    mode: str
    interval_days: int
    last_cycle: str | None
    last_finished_at: datetime | None
    next_due: datetime | None
    """None means due now: the source has never finished a cycle."""
    due: bool
    window_start: date | None
    full_replay_next: bool
    consecutive_failures: int
    last_full_replay: date | None = None
    """Start date of the last complete full replay in a watch cycle (None: none yet)."""
    windows_since_full_replay: int = 0
    """Complete window cycles of the source since that replay (all of them when None)."""


class WatchStatus(StrictModel):
    protocol_id: str | None
    has_plan: bool
    until: date | None
    open_cycle: str | None
    sources: tuple[SourceStatus, ...]


# --- reads ---


def cycles(project: Project) -> list[CycleView]:
    """Every cycle in start order, as the due and window computations read them."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cycle_id, started_at, finished_at, status, protocol_id FROM watch_cycles "
                "ORDER BY started_at, cycle_id"
            )
        ).all()
        source_rows = conn.execute(
            text("SELECT cycle_id, source, full_replay, complete FROM watch_cycle_sources")
        ).all()
    by_cycle: dict[str, list[tuple[str, bool, bool]]] = {}
    for cycle_id, source, full, complete in source_rows:
        by_cycle.setdefault(str(cycle_id), []).append((str(source), bool(full), bool(complete)))
    views: list[CycleView] = []
    for cycle_id, started, finished, status, protocol_id in rows:
        members = sorted(by_cycle.get(str(cycle_id), []))
        views.append(
            CycleView(
                cycle_id=str(cycle_id),
                started_at=parse_ts(str(started)),
                finished_at=None if finished is None else parse_ts(str(finished)),
                status=CycleStatus(str(status)),
                sources=tuple(s for s, _, _ in members),
                complete_sources=tuple(s for s, _, c in members if c),
                full_replay_sources=tuple(s for s, f, _ in members if f),
                protocol_id=str(protocol_id),
            )
        )
    return views


def search_baselines(project: Project) -> dict[str, date]:
    """Per source, the date (start) of the latest complete run of a planned query (purpose
    `search`) that belongs to no watch cycle: when the source's searches last completed outside
    watch cycles. A source with no such run is absent."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT q.source, MAX(r.started_at) FROM runs r JOIN queries q "
                "ON q.query_id = r.query_id WHERE r.status = 'complete' AND q.purpose = 'search' "
                "AND r.run_id NOT IN (SELECT run_id FROM watch_cycle_runs) GROUP BY q.source"
            )
        ).all()
    return {str(source): parse_ts(str(started)).date() for source, started in rows}


def watch_status(project: Project) -> WatchStatus:
    """Per source: last cycle, next due, mode, window start and failures; the open cycle."""
    current = current_protocol(project)
    plan = None if current is None else current.spec.watch_plan
    views = cycles(project)
    baselines = search_baselines(project)
    open_cycle = next((v.cycle_id for v in views if v.status is CycleStatus.OPEN), None)
    if current is None or plan is None:
        return WatchStatus(
            protocol_id=None if current is None else current.protocol_id,
            has_plan=False,
            until=None,
            open_cycle=open_cycle,
            sources=(),
        )
    now = project.clock.now()
    due = set(due_sources(plan, views, now))
    statuses: list[SourceStatus] = []
    for item in plan.sources:
        finished = [v for v in views if item.source in v.sources and v.finished_at is not None]
        last = max(finished, key=lambda v: v.finished_at or now, default=None)
        baseline = baselines.get(item.source)
        full = is_full_replay(item, views, baseline)
        complete = sorted(
            (v for v in views if item.source in v.complete_sources), key=lambda v: v.started_at
        )
        replays = [v for v in complete if item.source in v.full_replay_sources]
        statuses.append(
            SourceStatus(
                source=item.source,
                mode=item.mode,
                interval_days=item.interval_days,
                last_cycle=None if last is None else last.cycle_id,
                last_finished_at=None if last is None else last.finished_at,
                next_due=next_due(item, views),
                due=item.source in due,
                window_start=None if full else window_start(item, views, baseline),
                full_replay_next=full,
                consecutive_failures=consecutive_failures(item.source, views),
                last_full_replay=replays[-1].started_at.date() if replays else None,
                windows_since_full_replay=len(
                    [v for v in complete if not replays or v.started_at > replays[-1].started_at]
                ),
            )
        )
    return WatchStatus(
        protocol_id=current.protocol_id,
        has_plan=True,
        until=plan.until,
        open_cycle=open_cycle,
        sources=tuple(statuses),
    )


# --- the cycle ---


def watch_run(
    project: Project,
    *,
    sources: Mapping[str, SourceFactory],
    trigger: CycleTrigger,
    actor: Actor | None = None,
    force: bool = False,
    full_replay: bool = False,
    after_runs: Sequence[CycleHook] = (),
) -> CycleSummary | None:
    """Run the due watch cycle of the project; None, with nothing written, when none is due.

    Refused (nothing written) when there is no ready protocol with a `watch_plan`, when a due
    source has no adapter in `sources`, or when the protocol gate refuses a planned query.
    `force` runs every planned source whether or not it is due. An open cycle is resumed, never
    doubled: queries whose run in the cycle completed are skipped, the others run again.
    `full_replay` makes every source of a new cycle run as a full replay; only the researcher
    decides one, so it is refused (nothing written) unless `actor` is human. It does not change a
    cycle already open.
    """
    if full_replay and (actor is None or actor.kind != "human"):
        raise FactoryValidationError(
            [ValidationIssue("full_replay", "only a human requests a full replay")]
        )
    with _watch_lock(project):
        opened = _open_or_resume(project, sources, trigger, actor, force, full_replay)
        if opened is None:
            return None
        cycle_id, members, planned = opened
        notes: list[str] = []
        for member in members:
            for query in (q for q in planned if q.source == member.source):
                _run_planned(project, cycle_id, member, query, sources, actor, notes)
        fresh = new_work_ids(project, cycle_id)
        # Every work a run returned is deduplicated, not only the new ones (a later record can
        # give a known work an identifier), together with the works of earlier cycles whose
        # deduplication did not finish.
        carried = _unreconciled(project, cycle_id)
        to_dedup = {w for c in (cycle_id, *carried) for w in cycle_work_ids(project, c)}
        dedup_ok = True
        try:
            dedup_new(project, sorted(to_dedup))
        except Exception as exc:
            dedup_ok = False
            notes.append(f"dedup: {type(exc).__name__}: {exc}")
        status_runs: list[str] = []
        for hook in after_runs:
            try:
                status_runs.extend(hook(project, cycle_id, fresh))
            except Exception as exc:
                name = getattr(hook, "__name__", type(hook).__name__)
                notes.append(f"{name}: {type(exc).__name__}: {exc}")
        return _finish(
            project,
            cycle_id,
            tuple(status_runs),
            notes,
            fresh,
            dedup_ok,
            carried if dedup_ok else (),
        )


@contextmanager
def _watch_lock(project: Project) -> Iterator[None]:
    """Hold the project's watch lock (a cross-process file lock) for the whole of a cycle."""
    lock_path = project.paths.index_path.parent / "watch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _open_or_resume(
    project: Project,
    adapters: Mapping[str, SourceFactory],
    trigger: CycleTrigger,
    actor: Actor | None,
    force: bool,
    full_replay: bool = False,
) -> tuple[str, tuple[CycleSource, ...], tuple[PlannedQuery, ...]] | None:
    """Decide, and write `watch.cycle_started` when a new cycle opens, in one critical section."""
    with project.index.exclusive():
        project.index.sync()
        current = current_protocol(project)
        issues: list[ValidationIssue] = []
        if current is None or current.status is not ProtocolStatus.READY:
            issues.append(ValidationIssue("protocol", "record and ready a protocol first"))
        elif current.spec.watch_plan is None:
            issues.append(ValidationIssue("watch_plan", "the protocol declares no watch_plan"))
        if issues or current is None or current.spec.watch_plan is None:
            raise FactoryValidationError(issues)
        plan = current.spec.watch_plan
        now = project.clock.now()

        views = cycles(project)
        retry: set[str] = set()
        for view in views:
            if view.status is CycleStatus.OPEN:
                reason = _abandon_reason(view, current.protocol_id, now)
                if reason is not None:
                    _write_finished(project, view.cycle_id, CycleStatus.PARTIAL, (), reason)
                    retry.update(view.sources)  # an abandoned cycle must not postpone its sources
        views = cycles(project)
        planned = current.spec.queries

        open_view = next((v for v in views if v.status is CycleStatus.OPEN), None)
        if open_view is not None:
            members = _recorded_sources(project, open_view.cycle_id)
            _require_runnable(project, tuple(m.source for m in members), planned, adapters)
            require_for(project, actor or project.system_actor(), REQUESTS_SEARCH)
            return open_view.cycle_id, members, planned

        if force:
            due = tuple(sorted(item.source for item in plan.sources))
        else:
            due = due_sources(plan, views, now)
            if due or plan.until is None or plan.until >= now.date():
                planned_names = {item.source for item in plan.sources}
                due = tuple(sorted({*due, *(retry & planned_names)}))
        if not due:
            return None
        _require_runnable(project, due, planned, adapters)
        require_for(project, actor or project.system_actor(), REQUESTS_SEARCH)

        by_name = {item.source: item for item in plan.sources}
        baselines = search_baselines(project)
        chosen = tuple(
            _cycle_source(by_name[name], views, baselines.get(name), full_replay)
            for name in due
            if name in by_name
        )
        cycle_id = project.ids.new("wcy")
        started = WatchCycleStarted(
            cycle_id=cycle_id,
            protocol_id=current.protocol_id,
            sources=chosen,
            skipped=tuple(sorted(s.source for s in plan.sources if s.source not in due)),
            trigger=trigger,
        )
        who = actor or project.system_actor()
        input_blob = (
            project.blobs.put_json({"force": force, "trigger": trigger, "full_replay": full_replay})
            if who.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "watch.cycle_started",
                    started,
                    who,
                    refs=(cycle_id, current.protocol_id),
                    input_blob=input_blob,
                )
            ]
        )
        return cycle_id, chosen, planned


def _cycle_source(
    item: WatchSource,
    views: Sequence[CycleView],
    baseline: date | None = None,
    requested: bool = False,
) -> CycleSource:
    """How the source runs this cycle: a full replay, or a window from its last complete cycle
    (or, with none, from the baseline)."""
    if is_full_replay(item, views, baseline, requested):
        return CycleSource(source=item.source, mode=item.mode, window_start=None, full_replay=True)
    return CycleSource(
        source=item.source,
        mode="window",
        window_start=window_start(item, views, baseline),
        full_replay=False,
    )


def _recorded_sources(project: Project, cycle_id: str) -> tuple[CycleSource, ...]:
    """The sources an open cycle was started with, as recorded (never recomputed on resume)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT source, mode, window_start, full_replay FROM watch_cycle_sources "
                "WHERE cycle_id = :c ORDER BY source"
            ),
            {"c": cycle_id},
        ).all()
    return tuple(
        CycleSource(
            source=str(source),
            mode="window" if mode == "window" else "full",
            window_start=None if start is None else date.fromisoformat(str(start)),
            full_replay=bool(full),
        )
        for source, mode, start, full in rows
    )


def _abandon_reason(view: CycleView, protocol_id: str, now: datetime) -> str | None:
    if now - view.started_at > CYCLE_STALE_AFTER:
        return "abandoned"
    if view.protocol_id != protocol_id:
        return "protocol changed"
    return None


def _require_runnable(
    project: Project,
    members: Sequence[str],
    planned: Sequence[PlannedQuery],
    adapters: Mapping[str, SourceFactory],
) -> None:
    """Refuse, writing nothing, when a source has no adapter or the gate refuses a full query.

    Window queries are checked when they are registered, against their own cycle.
    """
    issues: list[ValidationIssue] = []
    for source in members:
        if source not in adapters:
            issues.append(ValidationIssue("sources", f"no adapter for {source!r}"))
    for query in planned:
        if query.source in members:
            spec = QuerySpec(
                source=query.source,
                kind=query.kind,
                text=query.text,
                purpose=QueryPurpose.SEARCH,
                filters=query.filters,
            )
            issues.extend(search_authorization(project, spec, deviation_id=None))
    if issues:
        raise FactoryValidationError(issues)


def _run_planned(
    project: Project,
    cycle_id: str,
    member: CycleSource,
    query: PlannedQuery,
    adapters: Mapping[str, SourceFactory],
    actor: Actor | None,
    notes: list[str],
) -> None:
    """Run one planned query inside the cycle unless a run of it already completed there.

    A full query reuses the registered query with the planned spec (registering one only when
    none exists); a window query is registered for this cycle, which authorises it.
    """
    windowed = member.mode == "window" and not member.full_replay and member.window_start
    spec = (
        window_spec(query, member.window_start)
        if windowed and member.window_start is not None
        else QuerySpec(
            source=query.source,
            kind=query.kind,
            text=query.text,
            purpose=QueryPurpose.SEARCH,
            filters=query.filters,
        )
    )
    who = actor or project.system_actor()
    try:
        if windowed:
            query_id = _registered_query(project, spec, cycle_id) or register_query(
                project, who, spec, sources=adapters, cycle_id=cycle_id
            )
        else:
            query_id = _registered_query(project, spec) or register_query(
                project, who, spec, sources=adapters
            )
        if _completed_in_cycle(project, cycle_id, query_id):
            return
        run_query(project, query_id, sources=adapters, actor=actor, cycle_id=cycle_id)
    except Exception as exc:  # a failed query must not stop the others
        notes.append(f"{query.source}: {type(exc).__name__}: {exc}")


def _registered_query(project: Project, spec: QuerySpec, cycle_id: str | None = None) -> str | None:
    """The earliest registered search query whose spec equals `spec`, if any.

    With `cycle_id`, only a query registered for that cycle (a window query is cycle-specific).
    """
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT query_id FROM queries WHERE purpose = :search AND source = :source "
                "AND kind = :kind AND text = :text AND filters = :filters "
                "ORDER BY registered_at, query_id"
            ),
            {
                "search": QueryPurpose.SEARCH.value,
                "source": spec.source,
                "kind": spec.kind.value,
                "text": spec.text,
                "filters": canonical_json(dict(spec.filters)).decode(),
            },
        ).all()
        if cycle_id is None:
            return str(rows[0][0]) if rows else None
        for (query_id,) in rows:
            if registered_cycle(project, str(query_id)) == cycle_id:
                return str(query_id)
    return None


def _completed_in_cycle(project: Project, cycle_id: str, query_id: str) -> bool:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM watch_cycle_runs wr JOIN runs r ON r.run_id = wr.run_id "
                "WHERE wr.cycle_id = :c AND wr.query_id = :q AND r.status = 'complete' LIMIT 1"
            ),
            {"c": cycle_id, "q": query_id},
        ).one_or_none()
    return row is not None


def _unreconciled(project: Project, current: str) -> tuple[str, ...]:
    """Finished cycles whose deduplication did not complete and that no later cycle reconciled."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cycle_id, dedup_complete, reconciled FROM watch_cycles "
                "WHERE status != 'open' AND cycle_id != :current ORDER BY started_at, cycle_id"
            ),
            {"current": current},
        ).all()
    done = {c for _, ok, rec in rows if ok for c in json.loads(str(rec or "[]"))}
    return tuple(str(cid) for cid, ok, _ in rows if not ok and str(cid) not in done)


def _finish(
    project: Project,
    cycle_id: str,
    status_runs: tuple[str, ...],
    notes: list[str],
    fresh: tuple[str, ...],
    dedup_ok: bool,
    reconciled: tuple[str, ...],
) -> CycleSummary:
    with project.index.exclusive():
        counts = source_counts(project, cycle_id)
        complete = [c for c in counts if c.complete]
        if counts and len(complete) == len(counts) and not notes:
            status = CycleStatus.COMPLETE
        elif any(c.complete_runs for c in counts):
            status = CycleStatus.PARTIAL
        else:
            status = CycleStatus.FAILED
        _write_finished(
            project,
            cycle_id,
            status,
            status_runs,
            "; ".join(notes) or None,
            dedup_complete=dedup_ok,
            reconciled=reconciled,
        )
        runs = cycle_run_ids(project, cycle_id)
    return CycleSummary(
        cycle_id=cycle_id, status=status, counts=counts, run_ids=runs, new_work_ids=fresh
    )


def _write_finished(
    project: Project,
    cycle_id: str,
    status: CycleStatus,
    status_runs: tuple[str, ...],
    note: str | None,
    *,
    dedup_complete: bool = False,
    reconciled: tuple[str, ...] = (),
) -> None:
    """Close the cycle: counts and run ids are read back from the index, never passed in."""
    finished = WatchCycleFinished(
        cycle_id=cycle_id,
        status=status,
        run_ids=cycle_run_ids(project, cycle_id),
        status_run_ids=status_runs,
        counts=source_counts(project, cycle_id),
        note=note,
        dedup_complete=dedup_complete,
        reconciled=reconciled,
    )
    with project.writing():
        project.record(
            [
                project.events.make(
                    "watch.cycle_finished", finished, project.system_actor(), refs=(cycle_id,)
                )
            ]
        )
