"""Per-paper appraisal with a declared instrument (IDEA-21, R-41).

Declaration only (slice M, decision 55); behaviour stays in `services/appraisal.py`. Optional:
a project that declares no `appraisal_instrument` sees at most one `check` warning in
`systematic` mode, no gate and no blocker."""

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
    name="appraisal",
    kind=ModuleKind.MINER,
    inputs=(
        ArtifactKind.CONVERSION,
        ArtifactKind.PROTOCOL,
    ),
    outputs=(ArtifactKind.RECORD,),
    events=EventFamily(
        types=(
            "appraisal.audit_labelled",
            "appraisal.audit_sampled",
            "appraisal.judged",
            "appraisal.recorded",
            "appraisal.resolved",
        ),
        tables=(
            "appraisal_answers",
            "appraisal_audit_items",
            "appraisal_audits",
            "appraisal_closures",
            "appraisal_judgements",
        ),
        note=(
            "a judgement item is a human act (events.actor.kind human), refused to an agent at"
            " the service and ignored by the fold; no total, weight or grade exists (decision 42)."
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("appraisal"),
    protocol_sections=("appraisal_instrument",),
    regime=QualityRegime(
        2,
        "session-and-model",
        "item-answer",
        "none",
        "agreed-sample",
        ("amendment", "conversion"),
    ),
    checks=(
        CheckRule("appraisal-open", ("warning", "warning", "warning")),
        CheckRule("appraisal-unjudged", ("warning", "warning", "warning")),
        CheckRule("appraisal-stale", ("warning", "warning", "warning")),
        CheckRule("appraisal-not-declared", (None, None, "warning")),
    ),
)

MODULE = RuleModule(SPEC)
