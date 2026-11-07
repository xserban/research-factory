"""Screening rankings: records ordered by similarity to the development seeds.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="ranking",
    kind=ModuleKind.BUILDER,
    inputs=(ArtifactKind.WORK, ArtifactKind.SEED),
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(
        types=("ranking.computed",),
        tables=(
            "ranking_positions",
            "rankings",
        ),
        system_only=True,
    ),
)

MODULE = RuleModule(SPEC)
