"""Merging of duplicate works.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="dedup",
    kind=ModuleKind.TRANSFORM,
    inputs=(ArtifactKind.WORK,),
    outputs=(ArtifactKind.MERGE,),
    events=EventFamily(
        types=(
            "dedup.merged",
            "dedup.reverted",
        ),
        tables=(
            "blocked_pairs",
            "merge_members",
            "merges",
        ),
    ),
    checks=(CheckRule("merge-verdict-conflict", ("warning", "warning", "warning")),),
)

MODULE = RuleModule(SPEC)
