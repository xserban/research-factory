"""Merging of duplicate works.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    GateKind,
    GateSpec,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
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
            "dedup.pair_decided",
            "dedup.reverted",
        ),
        tables=(
            "blocked_pairs",
            "dedup_pair_decisions",
            "merge_members",
            "merges",
        ),
    ),
    checks=(
        CheckRule("merge-verdict-conflict", ("warning", "warning", "warning")),
        CheckRule("version-pair-outcome-conflict", ("warning", "warning", "warning")),
    ),
    gates=(
        GateSpec(
            "dedup.version_pair",
            GateKind.DECISION,
            ("dedup.pair_decided",),
            PolicyKind.HUMAN,
            ("decision 117",),
        ),
    ),
)

MODULE = RuleModule(SPEC)
