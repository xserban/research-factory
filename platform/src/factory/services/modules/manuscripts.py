"""Verification of external manuscripts against the corpus (slice 7b, plan W-C).

Declaration only (slice M, decision 55); behaviour stays in the services. A manuscript's cited
sentences are checked by one verifier pass, with a human audit of a sample of positive verdicts:
the writer is outside the factory, so no session or model has to be kept apart from it (plan
ruling 6)."""

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

SPEC = ModuleSpec(
    name="manuscripts",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "manuscript.added",
            "manuscript.citation_decided",
            "manuscript.citation_resolved",
            "manuscript.segmented",
            "manuscript.unit_closed",
        ),
        tables=(
            "manuscript_citations",
            "manuscript_closures",
            "manuscript_sentences",
            "manuscripts",
        ),
    ),
    regime=QualityRegime(1, "none", "unit", "none", "gate-sample", ()),
    gates=(
        GateSpec(
            "manuscript.citation_confirm",
            GateKind.DECISION,
            ("manuscript.citation_decided",),
            PolicyKind.AGENT_AUDIT,
            ("slice 7b ruling 17", "slice 3a ruling 3"),
        ),
    ),
)

MODULE = RuleModule(SPEC)
