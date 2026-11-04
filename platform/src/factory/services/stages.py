"""The stage dimension of screening: which stages a pass can run at, its task kinds and its plan.

A pass runs at `title-abstract` or `full-text`; `either` is a criterion's `applies_at` only and is
refused as the stage of a run. Full-text screening needs a declared plan
(`ProtocolSpec.full_text_screening`, R-13); title/abstract uses `ProtocolSpec.screening`.

Invariants:
- Every refusal is a FactoryValidationError and writes nothing.
- `task_kind` and `stage_of_kind` are inverse on the four screening task kinds.
- `kinds_for` and `scope_of_kind` are inverse on the four extraction task kinds.
"""

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.extraction import Scope
from factory.model.protocol import ScreeningPlan, ScreeningStage
from factory.model.screening import PassLabel
from factory.services.protocol import ProtocolVersion

_KINDS: dict[tuple[ScreeningStage, PassLabel], str] = {
    (ScreeningStage.TITLE_ABSTRACT, PassLabel.A): "screen_a",
    (ScreeningStage.TITLE_ABSTRACT, PassLabel.B): "screen_b",
    (ScreeningStage.FULL_TEXT, PassLabel.A): "screen_ft_a",
    (ScreeningStage.FULL_TEXT, PassLabel.B): "screen_ft_b",
}

EXTRACT_KINDS: dict[PassLabel, str] = {PassLabel.A: "extract_a", PassLabel.B: "extract_b"}
"""The task kind of each evidence extraction pass; one task per work per pass."""

CONTRIB_KINDS: dict[PassLabel, str] = {PassLabel.A: "contrib_a", PassLabel.B: "contrib_b"}
"""The task kind of each contribution extraction pass (slice 3b); one task per work per pass."""


def kinds_for(scope: Scope) -> dict[PassLabel, str]:
    """The extraction task kinds of `scope`."""
    return CONTRIB_KINDS if scope is Scope.CONTRIBUTION else EXTRACT_KINDS


def scope_of_kind(kind: str) -> Scope | None:
    """The scope an extraction task kind belongs to; None for any other kind."""
    for scope in Scope:
        if kind in kinds_for(scope).values():
            return scope
    return None


def require_pass_stage(stage: ScreeningStage) -> ScreeningStage:
    """`stage` itself when a pass can run at it; raises on field `stage` for `either`."""
    if stage is ScreeningStage.EITHER:
        raise FactoryValidationError(
            [ValidationIssue("stage", "a screening run is title-abstract or full-text, not either")]
        )
    return stage


def task_kind(stage: ScreeningStage, label: PassLabel) -> str:
    """The task kind of pass `label` at `stage`: `screen_a`/`screen_b` or `screen_ft_a`/`_b`."""
    return _KINDS[(require_pass_stage(stage), label)]


def stage_of_kind(kind: str) -> ScreeningStage | None:
    """The stage a screening task kind belongs to; None for any other kind."""
    for (stage, _), known in _KINDS.items():
        if known == kind:
            return stage
    return None


def screening_plan(protocol: ProtocolVersion, stage: ScreeningStage) -> ScreeningPlan:
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
