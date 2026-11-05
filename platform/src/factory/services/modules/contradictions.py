"""Claim contradictions proposed by an agent and decided by a human.

Declaration only (slice M, decision 55); behaviour stays in the services."""

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
    name="contradictions",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "contradiction.decided",
            "contradiction.proposed",
        ),
        tables=("contradictions",),
    ),
    gates=(
        GateSpec(
            "hypotheses.contradiction_confirm",
            GateKind.DECISION,
            ("contradiction.decided",),
            PolicyKind.HUMAN,
            ("slice 6 ruling 17",),
        ),
    ),
)

MODULE = RuleModule(SPEC)
