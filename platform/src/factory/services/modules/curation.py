"""Curation: reviewed proposals made from audit findings (IDEA-15, plan SV, PD-8).

Declaration only (slice M, decision 55); behaviour stays in the services. The gate
`curation.decide` has the floor `human`: a human other than the proposer decides, and an accepted
amendment still goes through `protocol_amend` (R-34)."""

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
    name="curation",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=("curation.proposed", "curation.decided"),
        tables=("curation_proposals",),
    ),
    gates=(
        GateSpec(
            "curation.decide",
            GateKind.DECISION,
            ("curation.decided",),
            PolicyKind.HUMAN,
            ("R-34", "R-51", "R-52"),
        ),
    ),
)

MODULE = RuleModule(SPEC)
