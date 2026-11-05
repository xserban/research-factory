"""The computed outcome of registered hypotheses (slice 6, plan XP-B; R-121).

Declaration only (slice M, decision 55); behaviour stays in the services. The outcome is a builder
result: the platform writes `hypothesis.evaluated` as a `system` actor from recorded results and
the rule fixed at registration; no agent or human writes it."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="evaluation",
    kind=ModuleKind.BUILDER,
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(
        types=("hypothesis.evaluated",),
        tables=("hypothesis_evaluations",),
        system_only=True,
    ),
    checks=(
        CheckRule("evaluation-stale", ("error", "error", "error")),
        CheckRule("evaluation-event-foreign", ("warning", "warning", "warning")),
        CheckRule("hypothesis-evaluated-unconcluded", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
