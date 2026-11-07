"""Suggest and select: the decisions the scientist owns (slice 8, plan A).

Declaration only (slice M, decision 55); behaviour stays in `services/decisions.py`. An agent
proposes a set of items and a human selects; the selection is the human act, so no gate of the
registry stands over it (a gate would let a policy hand it to an agent). The check rules
(`services/decision_check.py`) are advisory except `record-without-selection`, an error in
`pilot` and `systematic`; the contract has no advisory severity, so advisory is a warning."""

from factory.modules.contract import CheckRule, EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="decisions",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=("decision.suggested", "decision.selected"),
        tables=("decision_sets", "decision_items"),
    ),
    checks=(
        CheckRule("record-without-selection", ("warning", "error", "error")),
        CheckRule("selection-not-acted", ("warning", "warning", "warning")),
        CheckRule("ungrounded-item", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
