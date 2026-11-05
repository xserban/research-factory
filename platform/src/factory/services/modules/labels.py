"""Free labels, consolidation and terms: organisation, never evidence.

Declaration only (slice M, decision 55); behaviour stays in the services. Labels are applied by
agents and humans, consolidated by a recorded, reversible procedure whose decisions are human, and
promoted to terms by a human (slice 3d rulings 12 to 16 and 26).
"""

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
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="labels",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "consolidation.decided",
            "consolidation.pass_completed",
            "consolidation.pass_started",
            "consolidation.proposed",
            "label.application_decided",
            "label.applied",
            "label.merged",
            "label.unmerged",
            "label.withdrawn",
            "term.promoted",
            "term.retired",
            "term.revised",
        ),
        tables=(
            "consolidation_decisions",
            "consolidation_passes",
            "consolidation_proposals",
            "label_merges",
            "labels",
            "term_aliases",
            "terms",
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("labels"),
    gates=(
        GateSpec(
            "labels.application_confirm",
            GateKind.DECISION,
            ("label.application_decided",),
            PolicyKind.HUMAN,
            ("slice 3d ruling 26", "R-51", "R-91"),
        ),
        GateSpec(
            "consolidation.decide",
            GateKind.DECISION,
            ("consolidation.decided",),
            PolicyKind.HUMAN,
            ("slice 3d ruling 26", "R-51", "R-91"),
        ),
        GateSpec(
            "terms.promote",
            GateKind.DECISION,
            ("term.promoted", "term.revised", "term.retired"),
            PolicyKind.HUMAN,
            ("slice 3d ruling 26", "R-51", "R-91"),
        ),
    ),
    checks=(
        CheckRule("consolidation-due", ("warning", "warning", "warning")),
        CheckRule("label-application-unconfirmed", (None, "warning", "warning")),
        CheckRule("term-unused", ("warning", "warning", "warning")),
        CheckRule("organisation-leak", ("error", "error", "error")),
    ),
)

MODULE = RuleModule(SPEC)
