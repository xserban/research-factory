"""Relations between works, ideas and the graph over them.

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
    name="lineage",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(
        ArtifactKind.RELATION,
        ArtifactKind.IDEA,
    ),
    events=EventFamily(
        types=(
            "idea.decided",
            "idea.merged",
            "idea.proposed",
            "idea.unmerged",
            "relation.decided",
            "relation.proposed",
        ),
        tables=(
            "graph_edges",
            "graph_nodes",
            "idea_members",
            "idea_merges",
            "ideas",
            "relations",
        ),
    ),
    gates=(
        GateSpec(
            "lineage.relation_confirm",
            GateKind.DECISION,
            ("relation.decided",),
            PolicyKind.HUMAN,
            ("slice 3b ruling 3",),
        ),
        GateSpec(
            "lineage.idea_confirm",
            GateKind.DECISION,
            ("idea.decided",),
            PolicyKind.HUMAN,
            ("slice 3b ruling 3",),
        ),
    ),
    checks=(
        CheckRule("relation-stale", ("warning", "warning", "warning")),
        CheckRule("relation-unconfirmed", ("warning", "warning", "warning")),
        CheckRule("relation-uncited-base", ("warning", "warning", "warning")),
        CheckRule("relation-without-basis", ("error", "error", "error")),
        CheckRule("idea-unconfirmed", ("warning", "warning", "warning")),
        CheckRule("graph-extraction-missing", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
