"""The headless runner (plan feed-hub H5, decision 119 item 4): Process now.

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
- The stage `mining` (IDEA-50) is an alias, resolved when a run starts: it becomes `mine:<miner id>`
  of the first miner (by name) with an open mining need (`work_queue.mining_needs`: requested or
  layer-filtered works with no current unit), and that resolved key is what the events record.
  It uses the miner stage's declared model and tools (`mine_next`, `mine_record`, `document_read`
  and the two reads) and the same cap on units; refused when no miner has a need. The runner
  records no human act: requests and layer moves are the researcher's, made before the run.
- The stages `spar` and `ask` (spar-night N3) answer chat requests (`services/chat_requests.py`):
  skill `rf-chat`, one request per run (`StageSpec.fixed_cap`; a cap asked for is overridden),
  pending units are the open requests of the kind, and the run takes its request with
  `chat_request_next`. They are not pipeline stages. The runner records no human act: the request
  is the researcher's, made before the run.
- The stages `spar2-search`, `spar2-read`, `spar2-against`, `spar2-for`, `spar2-critic` and
  `spar2-cover` (spar-night N6) are the role runs of the agentic spar (`services/spar_v2.py`): skill
  `rf-spar-v2`, one unit per run, Sonnet. Each has its own allow-list that leaves out what the role
  must not do (no role rates, writes a balance or records a lead). They are started only by the
  coordinator (`spar_v2.advance`), which names the request and role (`RoleAssignment`); the start
  writes `spar.role_started` with `runner.started`. After a run ends, the watcher advances a begun
  v2 request to its next role; a failed role stops the chain.
- Stages: `screen`, `extract`, `appraise`, `contributions`, `intuition` and `mine:<miner id>`; the
  derivation of which apply and the pipeline over them are in `factory.services.pipeline`. The
  child's MCP config carries `FACTORY_UNIT_CAP` and `FACTORY_RUN_ID`: the MCP server then refuses
  the `*_next` tools with `cap-reached` once it has served that many units (`mcp.unit_cap`). A
  per-stage run is refused while a pipeline holds the project.
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
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol

from pydantic import JsonValue
from sqlalchemy import text

import factory
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.model.runner import RunnerFinished, RunnerOutcome, RunnerStage, RunnerStarted
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.stages import EXTRACT_KINDS, task_kind
from factory.services.work_queue import advance, mining_needs, pending_work
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
    """The task kinds whose pending units the stage works on (pass A). Empty for a stage whose
    pending units `factory.services.pipeline` counts from the unit states."""
    unit: str = "unit"
    """What one unit is, for the prompt (`record screened`, `work extracted`, ...)."""
    miner: str | None = None
    miner_version: int | None = None
    """For a `mine:<id>` stage: the miner and the version the protocol lists."""
    fixed_cap: int | None = None
    """When set, the stage's cap: a run serves exactly this many units whatever cap was asked
    (the chat stages serve one request per run)."""


STAGES: Final[dict[str, StageSpec]] = {
    "screen": StageSpec(
        model="claude-haiku-5-5",
        skill="rf-screen",
        role="screener",
        tools=(
            "mcp__factory__screen_next",
            "mcp__factory__screen_record",
            "mcp__factory__document_read",  # full-text screening reads the converted document
            "mcp__factory__project_status",  # optional read named by the skill
        ),
        kinds=(
            task_kind(ScreeningStage.TITLE_ABSTRACT, PassLabel.A),
            task_kind(ScreeningStage.FULL_TEXT, PassLabel.A),
        ),
        unit="record screened",
    ),
    "extract": StageSpec(
        model="claude-sonnet-5-5",
        skill="rf-extract",
        role="extractor",
        tools=(
            "mcp__factory__extract_next",
            "mcp__factory__extract_record",
            "mcp__factory__document_read",
            "mcp__factory__project_status",
        ),
        kinds=(EXTRACT_KINDS[PassLabel.A],),
        unit="work extracted",
    ),
    "appraise": StageSpec(
        model="claude-sonnet-5-5",
        skill="rf-appraise",
        role="appraiser",
        tools=(
            "mcp__factory__appraisal_next",
            "mcp__factory__appraisal_record",
            "mcp__factory__document_read",
            "mcp__factory__appraisal_status",
        ),
        kinds=(),
        unit="work appraised",
    ),
    "contributions": StageSpec(
        model="claude-sonnet-5-5",
        skill="rf-contributions",
        role="contributor",
        tools=(
            "mcp__factory__contribution_next",
            "mcp__factory__contribution_record",
            "mcp__factory__document_read",
            "mcp__factory__project_status",
        ),
        kinds=(),
        unit="work read for contributions",
    ),
    "intuition": StageSpec(
        model="claude-sonnet-5-5",
        skill="rf-intuition",
        role="interpreter",
        tools=(
            "mcp__factory__intuition_next",
            "mcp__factory__interpretation_record",
            "mcp__factory__interpretation_list",
            "mcp__factory__document_read",
        ),
        kinds=(),
        unit="target interpreted",
    ),
    "spar": StageSpec(
        model="claude-sonnet-5-5",
        skill="rf-chat",
        role="sparrer",
        tools=(
            "mcp__factory__selection_resolve",
            "mcp__factory__claims_digest",
            "mcp__factory__corpus_search",
            "mcp__factory__chat_sections",
            "mcp__factory__chat_verify",
            "mcp__factory__paper_profiles",
            "mcp__factory__chat_candidates",
            "mcp__factory__chat_request_next",
            "mcp__factory__chat_request_view",
            "mcp__factory__document_read",
            "mcp__factory__sheet_open",
            "mcp__factory__sheet_argue",
            "mcp__factory__sheet_close",
            "mcp__factory__sheet_view",
            "mcp__factory__answer_view",  # a follow-up reads its parent
        ),
        kinds=(),
        unit="spar request answered",
        fixed_cap=1,
    ),
    "ask": StageSpec(
        model="claude-sonnet-5-5",
        skill="rf-chat",
        role="asker",
        tools=(
            "mcp__factory__selection_resolve",
            "mcp__factory__claims_digest",
            "mcp__factory__corpus_search",
            "mcp__factory__chat_sections",
            "mcp__factory__chat_verify",
            "mcp__factory__paper_profiles",
            "mcp__factory__chat_candidates",
            "mcp__factory__chat_request_next",
            "mcp__factory__chat_request_view",
            "mcp__factory__document_read",
            "mcp__factory__answer_record",
            "mcp__factory__answer_view",
            "mcp__factory__sheet_view",  # a follow-up reads its parent
        ),
        kinds=(),
        unit="ask request answered",
        fixed_cap=1,
    ),
}
_P: Final = "mcp__factory__"
_SPAR2_READ: Final = (
    f"{_P}spar_role_next",
    f"{_P}chat_sections",
    f"{_P}chat_verify",
    f"{_P}document_read",
)
_SPAR2_WRITER: Final = (
    f"{_P}spar_role_next",
    f"{_P}spar_readings_view",
    f"{_P}claims_digest",
    f"{_P}chat_verify",
    f"{_P}document_read",
    f"{_P}sheet_argue",
    f"{_P}sheet_close",
)
STAGES.update(
    {
        "spar2-search": StageSpec(
            model="claude-sonnet-5-5",
            skill="rf-spar-v2",
            role="searcher",
            tools=(
                f"{_P}spar_role_next",
                f"{_P}selection_resolve",
                f"{_P}claims_digest",
                f"{_P}corpus_search",
                f"{_P}chat_candidates",
                f"{_P}paper_profiles",
                f"{_P}chat_sections",
                f"{_P}chat_verify",
                f"{_P}document_read",
                f"{_P}sheet_open",
                f"{_P}sheet_view",
            ),
            kinds=(),
            unit="candidate list recorded",
            fixed_cap=1,
        ),
        "spar2-read": StageSpec(
            model="claude-sonnet-5-5",
            skill="rf-spar-v2",
            role="reader",
            tools=(*_SPAR2_READ, f"{_P}spar_reading_record"),
            kinds=(),
            unit="paper read",
            fixed_cap=1,
        ),
        "spar2-against": StageSpec(
            model="claude-sonnet-5-5",
            skill="rf-spar-v2",
            role="writer-against",
            tools=_SPAR2_WRITER,
            kinds=(),
            unit="case against written",
            fixed_cap=1,
        ),
        "spar2-for": StageSpec(
            model="claude-sonnet-5-5",
            skill="rf-spar-v2",
            role="writer-for",
            tools=_SPAR2_WRITER,
            kinds=(),
            unit="case for written",
            fixed_cap=1,
        ),
        "spar2-critic": StageSpec(
            model="claude-sonnet-5-5",
            skill="rf-spar-v2",
            role="critic",
            tools=(*_SPAR2_READ, f"{_P}sheet_view", f"{_P}sheet_check"),
            kinds=(),
            unit="sheet checked",
            fixed_cap=1,
        ),
        "spar2-cover": StageSpec(
            model="claude-sonnet-5-5",
            skill="rf-spar-v2",
            role="coverage",
            tools=(
                f"{_P}spar_role_next",
                f"{_P}spar_readings_view",
                f"{_P}claims_digest",
                f"{_P}paper_profiles",
                f"{_P}chat_sections",
                f"{_P}document_read",
                f"{_P}sheet_view",
                f"{_P}spar_coverage_record",
            ),
            kinds=(),
            unit="coverage swept",
            fixed_cap=1,
        ),
    }
)
CHAT_STAGES: Final = ("spar", "ask")
"""The stages that answer chat requests (`services/chat_requests.py`): one request per run; their
pending units are the open requests of the stage's kind."""
SPAR2_PREFIX: Final = "spar2-"
SPAR2_STAGES: Final = tuple(k for k in STAGES if k.startswith(SPAR2_PREFIX))
"""The role stages of the agentic spar (`services/spar_v2.py`); their pending units are the v2
requests whose next role they are."""


