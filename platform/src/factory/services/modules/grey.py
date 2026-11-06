"""Grey literature: declared sources, captured snapshots and reported searches.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="grey",
    kind=ModuleKind.RETRIEVAL,
    outputs=(ArtifactKind.WORK,),
    events=EventFamily(
        types=("grey.contact_logged", "grey.search_reported"),
        tables=("grey_contacts", "grey_searches"),
    ),
    protocol_sections=("grey_sources",),
    checks=(
        CheckRule("grey-undeclared", ("warning", "warning", "error")),
        CheckRule("grey-reported-only", ("warning", "warning", "error")),
    ),
)

MODULE = RuleModule(SPEC)
