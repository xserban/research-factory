"""The evidence report: groups, frontier and conflicts over final extraction rows.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="evidence",
    kind=ModuleKind.BUILDER,
    inputs=(ArtifactKind.RECORD,),
    outputs=(ArtifactKind.REPORT,),
    checks=(
        CheckRule("evidence-excluded-rows", ("warning", "warning", "warning")),
        CheckRule("evidence-ungrouped", ("warning", "warning", "warning")),
        CheckRule("evidence-direction", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
