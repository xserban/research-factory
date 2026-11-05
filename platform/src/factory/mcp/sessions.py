"""Who is calling, per tool call: the principal and the factory session (slice 5 ruling 8).

Every tool runs inside one `call_scope`, so a tool body reads the principal and session of the call
it serves and no closed-over value. `ScopedServer` puts each tool it registers under a wrapper, so a
tool added with a bare `@server.tool()` cannot run outside a scope.

Invariants:
- On stdio the provider returns the local principal and one session per process, as 00-system §7.
- On HTTP a factory session is minted per (principal, transport session), on the first tool call of
  that transport session, and records nothing. A transport session belongs to one principal for
  good; another principal's credential on it is refused as if the session did not exist.
- A transport session that is closed, or idle past the forget term with no request in flight, is
  forgotten. The SDK never issues its id again, so nothing can resurrect the factory session.
- A tool body runs on a worker thread of its own, with a copy of the context, so calls served at the
  same time never see each other's principal.
"""

import functools
import inspect
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Any, TypeAlias, cast

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp_types import Icon, ToolAnnotations
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from pydantic import JsonValue

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.identity import IdGenerator
from factory.model.screening import Channel
from factory.services.context import Principal

CONTEXT_PARAMETER = "mcp_context"
"""The keyword a wrapped tool takes its SDK context by; it is never part of the tool's schema."""

ToolContext: TypeAlias = Context[Any, Any]
ToolResult: TypeAlias = dict[str, JsonValue]
ToolFn: TypeAlias = Callable[..., ToolResult]
ToolWrapper: TypeAlias = Callable[[str, ToolFn], ToolFn]


@dataclass(frozen=True)
class CallContext:
    """The acting principal and factory session of one call. `context` is the SDK's, kept for
    elicitation; None outside a request."""

    principal: Principal
    session: str
    context: ToolContext | None = None


ContextProvider: TypeAlias = Callable[[ToolContext | None], CallContext]


class ThisSession(Enum):
    """What the tool bodies of `build_server` pass as `session`: the session of the running call,
    which is `current_call().session`. It is not a string, so a body that used it as one fails
    `mypy --strict`, and fails validation at run time."""

    CURRENT = "current"


THIS_SESSION = ThisSession.CURRENT

_CALL: ContextVar[CallContext] = ContextVar("factory_call")


def current_call() -> CallContext:
    """The call being served. Raises `LookupError` outside a `call_scope`."""
    return _CALL.get()


@contextmanager
def call_scope(call: CallContext, context: ToolContext | None) -> Iterator[CallContext]:
    scoped = replace(call, context=context)
    token = _CALL.set(scoped)
    try:
        yield scoped
    finally:
        _CALL.reset(token)


def stdio_provider(settings: Settings, clock: Clock) -> ContextProvider:
    """The local principal and one session, minted once for this process."""
    call = CallContext(Principal.local(settings, Channel.MCP), IdGenerator(clock).ulid())

    def provide(_: ToolContext | None) -> CallContext:
        return call

    return provide


class SessionPrincipalMismatch(FactoryValidationError):
    """A transport session bound to one principal was presented by another. The text is the one a
    session that does not exist would get: the SDK answers such a request the same way."""

    def __init__(self) -> None:
        super().__init__([_no_session()])


def _no_session() -> ValidationIssue:
    return ValidationIssue("session", "no such transport session")


@dataclass
class _Binding:
    credential: str
    user: str
    session: str
    last_seen: datetime
    in_flight: int = 0


