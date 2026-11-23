"""The full ingestion pipeline (plan feed-hub H8, decision 119): the ordered stages that apply to a
project, the pending units of each, and Process all.

Order: `screen` (title/abstract and full text) -> the automatic steps (`work_queue.advance` and
`references_extract`) -> `extract` -> `mine:<miner id>` (one stage per registered miner) ->
`appraise` -> `contributions` -> `intuition`. Which stages apply is read from the project's
configuration, never typed here:

- `screen`: a ready protocol. `extract`: a ready protocol with an `extraction_schema` (and the
  rest `require_schema` demands). `mine:<id>`: the miner is registered and listed in the protocol.
  `appraise`: the protocol declares an `appraisal_instrument`. `contributions`: a ready protocol
  with a `contribution_schema`. `intuition`: at least one confirmed idea.
- Pending units: `screen`, the open tasks of the two pass A screening kinds; `extract`,
  `contributions` and each miner, the pass A units of the scope that are queued, open or stale and
  whose work is converted; `appraise`, the pass A units not finished under the instrument in force;
  `intuition`, the confirmed ideas without a live interpretation. `extract` takes the larger of its
  open tasks and its unit count, since a task is made only when a session asks for the unit.

Invariants:
- Pure reads, except `begin_pipeline` and the runs. The platform calls no model: each stage run is
  one capped `claude -p` process (`services.runner`), the automatic steps are deterministic.
- One pipeline or run per project at a time. A pipeline holds an exclusive non-blocking `flock` on
  `runs/.pipeline.lock` from its start to its end; a second pipeline, or a per-stage run, started
  while it is held is refused. A pipeline row left open by a process that is gone (the lock is
  free) is closed as `lost` before the next one starts.
- `runner.pipeline_started` and `runner.pipeline_finished` are system events, one pair per
  pipeline; the finish names every stage run started and the outcome. A pipeline runs each stage
  with pending work at its turn, runs the automatic steps before the first stage and after each
  run, and stops at the first run that is `failed` or `lost` (or that cannot be started).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import IO, Final

from pydantic import Field
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.extraction import MinerScope, Scope, ScopeKey
from factory.model.protocol import ProtocolStatus
from factory.model.runner import PipelineFinished, PipelineOutcome, PipelineStarted
from factory.model.screening import PassLabel
from factory.services import runner
from factory.services.appraisal_passes import appraisal_progress
from factory.services.context import Project
from factory.services.extraction import require_schema, unit_states
from factory.services.fulltext_screening import fulltext_queue
from factory.services.ideas import confirmed_ideas
from factory.services.interpretations import intuition_pending
from factory.services.mining import miner_listing
from factory.services.protocol import current_protocol
from factory.services.work_queue import QueueItem

_LOG: Final = logging.getLogger(__name__)

CellState = str
"""`done`, `pending`, `n/a` or `stopped`."""

_PENDING_STATES: Final = ("queued", "open", "stale")

_ORDER: Final = ("screen", "extract", "appraise", "contributions", "intuition")
"""The fixed stages in pipeline order; the miner stages go after `extract`."""

_LABELS: Final = {
    "screen": "Screening",
    "extract": "Extraction",
    "appraise": "Appraisal",
    "contributions": "Contributions",
    "intuition": "Intuition",
}


class PipelineStage(StrictModel):
    """One stage of the pipeline: how to run it, how much is pending and whether it applies."""

    key: str
    label: str
    skill: str
    role: str
    model: str
    tools: tuple[str, ...]
    pending: int
    applies: bool
    reason: str
    """Why the stage applies or not, in plain words."""


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _ready(project: Project) -> bool:
    protocol = current_protocol(project)
    return protocol is not None and protocol.status is ProtocolStatus.READY


def _converted(project: Project) -> frozenset[str]:
    return frozenset(e.work_id for e in fulltext_queue(project).eligible)


def _scope_pending(project: Project, scope: ScopeKey, converted: frozenset[str]) -> int:
    return sum(
        1
        for s in unit_states(project, scope=scope)
        if s.pass_label is PassLabel.A and s.state in _PENDING_STATES and s.work_id in converted
    )


def unit_pending(project: Project, key: str) -> int | None:
    """The pass A units of `key` from the unit states, or None for `screen`, whose pending
    units are the open screening tasks only."""
    if key == "screen":
        return None
    if key == "appraise":
        progress = appraisal_progress(project)
        return 0 if progress is None else sum(1 for done in progress.values() if not done)
    if key == "intuition":
        return intuition_pending(project)
    if key.startswith(runner.MINE_PREFIX):
        return _scope_pending(
            project, MinerScope(key[len(runner.MINE_PREFIX) :]), _converted(project)
        )
    scope = Scope.CONTRIBUTION if key == "contributions" else Scope.EVIDENCE
    return _scope_pending(project, scope, _converted(project))


def stage_pending(project: Project, key: str) -> int:
    """The pending units of stage `key` (pass A); 0 for a stage that does not apply."""
    return sum(runner.pending_units(project, key).values())


def _applies(project: Project, key: str) -> tuple[bool, str]:
    """Whether `key` applies to the project, and why or why not."""
    if key == "screen":
        return (True, "the protocol is ready") if _ready(project) else (False, "no ready protocol")
    if key == "intuition":
        found = bool(confirmed_ideas(project))
        return (True, "confirmed ideas exist") if found else (False, "no confirmed idea")
    if key == "appraise":
        progress = appraisal_progress(project)
        if progress is None:
            return False, "the protocol declares no appraisal instrument"
        return True, "the protocol declares an appraisal instrument"
    scope = Scope.CONTRIBUTION if key == "contributions" else Scope.EVIDENCE
    try:
        require_schema(project, scope=scope)
    except FactoryValidationError as exc:
        return False, "; ".join(i.reason for i in exc.issues)
    return True, "the protocol declares the schema"


def _stage(project: Project, key: str, applies: bool, reason: str) -> PipelineStage:
    spec = runner.STAGES.get(key, runner.MINE_SPEC)
    count = stage_pending(project, key) if applies else 0
    label = _LABELS.get(key, f"Miner {key[len(runner.MINE_PREFIX) :]}")
    return PipelineStage(
        key=key,
        label=label,
        skill=spec.skill,
        role=spec.role,
        model=spec.model,
        tools=spec.tools,
        pending=count,
        applies=applies,
        reason=reason,
    )


def _miner_stages(project: Project) -> list[tuple[str, bool, str]]:
    """One `(key, applies, reason)` per registered miner name, by name: the version listed in the
    protocol applies when its calibration has passed or the protocol declares the use exploratory
    (a protocol amendment with a reason; IDEA-69); a listed version otherwise does not apply (the
    runner would refuse it), so a pipeline skips it instead of stopping there. Unlisted: not
    applicable."""
    from factory.services.miners import MinerState, miner_state  # miners imports the mining stack
    from factory.services.mining import use_is_exploratory
    from factory.services.validation_profile import miner_use_refusal

    protocol = current_protocol(project)
    uses = (protocol.spec.miners or ()) if protocol is not None else ()
    listed_evidence = {u.name: u.evidence for u in uses}
    names: set[str] = set()
    listed: dict[str, int] = {}
    for entry in miner_listing(project):
        names.add(entry.name)
        if entry.listed:
            listed[entry.name] = entry.version
    plan: list[tuple[str, bool, str]] = []
    for name in sorted(names):
        key = f"{runner.MINE_PREFIX}{name}"
        version = listed.get(name)
        if version is None:
            plan.append((key, False, "the miner is not listed in the protocol"))
            continue
        refusal = miner_use_refusal(project, evidence=listed_evidence.get(name, False))
        if refusal is not None:
            plan.append((key, False, refusal))
            continue
        state = miner_state(project, name, version)
        if state is MinerState.CALIBRATED:
            plan.append((key, True, "the protocol lists the miner"))
        elif use_is_exploratory(project, name, version):
            plan.append((key, True, "the protocol declares the miner use exploratory"))
        else:
            plan.append(
                (
                    key,
                    False,
                    f"version {version} has no passed calibration (state: {state.value}); "
                    "calibrate it, or have the researcher amend the protocol to declare the use "
                    "exploratory",
                )
            )
    return plan


def stages(project: Project) -> list[PipelineStage]:
    """Every stage of the pipeline in order with its pending count and whether it applies. A
    stage that does not apply has pending 0 and the reason. Read-only."""
    project.index.sync()
    plan: list[tuple[str, bool, str]] = []
    for key in _ORDER:
        plan.append((key, *_applies(project, key)))
        if key == "extract":
            plan.extend(_miner_stages(project))
    return [_stage(project, *row) for row in plan]


def pending_by_stage(project: Project) -> dict[str, int]:
    """The pending units of every applicable stage, by stage key."""
    return {s.key: s.pending for s in stages(project) if s.applies}


# --- Per-paper progress ---


def paper_progress(
    project: Project, items: Sequence[QueueItem], plan: Sequence[PipelineStage]
) -> dict[str, dict[str, CellState]]:
    """For each added paper (by entry id) a cell per applicable stage that has a per-paper reading
    (`intuition` is read per idea, not per paper, and is left out): `done`, `pending`, `n/a` (the
    work has no unit in the stage) or `stopped` (the paper's path has ended). Read-only."""
    keys = [s.key for s in plan if s.applies and s.key != "intuition"]
    by_work: dict[str, dict[str, bool]] = {}
    for key in keys:
        if key == "screen":
            continue
        if key == "appraise":
            by_work[key] = appraisal_progress(project) or {}
        elif key.startswith(runner.MINE_PREFIX):
            by_work[key] = _unit_done(project, MinerScope(key[len(runner.MINE_PREFIX) :]))
        else:
            by_work[key] = _unit_done(
                project, Scope.CONTRIBUTION if key == "contributions" else Scope.EVIDENCE
            )
    out: dict[str, dict[str, CellState]] = {}
    for item in items:
        cells: dict[str, CellState] = {}
        for key in keys:
            cells[key] = _cell(item, key, by_work.get(key, {}))
        out[item.entry_id] = cells
    return out


def _unit_done(project: Project, scope: ScopeKey) -> dict[str, bool]:
    return {
        s.work_id: s.state == "current"
        for s in unit_states(project, scope=scope)
        if s.pass_label is PassLabel.A
    }


def _cell(item: QueueItem, key: str, done: dict[str, bool]) -> CellState:
    if key == "screen":
        if item.stage in ("added", "lookup-failed", "in-corpus"):
            return "stopped" if item.stopped else "pending"
        return "done"
    if item.stopped:
        return "stopped"
    if item.stage not in ("converted", "extracted") or item.work_id is None:
        return "pending"
    state = done.get(item.work_id)
    if state is None:
        return "n/a"
    return "done" if state else "pending"


# --- Running ---


_LOCK_NAME: Final = ".pipeline.lock"
_THREADS: dict[str, threading.Thread] = {}


def _lock_path(project: Project) -> str:
    runs = project.paths.dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return str(runs / _LOCK_NAME)


def pipeline_active(project: Project) -> bool:
    """Whether a pipeline of the project is open: a `runner.pipeline_started` with no
    `runner.pipeline_finished` whose process still holds the pipeline lock, or is this process.
    Reads the lock without taking it, so that it never makes a concurrent `begin_pipeline` fail:
    the open pipeline row decides, and the lock only tells a live pipeline from an orphan."""
    if not _open_pipelines(project):
        return False
    probe = os.open(_lock_path(project), os.O_RDONLY | os.O_CREAT)
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True  # an exclusive holder: a pipeline is running
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False
    finally:
        os.close(probe)


def _acquire(project: Project) -> IO[str]:
    handle = open(_lock_path(project), "a")  # noqa: SIM115 - held until the pipeline ends
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise _refuse("pipeline", "a pipeline of this project is already running") from None
    return handle


def _release(handle: IO[str]) -> None:
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _open_pipelines(project: Project) -> list[str]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT pipeline_id FROM runner_pipelines WHERE outcome IS NULL "
                "ORDER BY started_event_id"
            )
        ).all()
    return [str(r[0]) for r in rows]


