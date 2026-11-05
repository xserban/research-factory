"""Briefings and agent context packs (slice 7b, plan V-C).

Declaration only (slice M, decision 55); behaviour stays in the services. A builder: it declares no
gate and owns one system event, `briefing.served`, which records the pack a session received."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="briefing",
    kind=ModuleKind.BUILDER,
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(
        types=("briefing.served",),
        tables=("briefings_served",),
        system_only=True,
    ),
    checks=(CheckRule("briefing-stale", ("warning", "warning", "warning")),),
)

MODULE = RuleModule(SPEC)
