"""Who may do what (slice 5 rulings 9 and 10; the spec's permissions table).

`authorize` decides; enforcement at the MCP server is deploy-B's.

Invariants:
- Deny by default: a role not listed holds nothing, and a principal with no role holds nothing.
- An agent acts for its principal and holds at most the principal's permissions, minus
  `HUMAN_ONLY`, whatever the role. A `system` actor is held to the same limit.
- `GATED_AGENT_ACTS` lifts that subtraction for an agent on those tools alone, never the cap: the
  principal's role must still hold the permission, so an agent never does what its person cannot.
- `lab:admin` comes from the lab `admin` role alone, never from a project role, and needs a lab.
- With a lab given, a principal the registry does not hold as active holds nothing.
- A refusal writes nothing and is one issue on field `permission`.
"""

from collections.abc import Mapping
from enum import StrEnum

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import ActorKind
from factory.model.lab import LabRole
from factory.model.members import ProjectRole
from factory.services.context import Principal, Project
from factory.services.lab import Lab, user_record
from factory.services.members import roles_of


class Permission(StrEnum):
    PROJECT_READ = "project:read"
    WORK_RUN = "work:run"
    PASS_JOIN_HUMAN = "pass:join-human"
    PROTOCOL_CHANGE = "protocol:change"
    HUMAN_LABEL = "human-act:label"
    HUMAN_CONFIRM = "human-act:confirm"
    REVIEW_DECIDE = "review:decide"
    PROJECT_GOVERN = "project:govern"
    LAB_ADMIN = "lab:admin"


HUMAN_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.HUMAN_LABEL,
        Permission.HUMAN_CONFIRM,
        Permission.REVIEW_DECIDE,
        Permission.PROJECT_GOVERN,
        Permission.PASS_JOIN_HUMAN,
        Permission.LAB_ADMIN,
    }
)
"""What an agent never holds, on any project."""

AGENT_PROPOSES_ONLY: frozenset[Permission] = frozenset({Permission.PROTOCOL_CHANGE})
"""The spec's table gives an agent `protocol:change` as "proposes only", so on a hosted project an
agent is refused it. Unhosted, it keeps the protocol tools it has always had (acceptance 1)."""

GATED_AGENT_ACTS: frozenset[str] = frozenset(
    {"mine_resolve", "reference_decide", "lead_decide", "hypothesis_register", "miner_register"}
)
"""Tools through which an agent acts at a decision gate of slices 6 and M: the gate policy says when
it may, so the human permission is not subtracted. The caller names the tool to `authorize`."""

_READ = frozenset({Permission.PROJECT_READ})
_CONTRIBUTE = _READ | {Permission.WORK_RUN}
_MAINTAIN = _CONTRIBUTE | {
    Permission.PASS_JOIN_HUMAN,
    Permission.PROTOCOL_CHANGE,
    Permission.HUMAN_LABEL,
    Permission.HUMAN_CONFIRM,
    Permission.REVIEW_DECIDE,
}

ROLE_PERMISSIONS: Mapping[ProjectRole, frozenset[Permission]] = {
    ProjectRole.OWNER: _MAINTAIN | {Permission.PROJECT_GOVERN},
    ProjectRole.MAINTAINER: _MAINTAIN,
    ProjectRole.CONTRIBUTOR: _CONTRIBUTE,
    ProjectRole.SCREENER: _READ | {Permission.PASS_JOIN_HUMAN},
    ProjectRole.OBSERVER: _READ,
}