def _record_finish(
    project: Project,
    pipeline_id: str,
    outcome: PipelineOutcome,
    run_ids: Sequence[str],
    stopped_at: str | None = None,
    reason: str | None = None,
) -> None:
    payload = PipelineFinished(
        pipeline_id=pipeline_id,
        outcome=outcome,
        run_ids=tuple(run_ids),
        stopped_at=stopped_at,
        reason=reason,
    )
    with project.writing():  # mint under the lock: append order is ID order (slice 5 ruling 3)
        project.record(
            [project.events.make("runner.pipeline_finished", payload, project.system_actor())]
        )


@dataclass(frozen=True)
class PipelinePlan:
    """A pipeline begun: its id, the lock it holds and the stages it will go through."""

    pipeline_id: str
    keys: tuple[str, ...]
    unit_cap: int
    lock: IO[str]


def _known_pipeline(project: Project, pipeline_id: str) -> bool:
    project.index.sync()
    with project.index.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM runner_pipelines WHERE pipeline_id = :p"), {"p": pipeline_id}
            ).first()
            is not None
        )


def begin_pipeline(
    project: Project,
    *,
    unit_cap: int = runner.DEFAULT_UNIT_CAP,
    from_stage: str | None = None,
    resumes: str | None = None,
) -> PipelinePlan:
    """Check that a pipeline can start and record `runner.pipeline_started`.

    Refuses, with nothing written, when `claude` is not on PATH, the cap is not 1..MAX_UNIT_CAP, a
    pipeline or a run is open, or no stage has pending work. A pipeline row left open by a process
    that is gone is closed as `lost` first. The returned plan holds the pipeline lock; the caller
    must pass it to `execute_pipeline`, which releases it. `from_stage` drops the planned stages
    before it (it must be an applicable stage); `resumes` names the earlier pipeline this one
    resumes (it must be a pipeline of this project)."""
    if not 1 <= unit_cap <= runner.MAX_UNIT_CAP:
        raise _refuse("unit_cap", f"must be between 1 and {runner.MAX_UNIT_CAP}")
    if runner.claude_path() is None:
        raise _refuse(
            "claude",
            "the `claude` executable is not on PATH; install Claude Code and log in, then retry",
        )
    if resumes is not None and not _known_pipeline(project, resumes):
        raise _refuse("resumes", f"{resumes} is not a pipeline of this project")
    handle = _acquire(project)
    try:
        for orphan in _open_pipelines(project):
            _record_finish(project, orphan, "lost", (), reason="the process that ran it ended")
        runner.finish_lost(project)
        if runner.has_open_run(project):
            raise _refuse("run", "a run of this project is already open; wait for it to finish")
        planned = [s for s in stages(project) if s.applies]
        if from_stage is not None:
            keys = [s.key for s in planned]
            if from_stage not in keys:
                raise _refuse("from_stage", f"{from_stage!r} is not an applicable stage")
            planned = planned[keys.index(from_stage) :]
        if not planned:
            raise _refuse("pipeline", "no stage applies to this project")
        before = {s.key: s.pending for s in planned}
        pipeline_id = project.ids.new("rpl")
        started = PipelineStarted(
            pipeline_id=pipeline_id,
            stages=tuple(s.key for s in planned),
            unit_cap=unit_cap,
            counts_before=before,
            resumes=resumes,
        )
        with project.writing():  # mint under the lock (slice 5 ruling 3)
            project.record(
                [project.events.make("runner.pipeline_started", started, project.system_actor())]
            )
    except BaseException:
        _release(handle)
        raise
    return PipelinePlan(pipeline_id, tuple(s.key for s in planned), unit_cap, handle)


