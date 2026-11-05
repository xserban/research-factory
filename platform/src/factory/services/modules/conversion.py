"""Conversion of stored documents to canonical Markdown with anchors.

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
    name="conversion",
    kind=ModuleKind.TRANSFORM,
    inputs=(ArtifactKind.DOCUMENT,),
    outputs=(ArtifactKind.CONVERSION,),
    events=EventFamily(
        types=(
            "document.conversion_failed",
            "document.converted",
        ),
        tables=(
            "document_conversions",
            "document_failures",
        ),
    ),
    checks=(CheckRule("conversion-not-chosen", ("warning", "warning", "warning")),),
)

MODULE = RuleModule(SPEC)