@dataclass(frozen=True)
class RoleAssignment:
    """The request, role and paper (readers) a role run is started for."""

    request_id: str
    role: str
    work_id: str | None = None


MINE_PREFIX: Final = "mine:"
MINING_STAGE: Final = "mining"
"""The alias stage that runs the first miner with an open mining need (see the module docstring)."""
MINE_SPEC: Final = StageSpec(
    model="claude-haiku-5-5",
    skill="rf-mine",
    role="miner",
    tools=(
        "mcp__factory__mine_next",
        "mcp__factory__mine_record",
        "mcp__factory__document_read",
        "mcp__factory__mine_status",
        "mcp__factory__miner_list",
    ),
    kinds=(),
    unit="work mined",
)


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


def stage_keys() -> str:
    """The valid stage keys, for a refusal."""
    return ", ".join([*STAGES, MINING_STAGE, f"{MINE_PREFIX}<miner id>"])


def is_stage_key(stage: str) -> bool:
    """Whether `stage` names a stage: a fixed one or `mine:<miner id>` (the miner is looked up
    when the stage is used)."""
    return (
        stage in STAGES
        or stage == MINING_STAGE
        or (stage.startswith(MINE_PREFIX) and len(stage) > len(MINE_PREFIX))
    )


def resolve_stage(project: Project, stage: str) -> str:
    """`stage` itself, except that `mining` becomes `mine:<miner id>` of the first miner with an
    open mining need; refuses (`stage`) when no miner has one. Read-only."""
    if stage != MINING_STAGE:
        return stage
    needs = mining_needs(project)
    if not needs:
        raise _refuse("stage", "no miner has an open mining need (a request or a layer)")
    return f"{MINE_PREFIX}{sorted(needs)[0]}"


