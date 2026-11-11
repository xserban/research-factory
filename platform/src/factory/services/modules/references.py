"""Reference extraction, resolution of references to works, citation contexts.

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

SPEC = ModuleSpec(
    name="references",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.CONVERSION,),
    outputs=(ArtifactKind.REFERENCE_EXTRACTION,),
    events=EventFamily(
        types=(
            "citation.contexts_recorded",
            "reference.extracted",
            "reference.layer_assigned",
            "reference.layer_labelled",
            "reference.layer_scheme_recorded",
            "reference.re_resolved",
            "reference.resolution_decided",
            "reference.resolved",
        ),
        tables=(
            "citation_contexts",
            "reference_context_sets",
            "reference_decisions",
            "reference_entries",
            "reference_extractions",
            "reference_layer_labels",
            "reference_layer_schemes",
            "reference_layers",
            "reference_links",
        ),
    ),
    gates=(
        GateSpec(
            "reference.link_confirm",
            GateKind.DECISION,
            ("reference.resolution_decided",),
            PolicyKind.AGENT_AUDIT,
            ("slice 3a ruling 3",),
        ),
    ),
    checks=(
        CheckRule("references-missing-extraction", (None, "warning", "error")),
        CheckRule("references-stale-extraction", ("warning", "warning", "warning")),
        CheckRule("references-parse-incomplete", ("warning", "warning", "warning")),
        CheckRule("references-unresolved-ceiling", ("warning", "warning", "warning")),
        CheckRule("references-library-missing", ("warning", "warning", "warning")),
        CheckRule("references-decision-lost", ("warning", "warning", "error")),
    ),
)

MODULE = RuleModule(SPEC)
