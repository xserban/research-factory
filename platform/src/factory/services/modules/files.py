"""Registered study files: files of the project folder named by an event with their hash.

Declaration only (slice M, decision 55); behaviour stays in `services/study_files.py`. A proposal
module in the sense that it records the researcher's own documents and judges nothing: it has no
gate, one warning (`unreferenced-files`, behaviour in `services/unreferenced_files.py`), and
owns the `registered_files` table."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="files",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(ArtifactKind.REPORT,),
    checks=(CheckRule("unreferenced-files", ("warning", "warning", "warning")),),
    events=EventFamily(types=("file.registered",), tables=("registered_files",)),
)

MODULE = RuleModule(SPEC)
