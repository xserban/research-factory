"""The portfolio across projects.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="portfolio",
    kind=ModuleKind.BUILDER,
    outputs=(ArtifactKind.REPORT,),
)

MODULE = RuleModule(SPEC)
