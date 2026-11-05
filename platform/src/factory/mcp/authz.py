"""Deny by default: every tool runs behind `authorised` (slice 5 rulings 10 and 12).

Wiring only: `access.authorize` decides, `AccessLog` records.

Invariants:
- A tool with no `TOOL_PERMISSIONS` row fails the build, so the server does not start.
- A refusal writes no event and leaves one access-log line; so does every call that ran.
- A tool on a human-only permission runs as the principal in person, which is what its body writes;
  any other runs as the principal's agent, and so does one of `GATED_AGENT_ACTS`, whose body writes
  an agent. `authorize` is told the tool, or it could not lift the subtraction for those.
- The active check never rests on `verify_token`: each call reads the lab itself, and an
  authenticated principal with no lab to read holds nothing.
- An authenticated caller naming a project that does not exist gets the refusal a project they hold
  no role in gets. On stdio the local user keeps the tool's own answer.
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC
from typing import Any, cast

from factory.clock import Clock
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.events.envelope import ActorKind
from factory.mcp.conventions import fail
from factory.mcp.sessions import (
    CallContext,
    ContextProvider,
    ToolContext,
    ToolFn,
    ToolResult,
    ToolWrapper,
    as_tool,
    call_scope,
)
from factory.model.identity import SLUG_RE
from factory.model.screening import Channel
from factory.services.access import (
    GATED_AGENT_ACTS,
    HUMAN_ONLY,
    TOOL_PERMISSIONS,
    Permission,
    authorize,
    not_held,
)
from factory.services.access_log import AccessEntry, AccessLog, Outcome, field_names
from factory.services.context import MAX_SLUG_LENGTH, Project
from factory.services.lab import Lab

ProjectOpener = Callable[[str, CallContext], Project]
LabOpener = Callable[[str], Lab | None]

_LOG = logging.getLogger(__name__)


def _loggable(slug: object) -> str | None:
    """`slug` when it reads as one: the argument is the caller's text, and a line carries none."""
    if isinstance(slug, str) and len(slug) <= MAX_SLUG_LENGTH and re.fullmatch(SLUG_RE, slug):
        return slug
    return None


def _result_issues(result: ToolResult) -> list[ValidationIssue]:
    errors = result.get("errors")
    if not isinstance(errors, list):
        return []
    fields = [e.get("field") for e in errors if isinstance(e, dict)]
    return [ValidationIssue(field, "") for field in fields if isinstance(field, str)]


def _outcome(result: ToolResult) -> tuple[Outcome, list[ValidationIssue]]:
    if result.get("ok") is True:
        return "ok", []
    issues = _result_issues(result)
    return ("refused" if any(i.field == "permission" for i in issues) else "error"), issues


def _admit(
    tool: str,
    call: CallContext,
    slug: object,
    actor_kind: ActorKind,
    permission: Permission,
    opener: ProjectOpener,
    lab_opener: LabOpener,
) -> None:
    """Return when the call may run; else raise the refusal."""
    authenticated = call.principal.credential is not None
    lab = lab_opener(call.session)
    if lab is None and authenticated:
        raise not_held(permission)
    project: Project | None = None
    if isinstance(slug, str):
        try:
            project = opener(slug, call)
        except ProjectNotFoundError:
            if authenticated:
                raise not_held(permission) from None
            return
    authorize(project, call.principal, actor_kind, permission, lab=lab, tool=tool)


def authorised(
    name: str,
    provider: ContextProvider,
    opener: ProjectOpener,
    lab_opener: LabOpener,
    log: AccessLog | None,
    clock: Clock,
) -> Callable[[ToolFn], ToolFn]:
    """The wrapper of tool `name`. Raises `KeyError` for a tool with no permission row."""
    permission = TOOL_PERMISSIONS[name]
    in_person = permission in HUMAN_ONLY and name not in GATED_AGENT_ACTS
    actor_kind: ActorKind = "human" if in_person else "agent"

    def write(
        call: CallContext | None,
        slug: object,
        outcome: Outcome,
        issues: list[ValidationIssue],
    ) -> None:
        if log is None:
            return
        try:
            log.write(
                AccessEntry(
                    ts=clock.now().astimezone(UTC),
                    principal=None if call is None else call.principal.user,
                    credential=None if call is None else call.principal.credential,
                    session=None if call is None else call.session,
                    channel=Channel.MCP.value,
                    tool=name,
                    project=_loggable(slug),
                    outcome=outcome,
                    fields=field_names(issues),
                )
            )
        except OSError:
            # The call has run and its event may be written: a retry by the agent must not follow.
            _LOG.exception("access log not written for %s", name)

    def decorate(fn: ToolFn) -> ToolFn:
        def run(context: ToolContext | None, arguments: dict[str, Any]) -> ToolResult:
            slug = arguments.get("project")
            try:
                call = provider(context)
            except FactoryValidationError as exc:
                write(None, slug, "refused", exc.issues)
                return fail(exc.issues)
            with call_scope(call, context) as scoped:
                try:
                    _admit(name, scoped, slug, actor_kind, permission, opener, lab_opener)
                except FactoryValidationError as exc:
                    write(scoped, slug, "refused", exc.issues)
                    return fail(exc.issues)
                try:
                    result = fn(**arguments)
                except Exception:
                    write(scoped, slug, "error", [])
                    raise
                outcome, issues = _outcome(result)
                write(scoped, slug, outcome, issues)
                return result

        wrapped = as_tool(fn, run)
        cast(Any, wrapped).__factory_permission__ = permission
        return wrapped

    return decorate


def authorising(
    provider: ContextProvider,
    opener: ProjectOpener,
    lab_opener: LabOpener,
    log: AccessLog | None,
    clock: Clock,
) -> ToolWrapper:
    """What `ScopedServer` puts every tool under."""

    def wrap(name: str, fn: ToolFn) -> ToolFn:
        return authorised(name, provider, opener, lab_opener, log, clock)(fn)

    return wrap
