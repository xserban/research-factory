"""Recorded pages: model-written documents about the corpus, checked when recorded (plan site-hub).

Declaration only (slice M, decision 55); behaviour stays in `services/pages.py`. A proposal module:
an agent writes a synthesis page, the platform checks it against the quoted rows and records it
with its provenance; the page is an interpretation and enters no count or result. It declares no
gate and owns no index table: pages are read through the generic event row and the input blob."""

from factory.modules.contract import ArtifactKind, EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="pages",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(types=("page.recorded",)),
)

MODULE = RuleModule(SPEC)
