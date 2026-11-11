"""Finding interrupted work (plan restart-and-costs R1, IDEA-59): what a power loss, a killed
process or an abandoned session left half done.

Invariants:
- `interrupted` is a pure read. It writes no event, never reconciles a run (`finish_lost` is not
  called, so an open run whose process is gone is reported, not closed) and closes no pipeline.
  The only side effect is that the index is synced (a rebuildable projection) and that the
  pipeline lock file is opened to read its state, as `pipeline.pipeline_active` does.
- Every rule is an existing read: `runner.run_status(reconcile=False)` for runs,
  `pipeline.pipeline_status` and `pipeline.pipeline_active` for pipelines, the lease rule of
  `tasks` (claimed and `lease_until <= now`, extraction tasks a newer task replaced left out) for
  leases, `work_queue.added_papers` for the automatic steps.
- A run is interrupted when it is `open-gone` (open, its process gone), `lost`, or `timeout`
  (`failed`, with no exit status or a kill-signal status, or named by the reason of a pipeline
  that stopped on a timeout). A run is left out when a later run of the same stage was `complete`
  (the work was resumed). `stage_pending` says whether its stage still has pending units.
- A pipeline is interrupted when it is `orphaned` (open, and no process holds the pipeline lock),
  `lost`, or stopped `failed` / `timeout`. It is left out when a later pipeline was `complete` or
  `idle`. `stages_left` are its planned stages from the one it stopped at (or, with none recorded,
  the first with no complete run) to the end, in order.
- A pass is stale when an agent session joined it, units of its task kind are still pending, and
  the session has recorded no event for `PASS_IDLE` (a task lease, 30 minutes: a session silent
  for longer holds no live claim). Human sessions are never reported.

Resuming (plan restart-and-costs R2): `resume` acts on `interrupted`.
- Resuming never edits an event. A resumed run (pipeline) is a new run (pipeline) that names the
  one it resumes in `resumes`; a run resumed with `start_run(resumes=...)` reuses the earlier run's
  recorded prompt blob, tools and model, and is refused when the stage's model or tools have
  changed since (a fresh run is then the researcher's call). A resumed pipeline re-plans the
  applicable stages from the first of `stages_left` that still applies, with fresh stage runs.
- Expired leases are not released by an event. The existing release path (`tasks.release_task`,
  and the fold of `task.released`) accepts only the session that holds a live claim, so a release
  of a lapsed lease, by the system or anyone, would be ignored; and a lapsed claim is claimable
  again by `claim_next`. `resume` therefore reports the lapsed leases as released-by-expiry and
  writes nothing for them.
- A stale agent pass is reported and never resumed: its session is a past process, and its
  identity (session, pass label) is not carried over. The remaining work is done by a new runner
  run, a new session, which the pass and independence rules govern as for any run.
- Order: reconcile open runs whose process is gone (`runner.finish_lost`, recording), the
  deterministic steps (`runner.advance_after`), then read `interrupted`. The newest interrupted
  pipeline is resumed; if none, the newest interrupted run of each stage with pending units is a
  resume candidate, but only one run starts (one run per project): the others are `queued`.
  Refusals (a live run or pipeline, a changed spec) are reported in `refused`, never raised.
- `dry_run` writes nothing, not even the reconcile, and starts nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal

from pydantic import Field
from sqlalchemy import text

from factory.clock import format_ts
from factory.errors import FactoryValidationError
from factory.model.base import StrictModel
from factory.model.extraction import scope_from_value
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.model.task import TASK_LEASE, TaskStatus
from factory.services import pipeline, runner
from factory.services.context import Project
from factory.services.extraction import abandoned_task_ids
from factory.services.stages import kinds_for, task_kind
from factory.services.work_queue import added_papers, pending_work

PASS_IDLE: Final = TASK_LEASE
"""How long a session that joined a pass may be silent before the pass counts as stale."""

_RECENT_ALL: Final = 100_000
_KILL_STATUSES: Final = frozenset({-15, -9, 143, 137})
"""Exit statuses of a run ended by SIGTERM / SIGKILL (direct, or through the `sh -c` wrapper)."""


class InterruptedRun(StrictModel):
    run_id: str
    stage: str
    model: str
    prompt_blob: str
    started_at: str
    kind: Literal["open-gone", "lost", "timeout"]
    stage_pending: bool
    """Whether the run's stage still has pending units (`runner.pending_units`)."""


