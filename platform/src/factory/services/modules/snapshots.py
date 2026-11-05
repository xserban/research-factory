"""Living-review snapshots and the digest: computed outputs recorded by the platform.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="snapshots",
    kind=ModuleKind.BUILDER,
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(
        types=(
            "digest.generated",
            "living.snapshot_recorded",
        ),
        tables=(
            "digests",
            "snapshots",
        ),
        system_only=True,
    ),
)

MODULE = RuleModule(SPEC)
