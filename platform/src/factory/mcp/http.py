"""The factory's MCP tools over authenticated streamable HTTP (slice 5, "Deployment topology").

Wiring only: `verify_token` decides who a token names, `SessionRegistry` maps transport sessions.

Invariants:
- Stateful mode only (plan ruling 1): the SDK refuses a request without `Mcp-Session-Id` after
  initialisation, and `http_provider` refuses a call of the sessionless protocol era.
- Nothing listens here: `build_http_app` returns an ASGI app and opens no socket.
- A token is checked on every HTTP request, so a revocation or a deactivation takes effect at once.
- A refusal at the transport leaves one access-log line, with no header value in it.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, timedelta
from functools import partial

import anyio.to_thread
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import DEFAULT_SESSION_IDLE_TIMEOUT
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryError
from factory.mcp.server import build_server
from factory.mcp.sessions import SessionRegistry, http_provider
from factory.model.fulltext import Route
from factory.model.identity import IdGenerator
from factory.model.screening import Channel
from factory.services.access_log import AccessEntry, AccessLog
from factory.services.credentials import verify_token
from factory.services.lab import Lab, open_lab
from factory.sources.fulltext.base import FullTextRoute
from factory.sources.registry import SourceFactory

SCOPE = "factory"
TRANSPORT_TOOL = "transport"
"""The `tool` of an access-log line for a request refused before any tool ran."""


class FactoryTokenVerifier:
    """The SDK's `TokenVerifier` over `verify_token`. The `AccessToken` carries the credential id,
    never the secret. The lab is opened per request, so the registry is read as it stands."""

    def __init__(self, lab_opener: Callable[[], Lab], clock: Clock) -> None:
        self._lab_opener = lab_opener
        self._clock = clock

    def _verify(self, token: str) -> AccessToken | None:
        try:
            verified = verify_token(self._lab_opener(), token, self._clock.now())
        except FactoryError:
            return None
        if verified is None:
            return None
        return AccessToken(
            token=verified.credential_id,
            client_id=verified.credential_id,
            subject=verified.user,
            scopes=[SCOPE],
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await anyio.to_thread.run_sync(partial(self._verify, token))


class TransportAccess:
    """Outermost ASGI layer: keeps the registry's idle clock, forgets a session the client ended,
    and logs each request the transport refused (status 400 and above) before any tool ran."""

    def __init__(
        self, app: ASGIApp, *, registry: SessionRegistry, log: AccessLog, clock: Clock
    ) -> None:
        self._app = app
        self._registry = registry
        self._log = log
        self._clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        transport = Headers(scope=scope).get(MCP_SESSION_ID_HEADER)
        status = 0

        async def watched(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        if transport is not None:
            self._registry.enter(transport)
        try:
            await self._app(scope, receive, watched)
        finally:
            if transport is not None:
                self._registry.leave(transport)
                if scope["method"] == "DELETE" and status < 400:
                    self._registry.forget(transport)
        if status >= 400:
            await anyio.to_thread.run_sync(partial(self._write, scope))

    def _write(self, scope: Scope) -> None:
        user = scope.get("user")
        token = user.access_token if isinstance(user, AuthenticatedUser) else None
        self._log.write(
            AccessEntry(
                ts=self._clock.now().astimezone(UTC),
                principal=None if token is None else token.subject,
                credential=None if token is None else token.client_id,
                session=None,
                channel=Channel.MCP.value,
                tool=TRANSPORT_TOOL,
                project=None,
                outcome="refused",
            )
        )


def build_http_app(
    settings: Settings,
    *,
    issuer_url: str,
    resource_url: str,
    allowed_hosts: Sequence[str],
    allowed_origins: Sequence[str],
    clock: Clock | None = None,
    sources: Mapping[str, SourceFactory] | None = None,
    fulltext_routes: Callable[[], Mapping[Route, FullTextRoute]] | None = None,
) -> Starlette:
    """The ASGI app of `factory serve --http`. `issuer_url` is what the protected-resource metadata
    names; v1 tokens are personal ones, so no authorisation server is run here (ruling 7)."""
    now = clock or SystemClock()
    ids = IdGenerator(now)
    server_session = ids.ulid()

    def lab_opener() -> Lab:
        return open_lab(settings, session=server_session, clock=now)

    registry = SessionRegistry(
        ids, clock=now, forget_after=timedelta(seconds=2 * DEFAULT_SESSION_IDLE_TIMEOUT)
    )
    server = build_server(
        settings,
        now,
        sources,
        fulltext_routes,
        context=http_provider(registry),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url),
            resource_server_url=AnyHttpUrl(resource_url),
            required_scopes=[SCOPE],
            validate_token_resource=False,
        ),
        token_verifier=FactoryTokenVerifier(lab_opener, now),
    )
    app = server.streamable_http_app(
        stateless_http=False,
        session_idle_timeout=DEFAULT_SESSION_IDLE_TIMEOUT,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts),
            allowed_origins=list(allowed_origins),
        ),
    )
    app.add_middleware(TransportAccess, registry=registry, log=AccessLog(settings.root), clock=now)
    return app
