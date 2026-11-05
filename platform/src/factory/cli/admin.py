"""`factory user`, `factory token` and `factory member` (slice 5, plan teams-A).

They parse input, call a service and format its answer. Each command is authorised through
`access.authorize` by its `TOOL_PERMISSIONS` row and leaves one access-log line on a server. The
shared helpers of `factory.cli.main` are imported inside each command, because that module imports
this one to register the command groups.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import typer

from factory.events.envelope import Actor
from factory.model.lab import DEFAULT_TOKEN_DAYS, MAX_TOKEN_DAYS, LabRole
from factory.model.members import ProjectRole
from factory.services import credentials as credentials_service
from factory.services import lab as lab_service
from factory.services import members as members_service
from factory.services.access import TOOL_PERMISSIONS, authorize
from factory.services.access_log import admin_call
from factory.services.context import Project, open_project
from factory.services.lab import Lab, lab_exists, open_lab

user_app = typer.Typer(name="user", help="The people of this lab.", no_args_is_help=True)
token_app = typer.Typer(name="token", help="Personal access tokens.", no_args_is_help=True)
member_app = typer.Typer(name="member", help="Project roles.", no_args_is_help=True)

Reason = Annotated[str, typer.Option("--reason", help="Why (required).")]
UserArg = Annotated[str, typer.Argument(help="User id.")]
SlugArg = Annotated[str, typer.Argument(help="Project slug.")]


@contextmanager
def _lab_call(ctx: typer.Context, tool: str) -> Iterator[tuple[Lab, Actor]]:
    """The lab and the admin's actor for one command: authorised, and left in the access log."""
    from factory.cli import main

    state = main._state(ctx)
    with (
        main._reporting_errors(),
        admin_call(
            state.settings, state.as_user, session=state.session, clock=state.clock, tool=tool
        ) as (settings, principal),
    ):
        lab = open_lab(settings, session=state.session, clock=state.clock)
        authorize(None, principal, "human", TOOL_PERMISSIONS[tool], lab=lab)
        yield lab, lab.human_actor()


@contextmanager
def _member_call(ctx: typer.Context, tool: str, slug: str) -> Iterator[Project]:
    """The project for one command, as the stated user: authorised, and left in the access log."""
    from factory.cli import main

    state = main._state(ctx)
    with (
        main._reporting_errors(),
        admin_call(
            state.settings,
            state.as_user,
            session=state.session,
            clock=state.clock,
            tool=tool,
            project=slug,
        ) as (settings, principal),
    ):
        project = open_project(
            settings, slug, session=state.session, clock=state.clock, principal=principal
        )
        lab = (
            open_lab(settings, session=state.session, clock=state.clock)
            if lab_exists(settings)
            else None
        )
        authorize(project, principal, "human", TOOL_PERMISSIONS[tool], lab=lab)
        yield project


@user_app.command("add")
def user_add(
    ctx: typer.Context,
    user: UserArg,
    name: Annotated[str, typer.Option("--name", help="Display name.")],
    email: Annotated[
        str | None, typer.Option("--email", help="Stored only as its SHA-256.")
    ] = None,
    admin: Annotated[bool, typer.Option("--admin", help="Give the lab admin role.")] = False,
) -> None:
    """Register a person. A user id is never reused."""
    with _lab_call(ctx, "cli:user add") as (lab, actor):
        role = LabRole.ADMIN if admin else LabRole.MEMBER
        lab_service.register_user(lab, actor, user, name, email, (role,))
    typer.echo(f"registered {user}")


@user_app.command("deactivate")
def user_deactivate(ctx: typer.Context, user: UserArg, reason: Reason) -> None:
    """Stop a person acting; their events stay attributed."""
    with _lab_call(ctx, "cli:user deactivate") as (lab, actor):
        lab_service.deactivate_user(lab, actor, user, reason)
    typer.echo(f"deactivated {user}")


