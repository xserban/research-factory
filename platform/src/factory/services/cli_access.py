"""Who may run a project command on a lab server (slice 5 ruling 10, R-111, acceptance 13).

Invariants:
- Only a root with `.server/` is checked. Anywhere else a project opens as it always has (stage 0).
- On such a root a command runs only through its `TOOL_PERMISSIONS` row, or as `project:read` when
  `CLI_READS` lists it. A command in neither is refused, so a new command is closed until it says
  what it needs.
- The check reads the lab, so a deactivated or unknown user is refused by the registry itself.
- A project that does not exist is refused as one the user holds no role in.
- Each checked command leaves one access-log line. A command that is refused writes nothing.
- `factory init` and `factory commit` act on the root, not on a project. `cli:init` is open on a
  root with no lab (`OPEN_WITHOUT_LAB`). `cli:commit` is `lab:admin` for a person; the OS account
  that owns `.server/` is the server itself, and runs it as the `system` job (`SYSTEM_JOBS`).
"""

import os

from factory.clock import Clock
from factory.config import Settings
from factory.errors import ProjectNotFoundError
from factory.events.envelope import ActorKind
from factory.model.screening import Channel
from factory.services.access import (
    SYSTEM_JOBS,
    TOOL_PERMISSIONS,
    Permission,
    authorize,
    not_held,
)
from factory.services.access_log import audited, os_login
from factory.services.context import Principal, Project, open_project
from factory.services.lab import lab_exists, open_lab, refuse

CLI_READS: frozenset[str] = frozenset(
    f"cli:{command}"
    for command in (
        "rebuild",
        "status",
        "gates",
        "trace",
        "check",
        "match",
        "references status",
        "references list",
        "snowball plan",
        "snowball compare",
        "watch status",
        "watch plan",
        "living prisma-update",
        "conclusions status",
        "conclusions diff",
        "notices list",
        "versions list",
        "inbox list",
        "report prisma",
        "report search",
        "report methods",
        "report discovery",
        "report evidence",
        "export bibtex",
        "export csl",
        "export prisma",
        "screen disagreements",
        "audit report",
        "screen-check report",
        "screen-check list",
        "gate audit report",
        "fulltext status",
        "document status",
        "document read",
        "extract status",
        "extract agreement",
        "extract audit-report",
        "miner list",
        "miner calibrate report",
        "mine agreement",
        "mine status",
        "mine audit report",
        "contributions status",
        "contributions list",
        "contributions agreement",
        "contributions audit report",
        "relations list",
        "ideas list",
        "ideas candidates",
        "vocabulary list",
        "cards list",
        "cards show",
        "finders conflicts",
        "finders gaps",
        "contradictions list",
        "leads list",
        "hypotheses list",
        "hypotheses show",
        "experiments list",
        "experiments show",
        "runs list",
        "graph build",
        "graph status",
        "graph query",
        "graph export",
        "view onion",
        "view coverage",
        "view timeline",
        "view horizon",
        "interpretations list",
        "interpretations show",
        "interpretations history",
        "concepts list",
        "concepts show",
        "concepts history",
        "concept-links list",
        "regions proposals",
        "regions export",
        "regions list",
        "regions show",
        "regions diff",
        "labels list",
        "terms list",
        "terms suggest",
        "consolidation status",
        "consolidation list",
        "import list",
        "import show",
        "import coverage",
        "library status",
        "library adoptable",
        "decide list",
        "decide show",
        "dashboard serve",
        "dashboard export",
    )
)
"""Commands with no `TOOL_PERMISSIONS` row because they record no research fact. `rebuild` and
`graph build` write only what is rebuilt from the log."""


def server_root(settings: Settings) -> bool:
    return (settings.root / ".server").is_dir()


def command_permission(tool: str) -> Permission:
    """The permission of `cli:<command path>`. Refused when the command declares none."""
    row = TOOL_PERMISSIONS.get(tool)
    if row is not None:
        return row
    if tool in CLI_READS:
        return Permission.PROJECT_READ
    raise refuse("permission", f"{tool} declares no permission")


def open_authorised(
    settings: Settings, slug: str, tool: str, *, session: str, clock: Clock
) -> Project:
    """Open `slug` on a server root for the command `tool`, as the user the events will name."""
    principal = Principal.local(settings, Channel.CLI)
    with audited(
        settings, principal, session=session, clock=clock, tool=tool, project=slug, login=os_login()
    ):
        permission = command_permission(tool)
        lab = open_lab(settings, session=session, clock=clock)
        try:
            project = open_project(settings, slug, session=session, clock=clock)
        except ProjectNotFoundError:
            raise not_held(permission) from None
        authorize(project, principal, "human", permission, lab=lab, tool=tool)
    return project


def _server_account(settings: Settings) -> bool:
    """Whether this process runs as the OS account that owns `.server/`, mode 0700: the only account
    that can read the registry's secrets, and so the one a scheduled job of the server runs as."""
    return server_root(settings) and (settings.root / ".server").stat().st_uid == os.getuid()


def authorise_root_command(settings: Settings, tool: str, *, session: str, clock: Clock) -> None:
    """Refuse a root command the acting user may not run. The lab is passed whenever one exists, so
    `OPEN_WITHOUT_LAB` holds only where nobody could hold the row."""
    principal = Principal.local(settings, Channel.CLI)
    actor_kind: ActorKind = (
        "system" if tool in SYSTEM_JOBS and _server_account(settings) else "human"
    )
    with audited(settings, principal, session=session, clock=clock, tool=tool, login=os_login()):
        lab = open_lab(settings, session=session, clock=clock) if lab_exists(settings) else None
        authorize(None, principal, actor_kind, TOOL_PERMISSIONS[tool], lab=lab, tool=tool)
