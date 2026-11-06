"""The evidence report: groups, frontier and conflicts over final extraction rows.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    BuilderReads,
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
    # The report reads the evidence schema and, dynamically, each miner version the protocol
    # admits as evidence (`services/evidence_miners.admitted_miners`); `check` adds those to
    # the static pairs so `miner-version-unread` clears for them.
    reads=BuilderReads(miners=()),
    checks=(
        CheckRule("evidence-excluded-rows", ("warning", "warning", "warning")),
        CheckRule("evidence-ungrouped", ("warning", "warning", "warning")),
        CheckRule("evidence-direction", ("warning", "warning", "warning")),
        CheckRule("copied-value-differs", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
