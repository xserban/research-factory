"""Dual extraction of field records (evidence pack), with agreement, resolution and audit.

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
    QualityRegime,
)
from factory.services.modules.base import RuleModule
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="extraction",
    kind=ModuleKind.MINER,
    inputs=(
        ArtifactKind.CONVERSION,
        ArtifactKind.PROTOCOL,
    ),
    outputs=(
        ArtifactKind.RECORD,
        ArtifactKind.CLAIM,
    ),
    events=EventFamily(
        types=(
            "extraction.audit_labelled",
            "extraction.audit_sampled",
            "extraction.claim_recorded",
            "extraction.closed",
            "extraction.pass_joined",
            "extraction.pass_opened",
            "extraction.recorded",
            "extraction.resolved",
        ),
        tables=(
            "extraction_audit_items",
            "extraction_audits",
            "extraction_claims",
            "extraction_closures",
            "extraction_fields",
            "extraction_passes",
            "extraction_resolutions",
            "extraction_rows",
            "extraction_sessions",
        ),
        note=(
            "historical name: every field miner writes this family (slice"
            " M ruling 2); the pack on each event says which."
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("extraction"),
    protocol_sections=("extraction_schema",),
    gates=(
        GateSpec(
            "extraction.resolve",
            GateKind.DECISION,
            ("extraction.resolved",),
            PolicyKind.HUMAN,
            ("decision 51",),
        ),
        GateSpec(
            "extraction.audit_label",
            GateKind.DECISION,
            ("extraction.audit_labelled",),
            PolicyKind.HUMAN,
            ("decision 51",),
        ),
    ),
    regime=QualityRegime(
        2,
        "session-and-model",
        "field-value",
        "none",
        "agreed-sample",
        ("amendment", "document-version", "conversion"),
    ),
    checks=(
        CheckRule("extraction-pending", ("warning", "warning", "warning")),
        CheckRule("extraction-single", (None, "warning", "error")),
        CheckRule("extraction-unresolved", (None, "warning", "error")),
        CheckRule("extraction-audit-missing", (None, "warning", "error")),
        CheckRule("extraction-error-high", (None, "warning", "error")),
        CheckRule("extraction-schema-stale", ("warning", "warning", "warning")),
        CheckRule("extraction-library-missing", ("warning", "warning", "warning")),
        CheckRule("extraction-document-stale", ("warning", "warning", "warning")),
        CheckRule("extraction-copy-flag", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
