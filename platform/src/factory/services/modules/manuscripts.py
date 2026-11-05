"""Verification of external manuscripts against the corpus (slice 7b, plan W-C).

Declaration only (slice M, decision 55); behaviour stays in the services. A manuscript's cited
sentences are checked by one verifier pass, with a human audit of a sample of positive verdicts:
the writer is outside the factory, so no session or model has to be kept apart from it (plan
ruling 6)."""

from factory.modules.contract import EventFamily, ModuleKind, ModuleSpec, QualityRegime
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="manuscripts",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=("manuscript.added", "manuscript.segmented"),
        tables=("manuscript_sentences", "manuscripts"),
    ),
    regime=QualityRegime(1, "none", "unit", "none", "gate-sample", ()),
)

MODULE = RuleModule(SPEC)