TOOL_PERMISSIONS: Mapping[str, Permission] = {
    # MCP tools that only read.
    "project_status": Permission.PROJECT_READ,
    "gate_status": Permission.PROJECT_READ,
    "watch_status": Permission.PROJECT_READ,
    "notice_list": Permission.PROJECT_READ,
    "conclusion_status": Permission.PROJECT_READ,
    "digest_get": Permission.PROJECT_READ,
    "seed_list": Permission.PROJECT_READ,
    "screen_agreement": Permission.PROJECT_READ,
    "report_prisma": Permission.PROJECT_READ,
    "report_methods": Permission.PROJECT_READ,
    "inbox_list": Permission.PROJECT_READ,
    "report_discovery": Permission.PROJECT_READ,
    "report_evidence": Permission.PROJECT_READ,
    "export_bibliography": Permission.PROJECT_READ,
    "trace": Permission.PROJECT_READ,
    "check": Permission.PROJECT_READ,
    "fulltext_status": Permission.PROJECT_READ,
    "document_read": Permission.PROJECT_READ,
    "extract_agreement": Permission.PROJECT_READ,
    "mine_status": Permission.PROJECT_READ,
    "miner_list": Permission.PROJECT_READ,
    "mine_disagreements": Permission.PROJECT_READ,
    "import_status": Permission.PROJECT_READ,
    "import_coverage": Permission.PROJECT_READ,
    "references_status": Permission.PROJECT_READ,
    "references_list": Permission.PROJECT_READ,
    "snowball_compare": Permission.PROJECT_READ,
    "graph_status": Permission.PROJECT_READ,
    "graph_query": Permission.PROJECT_READ,
    "graph_export": Permission.PROJECT_READ,
    "card_view": Permission.PROJECT_READ,
    "interpretation_list": Permission.PROJECT_READ,
    "match_query": Permission.PROJECT_READ,
    "finder_contradictions": Permission.PROJECT_READ,
    "finder_gaps": Permission.PROJECT_READ,
    "region_status": Permission.PROJECT_READ,
    "region_query": Permission.PROJECT_READ,
    "hypothesis_view": Permission.PROJECT_READ,
    "term_list": Permission.PROJECT_READ,
    "view_onion": Permission.PROJECT_READ,
    "view_coverage": Permission.PROJECT_READ,
    "view_timeline": Permission.PROJECT_READ,
    "view_horizon": Permission.PROJECT_READ,
    "experiment_view": Permission.PROJECT_READ,
    "xrun_list": Permission.PROJECT_READ,
    # MCP tools that run work.
    "search_run": Permission.WORK_RUN,
    "search_chase": Permission.WORK_RUN,
    "dedup_run": Permission.WORK_RUN,
    "watch_run": Permission.WORK_RUN,
    "question_record": Permission.WORK_RUN,
    "seed_add": Permission.WORK_RUN,
    "probe_run": Permission.WORK_RUN,
    "protocol_press_review": Permission.WORK_RUN,
    "screen_next": Permission.WORK_RUN,
    "screen_record": Permission.WORK_RUN,
    "inbox_add": Permission.WORK_RUN,
    "inbox_resolve": Permission.WORK_RUN,
    "fulltext_fetch": Permission.WORK_RUN,
    "extract_next": Permission.WORK_RUN,
    "extract_record": Permission.WORK_RUN,
    "mine_next": Permission.WORK_RUN,
    "mine_record": Permission.WORK_RUN,
    "contribution_next": Permission.WORK_RUN,
    "contribution_record": Permission.WORK_RUN,
    "references_extract": Permission.WORK_RUN,
    "snowball_round": Permission.WORK_RUN,
    "relation_propose": Permission.WORK_RUN,
    "idea_propose": Permission.WORK_RUN,
    "vocabulary_propose": Permission.WORK_RUN,
    "card_create": Permission.WORK_RUN,
    "card_assert": Permission.WORK_RUN,
    "intuition_next": Permission.WORK_RUN,
    "interpretation_record": Permission.WORK_RUN,
    "concept_propose": Permission.WORK_RUN,
    "concept_link": Permission.WORK_RUN,
    "contradiction_propose": Permission.WORK_RUN,
    "region_propose": Permission.WORK_RUN,
    "region_propose_member": Permission.WORK_RUN,
    "region_snapshot": Permission.WORK_RUN,
    "lead_record": Permission.WORK_RUN,
    "hypothesis_draft": Permission.WORK_RUN,
    "hypothesis_review_next": Permission.WORK_RUN,
    "hypothesis_review": Permission.WORK_RUN,
    "label_apply": Permission.WORK_RUN,
    "consolidation_next": Permission.WORK_RUN,
    "consolidation_propose": Permission.WORK_RUN,
    "experiment_design": Permission.WORK_RUN,
    "xrun_register": Permission.WORK_RUN,
    # `GATED_AGENT_ACTS`: the person's permission, which an agent needs its principal to hold.
    "mine_resolve": Permission.HUMAN_LABEL,
    "reference_decide": Permission.HUMAN_CONFIRM,
    "lead_decide": Permission.HUMAN_CONFIRM,
    "hypothesis_register": Permission.HUMAN_CONFIRM,
    "miner_register": Permission.PROTOCOL_CHANGE,
    # Refused to an agent on a hosted project (`AGENT_PROPOSES_ONLY`).
    "protocol_record": Permission.PROTOCOL_CHANGE,
    "protocol_amend": Permission.PROTOCOL_CHANGE,
    "protocol_deviation": Permission.PROTOCOL_CHANGE,
    # A person's act relayed over MCP: these tools write a human actor.
    "calibration_label": Permission.HUMAN_LABEL,
    "audit_sample": Permission.HUMAN_LABEL,
    "audit_record": Permission.HUMAN_LABEL,
    "extract_audit_sample": Permission.HUMAN_LABEL,
    "extract_audit_record": Permission.HUMAN_LABEL,
    "miner_calibration_label": Permission.HUMAN_LABEL,
    "notice_assess": Permission.HUMAN_CONFIRM,
    # Mutating CLI commands, as `cli:<group> <command>`. Read-only commands have no row, but for
    # the three lists of the admin groups, which are authorised like the rest of those groups.
    "cli:init": Permission.PROJECT_GOVERN,
    "cli:commit": Permission.LAB_ADMIN,
    "cli:server init": Permission.LAB_ADMIN,
    "cli:user add": Permission.LAB_ADMIN,
    "cli:user deactivate": Permission.LAB_ADMIN,
    "cli:user reactivate": Permission.LAB_ADMIN,
    "cli:user link": Permission.LAB_ADMIN,
    "cli:user list": Permission.LAB_ADMIN,
    "cli:token issue": Permission.LAB_ADMIN,
    "cli:token revoke": Permission.LAB_ADMIN,
    "cli:token list": Permission.LAB_ADMIN,
    "cli:member grant": Permission.PROJECT_GOVERN,
    "cli:member revoke": Permission.PROJECT_GOVERN,
    "cli:member list": Permission.PROJECT_READ,
    "cli:inbox add": Permission.WORK_RUN,
    "cli:inbox resolve": Permission.WORK_RUN,
    "cli:inbox withdraw": Permission.WORK_RUN,
    "cli:search chase": Permission.WORK_RUN,
    "cli:references extract": Permission.WORK_RUN,
    "cli:snowball run": Permission.WORK_RUN,
    "cli:fulltext import": Permission.WORK_RUN,
    "cli:fulltext fetch": Permission.WORK_RUN,
    "cli:fulltext restore": Permission.WORK_RUN,
    "cli:document convert": Permission.WORK_RUN,
    "cli:watch run": Permission.WORK_RUN,
    "cli:living snapshot": Permission.WORK_RUN,
    "cli:digest": Permission.WORK_RUN,
    "cli:import bib": Permission.WORK_RUN,
    "cli:import csl": Permission.WORK_RUN,
    "cli:import pdfs": Permission.WORK_RUN,
    "cli:import resolve": Permission.WORK_RUN,
    "cli:import admit": Permission.WORK_RUN,
    "cli:import attach": Permission.WORK_RUN,
    "cli:ideas define": Permission.WORK_RUN,
    "cli:interpretations write": Permission.WORK_RUN,
    "cli:cards assert": Permission.WORK_RUN,
    "cli:regions define": Permission.WORK_RUN,
    "cli:regions revise": Permission.WORK_RUN,
    "cli:regions snapshot": Permission.WORK_RUN,
    "cli:runs record": Permission.WORK_RUN,
    "cli:labels apply": Permission.WORK_RUN,
    "cli:labels withdraw": Permission.WORK_RUN,
    "cli:consolidation start": Permission.WORK_RUN,
    # The seed commands name held-out seeds, so they stay with those who may see them (ruling 20).
    "cli:seeds split": Permission.PROTOCOL_CHANGE,
    "cli:seeds explain": Permission.PROTOCOL_CHANGE,
    "cli:seeds admit": Permission.PROTOCOL_CHANGE,
    "cli:protocol confirm-press": Permission.PROTOCOL_CHANGE,
    "cli:miner register": Permission.PROTOCOL_CHANGE,
    "cli:miner retire": Permission.PROTOCOL_CHANGE,
    "cli:miner admit": Permission.PROTOCOL_CHANGE,
    "cli:experiments deviation": Permission.PROTOCOL_CHANGE,
    "cli:gate audit sample": Permission.HUMAN_LABEL,
    "cli:gate audit label": Permission.HUMAN_LABEL,
    "cli:calibrate draw": Permission.HUMAN_LABEL,
    "cli:calibrate label": Permission.HUMAN_LABEL,
    "cli:screen resolve": Permission.HUMAN_LABEL,
    "cli:audit sample": Permission.HUMAN_LABEL,
    "cli:audit label": Permission.HUMAN_LABEL,
    "cli:miner calibrate draw": Permission.HUMAN_LABEL,
    "cli:miner calibrate label": Permission.HUMAN_LABEL,
    "cli:mine resolve": Permission.HUMAN_LABEL,
    "cli:mine audit sample": Permission.HUMAN_LABEL,
    "cli:mine audit label": Permission.HUMAN_LABEL,
    "cli:extract resolve": Permission.HUMAN_LABEL,
    "cli:extract audit-sample": Permission.HUMAN_LABEL,
    "cli:extract audit-label": Permission.HUMAN_LABEL,
    "cli:contributions resolve": Permission.HUMAN_LABEL,
    "cli:contributions audit sample": Permission.HUMAN_LABEL,
    "cli:contributions audit label": Permission.HUMAN_LABEL,
    "cli:references decide": Permission.HUMAN_CONFIRM,
    "cli:notices assess": Permission.HUMAN_CONFIRM,
    "cli:versions prefer": Permission.HUMAN_CONFIRM,
    "cli:conclusions register": Permission.HUMAN_CONFIRM,
    "cli:conclusions retire": Permission.HUMAN_CONFIRM,
    "cli:import confirm": Permission.HUMAN_CONFIRM,
    "cli:import reject": Permission.HUMAN_CONFIRM,
    "cli:relations confirm": Permission.HUMAN_CONFIRM,
    "cli:relations reject": Permission.HUMAN_CONFIRM,
    "cli:ideas confirm": Permission.HUMAN_CONFIRM,
    "cli:ideas reject": Permission.HUMAN_CONFIRM,
    "cli:ideas merge": Permission.HUMAN_CONFIRM,
    "cli:ideas unmerge": Permission.HUMAN_CONFIRM,
    "cli:interpretations review": Permission.HUMAN_CONFIRM,
    "cli:interpretations supersede": Permission.HUMAN_CONFIRM,
    "cli:concepts define": Permission.HUMAN_CONFIRM,
    "cli:concepts source": Permission.HUMAN_CONFIRM,
    "cli:concepts approve": Permission.HUMAN_CONFIRM,
    "cli:concepts reject-source": Permission.HUMAN_CONFIRM,
    "cli:concepts review": Permission.HUMAN_CONFIRM,
    "cli:concepts merge": Permission.HUMAN_CONFIRM,
    "cli:concepts unmerge": Permission.HUMAN_CONFIRM,
    "cli:concept-links confirm": Permission.HUMAN_CONFIRM,
    "cli:concept-links reject": Permission.HUMAN_CONFIRM,
    "cli:vocabulary approve": Permission.HUMAN_CONFIRM,
    "cli:vocabulary reject": Permission.HUMAN_CONFIRM,
    "cli:vocabulary merge": Permission.HUMAN_CONFIRM,
    "cli:vocabulary unmerge": Permission.HUMAN_CONFIRM,
    "cli:cards confirm": Permission.HUMAN_CONFIRM,
    "cli:cards reject": Permission.HUMAN_CONFIRM,
    "cli:contradictions confirm": Permission.HUMAN_CONFIRM,
    "cli:contradictions reject": Permission.HUMAN_CONFIRM,
    "cli:regions review": Permission.HUMAN_CONFIRM,
    "cli:regions add": Permission.HUMAN_CONFIRM,
    "cli:regions remove": Permission.HUMAN_CONFIRM,
    "cli:regions reject": Permission.HUMAN_CONFIRM,
    "cli:regions link": Permission.HUMAN_CONFIRM,
    "cli:leads promote": Permission.HUMAN_CONFIRM,
    "cli:leads park": Permission.HUMAN_CONFIRM,
    "cli:leads discard": Permission.HUMAN_CONFIRM,
    "cli:hypotheses register": Permission.HUMAN_CONFIRM,
    "cli:hypotheses abandon": Permission.HUMAN_CONFIRM,
    "cli:hypotheses conclude": Permission.HUMAN_CONFIRM,
    "cli:models cutoff": Permission.HUMAN_CONFIRM,
    "cli:experiments freeze": Permission.HUMAN_CONFIRM,
    "cli:experiments unlock": Permission.HUMAN_CONFIRM,
    "cli:experiments accept-baseline": Permission.HUMAN_CONFIRM,
    "cli:labels confirm": Permission.HUMAN_CONFIRM,
    "cli:labels reject": Permission.HUMAN_CONFIRM,
    "cli:labels merge": Permission.HUMAN_CONFIRM,
    "cli:labels unmerge": Permission.HUMAN_CONFIRM,
    "cli:terms promote": Permission.HUMAN_CONFIRM,
    "cli:terms revise": Permission.HUMAN_CONFIRM,
    "cli:terms retire": Permission.HUMAN_CONFIRM,
    "cli:consolidation decide": Permission.HUMAN_CONFIRM,
    "cli:consolidation complete": Permission.HUMAN_CONFIRM,
}
"""One permission per MCP tool and per mutating CLI command (ruling 10). A tool with no row is a
tool the server refuses to start with."""