def automatic_steps(
    project: Project,
    *,
    unit_cap: int = runner.DEFAULT_UNIT_CAP,
    failed: set[str] | None = None,
) -> None:
    """The deterministic steps between stages: `work_queue.advance` for the added papers and
    `extract_references`, one work at a time, for the included works with a conversion and no
    current reference extraction, at most `unit_cap` works per call in work id order. A work
    whose extraction raises is logged and skipped, and added to `failed` (one set per pipeline)
    so that it is not tried again in the same pipeline. An exception never stops the pipeline."""
    from factory.services.document_read import default_conversion
    from factory.services.references import (
        current_extraction,
        extract_references,
        included_works,
    )
    from factory.sources.registry import lookup_sources

    runner.advance_after(project)
    skip = failed if failed is not None else set()
    try:
        project.index.sync()
        todo = [
            w
            for w in sorted(included_works(project))
            if w not in skip
            and default_conversion(project, w) is not None
            and current_extraction(project, w) is None
        ][:unit_cap]
    except Exception:
        _LOG.exception(
            "listing the works for reference extraction failed for %s", project.paths.slug
        )
        return
    sources = dict(lookup_sources())
    for work in todo:
        try:
            extract_references(project, project.system_actor(), [work], sources=sources)
        except Exception:
            skip.add(work)
            _LOG.exception("the reference extraction of %s failed; skipped", work)


