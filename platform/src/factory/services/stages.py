"""The stage dimension of screening: which stages a pass can run at, its task kinds and its plan.

A pass runs at `title-abstract` or `full-text`; `either` is a criterion's `applies_at` only and is
refused as the stage of a run. Full-text screening needs a declared plan
(`ProtocolSpec.full_text_screening`, R-13); title/abstract uses `ProtocolSpec.screening`.

Invariants:
- Every refusal is a FactoryValidationError and writes nothing.
- `task_kind` and `stage_of_kind` are inverse on the four screening task kinds.
- `kinds_for` and `scope_of_kind` are inverse on the four evidence and contribution task kinds;
  the two mine kinds belong to no fixed scope (the miner is in the task), so `scope_of_kind`
  is None for them and `is_mine_kind` tells them apart.
"""

from typing import TYPE_CHECKING

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.extraction import MinerScope, Scope, ScopeKey
from factory.model.protocol import ScreeningPlan, ScreeningStage
from factory.model.screening import PassLabel
from factory.services.modules import default_task_kinds

if TYPE_CHECKING:  # annotation only: protocol reaches this module through gates and passes
    from factory.services.protocol import ProtocolVersion

_REGISTRY = default_task_kinds()


def _extract_kinds(scope: Scope) -> dict[PassLabel, str]:
    return {
        label: _REGISTRY.kind_for(
            "contributions" if scope is Scope.CONTRIBUTION else "extraction",
            label=label,
            scope=scope.value,
        )
        for label in PassLabel
    }


EXTRACT_KINDS: dict[PassLabel, str] = _extract_kinds(Scope.EVIDENCE)
"""The task kind of each evidence extraction pass; one task per work per pass."""

CONTRIB_KINDS: dict[PassLabel, str] = _extract_kinds(Scope.CONTRIBUTION)
"""The task kind of each contribution extraction pass (slice 3b); one task per work per pass."""


MINE_KINDS: dict[PassLabel, str] = {
    label: _REGISTRY.kind_for("mining", label=label) for label in PassLabel
}
"""The task kinds of the passes of registered miners; every miner shares them."""


def kinds_for(scope: ScopeKey) -> dict[PassLabel, str]:
    """The extraction task kinds of `scope`."""
    if isinstance(scope, MinerScope):
        return MINE_KINDS
    return CONTRIB_KINDS if scope is Scope.CONTRIBUTION else EXTRACT_KINDS


def is_mine_kind(kind: str) -> bool:
    """Whether `kind` is a task kind of registered miners (`mine_a`, `mine_b`)."""
    info = _REGISTRY.describe(kind)
    return info is not None and info.module == "mining"


def scope_of_kind(kind: str) -> Scope | None:
    """The scope an extraction task kind belongs to; None for any other kind."""
    info = _REGISTRY.describe(kind)
    if info is None or info.scope is None:
        return None
    return Scope(info.scope)


def require_pass_stage(stage: ScreeningStage) -> ScreeningStage:
    """`stage` itself when a pass can run at it; raises on field `stage` for `either`."""
    if stage is ScreeningStage.EITHER:
        raise FactoryValidationError(
            [ValidationIssue("stage", "a screening run is title-abstract or full-text, not either")]
        )
    return stage


def task_kind(stage: ScreeningStage, label: PassLabel) -> str:
    """The task kind of pass `label` at `stage`: `screen_a`/`screen_b` or `screen_ft_a`/`_b`."""
    return _REGISTRY.kind_for("screening", stage=require_pass_stage(stage).value, label=label)


def stage_of_kind(kind: str) -> ScreeningStage | None:
    """The stage a screening task kind belongs to; None for any other kind."""
    info = _REGISTRY.describe(kind)
    if info is None or info.stage is None:
        return None
    return ScreeningStage(info.stage)


def screening_plan(protocol: "ProtocolVersion", stage: ScreeningStage) -> ScreeningPlan:
    """The plan that governs `stage`. Raises on field `full_text_screening` at full text when the
    protocol declares no plan (R-13: declare the full-text screening plan first)."""
    if require_pass_stage(stage) is ScreeningStage.TITLE_ABSTRACT:
        return protocol.spec.screening
    plan = protocol.spec.full_text_screening
    if plan is None:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "full_text_screening",
                    "declare the full-text screening plan in the protocol first (R-13)",
                )
            ]
        )
    return plan
