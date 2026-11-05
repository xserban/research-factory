"""Project roles, granted by events in the project's log (slice 5 ruling 9).

Invariants:
- An unhosted project with no grant treats `Settings.user` as `owner`, so stage 0 needs no grants
  (plan ruling 2). Once any grant has counted, only grants count, for good.
- Every check and the event it allows happen under one hold of the project write lock.
- A grant needs `project:govern`, through `access.authorize`: an agent never holds it.
- When a lab registry exists the grantee must be active in it. A rebuild cannot ask the lab, so
  this is the service's check alone.
- The first grant names an `owner`, and the last `owner` grant is not revoked (plan ruling 3), so
  a project always has someone who can grant.
- The first grant is the project creator's, or on a hosted project that of the person who hosted
  it, as the fold requires. A hosted project has no implicit owner, so its way in is
  `bootstrap_owner`.
"""

from factory.events.envelope import Actor
from factory.index import members as member_index
from factory.index.members import MEMBER_TABLES
from factory.model.members import MemberGranted, MemberRevoked, ProjectRole
from factory.services.context import Principal, Project, hosted_by
from factory.services.lab import Lab, lab_exists, open_lab, payload_of, refuse, user_record


def _implicit_owner(project: Project, user: str) -> bool:
    return user == project.settings.user and hosted_by(project.index) is None


def roles_of(project: Project, user: str, *, at: str | None = None) -> frozenset[ProjectRole]:
    """The roles `user` holds now, or just after the event `at`."""
    project.index.sync()
    with project.index.connect() as conn:
        if at is None:
            granted = member_index.any_grant(conn, MEMBER_TABLES)
            held = member_index.live_roles(conn, MEMBER_TABLES, user)
        else:
            granted = member_index.any_grant_by(conn, MEMBER_TABLES, at)
            held = member_index.roles_at(conn, MEMBER_TABLES, user, at)
    if granted:
        return held
    return frozenset({ProjectRole.OWNER}) if _implicit_owner(project, user) else frozenset()


def members(project: Project) -> dict[str, frozenset[ProjectRole]]:
    """Each member's live roles, by user; the implicit owner while no grant has counted."""
    project.index.sync()
    with project.index.connect() as conn:
        if member_index.any_grant(conn, MEMBER_TABLES):
            return member_index.all_members(conn, MEMBER_TABLES)
    user = project.settings.user
    return {user: frozenset({ProjectRole.OWNER})} if _implicit_owner(project, user) else {}


def _lab_of(project: Project) -> Lab | None:
    if not lab_exists(project.settings):
        return None
    return open_lab(project.settings, session=project.session, clock=project.clock)


def _require_govern(project: Project, actor: Actor, lab: Lab | None) -> None:
    from factory.services.access import Permission, authorize  # access reads `roles_of` here

    principal = Principal(actor.user, actor.credential, project.principal.channel)
    authorize(project, principal, actor.kind, Permission.PROJECT_GOVERN, lab=lab)


def _require_lab_admin(project: Project, actor: Actor, lab: Lab) -> None:
    from factory.services.access import Permission, authorize  # access reads `roles_of` here

    principal = Principal(actor.user, actor.credential, project.principal.channel)
    authorize(None, principal, actor.kind, Permission.LAB_ADMIN, lab=lab)


def _require_active(lab: Lab | None, user: str) -> None:
    if lab is None:
        return
    record = user_record(lab, user)
    if record is None or not record.active:
        raise refuse("user", f"no active user {user!r} in the lab registry")


def grant(project: Project, actor: Actor, user: str, role: ProjectRole, reason: str) -> None:
    """Grant `role` to `user`. Refused without `project:govern`, to a person the lab does not know
    as active, for a role already held, and for a first grant that names no owner."""
    payload = payload_of(MemberGranted, user=user, role=role, reason=reason)
    lab = _lab_of(project)
    with project.writing():
        _require_govern(project, actor, lab)
        _require_active(lab, user)
        with project.index.connect() as conn:
            first = not member_index.any_grant(conn, MEMBER_TABLES)
            entitled = member_index.may_first_grant(conn, actor)
            held = member_index.live_roles(conn, MEMBER_TABLES, user)
        if first and not entitled:
            raise refuse("permission", "the first grant is the project creator's")
        if first and role is not ProjectRole.OWNER:
            raise refuse("role", "the first grant must name an owner")
        if role in held:
            raise refuse("role", f"{user} already holds {role.value}")
        project.record([project.events.make("member.granted", payload, actor)])


def bootstrap_owner(project: Project, lab: Lab, actor: Actor, user: str, reason: str) -> None:
    """Name the first owner of a hosted project that has no grant, which nobody could otherwise do.
    Refused without `lab:admin`, on an unhosted project (`grant` serves it), once any grant has
    counted, to anyone but the person who hosted the project, and for a user not active in the
    lab."""
    payload = payload_of(MemberGranted, user=user, role=ProjectRole.OWNER, reason=reason)
    with project.writing():
        _require_lab_admin(project, actor, lab)
        if not project.is_hosted():
            raise refuse("project", "not hosted: the first grant is the creator's, through grant")
        with project.index.connect() as conn:
            granted = member_index.any_grant(conn, MEMBER_TABLES)
            entitled = member_index.may_first_grant(conn, actor)
        if granted:
            raise refuse("project", "this project has grants: an owner grants through grant")
        if not entitled:
            raise refuse("permission", "the first owner is named by the person who hosted it")
        _require_active(lab, user)
        project.record([project.events.make("member.granted", payload, actor)])


def revoke(project: Project, actor: Actor, user: str, role: ProjectRole, reason: str) -> None:
    """Revoke a grant. Refused without `project:govern`, for a grant not held, and for the last
    owner."""
    payload = payload_of(MemberRevoked, user=user, role=role, reason=reason)
    lab = _lab_of(project)
    with project.writing():
        _require_govern(project, actor, lab)
        with project.index.connect() as conn:
            held = member_index.live_roles(conn, MEMBER_TABLES, user)
            last = member_index.is_last_owner(conn, MEMBER_TABLES, user)
        if role not in held:
            raise refuse("role", f"{user} does not hold {role.value}")
        if role is ProjectRole.OWNER and last:
            raise refuse("role", "the last owner cannot be revoked")
        project.record([project.events.make("member.revoked", payload, actor)])
