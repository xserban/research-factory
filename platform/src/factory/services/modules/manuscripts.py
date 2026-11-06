"""Verification of external manuscripts against the corpus (slice 7b, plan W-C).

Declaration only (slice M, decision 55); behaviour stays in the services. A manuscript's cited
sentences are checked by one verifier pass, with a human audit of a sample of positive verdicts:
the writer is outside the factory, so no session or model has to be kept apart from it (plan
ruling 6)."""

from factory.modules.contract import (
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
    name="manuscripts",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "manuscript.added",
            "manuscript.audit_drawn",
            "manuscript.audited",
            "manuscript.citation_decided",
            "manuscript.citation_resolved",
            "manuscript.segmented",
            "manuscript.unit_closed",
            "manuscript.verified",
        ),
        tables=(
            "manuscript_audit_items",
            "manuscript_audits",
            "manuscript_citations",
            "manuscript_closures",
            "manuscript_flags",
            "manuscript_sentences",
            "manuscript_verdicts",
            "manuscripts",
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("manuscripts"),
    regime=QualityRegime(1, "none", "unit", "none", "gate-sample", ()),
    checks=(
        CheckRule("manuscript-citation-unresolved", ("warning", "warning", "warning")),
        CheckRule("manuscript-unverified", ("warning", "warning", "warning")),
    ),
    gates=(
        GateSpec(
            "manuscript.citation_confirm",
            GateKind.DECISION,
            ("manuscript.citation_decided",),
            PolicyKind.AGENT_AUDIT,
            ("slice 7b ruling 17", "slice 3a ruling 3"),
        ),
        GateSpec(
            "manuscript.audit_label",
            GateKind.DECISION,
            ("manuscript.audited",),
            PolicyKind.HUMAN,
            ("slice 7b ruling 12", "slice 7b ruling 17", "R-131"),
        ),
    ),
)

MODULE = RuleModule(SPEC)