class InterruptedPipeline(StrictModel):
    pipeline_id: str
    started_at: str
    kind: Literal["orphaned", "lost", "failed", "timeout"]
    stopped_at: str | None
    stages_left: list[str]
    reason: str | None


class ExpiredLeases(StrictModel):
    kind: str
    count: int
    task_ids: list[str]


class StalePass(StrictModel):
    module: Literal["screening", "extraction"]
    stage: str | None
    """The screening stage, for a screening pass."""
    scope: str | None
    """The extraction scope, for an extraction pass."""
    label: str
    session: str
    task_kind: str
    pending: int
    last_activity: str


class AutomaticLeft(StrictModel):
    """Added papers whose automatic step is undone: `resolve` (link never looked up), `fetch`
    (screened in, full text not sought) and `convert` (full text retrieved, not converted)."""

    resolve: int = 0
    fetch: int = 0
    convert: int = 0


class Interrupted(StrictModel):
    runs: list[InterruptedRun]
    pipelines: list[InterruptedPipeline]
    leases: list[ExpiredLeases]
    passes: list[StalePass]
    automatic: AutomaticLeft

    @property
    def is_clean(self) -> bool:
        a = self.automatic
        return not (
            self.runs
            or self.pipelines
            or self.leases
            or self.passes
            or a.resolve
            or a.fetch
            or a.convert
        )


def interrupted(project: Project, *, now: datetime | None = None) -> Interrupted:
    """Everything the project left interrupted, read-only (see the module docstring)."""
    when = project.clock.now() if now is None else now
    run_views = runner.run_status(project, reconcile=False, limit=_RECENT_ALL)
    pipelines = _pipelines(project, run_views)
    return Interrupted(
        runs=_runs(project, run_views, pipelines),
        pipelines=pipelines[0],
        leases=_leases(project, when),
        passes=_passes(project, when),
        automatic=_automatic(project),
    )


def _prompt_blobs(project: Project) -> dict[str, str]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT run_id, prompt_blob FROM runner_runs")).all()
    return {str(r[0]): str(r[1]) for r in rows}


def _runs(
    project: Project,
    views: list[runner.RunView],
    pipelines: tuple[list[InterruptedPipeline], list[str]],
) -> list[InterruptedRun]:
    timeout_reasons = pipelines[1]
    blobs = _prompt_blobs(project)
    found: list[InterruptedRun] = []
    # `views` are newest first: a stage seen complete earlier in the walk supersedes older runs.
    resumed: set[str] = set()
    for view in views:
        if view.status == "complete":
            resumed.add(view.stage)
            continue
        kind: Literal["open-gone", "lost", "timeout"] | None = None
        if view.status == "lost?":
            kind = "open-gone"
        elif view.status == "lost":
            kind = "lost"
        elif view.status == "failed" and (
            view.exit_status is None
            or view.exit_status in _KILL_STATUSES
            or any(view.run_id in reason for reason in timeout_reasons)
        ):
            kind = "timeout"
        if kind is None or view.stage in resumed:
            continue
        found.append(
            InterruptedRun(
                run_id=view.run_id,
                stage=view.stage,
                model=view.model,
                prompt_blob=blobs.get(view.run_id, ""),
                started_at=view.started_at,
                kind=kind,
                stage_pending=any(runner.pending_units(project, view.stage).values()),
            )
        )
    return found