def _holds(
    project: Project | None,
    principal: Principal,
    actor_kind: ActorKind,
    permission: Permission,
    lab: Lab | None,
    tool: str | None,
) -> bool:
    gated = (
        actor_kind == "agent"
        and tool in GATED_AGENT_ACTS
        and TOOL_PERMISSIONS.get(tool or "") == permission
    )
    if actor_kind != "human" and permission in HUMAN_ONLY and not gated:
        return False
    lab_roles: tuple[LabRole, ...] = ()
    if lab is not None:
        record = user_record(lab, principal.user)
        if record is None or not record.active:
            return False
        lab_roles = record.lab_roles
    if permission is Permission.LAB_ADMIN:
        return LabRole.ADMIN in lab_roles
    if project is None:
        return False
    if (
        actor_kind != "human"
        and permission in AGENT_PROPOSES_ONLY
        and not gated
        and project.is_hosted()
    ):
        return False
    return any(permission in ROLE_PERMISSIONS[role] for role in roles_of(project, principal.user))


def authorize(
    project: Project | None,
    principal: Principal,
    actor_kind: ActorKind,
    permission: Permission,
    *,
    lab: Lab | None = None,
    tool: str | None = None,
) -> None:
    """Return when the principal, acting as `actor_kind`, holds `permission`; else refuse. `tool`
    is the `TOOL_PERMISSIONS` key of the call, which the per-tool wrapper passes."""
    if not _holds(project, principal, actor_kind, permission, lab, tool):
        raise FactoryValidationError([ValidationIssue("permission", f"{permission} not held")])
