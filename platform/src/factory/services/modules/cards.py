"""Method cards and problem descriptions with verified property assertions.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
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
    name="cards",
    kind=ModuleKind.MINER,
    inputs=(
        ArtifactKind.CONVERSION,
        ArtifactKind.RECORD,
    ),
    outputs=(ArtifactKind.RECORD,),
    events=EventFamily(
        types=(
            "card.asserted",
            "card.assertion_decided",
            "card.created",
            "card.imported",
        ),
        tables=(
            "card_assertions",
            "card_props",
            "cards",
        ),
    ),
    gates=(
        GateSpec(
            "hypotheses.assertion_confirm",
            GateKind.DECISION,
            ("card.assertion_decided",),
            PolicyKind.HUMAN,
            ("slice 6 ruling 9",),
        ),
    ),
    regime=QualityRegime(1, "none", "assertion", "none", "agreed-sample", ("document-version",)),
    checks=(
        CheckRule("assertion-inferred-unconfirmed", (None, "warning", "warning")),
        CheckRule("assertion-stale", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
