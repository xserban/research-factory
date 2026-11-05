"""Dual extraction of contribution items (contribution pack); writes the extraction family.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
    QualityRegime,
)
from factory.services.modules.base import RuleModule
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="contributions",
    kind=ModuleKind.MINER,
    inputs=(
        ArtifactKind.CONVERSION,
        ArtifactKind.PROTOCOL,
    ),
    outputs=(ArtifactKind.RECORD,),
    events=EventFamily(
        note=(
            "writes the extraction.* family, discriminated by pack (slice"
            " M ruling 2); its gates are extraction.resolve and "
            "extraction.audit_label."
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("contributions"),
    protocol_sections=("contribution_schema",),
    regime=QualityRegime(
        2,
        "session-and-model",
        "field-value",
        "none",
        "agreed-sample",
        ("amendment", "document-version", "conversion"),
    ),
    checks=(
        CheckRule("contribution-missing-extraction", ("warning", "warning", "error")),
        CheckRule("contribution-stale", ("warning", "warning", "warning")),
        CheckRule("contribution-schema-missing", (None, "warning", "error")),
        CheckRule("contribution-closed-without-items", ("warning", "warning", "warning")),
        CheckRule("contribution-error-ceiling", (None, "warning", "error")),
    ),
)

MODULE = RuleModule(SPEC)
