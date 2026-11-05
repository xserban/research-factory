"""Leads, hypotheses, the critic review, registration and model cut-offs.

Declaration only (slice M, decision 55); behaviour stays in the services. Leads and hypotheses are
proposals an agent writes and a gate holder decides; the critic review is a quality regime, not a
gate (slice 6 reconciliation item 1)."""

from factory.modules.contract import (
    EventFamily,
    GateKind,
    GateSpec,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="hypotheses",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "hypothesis.abandoned",
            "hypothesis.concluded",
            "hypothesis.drafted",
            "lead.decided",
            "lead.recorded",
        ),
        tables=(
            "hypotheses",
            "lead_keys",
            "lead_triggers",
            "leads",
        ),
    ),
    protocol_sections=("hypothesis_plan",),
    gates=(
        GateSpec(
            "hypotheses.lead_decide",
            GateKind.DECISION,
            ("lead.decided",),
            PolicyKind.AGENT,
            ("slice 6 ruling 11", "R-51"),
        ),
    ),
)

MODULE = RuleModule(SPEC)