def _pipelines(
    project: Project, runs: list[runner.RunView]
) -> tuple[list[InterruptedPipeline], list[str]]:
    """The interrupted pipelines and the reasons of those stopped on a timeout."""
    views = pipeline.pipeline_status(project, limit=_RECENT_ALL)
    orphaned = not pipeline.pipeline_active(project)
    outcome_of = {r.run_id: r.status for r in runs}
    stage_of = {r.run_id: r.stage for r in runs}
    found: list[InterruptedPipeline] = []
    timeouts: list[str] = []
    settled = False  # a newer pipeline completed or found nothing to do
    for view in views:  # newest first
        if view.status in ("complete", "idle"):
            settled = True
            continue
        timed_out = view.status == "failed" and (view.reason or "").startswith("timeout:")
        if timed_out and view.reason:
            timeouts.append(view.reason)
        kind: Literal["orphaned", "lost", "failed", "timeout"]
        if view.status == "running":
            if not orphaned:
                continue
            kind = "orphaned"
        elif view.status == "lost":
            kind = "lost"
        else:
            kind = "timeout" if timed_out else "failed"
        if settled:
            continue
        done = {
            stage_of[r] for r in view.run_ids if outcome_of.get(r) == "complete" and r in stage_of
        }
        start = (
            view.stopped_at
            if view.stopped_at in view.stages
            else next((s for s in view.stages if s not in done), None)
        )
        left = view.stages[view.stages.index(start) :] if start is not None else []
        found.append(
            InterruptedPipeline(
                pipeline_id=view.pipeline_id,
                started_at=view.started_at,
                kind=kind,
                stopped_at=view.stopped_at,
                stages_left=left,
                reason=view.reason,
            )
        )
    return found, timeouts


def _leases(project: Project, now: datetime) -> list[ExpiredLeases]:
    project.index.sync()
    abandoned = abandoned_task_ids(project)
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT kind, task_id FROM tasks WHERE status = :claimed AND lease_until <= :now "
                "ORDER BY kind, task_id"
            ),
            {"claimed": TaskStatus.CLAIMED.value, "now": format_ts(now)},
        ).all()
    by_kind: dict[str, list[str]] = {}
    for kind, task_id in rows:
        if str(task_id) not in abandoned:
            by_kind.setdefault(str(kind), []).append(str(task_id))
    return [ExpiredLeases(kind=k, count=len(ids), task_ids=ids) for k, ids in by_kind.items()]


def _last_activity(project: Project, session: str) -> str | None:
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT MAX(ts) FROM events WHERE session = :s"), {"s": session}
        ).scalar_one()
    return None if value is None else str(value)


def _passes(project: Project, now: datetime) -> list[StalePass]:
    project.index.sync()
    pending = pending_work(project)
    cutoff = format_ts(now - PASS_IDLE)
    with project.index.connect() as conn:
        screening = conn.execute(
            text(
                "SELECT stage, pass_label, session FROM pass_sessions "
                "WHERE actor_kind = 'agent' ORDER BY stage, session"
            )
        ).all()
        extraction = conn.execute(
            text(
                "SELECT scope, pass_label, session FROM extraction_sessions ORDER BY scope, session"
            )
        ).all()
    candidates: list[tuple[Literal["screening", "extraction"], str, str, str, str]] = []
    for stage, label, session in screening:
        kind = task_kind(ScreeningStage(str(stage)), PassLabel(str(label)))
        candidates.append(("screening", str(stage), str(label), str(session), kind))
    for scope, label, session in extraction:
        kind = kinds_for(scope_from_value(str(scope)))[PassLabel(str(label))]
        candidates.append(("extraction", str(scope), str(label), str(session), kind))
    found: list[StalePass] = []
    for module, where, label, session, kind in candidates:
        count = pending.get(kind, 0)
        last = _last_activity(project, session)
        if count == 0 or last is None or last > cutoff:
            continue
        found.append(
            StalePass(
                module=module,
                stage=where if module == "screening" else None,
                scope=where if module == "extraction" else None,
                label=label,
                session=session,
                task_kind=kind,
                pending=count,
                last_activity=last,
            )
        )
    return found


def _automatic(project: Project) -> AutomaticLeft:
    counts = {"added": 0, "screened-in": 0, "full-text": 0}
    for item in added_papers(project):
        if not item.stopped and item.stage in counts:
            counts[item.stage] += 1
    return AutomaticLeft(
        resolve=counts["added"], fetch=counts["screened-in"], convert=counts["full-text"]
    )


class PipelineResume(StrictModel):
    resumes: str
    from_stage: str
    stages: list[str]
    """The planned stages from `from_stage` that still apply."""


class RunResume(StrictModel):
    resumes: str
    stage: str
    model: str


