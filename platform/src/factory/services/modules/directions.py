"""The failed-directions registry (slice 6, plan XP-B; spec ruling 27; R-52, R-124).

Declaration only (slice M, decision 55); behaviour stays in the services. The registry rows are a
projection of the events that make a direction fail (evaluations, abandonments, discarded leads,
baseline verdicts: owned by the modules that write them) and of the human `direction.closed`
record this module owns. The gate `hypotheses.close` has the floor `human` and no preset: closing a
direction, like concluding or abandoning a hypothesis, is the researcher's act."""

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
    name="directions",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=("direction.closed",),
        tables=("directions", "direction_keys"),
    ),
    gates=(
        GateSpec(
            "hypotheses.close",
            GateKind.DECISION,
            ("direction.closed",),
            PolicyKind.HUMAN,
            ("slice 6 ruling 27", "R-52", "R-124"),
        ),
    ),
)

MODULE = RuleModule(SPEC)
