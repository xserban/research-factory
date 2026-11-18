"""Argument sheets of the papers chat (plan chat T7, section 4.6).

Declaration only (slice M, decision 55); behaviour stays in `services/sheets.py`. A proposal
module: an agent session records a hypothesis, the candidates computed over a selection and the
arguments against and for it, each with a verified quote; the researcher rates arguments. A sheet
is a note, never evidence: it enters no count, table or result of another module."""

from factory.modules.contract import ArtifactKind, EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="sheets",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(
        types=(
            "sheet.opened",
            "sheet.argument_recorded",
            "sheet.section_closed",
            "sheet.argument_rated",
        ),
        tables=("sheets", "sheet_candidates", "sheet_arguments", "sheet_ratings"),
    ),
)

MODULE = RuleModule(SPEC)
