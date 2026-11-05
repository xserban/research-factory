"""Writing from verified material: drafts, sentences, supports and write-time checks (slice 7b,
plan W-A).

Declaration only (slice M, decision 55); behaviour stays in the services. Drafting is a proposal an
agent or a human makes sentence by sentence; its quality regime is one independent verifier pass
and a human audit of a sample of positive verdicts, and a draft leaves through the gate
`writing.release`, whose exploratory and pilot presets are in `modules/presets.py` (plan W-B)."""

from factory.modules.contract import (
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
    name="writing",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "draft.audit_drawn",
            "draft.audited",
            "draft.created",
            "draft.outline_repinned",
            "draft.released",
            "draft.reordered",
            "draft.sentence_recorded",
            "draft.sentence_withdrawn",
            "draft.verified",
        ),
        tables=(
            "draft_audit_items",
            "draft_audits",
            "draft_releases",
            "draft_sections",
            "draft_sentences",
            "drafts",
            "sentence_flags",
            "sentence_stats",
            "sentence_supports",
            "sentence_verdicts",
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("writing"),
    regime=QualityRegime(
        1,
        "session-and-model",
        "sentence",
        "none",
        "gate-sample",
        ("support-eligibility", "stat-value"),
    ),
    gates=(
        GateSpec(
            "writing.release",
            GateKind.DECISION,
            ("draft.released",),
            PolicyKind.AGENT,
            ("slice 7b ruling 13", "R-39", "R-130"),
        ),
        GateSpec(
            "writing.audit_label",
            GateKind.DECISION,
            ("draft.audited",),
            PolicyKind.HUMAN,
            ("slice 7b ruling 12", "R-131"),
        ),
    ),
)

MODULE = RuleModule(SPEC)
