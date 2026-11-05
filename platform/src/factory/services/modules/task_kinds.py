"""The task kinds of the built modules, registered once (slice M ruling 21, decision 55).

Kind strings are persisted in `task.created` events and must not change. Everything else asks
`default_task_kinds()`; no other service writes a kind literal.

Invariants:
- The registry is built once and shared; callers only read it.
- A kind's `(module, stage, label, scope)` is unique (the registry enforces it).
"""

from functools import lru_cache

from factory.model.extraction import Scope
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.model.task import (
    CONSOLIDATE_TASK_KIND,
    DRAFT_SLOT_TASK_KIND,
    HYPOTHESIS_REVIEW_TASK_KIND,
    INTUITION_TASK_KIND,
)
from factory.modules.registry import TaskKindRegistry

_SCREENING: tuple[tuple[str, ScreeningStage, PassLabel], ...] = (
    ("screen_a", ScreeningStage.TITLE_ABSTRACT, PassLabel.A),
    ("screen_b", ScreeningStage.TITLE_ABSTRACT, PassLabel.B),
    ("screen_ft_a", ScreeningStage.FULL_TEXT, PassLabel.A),
    ("screen_ft_b", ScreeningStage.FULL_TEXT, PassLabel.B),
)
_EXTRACTION: tuple[tuple[str, str, str, PassLabel], ...] = (
    ("extract_a", "extraction", Scope.EVIDENCE.value, PassLabel.A),
    ("extract_b", "extraction", Scope.EVIDENCE.value, PassLabel.B),
    ("contrib_a", "contributions", Scope.CONTRIBUTION.value, PassLabel.A),
    ("contrib_b", "contributions", Scope.CONTRIBUTION.value, PassLabel.B),
)
_MINING: tuple[tuple[str, PassLabel], ...] = (("mine_a", PassLabel.A), ("mine_b", PassLabel.B))
"""The task kinds of registered miners: the miner is in the task content (`TASK_KIND_RE` admits
no digits or hyphens, so a kind per miner is not possible; slice M, Generic mine path)."""


@lru_cache(maxsize=1)
def default_task_kinds() -> TaskKindRegistry:
    """Every task kind of the platform, with the module and pass each belongs to."""
    registry = TaskKindRegistry()
    for kind, stage, label in _SCREENING:
        registry.register(kind, "screening", stage=stage.value, label=label, scope=None)
    for kind, module, scope, label in _EXTRACTION:
        registry.register(kind, module, stage=None, label=label, scope=scope)
    for kind, label in _MINING:
        registry.register(kind, "mining", stage=None, label=label, scope=None)
    registry.register(INTUITION_TASK_KIND, "intuition", stage=None, label=None, scope=None)
    registry.register(HYPOTHESIS_REVIEW_TASK_KIND, "hypotheses", stage=None, label=None, scope=None)
    registry.register(CONSOLIDATE_TASK_KIND, "labels", stage=None, label=None, scope=None)
    registry.register(DRAFT_SLOT_TASK_KIND, "writing", stage=None, label=None, scope=None)
    return registry
