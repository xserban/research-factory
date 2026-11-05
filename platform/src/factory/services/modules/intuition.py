"""The intuition layer: interpretations and concepts with their sources and links.

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
)
from factory.services.modules.base import RuleModule
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="intuition",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(
        ArtifactKind.INTERPRETATION,
        ArtifactKind.CONCEPT,
    ),
    events=EventFamily(
        types=(
            "concept.defined",
            "concept.link_decided",
            "concept.link_proposed",
            "concept.merged",
            "concept.reviewed",
            "concept.source_decided",
            "concept.unmerged",
            "interpretation.recorded",
            "interpretation.reviewed",
        ),
        tables=(
            "concept_aliases",
            "concept_definitions",
            "concept_merges",
            "concept_quotes",
            "concept_reviews",
            "concept_source_decisions",
            "concept_uses",
            "concepts",
            "interpretation_reviews",
            "interpretation_sources",
            "interpretations",
            "layer_edges",
            "layer_nodes",
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("intuition"),
    gates=(
        GateSpec(
            "intuition.review",
            GateKind.DECISION,
            (
                "interpretation.reviewed",
                "concept.reviewed",
            ),
            PolicyKind.HUMAN,
            ("slice 3c",),
        ),
        GateSpec(
            "intuition.source_approve",
            GateKind.DECISION,
            ("concept.source_decided",),
            PolicyKind.HUMAN,
            ("slice 3c",),
        ),
        GateSpec(
            "intuition.uses_confirm",
            GateKind.DECISION,
            ("concept.link_decided",),
            PolicyKind.HUMAN,
            ("slice 3c",),
        ),
    ),
    checks=(
        CheckRule("interpretation-unreviewed", ("warning", "warning", "error")),
        CheckRule("concept-unreviewed", ("warning", "warning", "error")),
        CheckRule("interpretation-source-stale", ("warning", "warning", "warning")),
        CheckRule("interpretation-self-reviewed", ("warning", "warning", "warning")),
        CheckRule("concept-source-missing", ("warning", "warning", "warning")),
        CheckRule("concept-link-unconfirmed", ("warning", "warning", "warning")),
        CheckRule("layer-review-dropped", ("warning", "warning", "warning")),
        CheckRule("layer-leak", ("error", "error", "error")),
        CheckRule("layer-scan-incomplete", ("warning", "warning", "warning")),
        CheckRule("concept-cycle", ("error", "error", "error")),
    ),
)

MODULE = RuleModule(SPEC)