def execute_pipeline(
    project: Project, plan: PipelinePlan, *, launcher: runner.Launcher | None = None
) -> str:
    """Run the stages of `plan` in order and record `runner.pipeline_finished`; returns the
    pipeline id. Releases the pipeline lock at the end, whatever happens."""
    run_ids: list[str] = []
    failed: set[str] = set()
    outcome: PipelineOutcome = "idle"
    stopped_at: str | None = None
    reason: str | None = None
    try:
        automatic_steps(project, unit_cap=plan.unit_cap, failed=failed)
        for key in plan.keys:
            if stage_pending(project, key) == 0:
                continue
            try:
                run_id = runner.start_run(
                    project, key, unit_cap=plan.unit_cap, launcher=launcher, pipeline=True
                )
            except FactoryValidationError as exc:
                outcome, stopped_at = "failed", key
                reason = "; ".join(f"{i.field}: {i.reason}" for i in exc.issues)
                break
            run_ids.append(run_id)
            limit = runner.run_time_limit(plan.unit_cap)
            if not runner.wait_until_closed(project, run_id, limit=limit):
                outcome, stopped_at = "failed", key
                reason = f"timeout: the run {run_id} passed its {limit:.0f} s limit and was killed"
                break
            result = runner.run_outcome(project, run_id)
            if result != "complete":
                outcome = "lost" if result == "lost" else "failed"
                stopped_at = key
                reason = f"the run {run_id} ended {result or 'without a record'}"
                break
            outcome = "complete"
            automatic_steps(project, unit_cap=plan.unit_cap, failed=failed)
    except BaseException as exc:
        outcome, reason = "failed", f"{type(exc).__name__}: {exc}"
        _LOG.exception("pipeline %s failed", plan.pipeline_id)
        if not isinstance(exc, Exception):
            raise
    finally:
        try:
            _record_finish(project, plan.pipeline_id, outcome, run_ids, stopped_at, reason)
        finally:
            _release(plan.lock)
    return plan.pipeline_id


