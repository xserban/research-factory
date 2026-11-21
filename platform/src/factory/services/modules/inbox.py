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
            "inbox.prioritised",
        ),
        tables=(
            "inbox_items",
            "inbox_resolutions",
            "inbox_hints",
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
        GateSpec(
            "inbox.prioritise",
            GateKind.DECISION,
            ("inbox.prioritised",),
            PolicyKind.HUMAN,
            ("plan XL PD-10", "R-34"),
        ),
    ),
    checks=(
        CheckRule("inbox-open-after-screening", ("warning", "warning", "warning")),
        CheckRule("inbox-resolve-failed", ("warning", "warning", "warning")),
        CheckRule("supplied-without-plan", (None, "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
