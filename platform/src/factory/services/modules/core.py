"""The project record, the task queue and the cross-cutting checks.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="core",
    kind=ModuleKind.CORE,
    outputs=(ArtifactKind.TASK,),
    events=EventFamily(
        types=(
            "project.created",
            "task.claimed",
            "task.completed",
            "task.created",
            "task.released",
        ),
        tables=(
            "event_refs",
            "events",
            "meta",
            "project",
            "sync_state",
            "tasks",
        ),
    ),
    protocol_sections=("gate_policies",),
    checks=(
        CheckRule("broken-link", ("error", "error", "error")),
        CheckRule("missing-provenance", ("error", "error", "error")),
        CheckRule("gate-below-policy", ("warning", "warning", "error")),
    ),
)

MODULE = RuleModule(SPEC)