def run_pipeline(
    project: Project,
    *,
    unit_cap: int = runner.DEFAULT_UNIT_CAP,
    launcher: runner.Launcher | None = None,
    from_stage: str | None = None,
    resumes: str | None = None,
) -> str:
    """Process all in the foreground: begin, run every stage with pending work, record the end;
    returns the pipeline id. Refusals are `FactoryValidationError`, nothing written."""
    plan = begin_pipeline(project, unit_cap=unit_cap, from_stage=from_stage, resumes=resumes)
    return execute_pipeline(project, plan, launcher=launcher)


def start_pipeline(
    project: Project,
    *,
    unit_cap: int = runner.DEFAULT_UNIT_CAP,
    launcher: runner.Launcher | None = None,
    from_stage: str | None = None,
    resumes: str | None = None,
) -> str:
    """Process all in a background daemon thread (the hub): the checks and `pipeline_started`
    happen now, the stages in the thread; returns the pipeline id."""
    plan = begin_pipeline(project, unit_cap=unit_cap, from_stage=from_stage, resumes=resumes)
    thread = threading.Thread(
        target=execute_pipeline,
        args=(project, plan),
        kwargs={"launcher": launcher},
        name=plan.pipeline_id,
        daemon=True,
    )
    _THREADS[plan.pipeline_id] = thread
    try:
        thread.start()
    except BaseException:
        _THREADS.pop(plan.pipeline_id, None)
        _record_finish(project, plan.pipeline_id, "failed", (), reason="the thread did not start")
        _release(plan.lock)
        raise
    return plan.pipeline_id


def wait(pipeline_id: str, timeout: float | None = None) -> bool:
    """Block until the pipeline thread (started by this process) ends. False on timeout or when
    this process did not start it."""
    thread = _THREADS.get(pipeline_id)
    if thread is None:
        return False
    thread.join(timeout)
    return not thread.is_alive()


class PipelineView(StrictModel):
    pipeline_id: str
    started_at: str
    stages: list[str]
    unit_cap: int
    counts_before: dict[str, int]
    status: str
    """`running`, or the outcome: `complete`, `failed`, `lost`, `idle`."""
    run_ids: list[str] = Field(default_factory=list)
    stopped_at: str | None = None
    reason: str | None = None


def pipeline_status(project: Project, *, limit: int = 5) -> list[PipelineView]:
    """The most recent pipelines, newest first. Read-only (an orphaned open pipeline shows as
    `running` until the next start closes it)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.pipeline_id, ev.ts, p.stages, p.unit_cap, p.counts_before, p.outcome, "
                "p.run_ids, p.stopped_at, p.reason FROM runner_pipelines p "
                "JOIN events ev ON ev.id = p.started_event_id "
                "ORDER BY p.started_event_id DESC LIMIT :n"
            ),
            {"n": limit},
        ).all()
    return [
        PipelineView(
            pipeline_id=str(r[0]),
            started_at=str(r[1]),
            stages=list(json.loads(str(r[2]))),
            unit_cap=int(r[3]),
            counts_before=json.loads(str(r[4])),
            status="running" if r[5] is None else str(r[5]),
            run_ids=[] if r[6] is None else list(json.loads(str(r[6]))),
            stopped_at=None if r[7] is None else str(r[7]),
            reason=None if r[8] is None else str(r[8]),
        )
        for r in rows
    ]