class ResumePlan(StrictModel):
    """What `resume` does (or would do, for a dry run)."""

    reconcile: list[str]
    """Open runs whose process is gone, closed first."""
    leases: list[ExpiredLeases]
    """Lapsed leases: released by expiry, no event (see the module docstring)."""
    pipeline: PipelineResume | None
    run: RunResume | None
    queued: list[str]
    """Other interrupted runs with pending units, resumed by a later call."""
    stale_passes: list[StalePass]
    automatic: AutomaticLeft

    @property
    def is_empty(self) -> bool:
        a = self.automatic
        return not (
            self.reconcile
            or self.leases
            or self.pipeline
            or self.run
            or self.queued
            or self.stale_passes
            or a.resolve
            or a.fetch
            or a.convert
        )


class ResumeResult(StrictModel):
    plan: ResumePlan
    reconciled: list[str]
    pipeline_id: str | None = None
    run_id: str | None = None
    refused: list[str] = Field(default_factory=list)


def _plan(project: Project, found: Interrupted, reconcile: list[str]) -> ResumePlan:
    pipeline_plan: PipelineResume | None = None
    covered: set[str] = set()
    if found.pipelines:
        newest = found.pipelines[0]
        applicable = [s.key for s in pipeline.stages(project) if s.applies]
        left = [k for k in newest.stages_left if k in applicable]
        if left:
            first = applicable.index(left[0])
            pipeline_plan = PipelineResume(
                resumes=newest.pipeline_id, from_stage=left[0], stages=applicable[first:]
            )
            covered = set(applicable[first:])
    candidates: list[InterruptedRun] = []
    seen: set[str] = set()
    for run in found.runs:  # newest first: one candidate per stage
        if run.stage in seen or not run.stage_pending or run.stage in covered:
            continue
        seen.add(run.stage)
        candidates.append(run)
    run_plan: RunResume | None = None
    queued: list[str] = []
    if pipeline_plan is None and candidates:
        head = candidates[0]
        run_plan = RunResume(resumes=head.run_id, stage=head.stage, model=head.model)
        queued = [r.run_id for r in candidates[1:]]
    return ResumePlan(
        reconcile=reconcile,
        leases=found.leases,
        pipeline=pipeline_plan,
        run=run_plan,
        queued=queued,
        stale_passes=found.passes,
        automatic=found.automatic,
    )


def resume(
    project: Project,
    *,
    dry_run: bool = False,
    unit_cap: int | None = None,
    launcher: runner.Launcher | None = None,
) -> ResumePlan | ResumeResult:
    """Resume the project's interrupted work (see the module docstring). A dry run returns the
    `ResumePlan` and writes nothing; otherwise the plan is carried out and a `ResumeResult`
    returned. Pipelines and runs start in the background (their threads record the end);
    `pipeline_id` / `run_id` name what started. `unit_cap` defaults to the earlier run's (a run)
    or the default (a pipeline)."""
    if dry_run:
        found = interrupted(project)
        gone = [r.run_id for r in found.runs if r.kind == "open-gone"]
        return _plan(project, found, gone)
    reconciled = runner.finish_lost(project)
    runner.advance_after(project)
    found = interrupted(project)
    plan = _plan(project, found, [])
    pipeline_id: str | None = None
    run_id: str | None = None
    refused: list[str] = []
    try:
        if plan.pipeline is not None:
            pipeline_id = pipeline.start_pipeline(
                project,
                unit_cap=unit_cap or runner.DEFAULT_UNIT_CAP,
                launcher=launcher,
                from_stage=plan.pipeline.from_stage,
                resumes=plan.pipeline.resumes,
            )
        elif plan.run is not None:
            run_id = runner.start_run(
                project,
                plan.run.stage,
                unit_cap=unit_cap,
                launcher=launcher,
                resumes=plan.run.resumes,
            )
    except FactoryValidationError as exc:
        refused = [f"{i.field}: {i.reason}" for i in exc.issues]
    return ResumeResult(
        plan=plan, reconciled=reconciled, pipeline_id=pipeline_id, run_id=run_id, refused=refused
    )


__all__ = [
    "PASS_IDLE",
    "AutomaticLeft",
    "ExpiredLeases",
    "Interrupted",
    "InterruptedPipeline",
    "InterruptedRun",
    "PipelineResume",
    "ResumePlan",
    "ResumeResult",
    "RunResume",
    "StalePass",
    "interrupted",
    "resume",
]
