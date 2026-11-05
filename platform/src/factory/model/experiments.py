"""Experiment designs, runs, results and baseline verdicts (slice 6, plan XP-A).

Invariants enforced here (validated at the boundary, before any event is written):
- A design pre-registers everything that decides the outcome: one factor, the fixed
  configuration, seeds, multiverse axes, ablations, controls, baselines, datasets with split roles,
  metrics, budget, code and environment. Configuration values are scalars held as canonical
  strings (an int or a bool is spelled; a float is refused because it is not exact).
- No input model carries an id, a version, a state, a nonce, a flag or a configuration map: the
  platform computes them. `E@` hashes every field except `notes` (`factory.hypotheses.design`).
- A results file is schema 1, at most 64 KiB, and is stored byte for byte as a blob.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.cards import ROW_KEY_RE
from factory.model.hypotheses import HYP_ID_RE, Decimal0
from factory.model.identity import ULID_RE
from factory.model.screening import NonBlank
from factory.packs import UnitFamily

EXP_ID_RE = rf"^exp_{ULID_RE}$"
E_VERSION_RE = r"^E@[0-9a-f]{8}$"
XRUN_ID_RE = rf"^xrn_{ULID_RE}$"
CONFIG_KEY_RE = r"^[a-z0-9_.-]{1,64}$"
ARM_RE = (
    r"^(?:treatment|baseline|(?:ablation|control):[a-z0-9_.-]{1,64}|reproduction:rk_[0-9a-f]{12})$"
)
SHA256_RE = r"^[0-9a-f]{64}$"
MAX_RESULTS_BYTES = 64 * 1024
MAX_UNIVERSES = 256

SplitRole = Literal["dev", "confirmatory"]
ExperimentId = Annotated[str, StringConstraints(pattern=EXP_ID_RE)]
RunId = Annotated[str, StringConstraints(pattern=XRUN_ID_RE)]
EVersion = Annotated[str, StringConstraints(pattern=E_VERSION_RE)]
Key = Annotated[str, StringConstraints(pattern=CONFIG_KEY_RE)]
Short = Annotated[NonBlank, Field(max_length=200)]


def _scalar(value: Any) -> Any:
    """A configuration value as its canonical string: bool and int are spelled, a float is
    refused (not exact; give it as a decimal string)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise ValueError("give a decimal as a string; a float is not exact")
    return value


Scalar = Annotated[str, BeforeValidator(_scalar), Field(min_length=1, max_length=200)]


class Dataset(StrictModel):
    name: Key
    version: Short
    sha256: Annotated[str, StringConstraints(pattern=SHA256_RE)]
    role: SplitRole


class DesignMetric(StrictModel):
    name: Annotated[NonBlank, Field(max_length=120)]
    direction: Literal["higher", "lower"]
    unit_family: UnitFamily
    unit: Annotated[NonBlank, Field(max_length=40)] | None = None
    primary: bool = False


class Ablation(StrictModel):
    name: Key
    key: Key
    value: Scalar


class Control(StrictModel):
    name: Key
    kind: Literal["positive", "negative"]
    overrides: dict[Key, Scalar] = Field(min_length=1)
    expect: Literal["effect", "no-effect"]

    @model_validator(mode="after")
    def _expectation_matches_kind(self) -> Self:
        if (self.kind == "positive") != (self.expect == "effect"):
            raise ValueError("a positive control expects an effect, a negative one none")
        return self


class Baseline(StrictModel):
    row_key: Annotated[str, StringConstraints(pattern=ROW_KEY_RE)]
    tolerance: Decimal0
    tolerance_kind: Literal["absolute", "relative"] = "relative"
    split: SplitRole = "confirmatory"


class Budget(StrictModel):
    gpu_hours: Decimal0
    per_run_gpu_hours: Decimal0
    max_runs: int = Field(ge=1)


class CodeRef(StrictModel):
    uri: Short
    commit: Short


class ExperimentDesign(StrictModel):
    hypothesis: Annotated[str, StringConstraints(pattern=HYP_ID_RE)]
    factor: dict[Key, tuple[Scalar, Scalar]] = Field(min_length=1)
    """Key to (baseline value, treatment value)."""
    base_config: dict[Key, Scalar]
    code: CodeRef
    environment: Short
    datasets: tuple[Dataset, ...]
    metrics: tuple[DesignMetric, ...]
    seeds: tuple[int, ...] = Field(min_length=1)
    axes: dict[Key, tuple[Scalar, ...]] = Field(default_factory=dict)
    primary_universe: dict[Key, Scalar] = Field(default_factory=dict)
    ablations: tuple[Ablation, ...] = ()
    controls: tuple[Control, ...] = ()
    baselines: tuple[Baseline, ...] = ()
    budget: Budget
    test_access_limit: int | None = Field(default=None, ge=1)
    """None takes the plan's limit (`hypothesis_plan.test_access_limit`)."""
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if any(s < 0 for s in self.seeds):
            raise ValueError("seeds are non-negative integers")
        if any(len(values) == 0 for values in self.axes.values()):
            raise ValueError("an axis lists at least one value")
        return self


class Cell(StrictModel):
    """A planned or exploratory run position: universe coordinates, seed, arm and split."""

    universe: tuple[tuple[Key, Scalar], ...]
    seed: int = Field(ge=0)
    arm: Annotated[str, StringConstraints(pattern=ARM_RE)]
    split: SplitRole

    @model_validator(mode="after")
    def _sorted(self) -> Self:
        keys = [k for k, _ in self.universe]
        if keys != sorted(set(keys)):
            raise ValueError("universe coordinates are sorted by key and unique")
        return self


# --- Results file -----------------------------------------------------------------------------


class ResultMetric(StrictModel):
    value: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    unit: Annotated[NonBlank, Field(max_length=40)] | None = None


class ResultCompute(StrictModel):
    gpu_hours: Decimal0
    wall_clock_s: int = Field(ge=0)
    hardware: Annotated[str, StringConstraints(max_length=200)]


class ResultArtifact(StrictModel):
    name: Short
    sha256: Annotated[str, StringConstraints(pattern=SHA256_RE)]
    uri: Annotated[NonBlank, Field(max_length=500)]


class ResultsFile(StrictModel):
    """The runner's metrics file, schema 1 (ruling 5)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schema")
    run: RunId
    metrics: dict[str, ResultMetric]
    compute: ResultCompute
    exit_status: int
    code_commit: Short
    environment: Short
    nonce: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")] | None = None
    tracker_run: Annotated[NonBlank, Field(max_length=200)] | None = None
    artifacts: tuple[ResultArtifact, ...] = ()
