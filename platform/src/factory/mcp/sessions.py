"""Who is calling, per tool call: the principal and the factory session (slice 5 ruling 8).

Every tool runs inside one `call_scope`, so a tool body reads the principal and session of the call
it serves and no closed-over value. `ScopedServer` puts each tool it registers under a wrapper, so a
tool added with a bare `@server.tool()` cannot run outside a scope.

Invariants:
- On stdio the provider returns the local principal and one session per process, as 00-system §7.
- A tool body runs on a worker thread of its own, with a copy of the context, so calls served at the
  same time never see each other's principal.
"""

import functools
import inspect
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, TypeAlias, cast

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import Icon, ToolAnnotations
from pydantic import JsonValue

from factory.clock import Clock
from factory.config import Settings
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