def _mine_use(project: Project, miner: str) -> int:
    """The version of `miner` the current protocol lists; refuses when none."""
    from factory.services.mining import miner_listing  # mining imports the extraction stack

    versions = [m.version for m in miner_listing(project) if m.name == miner and m.listed]
    if not versions:
        raise _refuse("stage", f"miner {miner!r} is not registered and listed in the protocol")
    return max(versions)


def _require_calibrated_mine(project: Project, spec: StageSpec) -> None:
    """Refuse (field `stage`) a production run of a mine stage whose listed version has no passed
    calibration, before any session starts. The rule is `miner_state` (the state the miner pass
    itself checks: see `factory.services.mining._require_calibrated`); a use the protocol declares
    exploratory (an amendment with a reason; IDEA-69) skips it.
    Read-only."""
    if spec.miner is None or spec.miner_version is None:
        return
    from factory.services.miners import MinerState, miner_state  # miners imports the mining stack
    from factory.services.mining import use_is_exploratory

    state = miner_state(project, spec.miner, spec.miner_version)
    if state is MinerState.CALIBRATED or use_is_exploratory(
        project, spec.miner, spec.miner_version
    ):
        return
    raise _refuse(
        "stage",
        f"miner {spec.miner} version {spec.miner_version} has no passed calibration "
        f"(state: {state.value}); calibrate it first, or have the researcher amend the protocol "
        "to declare the miner use exploratory, with a reason (`factory protocol amend`)",
    )


def stage_spec(project: Project, stage: str) -> StageSpec:
    """The spec of `stage`; for `mine:<id>` the miner and the version the protocol lists."""
    spec = STAGES.get(stage)
    if spec is not None:
        return spec
    if stage.startswith(MINE_PREFIX) and len(stage) > len(MINE_PREFIX):
        miner = stage[len(MINE_PREFIX) :]
        return replace(MINE_SPEC, miner=miner, miner_version=_mine_use(project, miner))
    raise _refuse("stage", "must be one of " + stage_keys())


def _skill_text(project: Project, skill: str) -> str:
    path = project.settings.plugin_dir / "skills" / skill / "SKILL.md"
    if not path.is_file():
        raise _refuse("skill", f"no installed skill {skill!r} under {project.settings.plugin_dir}")
    return path.read_text(encoding="utf-8")


_CHAT_PROMPT: Final = (
    "You are an unattended headless run of stage `{stage}` for the Research Factory project "
    "`{slug}`. Nobody answers questions during this run: ask the researcher nothing, wait for "
    "nothing, and make no step of the skill depend on a reply. The researcher's order is a "
    "recorded request; the steps of the skill that agree the wording, the selection and the mode "
    "with the researcher are already done in it.\n\n"
    "Parameters for every factory call: project `{slug}`, role `{role}`, model `{model}`, "
    "skill `{skill}`.\n\n"
    "Start by calling `chat_request_next`. It serves the oldest open request of kind `{stage}` "
    "and marks it taken by this run: `request_id`, `{field}`, `selection` (`layers`, `include`, "
    "`exclude`: pass them as they are to `selection_resolve`, `claims_digest`, `corpus_search` "
    "and the other tools), `parent` and `note`. If `batch` is null, say so and stop. Then follow "
    "exactly the skill's {mode_name} procedure below, as in its section `Unattended run`.\n\n"
    "{extra}"
    "Record the result with `request_id` set to the served `request_id` in `{record}`. "
    "Rate nothing and write no balance or verdict: the researcher does. When you have recorded "
    "the result, finish with a short summary: the request id, the {result} id, what the "
    "{result} contains, the gaps and unread tiers, and any refusal or `blocked` text verbatim.\n\n"
    "Limit: stop after {unit_cap} units or when the queue is empty, whichever comes first. A "
    "unit is one {unit}. The server refuses further units with `cap-reached` once the limit is "
    "served: then stop. Use no other tools.\n\n"
    "=== SKILL {skill} ===\n{skill_text}"
)
_SPAR_EXTRA: Final = (
    "Mode: Explore, unless the request's `mode` is `prepare`. In Explore one session writes both "
    "cases: `sheet_open` (with `request_id`), `sheet_argue` against, `sheet_close` against, "
    "`sheet_argue` for, `sheet_close` for. In Prepare, the case for must come from a session "
    "that wrote no argument against, so a Prepare request is one of two kinds. With no `parent`: "
    "open the sheet in mode `prepare` (with `request_id`), write only the case against, close "
    "the section `against` and stop; the case for is a second request. With a `parent` that is "
    "a sheet whose case against is closed: do not open a sheet; read the parent with "
    "`sheet_view`, argue only the case for into it with `sheet_argue` (its `sheet_id` is the "
    "parent), and close `for` with `sheet_close`, passing `request_id`. Outside Prepare a "
    "`parent`, a sheet or an answer, is an earlier result you read first (`sheet_view` or "
    "`answer_view`) and take into account; the new sheet stands on its own.\n\n"
)
_ASK_EXTRA: Final = (
    "A `parent`, a sheet or an answer, is an earlier result you read first (`answer_view` or "
    "`sheet_view`) and take into account: pass it as `parent` to `answer_record`. The request has "
    "no mode.\n\n"
)


