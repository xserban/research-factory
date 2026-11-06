"""Dual screening with calibration, agreement and audit (title-abstract and full-text stages).

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
    name="screening",
    kind=ModuleKind.FILTER,
    inputs=(
        ArtifactKind.WORK,
        ArtifactKind.PROTOCOL,
    ),
    outputs=(ArtifactKind.DECISION,),
    events=EventFamily(
        types=(
            "audit.labelled",
            "audit.sampled",
            "calibration.drawn",
            "calibration.labelled",
            "screening.decision_recorded",
            "screening.disagreement_resolved",
            "screening.pass_joined",
            "screening.pass_opened",
            "screening.sample_extended",
        ),
        tables=(
            "audit_events",
            "audit_items",
            "audit_top_ups",
            "audits",
            "calibration_draws",
            "calibration_items",
            "calibration_labels",
            "decisions",
            "label_sessions",
            "pass_sessions",
            "passes",
            "resolutions",
            "stage_judges",
        ),
        note=(
            "label_sessions is also written by the notice projection (a "
            "relayed assessment); its owner is the module whose pass "
            "joins it constrains."
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("screening"),
    protocol_sections=(
        "screening",
        "full_text_screening",
    ),
    gates=(
        GateSpec(
            "screening.calibration_label",
            GateKind.DECISION,
            ("calibration.labelled",),
            PolicyKind.HUMAN,
            ("decision 37 items 5, 6",),
        ),
        GateSpec(
            "screening.resolve",
            GateKind.DECISION,
            ("screening.disagreement_resolved",),
            PolicyKind.HUMAN,
            ("decision 37 item 6",),
        ),
        GateSpec(
            "screening.audit_label",
            GateKind.DECISION,
            ("audit.labelled",),
            PolicyKind.HUMAN,
            ("decision 37 item 6",),
        ),
    ),
    regime=QualityRegime(
        2,
        "session-model-and-user",
        "outcome",
        "human-labelled",
        "agreed-sample",
        ("amendment", "document-version"),
    ),
    checks=(
        CheckRule("screening-pending", ("warning", "warning", "warning")),
        CheckRule("single-pass", (None, "warning", "error")),
        CheckRule("calibration-missing", (None, "error", "error")),
        CheckRule("kappa-below-floor", ("warning", "warning", "warning")),
        CheckRule("audit-missing", (None, "warning", "error")),
        CheckRule("audit-error-high", (None, "warning", "error")),
        CheckRule("fulltext-decision-stale-document", ("warning", "warning", "warning")),
        CheckRule("calibration-model-drift", (None, "warning", "error")),
        CheckRule("pass-same-user", ("error", "error", "error")),
    ),
)

MODULE = RuleModule(SPEC)
