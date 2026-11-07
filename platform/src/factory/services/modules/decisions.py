"""Suggest and select: the decisions the scientist owns (slice 8, plan A).

Declaration only (slice M, decision 55); behaviour stays in `services/decisions.py`. An agent
proposes a set of items and a human selects; the selection is the human act, so no gate of the
registry stands over it (a gate would let a policy hand it to an agent). The check rules land
with plan task A8."""

from factory.modules.contract import EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="decisions",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=("decision.suggested", "decision.selected"),
        tables=("decision_sets", "decision_items"),
    ),
)

MODULE = RuleModule(SPEC)