def _chat_prompt(project: Project, stage: str, spec: StageSpec, unit_cap: int) -> str:
    spar = stage == "spar"
    return _CHAT_PROMPT.format(
        stage=stage,
        slug=project.paths.slug,
        role=spec.role,
        model=spec.model,
        skill=spec.skill,
        field="hypothesis` and `mode" if spar else "question",
        mode_name="Spar" if spar else "Ask",
        extra=_SPAR_EXTRA if spar else _ASK_EXTRA,
        record="`sheet_open` or `sheet_close`" if spar else "`answer_record`",
        result="sheet" if spar else "answer",
        unit_cap=unit_cap,
        unit=spec.unit,
        skill_text=_skill_text(project, spec.skill),
    )


_SPAR2_PROMPT: Final = (
    "You are one role session of the agentic spar, stage `{stage}` (the role `{role}`), for the "
    "Research Factory project `{slug}`. Nobody answers questions during this run: ask the "
    "researcher nothing and wait for nothing. Other roles ran or will run as separate sessions; "
    "you do only your own role, as the section `{section}` of the skill says.\n\n"
    "Parameters for every factory call: project `{slug}`, role `{role}`, model `{model}`, "
    "skill `{skill}`.\n\n"
    "{assigned}"
    "Start by calling `spar_role_next`: it serves your assignment (the hypothesis, the selection, "
    "the sheet and what your role needs); you pass no request id anywhere, the platform derives "
    "it from this run. Rate nothing, write no balance or verdict on the hypothesis, record no "
    "lead: the researcher does. Copy quotes exactly and verify them. When you have recorded "
    "your result, finish with a short summary: what you recorded, the gaps and any refusal "
    "verbatim.\n\n"
    "Limit: stop after {unit_cap} units. A unit is one {unit}. The server refuses further units "
    "with `cap-reached` once the limit is served: then stop. Use no other tools.\n\n"
    "=== SKILL {skill} ===\n{skill_text}"
)


def _spar2_prompt(
    project: Project,
    stage: str,
    spec: StageSpec,
    unit_cap: int,
    assignment: RoleAssignment | None,
) -> str:
    assigned = ""
    if assignment is not None:
        assigned = f"This run is assigned the chat request `{assignment.request_id}`"
        if assignment.work_id is not None:
            assigned += f", paper `{assignment.work_id}`"
        assigned += ".\n\n"
    return _SPAR2_PROMPT.format(
        stage=stage,
        role=spec.role,
        section=stage.removeprefix(SPAR2_PREFIX),
        slug=project.paths.slug,
        model=spec.model,
        skill=spec.skill,
        assigned=assigned,
        unit_cap=unit_cap,
        unit=spec.unit,
        skill_text=_skill_text(project, spec.skill),
    )


def _prompt(
    project: Project,
    stage: str,
    spec: StageSpec,
    unit_cap: int,
    assignment: RoleAssignment | None = None,
) -> str:
    if stage in SPAR2_STAGES:
        return _spar2_prompt(project, stage, spec, unit_cap, assignment)
    if stage in CHAT_STAGES:
        return _chat_prompt(project, stage, spec, unit_cap)
    slug = project.paths.slug
    parameters = f"project `{slug}`, pass_label `A`, role `{spec.role}`, model `{spec.model}`, "
    miner = ""
    if spec.miner is not None:
        parameters += f"miner `{spec.miner}`, version {spec.miner_version}, "
        miner = f" of miner `{spec.miner}` (version {spec.miner_version})"
    if spec.skill == "rf-intuition":
        parameters = f"project `{slug}`, role `{spec.role}`, model `{spec.model}`, "
    extra = ""
    if spec.skill == "rf-screen":
        from factory.services.screening import SCREEN_BATCH  # screening imports much

        extra = (
            "Screening order for this run: the skill says full-text mode runs only when the "
            "researcher asks; for this run that is overridden, the researcher has asked for it. "
            'First screen at title and abstract: call `screen_next` with `stage="title-abstract"` '
            "and screen every batch served, until it serves no batch. Then screen at full text: "
            'call `screen_next` with `stage="full-text"` and follow the skill\'s full-text mode '
            "until it serves no batch. Both stages are pass A, and a batch of up to "
            f"{SCREEN_BATCH} records is {SCREEN_BATCH} units. If a stage serves no batch because "
            "of a `blocked` reason, report it verbatim and go on to the next stage.\n\n"
        )
    if spec.skill == "rf-intuition":
        extra = (
            "Proposing background concepts (`concept_propose`, `concept_link`) is out of scope "
            "for this run: interpret the served ideas only, and ignore the skill's concept "
            "steps.\n\n"
        )
    return (
        f"You are pass A of stage `{stage}`{miner} for the Research Factory project `{slug}`. "
        "Work through the factory MCP tools and follow exactly the skill below "
        "(you are pass `A`).\n\n"
        f"Parameters for every factory call: {parameters}skill `{spec.skill}`.\n\n"
        f"{extra}"
        f"Limit: stop after {unit_cap} units or when the queue is empty, whichever comes first. "
        f"A unit is one {spec.unit}. The server refuses further units with `cap-reached` once "
        "the limit is served: then stop. Use no other tools. Finally print "
        "how many units you handled and any `blocked` text or error verbatim.\n\n"
        f"=== SKILL {spec.skill} ===\n{_skill_text(project, spec.skill)}"
    )


