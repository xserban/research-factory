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
            "ledger.confirmed",
            "budget.set",
        ),
        tables=(
            "budgets",
            "event_refs",
            "events",
            "gate_audit_items",
            "gate_audits",
            "ledger_confirmations",
            "member_events",
            "members",
            "meta",
            "project",
            "project_hosts",
            "project_visibility",
            "request_starts",
            "reviews",
            "source_requests",
            "sync_state",
            "task_claims",
            "task_usage",
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
        CheckRule("mcp-code-lines-differ", ("warning", "warning", "warning")),
        CheckRule("mcp-config-unresolved", ("warning", "warning", "warning")),
        CheckRule("member-event-unfolded", ("error", "error", "error")),
        CheckRule("future-dated-event", ("warning", "warning", "warning")),
        CheckRule("member-missing-reviewer-of-record", (None, "warning", "error")),
        CheckRule("review-open", ("warning", "warning", "warning")),
        CheckRule("review-stale", ("warning", "warning", "warning")),
        CheckRule("ledger-unconfirmed", (None, "warning", "error")),
        CheckRule("budget-exhausted", ("warning", "warning", "warning")),
        CheckRule("human-act-relayed", (None, None, "warning")),
    ),
)

MODULE = RuleModule(SPEC)
