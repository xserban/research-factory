"""The benchmark ledger: reported against reproduced and own results (slice 6, plan XP-B).

Declaration only (slice M, decision 55); behaviour stays in the services. A builder: it reads the
evidence report and the evaluations and writes nothing; slice 5 keeps `ledger` for credit."""

from factory.modules.contract import (
    ArtifactKind,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="benchmark_ledger",
    kind=ModuleKind.BUILDER,
    inputs=(ArtifactKind.REPORT,),
    outputs=(ArtifactKind.REPORT,),
)

MODULE = RuleModule(SPEC)
