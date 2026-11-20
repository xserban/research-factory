"""Events of the lifecycle conductor (plan tiers-and-autonomy C8, spec slice-9 section 7):
`conductor.*`.

A conductor run takes a tier's plan through its stages one step at a time. Every step is one outside
`claude -p` run started through `factory.services.runner` (a proposer), and, where an agent may
close a gate of the step at the study's autonomy level, a second run of a verifier and a third of
an auditor, each its own session. The conductor is bookkeeping: it starts runs, counts and stops;
every judgement is a role's, and it records no human act.

`conductor.*` are system events. The service refuses a human or an agent actor and the derivation
(`factory.services.conductor`) ignores a hand-written one; there is no projection table: the state
is derived from the events, as the plan of a v2 spar is derived from the sheet. Pure value types.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.runner import RUNNER_RUN_ID_RE
from factory.model.screening import NonBlank

CONDUCTOR_ID_RE = rf"^cnd_{ULID_RE}$"

ConductorRole = Literal["proposer", "verifier", "auditor"]
StepOutcome = Literal["complete", "failed", "lost"]
PauseReason = Literal[
    "failed-run",
    "lost-run",
    "budget",
    "trust-pause",
    "human-gate",
    "refused",
]


class ConductorStarted(StrictModel):
    """The plan being run: the tier and autonomy level it ran at, the ordered stage ids, the budget
    and the plan as a blob (the input of the run). `steps` are the stage ids not skipped."""

    conductor_id: str = Field(pattern=CONDUCTOR_ID_RE)
    tier: NonBlank
    autonomy_level: NonBlank
    steps: tuple[NonBlank, ...] = Field(min_length=1)
    max_minutes: int = Field(ge=1)
    max_runs: int = Field(ge=1)
    max_units_per_run: int = Field(ge=1)
    plan_blob: Annotated[str, Field(pattern=BLOB_REF_RE)]


class ConductorStepStarted(StrictModel):
    """One role run of one step was started (`run_id` is the runner's run)."""

    conductor_id: str = Field(pattern=CONDUCTOR_ID_RE)
    step: int = Field(ge=0)
    stage_id: NonBlank
    role: ConductorRole
    run_id: str = Field(pattern=RUNNER_RUN_ID_RE)
    attempt: int = Field(ge=1)


class ConductorStepFinished(StrictModel):
    """The runner's outcome of that run, copied once it is known. `run_id` is None for a work-queue
    step (`screen`, `extract`) that had nothing pending: it is complete without a run."""

    conductor_id: str = Field(pattern=CONDUCTOR_ID_RE)
    step: int = Field(ge=0)
    stage_id: NonBlank
    role: ConductorRole
    run_id: str | None = Field(default=None, pattern=RUNNER_RUN_ID_RE)
    outcome: StepOutcome


class ConductorPaused(StrictModel):
    """The conductor stopped; `reason` is computed, never typed by an agent. `gate_id` names the
    gate of a `human-gate` or `trust-pause` stop."""

    conductor_id: str = Field(pattern=CONDUCTOR_ID_RE)
    reason: PauseReason
    step: int | None = Field(default=None, ge=0)
    stage_id: str | None = None
    gate_id: str | None = None
    detail: str = ""


class ConductorFinished(StrictModel):
    """Every planned step ran to a complete run (and no gate waits)."""

    conductor_id: str = Field(pattern=CONDUCTOR_ID_RE)
    steps_done: int = Field(ge=1)
    runs: int = Field(ge=0)
