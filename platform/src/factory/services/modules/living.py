"""Living review: watch cycles, notices, versions and registered conclusions.

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
    name="living",
    kind=ModuleKind.RETRIEVAL,
    outputs=(
        ArtifactKind.WORK,
        ArtifactKind.DOCUMENT,
    ),
    events=EventFamily(
        types=(
            "conclusion.registered",
            "conclusion.retired",
            "document.preferred",
            "notice.assessed",
            "notice.observed",
            "version.linked",
            "version.observed",
            "watch.cycle_finished",
            "watch.cycle_started",
        ),
        tables=(
            "conclusions",
            "document_preferences",
            "notice_assessments",
            "notices",
            "version_links",
            "version_observations",
            "watch_cycle_runs",
            "watch_cycle_sources",
            "watch_cycles",
            "work_aliases",
        ),
        note=(
            "document.preferred is written by version tracking, so it is "
            "owned here, not by conversion."
        ),
    ),
    protocol_sections=("watch_plan",),
    gates=(
        GateSpec(
            "living.notice_assess",
            GateKind.DECISION,
            ("notice.assessed",),
            PolicyKind.HUMAN,
            ("slice 4b ruling 12",),
        ),
        GateSpec(
            "living.document_prefer",
            GateKind.DECISION,
            ("document.preferred",),
            PolicyKind.HUMAN,
            ("slice 4b ruling 15",),
        ),
        GateSpec(
            "living.conclusion_register",
            GateKind.DECISION,
            (
                "conclusion.registered",
                "conclusion.retired",
            ),
            PolicyKind.HUMAN,
            ("slice 4b ruling 16",),
        ),
    ),
    checks=(
        CheckRule("watch-plan-missing", ("warning", "error", "error")),
        CheckRule("watch-overdue", ("warning", "warning", "warning")),
        CheckRule("watch-source-failing", ("warning", "warning", "error")),
        CheckRule("watch-cycle-open", ("warning", "warning", "warning")),
        CheckRule("window-misses", ("warning", "warning", "warning")),
        CheckRule("update-audit-outstanding", (None, "warning", "error")),
        CheckRule("included-retracted", ("warning", "warning", "error")),
        CheckRule("notice-unassessed", ("warning", "warning", "warning")),
        CheckRule("notice-unchecked-crossref", ("warning", "warning", "warning")),
        CheckRule("notice-coverage-age", ("warning", "warning", "warning")),
        CheckRule("newer-version-available", ("warning", "warning", "warning")),
        CheckRule("version-of-record-available", ("warning", "warning", "warning")),
        CheckRule("version-link-conflict", ("warning", "warning", "warning")),
        CheckRule("status-lookup-failed", ("warning", "warning", "warning")),
        CheckRule("conclusion-changed", ("warning", "warning", "warning")),
        CheckRule("conclusion-basis-affected", ("warning", "warning", "error")),
    ),
)

MODULE = RuleModule(SPEC)
