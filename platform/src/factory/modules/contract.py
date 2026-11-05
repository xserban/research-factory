"""The stage-module contract: pure declarations (slice M rulings 1, 5; decision 55).

A module declares what it owns (event types, index tables, task kinds, protocol sections, check
codes, decision gates, strategies) and the quality regime it runs under. Behaviour stays in
`factory.services`; this package imports nothing from it (nor from `index`, `mcp`, `cli`), so
every declaration is data a test can check exhaustively.

Invariants:
- Every dataclass is frozen; a declaration cannot change after construction.
- `ModuleSpec` refuses an inconsistent declaration at construction: a builder owns no gate and
  no agent-written event family; a miner declares a quality regime; a decision gate names the
  event types that record an act at it; a computed gate names none.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from factory.services.context import Project

Severity = Literal["error", "warning"]
Levels = tuple[Severity | None, Severity | None, Severity | None]
"""The severity of a finding in `exploratory`, `pilot` and `systematic` (None: no finding)."""


class ModuleKind(StrEnum):
    """The closed list of module kinds (slice-M ruling 5 and reconciliation item 2)."""

    CORE = "core"
    SCOPING = "scoping"
    RETRIEVAL = "retrieval"
    TRANSFORM = "transform"
    FILTER = "filter"
    MINER = "miner"
    PROPOSAL = "proposal"
    BUILDER = "builder"


class GateKind(StrEnum):
    DECISION = "decision"
    COMPUTED = "computed"


class PolicyKind(StrEnum):
    HUMAN = "human"
    AGENT_AUDIT = "agent_audit"
    AGENT = "agent"


class Autonomy(StrEnum):
    HUMAN = "human"
    AUDITED_AGENT = "audited-agent"
    AGENT = "agent"


class ArtifactKind(StrEnum):
    """The id families a module reads and writes (00-system section 3 and the slice specs)."""

    QUESTION = "question"
    PROTOCOL = "protocol"
    SEED = "seed"
    QUERY = "query"
    SEARCH_RUN = "search-run"
    WORK = "work"
    MERGE = "merge"
    DECISION = "decision"
    TASK = "task"
    FETCH = "fetch"
    ATTEMPT = "attempt"
    DOCUMENT = "document"
    CONVERSION = "conversion"
    RECORD = "record"
    CLAIM = "claim"
    REFERENCE_EXTRACTION = "reference-extraction"
    SNOWBALL_ROUND = "snowball-round"
    RELATION = "relation"
    IDEA = "idea"
    INTERPRETATION = "interpretation"
    CONCEPT = "concept"
    MINER = "miner"
    REPORT = "report"


@dataclass(frozen=True)
class GatePolicy:
    """Who may pass a decision gate: `human`, `agent_audit(fraction, minimum)` or `agent`."""

    kind: PolicyKind
    fraction: float | None = None
    minimum: int | None = None


@dataclass(frozen=True)
class GateSpec:
    """A gate named `<namespace>.<act>`; the namespace need not be a module name."""

    gate_id: str
    kind: GateKind
    act_events: tuple[str, ...]
    floor: PolicyKind
    rigour: tuple[str, ...]


@dataclass(frozen=True)
class EventFamily:
    """The event types and index tables a module owns.

    `system_only` marks a family whose events the platform or a human writes and no agent does
    (a builder's computed outputs and registered inputs, reconciliation item 3)."""

    types: tuple[str, ...] = ()
    note: str = ""
    tables: tuple[str, ...] = ()
    system_only: bool = False


@dataclass(frozen=True)
class QualityRegime:
    passes: Literal[1, 2]
    independence: Literal["session-and-model", "none"]
    agreement_unit: str
    calibration: Literal["human-labelled", "none"]
    audit: Literal["agreed-sample", "gate-sample", "none"]
    staleness: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckRule:
    code: str
    levels: Levels


@dataclass(frozen=True)
class BuilderReads:
    """The registered `(miner name, version)` pairs a builder reads (slice M ruling 17). Records of
    any other version are invisible to it; `check` lists records no builder reads."""

    miners: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class StrategySpec:
    name: str
    version: str
    skill: str | None = None


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    kind: ModuleKind
    inputs: tuple[ArtifactKind, ...] = ()
    outputs: tuple[ArtifactKind, ...] = ()
    events: EventFamily = field(default_factory=EventFamily)
    task_kinds: tuple[str, ...] = ()
    protocol_sections: tuple[str, ...] = ()
    gates: tuple[GateSpec, ...] = ()
    regime: QualityRegime | None = None
    checks: tuple[CheckRule, ...] = ()
    strategies: tuple[StrategySpec, ...] = ()
    reads: BuilderReads = field(default_factory=BuilderReads)

    def __post_init__(self) -> None:
        problems: list[str] = []
        if self.kind is ModuleKind.BUILDER:
            if self.gates:
                problems.append("a builder declares no gate")
            if self.events.types and not self.events.system_only:
                problems.append("a builder owns no agent-written event type")
        if self.kind is ModuleKind.MINER and self.regime is None:
            problems.append("a miner declares a quality regime")
        for gate in self.gates:
            if gate.kind is GateKind.DECISION and not gate.act_events:
                problems.append(f"decision gate {gate.gate_id} names no act event")
            if gate.kind is GateKind.COMPUTED and gate.act_events:
                problems.append(f"computed gate {gate.gate_id} names act events")
        if problems:
            raise ValueError(f"module {self.name}: " + "; ".join(problems))


@dataclass(frozen=True)
class CheckHit:
    """One condition found by a rule, before its severity is read for a mode.

    `seq` is the position of the rule that found it in the order `check` reports in; the
    composed report keeps hits sorted by it, so the order does not depend on which module
    owns a rule."""

    code: str
    refs: tuple[str, ...]
    message: str
    role: str | None = None
    severity: Severity | None = None
    seq: int = 0


@dataclass(frozen=True)
class MethodsSection:
    title: str
    text: str


@dataclass(frozen=True)
class AutonomyAct:
    gate_id: str
    event_id: str
    actor_kind: str
    protocol_id: str | None


class StageModule(Protocol):
    """A module as `check` and `methods` see it: its declaration and three read hooks."""

    spec: ModuleSpec

    def hits(self, project: Project) -> list[CheckHit]: ...

    def methods(self, project: Project) -> MethodsSection | None: ...

    def autonomy_acts(self, project: Project) -> Iterable[AutonomyAct]: ...
