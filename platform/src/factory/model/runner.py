"""Events of the headless runner (plan feed-hub H5, decision 118 item 4): `runner.*`.

A run is one outside `claude -p` process started by the platform for one stage (`screen` or
`extract`) of one project. The platform holds no key and calls no model API: it starts the
executable the researcher installed, with a strict MCP config and an allow-list of the stage's
tools. Every judgement is written by that process through MCP with the agent's own provenance.

`runner.started` and `runner.finished` are system events. The service refuses a human or an
agent actor and the fold ignores a hand-written one, so a runner never records a human act.
Pure value types; written by `factory.services.runner`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.screening import NonBlank

RUNNER_RUN_ID_RE = rf"^rnr_{ULID_RE}$"

BlobRef = Annotated[str, StringConstraints(pattern=BLOB_REF_RE)]
RunnerStage = Literal["screen", "extract"]
RunnerOutcome = Literal["complete", "failed", "lost"]


class RunnerStarted(StrictModel):
    """The command is the argv with the prompt text replaced by a placeholder; it names paths
    only, never a secret. `counts_before` is the pending units per task kind of the stage."""

    run_id: str = Field(pattern=RUNNER_RUN_ID_RE)
    stage: RunnerStage
    model: NonBlank
    allowed_tools: tuple[NonBlank, ...] = Field(min_length=1)
    prompt_blob: BlobRef
    unit_cap: int = Field(ge=1)
    counts_before: dict[str, Annotated[int, Field(ge=0)]]
    command: tuple[str, ...] = Field(min_length=1)


class RunnerFinished(StrictModel):
    """`exit_status` is None when the process's status is unknown (`lost`, or it never started)."""

    run_id: str = Field(pattern=RUNNER_RUN_ID_RE)
    exit_status: int | None = None
    outcome: RunnerOutcome
    log_blob: BlobRef
    counts_after: dict[str, Annotated[int, Field(ge=0)]]
