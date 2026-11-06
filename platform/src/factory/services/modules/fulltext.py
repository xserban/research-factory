"""Acquisition of full-text documents into the library.

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
    name="fulltext",
    kind=ModuleKind.TRANSFORM,
    inputs=(ArtifactKind.WORK,),
    outputs=(
        ArtifactKind.FETCH,
        ArtifactKind.ATTEMPT,
        ArtifactKind.DOCUMENT,
    ),
    events=EventFamily(
        types=(
            "fulltext.attempted",
            "fulltext.document_added",
            "fulltext.fetch_started",
            "fulltext.source_changed",
            "fulltext.source_resolved",
        ),
        tables=(
            "fulltext_attempts",
            "fulltext_documents",
            "fulltext_fetches",
            "fulltext_source_changes",
        ),
    ),
    checks=(
        CheckRule("library-missing", ("warning", "warning", "warning")),
        CheckRule("library-corrupt", ("error", "error", "error")),
        CheckRule("source-changed", ("warning", "warning", "warning")),
        CheckRule("source-version-differs", ("warning", "warning", "warning")),
        CheckRule("fulltext-unsought", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
