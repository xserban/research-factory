"""Generic mining over registered miners (slice M, M-C).

Declaration only (decision 55); behaviour stays in `services/mining.py`. The module grows with
the plan: task kinds here, the registration event, the `miners` section, the gate and the check
rules as their tasks land."""

from factory.modules.contract import (
    ArtifactKind,
    EventFamily,
    ModuleKind,
    ModuleSpec,
    QualityRegime,
)
from factory.services.modules.base import RuleModule
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="mining",
    kind=ModuleKind.MINER,
    inputs=(ArtifactKind.CONVERSION, ArtifactKind.PROTOCOL, ArtifactKind.MINER),
    outputs=(ArtifactKind.RECORD,),
    events=EventFamily(
        types=("miner.registered",),
        tables=("miners",),
        note="registered miners are data; their records are written in the extraction.* family.",
    ),
    task_kinds=default_task_kinds().kinds_of("mining"),
    protocol_sections=("miners",),
    regime=QualityRegime(
        2,
        "session-and-model",
        "field-value",
        "none",
        "agreed-sample",
        ("amendment", "document-version", "conversion"),
    ),
)

MODULE = RuleModule(SPEC)
