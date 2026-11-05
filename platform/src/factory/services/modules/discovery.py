"""The discovery record: how each work was found (computed on read).

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="discovery",
    kind=ModuleKind.BUILDER,
    outputs=(ArtifactKind.WORK,),
)

MODULE = RuleModule(SPEC)
