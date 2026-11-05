"""The inbox of supplied links and their lookups.

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
    name="inbox",
    kind=ModuleKind.RETRIEVAL,
    outputs=(ArtifactKind.WORK,),
    events=EventFamily(
        types=(
            "inbox.link_added",
            "inbox.link_resolved",
            "inbox.link_withdrawn",
        ),
        tables=(
            "inbox_items",
            "inbox_resolutions",
        ),
    ),
    protocol_sections=("supplied_links",),
    gates=(
        GateSpec(
            "inbox.withdraw",
            GateKind.DECISION,
            ("inbox.link_withdrawn",),
            PolicyKind.HUMAN,
            ("slice 4a ruling 13",),
        ),
    ),
    checks=(
        CheckRule("inbox-open-after-screening", ("warning", "warning", "warning")),
        CheckRule("inbox-resolve-failed", ("warning", "warning", "warning")),
        CheckRule("supplied-without-plan", (None, "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
