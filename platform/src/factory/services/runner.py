"""The headless runner (plan feed-hub H5, decision 118 item 4): Process now.

The platform starts the `claude` executable the researcher installed, as an outside process
(`claude -p`, a strict MCP config naming this factory, an allow-list of the stage's tools, one
declared model per stage, a cap on units). It holds no key, imports no model SDK and calls no model
API; every judgement is written by that process through MCP with its own provenance.

Invariants:
- One open run per project. A run is open from `runner.started` until `runner.finished`. An open
  run whose process is gone (dead pid, or no pid kept) and that no watcher of this process is
  waiting on is closed as `lost` before anything else (`finish_lost`).
- `start_run` refuses, with nothing written, when `claude` is not on PATH, when a run is open,
  when the stage has no pending unit, when the cap is not 1..MAX_UNIT_CAP, or when the skill is not
  installed. A refusal is one `FactoryValidationError`.
- Both events are written as the system actor. The prompt text is stored as a blob and never put
  in the recorded command (the command names `prompt.txt` instead); the MCP config carries only
  the root, plugin dir, PYTHONPATH and ranker model paths, never a secret.
- A daemon watcher thread records `runner.finished` when the process exits: `complete` for exit
  status 0, otherwise `failed`. Once that is recorded the same thread runs the deterministic steps
  (`work_queue.advance`, H6); an exception there is logged and never reaches the run. Started from
  the CLI without waiting, the process may outlive this one; its end is then recorded by the next
  reconcile (`finish_lost`): from the exit status that the launch wrapper (`sh -c`) wrote to the
  `exit` file (`complete` or `failed`), `lost` only when there is none; the same steps follow.
- The child may use only the stage's factory tools: the built-in tools are disallowed, permission
  mode is `dontAsk`, and it runs with the run folder as working directory.
- Run bookkeeping is serialised across processes by `flock` on `runs/.lock`. A `starting` marker
  younger than 60 s without a pid keeps a run alive for other processes.
- The run folder `projects/<slug>/runs/<run_id>/` holds `prompt.txt`, `mcp.json`, `starting`,
  `pid`, `exit` and `log.jsonl`; it is evidence, not state: the events are the record.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from pydantic import JsonValue
from sqlalchemy import text

import factory
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.model.runner import RunnerFinished, RunnerOutcome, RunnerStage, RunnerStarted
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.stages import EXTRACT_KINDS, task_kind
from factory.services.work_queue import advance, pending_work
from factory.sources.fulltext.registry import default_routes
from factory.sources.registry import default_sources

MAX_UNIT_CAP: Final = 200
DEFAULT_UNIT_CAP: Final = 25
_RECENT: Final = 10
_PROMPT_PLACEHOLDER: Final = "<prompt: see prompt.txt in the run folder>"
STARTING_GRACE: Final = 60.0
"""Seconds a `starting` marker without a pid keeps a run alive (another process is launching it)."""
_RETRY_PAUSE: Final = 1.0
BUILTIN_TOOLS: Final = (
    "Bash",
    "Edit",
    "Write",
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
    "NotebookEdit",
)
"""The built-in tools the child is denied: it may use only the factory tools of its stage."""
_WRAPPER: Final = 'EXIT="$1"; shift; "$@"; echo $? > "$EXIT"'


@dataclass(frozen=True)
class StageSpec:
    model: str
    skill: str
    role: str
    tools: tuple[str, ...]
    kinds: tuple[str, ...]
    """The task kinds whose pending units the stage works on (pass A)."""


STAGES: Final[dict[str, StageSpec]] = {
    "screen": StageSpec(
        model="claude-haiku-5-5",
        skill="rf-screen",
        role="screener",
        tools=("mcp__factory__screen_next", "mcp__factory__screen_record"),
        kinds=(
            task_kind(ScreeningStage.TITLE_ABSTRACT, PassLabel.A),
            task_kind(ScreeningStage.FULL_TEXT, PassLabel.A),
        ),
    ),
    "extract": StageSpec(
        model="claude-sonnet-5-5",
        skill="rf-extract",
        role="extractor",
        tools=(
            "mcp__factory__extract_next",
            "mcp__factory__extract_record",
            "mcp__factory__document_read",
        ),
        kinds=(EXTRACT_KINDS[PassLabel.A],),
    ),
}


class Process(Protocol):
    pid: int

    def wait(self) -> int: ...


Launcher = Callable[[Sequence[str], Path], Process]
"""`launcher(argv, log_path)` starts the process with stdout and stderr into `log_path`."""


def default_launcher(argv: Sequence[str], log_path: Path) -> Process:
    """Start `argv` detached from this terminal: stdin from /dev/null, a new session, working
    directory the run folder (the folder of `log_path`)."""
    with log_path.open("wb") as log:
        return subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=log_path.parent,
        )


def claude_path() -> str | None:
    """The `claude` executable on PATH, or None."""
    return shutil.which("claude")


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _factory_executable() -> str:
    sibling = Path(sys.executable).parent / "factory"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("factory")
    if found is None:
        raise _refuse("factory", "no `factory` executable beside this Python or on PATH")
    return found


def _stage(stage: str) -> StageSpec:
    spec = STAGES.get(stage)
    if spec is None:
        raise _refuse("stage", "must be one of " + ", ".join(STAGES))
    return spec


def _skill_text(project: Project, skill: str) -> str:
    path = project.settings.plugin_dir / "skills" / skill / "SKILL.md"
    if not path.is_file():
        raise _refuse("skill", f"no installed skill {skill!r} under {project.settings.plugin_dir}")
    return path.read_text(encoding="utf-8")


def _prompt(project: Project, stage: str, spec: StageSpec, unit_cap: int) -> str:
    slug = project.paths.slug
    return (
        f"You are pass A of stage `{stage}` for the Research Factory project `{slug}`. "
        "Work through the factory MCP tools and follow exactly the skill below "
        "(you are pass `A`).\n\n"
        f"Parameters for every factory call: project `{slug}`, pass_label `A`, "
        f"role `{spec.role}`, "
        f"model `{spec.model}`, skill `{spec.skill}`.\n\n"
        f"Limit: stop after {unit_cap} units or when the queue is empty, whichever comes first. "
        "A unit is one record screened or one work extracted. Use no other tools. Finally print "
        "how many units you handled and any `blocked` text or error verbatim.\n\n"
        f"=== SKILL {spec.skill} ===\n{_skill_text(project, spec.skill)}"
    )


def mcp_config(project: Project) -> dict[str, JsonValue]:
    """The strict MCP config: this factory, with the root, plugin dir, PYTHONPATH and ranker
    model (when set) as its only environment."""
    env: dict[str, JsonValue] = {
        "PYTHONPATH": os.environ.get("PYTHONPATH") or str(Path(factory.__file__).parents[1]),
        "FACTORY_PLUGIN_DIR": str(project.settings.plugin_dir),
        "FACTORY_ROOT": str(project.settings.root),
    }
    ranker = os.environ.get("FACTORY_RANKER_MODEL")
    if ranker:
        env["FACTORY_RANKER_MODEL"] = ranker
    return {
        "mcpServers": {"factory": {"command": _factory_executable(), "args": ["serve"], "env": env}}
    }


def build_command(
    project: Project,
    stage: str,
    unit_cap: int = DEFAULT_UNIT_CAP,
    *,
    mcp_path: Path = Path("mcp.json"),
    claude: str = "claude",
) -> tuple[list[str], dict[str, JsonValue], str]:
    """`(argv, mcp config, prompt)` for one run of `stage`. Pure: starts and writes nothing."""
    spec = _stage(stage)
    if not 1 <= unit_cap <= MAX_UNIT_CAP:
        raise _refuse("unit_cap", f"must be between 1 and {MAX_UNIT_CAP}")
    prompt = _prompt(project, stage, spec, unit_cap)
    argv = [
        claude,
        "-p",
        prompt,
        "--model",
        spec.model,
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_path),
        "--allowedTools",
        *spec.tools,
        "--disallowedTools",
        *BUILTIN_TOOLS,
        "--permission-mode",
        "dontAsk",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    return argv, mcp_config(project), prompt


def pending_units(project: Project, stage: str) -> dict[str, int]:
    """The pending units per task kind of `stage` (pass A)."""
    pending = pending_work(project)
    return {kind: pending.get(kind, 0) for kind in _stage(stage).kinds}


def _run_dir(project: Project, run_id: str) -> Path:
    return project.paths.dir / "runs" / run_id


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(folder: Path) -> int | None:
    try:
        return int((folder / "pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


_LOCK = threading.RLock()
_FLOCK_DEPTH = 0


@contextmanager
def _runs_lock(project: Project) -> Iterator[None]:
    """Serialise run bookkeeping across threads (`_LOCK`) and processes (`flock` on
    `runs/.lock`). Re-entrant: only the outermost entry takes the file lock."""
    global _FLOCK_DEPTH
    with _LOCK:
        if _FLOCK_DEPTH > 0:
            _FLOCK_DEPTH += 1
            try:
                yield
            finally:
                _FLOCK_DEPTH -= 1
            return
        runs = project.paths.dir / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        with (runs / ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            _FLOCK_DEPTH = 1
            try:
                yield
            finally:
                _FLOCK_DEPTH = 0
                fcntl.flock(handle, fcntl.LOCK_UN)


_WATCHING: set[tuple[str, str]] = set()
_THREADS: dict[str, threading.Thread] = {}


class RunView(StrictModel):
    run_id: str
    stage: str
    model: str
    unit_cap: int
    started_at: str
    status: str
    """`running`, `lost?` (open, process gone, not yet reconciled), `complete`, `failed`, `lost`."""
    exit_status: int | None
    counts_before: dict[str, int]
    counts_after: dict[str, int] | None


def _rows(project: Project, where: str = "") -> list[tuple[str, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT r.run_id, r.stage, r.model, r.unit_cap, ev.ts, r.outcome, "
                    "r.exit_status, r.counts_before, r.counts_after FROM runner_runs r "
                    "JOIN events ev ON ev.id = r.started_event_id "
                    f"{where} ORDER BY r.started_event_id DESC"
                )
            ).all()
        ]


def _open_run_ids(project: Project) -> list[str]:
    return [str(r[0]) for r in _rows(project, "WHERE r.outcome IS NULL")]


def _starting(folder: Path) -> bool:
    """True when a `starting` marker younger than STARTING_GRACE says a launch is under way."""
    try:
        return time.time() - (folder / "starting").stat().st_mtime < STARTING_GRACE
    except OSError:
        return False


def _read_exit(folder: Path) -> int | None:
    """The exit status the launch wrapper recorded, or None when absent or incomplete."""
    try:
        return int((folder / "exit").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _is_gone(project: Project, run_id: str) -> bool:
    if (str(project.paths.root), run_id) in _WATCHING:
        return False
    folder = _run_dir(project, run_id)
    pid = _read_pid(folder)
    if pid is None:
        return not _starting(folder)
    return not _pid_alive(pid)


def _log_blob(project: Project, folder: Path) -> str:
    try:
        data = (folder / "log.jsonl").read_bytes()
    except OSError:
        data = b""
    return project.blobs.put(data)


def _finish(
    project: Project,
    run_id: str,
    stage: str,
    outcome: RunnerOutcome,
    exit_status: int | None,
) -> None:
    folder = _run_dir(project, run_id)
    payload = RunnerFinished(
        run_id=run_id,
        exit_status=exit_status,
        outcome=outcome,
        log_blob=_log_blob(project, folder),
        counts_after=pending_units(project, stage),
    )
    with _runs_lock(project):
        if run_id not in _open_run_ids(project):
            return
        project.record([project.events.make("runner.finished", payload, project.system_actor())])


def finish_lost(project: Project, *, advance_after: bool = True) -> list[str]:
    """Close each open run whose process is gone. With the exit status the launch wrapper left in
    the run folder the run is `complete` (0) or `failed`; without it, `lost`. Returns the run ids
    closed. When `advance_after` and a run was closed, the deterministic steps run afterwards
    (outside the lock), as the watcher does."""
    closed: list[str] = []
    with _runs_lock(project):
        for row in _rows(project, "WHERE r.outcome IS NULL"):
            run_id = str(row[0])
            if not _is_gone(project, run_id):
                continue
            code = _read_exit(_run_dir(project, run_id))
            outcome: RunnerOutcome = (
                "lost" if code is None else ("complete" if code == 0 else "failed")
            )
            _finish(project, run_id, str(row[1]), outcome, code)
            closed.append(run_id)
    if closed and advance_after:
        _advance_after(project)
    return closed


_LOG: Final = logging.getLogger(__name__)


def _watch(project: Project, run_id: str, stage: str, process: Process) -> None:
    try:
        code = process.wait()
    except OSError:
        code = None
    recorded = False
    try:
        for attempt in (1, 2):
            try:
                _finish(project, run_id, stage, "complete" if code == 0 else "failed", code)
                recorded = True
                break
            except Exception:
                _LOG.exception("recording the end of run %s failed (attempt %d)", run_id, attempt)
                if attempt == 1:
                    time.sleep(_RETRY_PAUSE)
    finally:
        _WATCHING.discard((str(project.paths.root), run_id))
    if recorded:
        _advance_after(project)


def _advance_after(project: Project) -> None:
    """The deterministic steps for the added papers, after a run has been recorded (H6). Any
    exception is logged: the run is already closed and the steps are retried by the next call."""
    try:
        advance(project, sources=dict(default_sources()), fetchers=default_routes(project.settings))
    except Exception:
        _LOG.exception("the automatic steps after run %s failed", project.paths.slug)


def start_run(
    project: Project,
    stage: str,
    *,
    unit_cap: int = DEFAULT_UNIT_CAP,
    launcher: Launcher | None = None,
) -> str:
    """Start one run of `stage`; returns its `run_id` once the process is started and recorded."""
    spec = _stage(stage)
    if not 1 <= unit_cap <= MAX_UNIT_CAP:
        raise _refuse("unit_cap", f"must be between 1 and {MAX_UNIT_CAP}")
    claude = claude_path()
    if claude is None:
        raise _refuse(
            "claude",
            "the `claude` executable is not on PATH; install Claude Code and log in, then retry",
        )
    finish_lost(project)
    with _runs_lock(project):
        finish_lost(project, advance_after=False)
        if _open_run_ids(project):
            raise _refuse("run", "a run of this project is already open; wait for it to finish")
        counts = pending_units(project, stage)
        if sum(counts.values()) == 0:
            raise _refuse("stage", f"no pending unit for stage {stage!r}")
        run_id = project.ids.new("rnr")
        folder = _run_dir(project, run_id)
        mcp_path = folder / "mcp.json"
        argv, config, prompt = build_command(
            project, stage, unit_cap, mcp_path=mcp_path, claude=claude
        )
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "starting").write_text(str(time.time()), encoding="utf-8")
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        mcp_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
        recorded = [_PROMPT_PLACEHOLDER if part == prompt else part for part in argv]
        started = RunnerStarted(
            run_id=run_id,
            stage=_as_stage(stage),
            model=spec.model,
            allowed_tools=spec.tools,
            prompt_blob=project.blobs.put(prompt.encode("utf-8")),
            unit_cap=unit_cap,
            counts_before=counts,
            command=tuple(recorded),
        )
        project.record([project.events.make("runner.started", started, project.system_actor())])
        launch = launcher or default_launcher
        try:
            wrapped = ["sh", "-c", _WRAPPER, "sh", str(folder / "exit"), *argv]
            process = launch(wrapped, folder / "log.jsonl")
        except OSError as exc:
            _finish(project, run_id, stage, "failed", None)
            raise _refuse("claude", f"could not start `claude`: {exc}") from exc
        (folder / "pid").write_text(str(process.pid), encoding="utf-8")
        _WATCHING.add((str(project.paths.root), run_id))
        thread = threading.Thread(
            target=_watch, args=(project, run_id, stage, process), name=run_id, daemon=True
        )
        _THREADS[run_id] = thread
        thread.start()
    return run_id


def _as_stage(stage: str) -> RunnerStage:
    if stage == "screen":
        return "screen"
    return "extract"


def wait(run_id: str, timeout: float | None = None) -> bool:
    """Block until the watcher of `run_id` (started by this process) has recorded the end.
    False on timeout or when this process does not watch the run."""
    thread = _THREADS.get(run_id)
    if thread is None:
        return False
    thread.join(timeout)
    return not thread.is_alive()


def run_status(project: Project, *, reconcile: bool = True, limit: int = _RECENT) -> list[RunView]:
    """The open run and the most recent runs, newest first. `reconcile=False` writes nothing: an
    open run whose process is gone is then shown as `lost?`."""
    if reconcile:
        finish_lost(project)
    views: list[RunView] = []
    for row in _rows(project)[:limit]:
        run_id, stage, model, cap, started_at, outcome, exit_status, before, after = row
        status = str(outcome) if outcome is not None else "running"
        if outcome is None and _is_gone(project, str(run_id)):
            status = "lost?"
        views.append(
            RunView(
                run_id=str(run_id),
                stage=str(stage),
                model=str(model),
                unit_cap=int(cap),
                started_at=str(started_at),
                status=status,
                exit_status=None if exit_status is None else int(exit_status),
                counts_before=json.loads(str(before)),
                counts_after=None if after is None else json.loads(str(after)),
            )
        )
    return views
