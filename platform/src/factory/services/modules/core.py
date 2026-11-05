"""The project record, the task queue and the cross-cutting checks.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.model.members import ProjectRole
from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
    RoleGate,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="core",
    kind=ModuleKind.CORE,
    outputs=(ArtifactKind.TASK,),
    events=EventFamily(
        types=(
            "project.created",
            "project.hosted",
            "project.visibility_set",
            "member.granted",
            "member.revoked",
            "review.requested",
            "review.decided",
            "task.claimed",
            "task.completed",
            "task.created",
            "task.released",
            "gate.audit_sampled",
            "gate.audit_labelled",
        ),
        tables=(
            "event_refs",
            "events",
            "gate_audit_items",
            "gate_audits",
            "member_events",
            "members",
            "meta",
            "project",
            "project_hosts",
            "project_visibility",
            "reviews",
            "sync_state",
            "tasks",
        ),
    ),
    protocol_sections=("gate_policies",),
    role_gates=(
        RoleGate("member.grant", ProjectRole.OWNER),
        RoleGate("project.visibility", ProjectRole.OWNER),
        RoleGate("budget.set", ProjectRole.OWNER),
    ),
    checks=(
        CheckRule("broken-link", ("error", "error", "error")),
        CheckRule("missing-provenance", ("error", "error", "error")),
        CheckRule("gate-below-policy", ("warning", "warning", "error")),
        CheckRule("gate-audit-missing", (None, "warning", "error")),
        CheckRule("gate-audit-error-high", (None, "warning", "error")),
        CheckRule("gate-audit-unlabelled", (None, "warning", "error")),
        CheckRule("gate-policy-below-pilot-preset", (None, "error", "error")),
        CheckRule("gate-policy-below-systematic-preset", (None, None, "error")),
        CheckRule("host-mismatch", ("error", "error", "error")),
        CheckRule("host-mismatch-unchecked", ("warning", "warning", "warning")),
        CheckRule("member-event-unfolded", ("error", "error", "error")),
        CheckRule("future-dated-event", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
