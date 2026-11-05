"""The property vocabulary of cards and problem descriptions.

Declaration only (slice M, decision 55); behaviour stays in the services."""

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

SPEC = ModuleSpec(
    name="vocabulary",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "vocabulary.property_decided",
            "vocabulary.property_merged",
            "vocabulary.property_proposed",
            "vocabulary.property_unmerged",
        ),
        tables=(
            "properties",
            "property_merges",
        ),
    ),
    gates=(
        GateSpec(
            "hypotheses.property_approve",
            GateKind.DECISION,
            ("vocabulary.property_decided",),
            PolicyKind.HUMAN,
            ("slice 6 ruling 4",),
        ),
    ),
    checks=(CheckRule("property-proposed-unapproved", ("warning", "warning", "warning")),),
)

MODULE = RuleModule(SPEC)