class SessionRegistry:
    """Transport sessions and the factory sessions minted for them, in memory: a restart ends every
    transport session too. Safe to use from the event loop and from worker threads."""

    def __init__(self, ids: IdGenerator, *, clock: Clock, forget_after: timedelta) -> None:
        self._ids = ids
        self._clock = clock
        self._forget_after = forget_after
        self._lock = Lock()
        self._bindings: dict[str, _Binding] = {}

    def session_for(self, credential_id: str, user: str, transport_session: str) -> str:
        """The factory session of `transport_session`, minted on its first call. Raises
        `SessionPrincipalMismatch` when another credential or user holds it."""
        now = self._clock.now()
        with self._lock:
            binding = self._bindings.get(transport_session)
            if binding is None:
                self._sweep(now)
                binding = _Binding(credential_id, user, self._ids.ulid(), now)
                self._bindings[transport_session] = binding
            elif (binding.credential, binding.user) != (credential_id, user):
                raise SessionPrincipalMismatch
            binding.last_seen = now
            return binding.session

    def forget(self, transport_session: str) -> None:
        with self._lock:
            self._bindings.pop(transport_session, None)

    def enter(self, transport_session: str) -> None:
        """A request for this transport session began. An unknown id is ignored."""
        with self._lock:
            binding = self._bindings.get(transport_session)
            if binding is not None:
                binding.in_flight += 1

    def leave(self, transport_session: str) -> None:
        """A request for this transport session ended; its idle time counts from here. The first
        request of a session binds it while in flight, so the count stops at zero."""
        now = self._clock.now()
        with self._lock:
            binding = self._bindings.get(transport_session)
            if binding is not None:
                binding.in_flight = max(0, binding.in_flight - 1)
                binding.last_seen = now

    def _sweep(self, now: datetime) -> None:
        idle = [
            transport
            for transport, binding in self._bindings.items()
            if binding.in_flight == 0 and now - binding.last_seen > self._forget_after
        ]
        for transport in idle:
            del self._bindings[transport]


def http_provider(registry: SessionRegistry) -> ContextProvider:
    """The principal of the verified token and the factory session of the transport session.

    The session header is trusted only on the stateful path, where the SDK has checked that it names
    a live session of this credential. A request of the sessionless protocol era reaches a tool
    without that check, whatever header it carries, so it is refused (slice 5 ruling 8)."""

    def provide(context: ToolContext | None) -> CallContext:
        token = get_access_token()
        if context is None or token is None or token.subject is None:
            raise FactoryValidationError([_no_session()])
        transport = (context.headers or {}).get(MCP_SESSION_ID_HEADER)
        if not transport or context.protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS:
            raise FactoryValidationError([_no_session()])
        session = registry.session_for(token.client_id, token.subject, transport)
        return CallContext(Principal(token.subject, token.client_id, Channel.MCP), session)

    return provide


def as_tool(fn: ToolFn, run: Callable[[ToolContext | None, dict[str, Any]], ToolResult]) -> ToolFn:
    """A tool with `fn`'s name, docstring and schema that hands its arguments and the SDK's context
    to `run`. It stays a plain function, so the SDK runs it on a worker thread as it ran `fn`."""

    @functools.wraps(fn)
    def tool(*, mcp_context: ToolContext | None = None, **arguments: Any) -> ToolResult:
        return run(mcp_context, arguments)

    signature = inspect.signature(fn)
    parameter = inspect.Parameter(
        CONTEXT_PARAMETER, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context | None
    )
    described = cast(Any, tool)
    described.__signature__ = signature.replace(
        parameters=[*signature.parameters.values(), parameter]
    )
    described.__annotations__ = {**fn.__annotations__, CONTEXT_PARAMETER: Context | None}
    return tool


def scoped(provider: ContextProvider) -> ToolWrapper:
    """Run each tool inside the scope of the call `provider` names."""

    def wrap(name: str, fn: ToolFn) -> ToolFn:
        def run(context: ToolContext | None, arguments: dict[str, Any]) -> ToolResult:
            with call_scope(provider(context), context):
                return fn(**arguments)

        return as_tool(fn, run)

    return wrap


class ScopedServer(MCPServer[Any]):
    """An `MCPServer` that registers each tool under `wrap`. Every registration ends in `add_tool`,
    the decorator's included, so no tool escapes the wrapper."""

    def __init__(self, name: str, *, wrap: ToolWrapper, **options: Any) -> None:
        super().__init__(name, **options)
        self._factory_wrap = wrap

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: Sequence[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> None:
        super().add_tool(
            self._factory_wrap(name or fn.__name__, fn),
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=None if icons is None else list(icons),
            meta=meta,
            structured_output=structured_output,
        )