@user_app.command("reactivate")
def user_reactivate(ctx: typer.Context, user: UserArg, reason: Reason) -> None:
    """Let a deactivated person act again."""
    with _lab_call(ctx, "cli:user reactivate") as (lab, actor):
        lab_service.reactivate_user(lab, actor, user, reason)
    typer.echo(f"reactivated {user}")


@user_app.command("link")
def user_link(
    ctx: typer.Context,
    user: UserArg,
    issuer: Annotated[str, typer.Option("--issuer", help="The identity provider.")],
    subject: Annotated[str, typer.Option("--subject", help="The provider's subject.")],
) -> None:
    """Link an external identity to a person."""
    with _lab_call(ctx, "cli:user link") as (lab, actor):
        lab_service.link_identity(lab, actor, user, issuer, subject)
    typer.echo(f"linked {user}")


@user_app.command("list")
def user_list(ctx: typer.Context) -> None:
    """Every person ever registered, with their state and lab roles."""
    with _lab_call(ctx, "cli:user list") as (lab, _):
        records = lab_service.list_users(lab)
    if not records:
        typer.echo("no users")
    for record in records:
        state = "active" if record.active else "inactive"
        roles = ",".join(record.lab_roles)
        typer.echo(f"{record.user}  {state}  {roles}  {record.display_name}")


@token_app.command("issue")
def token_issue(
    ctx: typer.Context,
    user: UserArg,
    days: Annotated[
        int, typer.Option("--days", min=1, max=MAX_TOKEN_DAYS, help="Days until it expires.")
    ] = DEFAULT_TOKEN_DAYS,
) -> None:
    """Issue a token. It is printed here once and can never be shown again."""
    with _lab_call(ctx, "cli:token issue") as (lab, actor):
        issued = credentials_service.issue_token(lab, actor, user, days=days)
    typer.echo(f"{issued.credential_id}  expires {issued.expires.date().isoformat()}")
    typer.echo(issued.token)


@token_app.command("revoke")
def token_revoke(
    ctx: typer.Context,
    credential_id: Annotated[str, typer.Argument(help="The `crd_` id.")],
    reason: Reason,
) -> None:
    """Revoke a token for good."""
    with _lab_call(ctx, "cli:token revoke") as (lab, actor):
        credentials_service.revoke(lab, actor, credential_id, reason)
    typer.echo(f"revoked {credential_id}")


@token_app.command("list")
def token_list(
    ctx: typer.Context,
    user: Annotated[str | None, typer.Option("--user", help="Only this user's.")] = None,
) -> None:
    """Tokens by id, with owner and expiry; never a secret."""
    with _lab_call(ctx, "cli:token list") as (lab, _):
        records = credentials_service.list_credentials(lab, user)
    if not records:
        typer.echo("no tokens")
    for record in records:
        state = "revoked" if record.revoked else "live"
        expires = record.expires.date().isoformat()
        typer.echo(f"{record.credential_id}  {record.user}  expires {expires}  {state}")


@member_app.command("grant")
def member_grant(
    ctx: typer.Context, slug: SlugArg, user: UserArg, role: ProjectRole, reason: Reason
) -> None:
    """Grant a project role."""
    with _member_call(ctx, "cli:member grant", slug) as project:
        members_service.grant(project, project.human_actor(), user, role, reason)
    typer.echo(f"granted {role.value} to {user}")


@member_app.command("revoke")
def member_revoke(
    ctx: typer.Context, slug: SlugArg, user: UserArg, role: ProjectRole, reason: Reason
) -> None:
    """Revoke a project role; the last owner cannot be revoked."""
    with _member_call(ctx, "cli:member revoke", slug) as project:
        members_service.revoke(project, project.human_actor(), user, role, reason)
    typer.echo(f"revoked {role.value} from {user}")


@member_app.command("list")
def member_list(ctx: typer.Context, slug: SlugArg) -> None:
    """Each member's live roles."""
    with _member_call(ctx, "cli:member list", slug) as project:
        held = members_service.members(project)
    if not held:
        typer.echo("no members")
    for user, roles in held.items():
        typer.echo(f"{user}  {','.join(sorted(roles))}")
