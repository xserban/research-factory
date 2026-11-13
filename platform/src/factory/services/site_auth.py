"""The authentication seam of the hub servers (plan 2026-11-13-main-hub, part 2).

One function, `Authenticator.check`, decides for every request to the hub servers who the actor
is and whether it may do the act. `site_server` only asks; it holds no token, host or origin test
of its own, so replacing the implementation (a login, a user's project list) changes nothing else.
There is one implementation, `LoopbackTokenAuth`: the request must come from a loopback host (and,
for a write, from a loopback origin), and a write must carry the token of the scope it is made in.
There are no users, no sessions and no database.

Invariants:
- `check` is total: it never raises, and a malformed request is a refusal with a reason.
- An allowed decision names the actor, today always `human` (the local researcher, as the CLI is):
  every write route of the hub records its events as the human actor, so an authenticator that does
  not allow `human` cannot let a write happen, and nothing here ever returns `system` or `agent`.
- A read needs only a loopback host. A write also needs a loopback origin when the browser sends
  one, and the token of its scope (a project's slug, or the hub itself with `Scope(None)`).
- Tokens are derived from the server's secret and the scope, so one scope's token authorises no
  other scope. `page_credential` issues the token a served page carries for its scope.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, Protocol

LOOPBACK: Final = {"127.0.0.1", "localhost", "[::1]"}
HUB_SLUG: Final = "hub:feed"
"""The scope slug the hub's own token is derived from; no project folder can have a colon."""


@dataclass(frozen=True)
class Scope:
    """What a request is made in: a project (its slug) or the hub itself (`slug` None)."""

    slug: str | None


@dataclass(frozen=True)
class AuthRequest:
    """The facts of one request the decision may use. `act` is `read` for a read, else the route's
    path inside its scope (for example `/api/feed/react`)."""

    method: str
    path: str
    host: str
    origin: str | None
    credential: str | None
    scope: Scope
    act: str


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    actor: Literal["human"] | None
    reason: str


class Authenticator(Protocol):
    """The seam: who is this request, and may it do this act."""

    def check(self, request: AuthRequest) -> AuthDecision: ...

    def page_credential(self, scope: Scope) -> str:
        """The token a page served for `scope` carries and sends back with its writes."""
        ...


def _refuse(reason: str) -> AuthDecision:
    return AuthDecision(False, None, reason)


def host_name(host: str) -> str:
    """The host part of a `Host` header value, without the port."""
    return host.split("]", 1)[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]


class LoopbackTokenAuth:
    """Loopback host, same-origin writes, and the per-scope token. The only implementation."""

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._port_of: Callable[[], int] = lambda: -1

    def bind(self, port_of: Callable[[], int]) -> None:
        """Say which port the server listens on (known once it is bound), for the origin test."""
        self._port_of = port_of

    def page_credential(self, scope: Scope) -> str:
        slug = HUB_SLUG if scope.slug is None else scope.slug
        return hmac.new(self._secret, slug.encode(), "sha256").hexdigest()

    def check(self, request: AuthRequest) -> AuthDecision:
        if host_name(request.host) not in LOOPBACK:
            return _refuse("host is not loopback")
        if request.act == "read":
            return AuthDecision(True, "human", "")
        if request.origin is not None:
            allowed = {f"http://{name}:{self._port_of()}" for name in LOOPBACK}
            if request.origin not in allowed:
                return _refuse("origin is not this server")
        sent = (request.credential or "").encode()
        if not hmac.compare_digest(sent, self.page_credential(request.scope).encode()):
            return _refuse("missing or wrong token for this scope")
        return AuthDecision(True, "human", "")
