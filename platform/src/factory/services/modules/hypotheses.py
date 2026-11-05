"""Leads, hypotheses, the critic review, registration and model cut-offs.

Declaration only (slice M, decision 55); behaviour stays in the services. Leads and hypotheses are
proposals an agent writes and a gate holder decides; the critic review is a quality regime, not a
gate (slice 6 reconciliation item 1)."""

from factory.modules.contract import (
    CheckRule,
    EventFamily,
    GateKind,
    GateSpec,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
)
from factory.services.modules.base import RuleModule
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="hypotheses",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "hypothesis.abandoned",
            "hypothesis.concluded",
            "hypothesis.drafted",
            "hypothesis.registered",
            "hypothesis.reviewed",
            "lead.decided",
            "lead.recorded",
            "model.cutoff_declared",
        ),
        tables=(
            "hypotheses",
            "hypothesis_registrations",
            "hypothesis_reviews",
            "lead_keys",
            "lead_triggers",
            "leads",
            "model_cutoffs",
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("hypotheses"),
    protocol_sections=("hypothesis_plan",),
    gates=(
        GateSpec(
            "hypotheses.register",
            GateKind.DECISION,
            ("hypothesis.registered",),
            PolicyKind.AGENT,
            ("slice 6 ruling 14", "R-51", "R-52", "R-53"),
        ),
        GateSpec(
            "hypotheses.lead_decide",
            GateKind.DECISION,
            ("lead.decided",),
            PolicyKind.AGENT,
            ("slice 6 ruling 11", "R-51"),
        ),
    ),
    checks=(
        CheckRule("lead-undecided", (None, "warning", "warning")),
        CheckRule("hypothesis-unreviewed", (None, "warning", "warning")),
        CheckRule("hypothesis-registered-untested", ("warning", "warning", "warning")),
        CheckRule("hypothesis-cutoff-unknown", ("warning", "warning", "error")),
        CheckRule("hypothesis-contaminated", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
