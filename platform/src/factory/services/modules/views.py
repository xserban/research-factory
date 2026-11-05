"""The read-only views over the log (slice 7b, plan V-A): the onion view and processing depth.

Declaration only (slice M, decision 55); behaviour stays in the services. A builder owns no event
type, table, gate or task kind: it writes nothing."""

from factory.modules.contract import (
    ArtifactKind,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="views",
    kind=ModuleKind.BUILDER,
    inputs=(ArtifactKind.WORK, ArtifactKind.RELATION),
    outputs=(ArtifactKind.REPORT,),
)

MODULE = RuleModule(SPEC)