def mcp_config(
    project: Project, unit_cap: int | None = None, run_id: str | None = None
) -> dict[str, JsonValue]:
    """The strict MCP config: this factory, with the root, plugin dir, PYTHONPATH and ranker
    model (when set) as its only environment, and, for a run, `FACTORY_UNIT_CAP` and
    `FACTORY_RUN_ID` and `FACTORY_RUN_DIR` (the MCP server then serves at most that many units and
    writes its count to the run folder: see `mcp.unit_cap`)."""
    env: dict[str, JsonValue] = {
        "PYTHONPATH": os.environ.get("PYTHONPATH") or str(Path(factory.__file__).parents[1]),
        "FACTORY_PLUGIN_DIR": str(project.settings.plugin_dir),
        "FACTORY_ROOT": str(project.settings.root),
    }
    ranker = os.environ.get("FACTORY_RANKER_MODEL")
    if ranker:
        env["FACTORY_RANKER_MODEL"] = ranker
    if unit_cap is not None:
        env["FACTORY_UNIT_CAP"] = str(unit_cap)
    if run_id is not None:
        env["FACTORY_RUN_ID"] = run_id
        env["FACTORY_RUN_DIR"] = str(_run_dir(project, run_id))
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
    run_id: str | None = None,
    prompt_override: str | None = None,
    assignment: RoleAssignment | None = None,
) -> tuple[list[str], dict[str, JsonValue], str]:
    """`(argv, mcp config, prompt)` for one run of `stage`. Pure: starts and writes nothing.
    `prompt_override` is used in place of the built prompt (a resumed run's recorded prompt)."""
    spec = stage_spec(project, stage)
    if spec.fixed_cap is not None:
        unit_cap = spec.fixed_cap
    if not 1 <= unit_cap <= MAX_UNIT_CAP:
        raise _refuse("unit_cap", f"must be between 1 and {MAX_UNIT_CAP}")
    prompt = (
        prompt_override
        if prompt_override is not None
        else _prompt(project, stage, spec, unit_cap, assignment)
    )
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
    return argv, mcp_config(project, unit_cap, run_id), prompt


def _screen_servable(project: Project, stage: ScreeningStage) -> tuple[int, bool]:
    """`(records, blocked)`: the records `screen_next` would serve a pass A agent at `stage` now,
    and whether a gate limits it. Undecided works of the stage's population, but none while the
    corpus awaits `dedup_run` or while a required calibration set is not drawn, and only the
    undecided calibration works while the calibration gate of pass A is closed (ordinary batches
    wait, open tasks of them included; see `screening.screen_next`). Read-only."""
    from factory.services.calibration import (
        calibration_drawn,
        calibration_items,
        calibration_status,
        stage_population,
    )
    from factory.services.dedup import dedup_current
    from factory.services.screening import live_decisions

    if not dedup_current(project):
        return 0, True
    status = calibration_status(project, stage=stage)
    if status.required and not calibration_drawn(project, stage=stage):
        return 0, True
    population = stage_population(project, stage)
    decided = {d.work_id for d in live_decisions(project, PassLabel.A, stage=stage)}
    gated = status.required and not status.passed[PassLabel.A.value]
    if gated:
        population = population & set(calibration_items(project, stage=stage))
    return len(population - decided), gated


def pending_units(project: Project, stage: str) -> dict[str, int]:
    """The pending units of `stage` (pass A): per task kind for `screen` and `extract`; for the
    other stages (`factory.services.pipeline.pending_by_stage`) one count under the stage key."""
    stage = resolve_stage(project, stage)
    if stage in CHAT_STAGES:
        from factory.services.chat_requests import open_count

        return {stage: open_count(project, stage)}
    if stage in SPAR2_STAGES:
        from factory.services.spar_v2 import pending_by_role

        return {stage: pending_by_role(project, stage.removeprefix(SPAR2_PREFIX))}
    spec = STAGES.get(stage)
    if spec is None or not spec.kinds:
        if not is_stage_key(stage):
            raise _refuse("stage", "must be one of " + stage_keys())
        from factory.services.pipeline import unit_pending  # pipeline imports this module

        return {stage: unit_pending(project, stage) or 0}
    pending = pending_work(project)
    counts = {kind: pending.get(kind, 0) for kind in spec.kinds}
    if stage == "screen":  # a screening task is made only when `screen_next` serves the record
        for kind, screening_stage in zip(
            spec.kinds, (ScreeningStage.TITLE_ABSTRACT, ScreeningStage.FULL_TEXT), strict=True
        ):
            servable, blocked = _screen_servable(project, screening_stage)
            counts[kind] = servable if blocked else max(counts[kind], servable)
    if stage == "extract":  # a task is made only when a session asks for the unit
        from factory.services.pipeline import unit_pending

        counts[spec.kinds[0]] = max(counts[spec.kinds[0]], unit_pending(project, stage) or 0)
    return counts


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


def has_open_run(project: Project) -> bool:
    """Whether a run of the project is open (recorded started, not finished)."""
    return bool(_open_run_ids(project))


