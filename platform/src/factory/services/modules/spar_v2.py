"""The agentic spar, engine v2 (plan spar-night N6, IDEA-101).

Declaration only (slice M, decision 55); behaviour stays in `services/spar_v2.py`. A proposal
module: a coordinator runs separate role sessions for one chat request (searcher, readers, two
writers, critic, coverage sweep); the platform sequences them and derives the state from events.
Readings, checks and the coverage record are notes, never evidence: the critic's check is not a
rating, and nothing here enters a count, table or result of another module."""

from factory.modules.contract import ArtifactKind, EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="spar_v2",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(ArtifactKind.RECORD,),
    events=EventFamily(
        types=(
            "spar.role_started",
            "spar.reading_recorded",
            "sheet.argument_checked",
            "spar.coverage_recorded",
        ),
        tables=("spar_roles", "spar_readings", "argument_checks", "spar_coverage"),
    ),
)

MODULE = RuleModule(SPEC)
