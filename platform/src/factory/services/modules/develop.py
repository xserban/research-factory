"""Rendered level documents (slice 8, plan A9): the goal, questions, plan, seeds, probe and
protocol documents drawn from the decision events.

Declaration only (slice M, decision 55); behaviour stays in `services/develop_render.py`."""

from factory.modules.contract import ArtifactKind, EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="develop",
    kind=ModuleKind.BUILDER,
    inputs=(ArtifactKind.DECISION,),
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(
        types=("document.rendered",),
        tables=("document_renders",),
        system_only=True,
    ),
)

MODULE = RuleModule(SPEC)