def run_outcome(project: Project, run_id: str) -> str | None:
    """The recorded outcome of `run_id` (`complete`, `failed`, `lost`), None while it is open."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT outcome FROM runner_runs WHERE run_id = :r"), {"r": run_id}
        ).first()
    return None if row is None or row[0] is None else str(row[0])


RUN_SECONDS_PER_UNIT: Final = 120
RUN_SECONDS_BASE: Final = 600
KILL_GRACE: Final = 10.0
"""Seconds between SIGTERM and SIGKILL of a run that has passed its time limit."""
_monotonic: Callable[[], float] = time.monotonic
_PROCESSES: dict[str, Process] = {}


def run_time_limit(unit_cap: int) -> float:
    """The wall-clock limit of one run in seconds: `unit_cap * 120 + 600`."""
    return float(unit_cap * RUN_SECONDS_PER_UNIT + RUN_SECONDS_BASE)


def _signal_group(pid: int, sig: int) -> None:
    """Signal the process group of `pid` (the run was started in its own session); never this
    process's own group; a process already gone is ignored."""
    try:
        group = os.getpgid(pid)
        if group == os.getpgrp():
            return
        os.killpg(group, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate(project: Project, run_id: str) -> None:
    """Kill the process group of `run_id`: SIGTERM, then SIGKILL after KILL_GRACE seconds, and
    make sure the run is recorded `failed` (the watcher records it from the exit status; a run
    with no watcher here is closed directly)."""
    process = _PROCESSES.get(run_id)
    pid = process.pid if process is not None else _read_pid(_run_dir(project, run_id))
    if pid is not None:
        _signal_group(pid, signal.SIGTERM)
        if not wait(run_id, KILL_GRACE):
            _signal_group(pid, signal.SIGKILL)
            wait(run_id, KILL_GRACE)
    if run_outcome(project, run_id) is None:
        for row in _rows(project, "WHERE r.outcome IS NULL"):
            if str(row[0]) == run_id:
                _finish(project, run_id, str(row[1]), "failed", None)


def wait_until_closed(
    project: Project, run_id: str, poll: float = 1.0, *, limit: float | None = None
) -> bool:
    """Block until `run_id` is closed: its watcher thread (this process) ends, else the run is
    reconciled by `finish_lost` once its process is gone. Returns True. After `limit` seconds
    the process group is killed (see `_terminate`), the run is recorded `failed`, and the result
    is False."""
    deadline = None if limit is None else _monotonic() + limit
    while True:
        if wait(run_id, poll) or run_outcome(project, run_id) is not None:
            return True
        if _THREADS.get(run_id) is None:
            finish_lost(project)
        if deadline is not None and _monotonic() >= deadline:
            _terminate(project, run_id)
            return False


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
        with project.writing():  # mint under the lock (slice 5 ruling 3)
            project.record(
                [project.events.make("runner.finished", payload, project.system_actor())]
            )


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
        _PROCESSES.pop(run_id, None)
    if recorded:
        _advance_after(project)


def advance_after(project: Project) -> None:
    """The deterministic steps for the added papers (`work_queue.advance`), errors logged."""
    _advance_after(project)


def _advance_after(project: Project) -> None:
    """The deterministic steps for the added papers, after a run has been recorded (H6). Any
    exception is logged: the run is already closed and the steps are retried by the next call."""
    try:
        advance(project, sources=dict(default_sources()), fetchers=default_routes(project.settings))
    except Exception:
        _LOG.exception("the automatic steps after run %s failed", project.paths.slug)
    try:
        from factory.services.spar_v2 import advance_open

        advance_open(project)  # the next role of a v2 spar whose chain was begun
    except Exception:
        _LOG.exception("advancing the v2 spar of %s failed", project.paths.slug)


class RunRecord(StrictModel):
    """The recorded start of a run: what a resumed run reuses."""

    run_id: str
    stage: str
    model: str
    allowed_tools: tuple[str, ...]
    prompt_blob: str
    unit_cap: int
    outcome: str | None
    adopted: bool = False


def run_record(project: Project, run_id: str) -> RunRecord | None:
    """The `runner.started` facts of `run_id` as folded, or None when it is not a run of this
    project. Read-only."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT stage, model, allowed_tools, prompt_blob, unit_cap, outcome, adopted "
                "FROM runner_runs WHERE run_id = :r"
            ),
            {"r": run_id},
        ).first()
    if row is None:
        return None
    return RunRecord(
        run_id=run_id,
        stage=str(row[0]),
        model=str(row[1]),
        allowed_tools=tuple(json.loads(str(row[2]))),
        prompt_blob=str(row[3]),
        unit_cap=int(row[4]),
        outcome=None if row[5] is None else str(row[5]),
        adopted=bool(row[6]),
    )


def _resumed_prompt(project: Project, earlier: RunRecord, spec: StageSpec, unit_cap: int) -> str:
    """The earlier run's recorded prompt, for a run that resumes it. Refuses when the stage's
    model or tools are no longer the recorded ones: a changed spec is a fresh run, never a
    silent change. For an adopted run (`RunRecord.adopted`) the recorded tools are what the outside
    driver had, so they need only be a subset of the stage's tools; the resumed run then uses the
    full stage tools (the recorded event says so). Any other run needs equal tools. A cap different
    from the recorded one changes only the limit sentence."""
    if earlier.adopted:
        tools_ok = set(earlier.allowed_tools) <= set(spec.tools)
    else:
        tools_ok = earlier.allowed_tools == spec.tools
    if earlier.model != spec.model or not tools_ok:
        raise _refuse(
            "resumes",
            f"the model or tools of stage {earlier.stage!r} changed since run {earlier.run_id}; "
            "start a fresh run instead of resuming it",
        )
    prompt = project.blobs.get(earlier.prompt_blob).decode("utf-8")
    if unit_cap != earlier.unit_cap:
        old = f"stop after {earlier.unit_cap} units"
        if old not in prompt:
            raise _refuse("unit_cap", "the recorded prompt names no cap to change; use the same")
        prompt = prompt.replace(old, f"stop after {unit_cap} units", 1)
    return prompt


def start_run(
    project: Project,
    stage: str,
    *,
    unit_cap: int | None = None,
    launcher: Launcher | None = None,
    pipeline: bool = False,
    resumes: str | None = None,
    prompt_override: str | None = None,
    assignment: RoleAssignment | None = None,
) -> str:
    """Start one run of `stage`; returns its `run_id` once the process is started and recorded.

    A mine stage is refused before launch (field `stage`) unless the version's calibration has
    passed or the protocol declares the miner use exploratory (IDEA-69; no quality claim); the run
    records that state in `runner.started`.
    Refused while a pipeline runs, unless `pipeline` (the pipeline's own call).

    `resumes` names an earlier, not complete run of the same stage (plan restart-and-costs R2): the
    new run is a new run (the earlier run's events are never edited) that reuses the earlier
    run's recorded prompt, tools and model, and names it in `runner.started`. `unit_cap` then
    defaults to the earlier run's. `prompt_override` replaces the built prompt (and is what a
    resume passes after reading the blob).

    A role stage of the agentic spar (`spar2-*`) is started only with its `assignment`, by the
    coordinator (`spar_v2.advance`); the assignment must be the request's next role, and the start
    writes `spar.role_started` in the same batch as `runner.started`."""
    stage = resolve_stage(project, stage)
    spec = stage_spec(project, stage)
    if (stage in SPAR2_STAGES) != (assignment is not None) or (
        assignment is not None and stage != f"{SPAR2_PREFIX}{assignment.role}"
    ):
        raise _refuse(
            "stage", "a spar2 role run is started for its request by `factory chat advance`"
        )
    from factory.services.mining import use_is_exploratory

    exploratory = (
        spec.miner is not None
        and spec.miner_version is not None
        and use_is_exploratory(project, spec.miner, spec.miner_version)
    )
    earlier = None
    if resumes is not None:
        earlier = run_record(project, resumes)
        if earlier is None:
            raise _refuse("resumes", f"{resumes} is not a run of this project")
        if earlier.stage != stage:
            raise _refuse("resumes", f"{resumes} ran stage {earlier.stage!r}, not {stage!r}")
        if spec.fixed_cap is not None:
            raise _refuse("resumes", "a chat request is not resumed; order it again")
        if earlier.outcome == "complete":
            from factory.services.usage_limit import limit_stop

            # a run the usage limit stopped exits 0 and is recorded complete, but is resumable
            if limit_stop(project, resumes, stage_pending=True) is None:
                raise _refuse("resumes", f"{resumes} completed; there is nothing to resume")
    _require_calibrated_mine(project, spec)
    if unit_cap is None:
        unit_cap = DEFAULT_UNIT_CAP if earlier is None else earlier.unit_cap
    if spec.fixed_cap is not None:
        unit_cap = spec.fixed_cap  # a chat stage serves one request per run
    if earlier is not None and prompt_override is None:
        prompt_override = _resumed_prompt(project, earlier, spec, unit_cap)
    if not 1 <= unit_cap <= MAX_UNIT_CAP:
        raise _refuse("unit_cap", f"must be between 1 and {MAX_UNIT_CAP}")
    claude = claude_path()
    if claude is None:
        raise _refuse(
            "claude",
            "the `claude` executable is not on PATH; install Claude Code and log in, then retry",
        )
    if not pipeline:
        from factory.services.pipeline import pipeline_active

        if pipeline_active(project):
            raise _refuse("pipeline", "a pipeline of this project is running; wait for it to end")
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
            project,
            stage,
            unit_cap,
            mcp_path=mcp_path,
            claude=claude,
            run_id=run_id,
            prompt_override=prompt_override,
            assignment=assignment,
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
            resumes=resumes,
            exploratory=exploratory,
        )
        with project.writing():  # mint under the lock (slice 5 ruling 3)
            batch = [project.events.make("runner.started", started, project.system_actor())]
            if assignment is not None:
                from factory.index.spar_v2 import Slot
                from factory.services.spar_v2 import role_started_event

                batch.append(
                    role_started_event(
                        project,
                        assignment.request_id,
                        run_id,
                        Slot(assignment.role, assignment.work_id),
                    )
                )
            project.record(batch)
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
        _PROCESSES[run_id] = process
        thread.start()
    return run_id


def _as_stage(stage: str) -> RunnerStage:
    """`stage` as the event's stage key; refuses an unknown key."""
    if not is_stage_key(stage):
        raise _refuse("stage", "must be one of " + stage_keys())
    return stage


_ADOPTED_ENV_KEYS: Final = frozenset(
    {
        "PYTHONPATH",
        "FACTORY_PLUGIN_DIR",
        "FACTORY_ROOT",
        "FACTORY_RANKER_MODEL",
        "FACTORY_UNIT_CAP",
        "FACTORY_RUN_ID",
        "FACTORY_RUN_DIR",
    }
)
"""The environment keys a run's MCP config may carry (see `mcp_config`). An adopted config keeps
only these; any other key, a secret among them, is dropped."""
_standard_mcp_config: Final = mcp_config


_SECRET_WORDS: Final = ("key", "token", "secret", "password")


def _looks_secret(arg: str) -> bool:
    lowered = arg.lower()
    return any(word in lowered for word in _SECRET_WORDS)


def _safe_args(args: Sequence[object]) -> list[JsonValue]:
    """`args` without any that looks like a secret (contains `key`, `token`, `secret` or
    `password`, any case) and, for such a flag without `=`, the value that follows it."""
    kept: list[JsonValue] = []
    skip_value = False
    for arg in args:
        if not isinstance(arg, str):
            continue
        if skip_value:
            skip_value = False
            if not arg.startswith("-"):
                continue
        if _looks_secret(arg):
            skip_value = "=" not in arg
            continue
        kept.append(arg)
    return kept


def _adopted_mcp_config(source: Path) -> dict[str, JsonValue]:
    """The MCP config of an outside driver, reduced to what is safe to keep: per server only
    `command`, `args` (any that looks like a secret dropped, with its value) and the allowed
    environment keys; `url`, `headers` and every other field are dropped. Reads `source` and
    writes nothing to it."""
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _refuse("mcp_config", f"not a readable JSON file: {exc}") from exc
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise _refuse("mcp_config", "has no `mcpServers` object")
    kept: dict[str, JsonValue] = {}
    for name, server in servers.items():
        if not isinstance(server, dict):
            raise _refuse("mcp_config", f"server {name!r} is not an object")
        env = server.get("env", {})
        if not isinstance(env, dict):
            raise _refuse("mcp_config", f"server {name!r} has an `env` that is not an object")
        entry: dict[str, JsonValue] = {}
        if isinstance(server.get("command"), str):
            entry["command"] = server["command"]
        args = server.get("args")
        if isinstance(args, list):
            entry["args"] = _safe_args(args)
        entry["env"] = {k: v for k, v in env.items() if k in _ADOPTED_ENV_KEYS}
        kept[str(name)] = entry
    return {"mcpServers": kept}


_CAP_SENTENCE_RE: Final = re.compile(r"stop after (\d+) units")


def _adopted_cap(prompt: str) -> int | None:
    """The cap the prompt's `stop after N units` sentence states, None when it has none."""
    found = _CAP_SENTENCE_RE.search(prompt)
    if found is None:
        return None
    cap = int(found.group(1))
    if not 1 <= cap <= MAX_UNIT_CAP:
        raise _refuse("prompt", f"its cap {cap} is not between 1 and {MAX_UNIT_CAP}")
    return cap


def _project_relative(project: Project, path: Path) -> str:
    """`path` relative to the project folder when it lies inside it, else just its file name."""
    try:
        return str(path.resolve().relative_to(project.paths.dir.resolve()))
    except ValueError:
        return path.name


def adopt_driver(
    project: Project,
    *,
    stage: str,
    prompt_file: Path,
    model: str,
    tools: Sequence[str],
    mcp_config: Path | None,
    log_file: Path | None,
    started_at: datetime | None,
) -> str:
    """Record a driver started outside the runner (plan restart-and-costs R4) as a run of `stage`,
    so `resume` can restart it. Returns the new `run_id`.

    The prompt is copied into the run folder and stored as a blob; `runner.started` records the
    prompt blob, the given tools and model (what the driver really had; the event is marked
    `adopted`, and a resume of it uses the full stage tools), and the command
    `["adopted", <prompt path>]`, the path relative to the project folder when inside it, else
    the file name. The cap is the prompt's `stop after N units` sentence; a prompt without one gets
    the default cap and the standard limit sentence appended to the stored copy (the source file is
    never changed). With a
    `log_file`, the log is copied in and `runner.finished` is recorded at once with outcome `lost`
    (the status of the outside process is unknown). Without one, the run is closed as `lost` by
    the next reconcile, as any run whose process is gone. `started_at` is kept in the run folder
    (`adopted.json`): an event carries no time of its own here.

    Refused, with nothing written: an unknown stage, a blank model, no tools, tools outside the
    stage's spec (named), a missing prompt or log file, an unreadable MCP config, an open run.
    Reads the source files only."""
    if not is_stage_key(stage):
        raise _refuse("stage", "must be one of " + stage_keys())
    spec = stage_spec(project, stage)
    if not model.strip():
        raise _refuse("model", "must not be blank")
    names = tuple(tools)
    if not names:
        raise _refuse("tools", "name at least one tool of the stage")
    extra = [tool for tool in names if tool not in spec.tools]
    if extra:
        raise _refuse("tools", f"not tools of stage {stage!r}: " + ", ".join(extra))
    if not prompt_file.is_file():
        raise _refuse("prompt", f"{prompt_file} is not a file")
    prompt_bytes = prompt_file.read_bytes()
    try:
        prompt_text = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _refuse("prompt", "is not UTF-8 text") from exc
    unit_cap = _adopted_cap(prompt_text)
    if unit_cap is None:
        unit_cap = DEFAULT_UNIT_CAP
        prompt_bytes = (
            prompt_text
            + f"\n\nLimit: stop after {unit_cap} units or when the queue is empty, whichever "
            f"comes first. A unit is one {spec.unit}. The server refuses further units with "
            "`cap-reached` once the limit is served: then stop.\n"
        ).encode("utf-8")
    if log_file is not None and not log_file.is_file():
        raise _refuse("log", f"{log_file} is not a file")
    config: dict[str, JsonValue] | None = (
        None if mcp_config is None else _adopted_mcp_config(mcp_config)
    )
    with _runs_lock(project):
        finish_lost(project, advance_after=False)
        if _open_run_ids(project):
            raise _refuse("run", "a run of this project is already open; wait for it to finish")
        counts = pending_units(project, stage)
        run_id = project.ids.new("rnr")
        folder = _run_dir(project, run_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prompt.txt").write_bytes(prompt_bytes)
        if config is None:
            config = _standard_mcp_config(project, DEFAULT_UNIT_CAP, run_id)
        (folder / "mcp.json").write_text(json.dumps(config, indent=1), encoding="utf-8")
        if log_file is not None:
            shutil.copyfile(log_file, folder / "log.jsonl")
        adopted = {
            "prompt_source": str(prompt_file.resolve()),
            "mcp_config_source": None if mcp_config is None else str(mcp_config.resolve()),
            "log_source": None if log_file is None else str(log_file.resolve()),
            "started_at": None if started_at is None else started_at.isoformat(),
        }
        (folder / "adopted.json").write_text(json.dumps(adopted, indent=1), encoding="utf-8")
        started = RunnerStarted(
            run_id=run_id,
            stage=_as_stage(stage),
            model=model,
            allowed_tools=names,
            prompt_blob=project.blobs.put(prompt_bytes),
            unit_cap=unit_cap,
            counts_before=counts,
            command=("adopted", _project_relative(project, prompt_file)),
            adopted=True,
        )
        with project.writing():  # mint under the lock (slice 5 ruling 3)
            project.record([project.events.make("runner.started", started, project.system_actor())])
        if log_file is not None:
            _finish(project, run_id, stage, "lost", None)
    return run_id


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
