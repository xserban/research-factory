"""Who may do what (slice 5 rulings 9 and 10; the spec's permissions table).

`authorize` decides; enforcement at the MCP server is deploy-B's.

Invariants:
- Deny by default: a role not listed holds nothing, and a principal with no role holds nothing.
- An agent acts for its principal and holds at most the principal's permissions, minus
  `HUMAN_ONLY`, whatever the role. A `system` actor is held to the same limit.
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


def _holds(
    project: Project | None,
    principal: Principal,
    actor_kind: ActorKind,
    permission: Permission,
    lab: Lab | None,
) -> bool:
    if actor_kind != "human" and permission in HUMAN_ONLY:
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
    if actor_kind != "human" and permission in AGENT_PROPOSES_ONLY and project.is_hosted():
        return False
    return any(permission in ROLE_PERMISSIONS[role] for role in roles_of(project, principal.user))


def authorize(
    project: Project | None,
    principal: Principal,
    actor_kind: ActorKind,
    permission: Permission,
    *,
    lab: Lab | None = None,
) -> None:
    """Return when the principal, acting as `actor_kind`, holds `permission`; else refuse."""
    if not _holds(project, principal, actor_kind, permission, lab):
        raise FactoryValidationError([ValidationIssue("permission", f"{permission} not held")])
