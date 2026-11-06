"""The outbound guard (slice 5 security model; plan ruling 5): a server must not be turned into a
way to reach its own network.

Invariants:
- Only `https` URLs with a host are fetched.
- Every address the host resolves to must be global; one private, loopback, link-local or reserved
  address refuses the URL, before any connection is made.
- A name that does not resolve is refused. An IP literal is checked as it stands.
- The check runs again on every redirect hop (`client_hook`), so a public URL cannot lead inward.
"""

import ipaddress
import socket
from collections.abc import Callable

import httpx

Resolver = Callable[[str], list[str]]


class OutboundRefused(httpx.RequestError):
    """A request the guard refused. A `RequestError`, so callers that catch `httpx.HTTPError` treat
    it as a failed fetch; not a `TransportError`, so it is never retried."""


def default_resolve(host: str) -> list[str]:
    """Every address `host` resolves to, as text. Raises `OSError` when it does not resolve."""
    return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})


def require_public_https(url: str, resolve: Resolver = default_resolve) -> None:
    """Return when `url` is an https URL whose host resolves only to global addresses; else raise
    `OutboundRefused`."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise OutboundRefused(f"not a URL: {url[:80]!r}") from None
    if parsed.scheme != "https" or not parsed.host:
        raise OutboundRefused("only https URLs are fetched")
    host = parsed.host
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = resolve(host)
        except OSError:
            raise OutboundRefused(f"{host} does not resolve") from None
    if not addresses:
        raise OutboundRefused(f"{host} does not resolve")
    for address in addresses:
        try:
            public = ipaddress.ip_address(address.split("%", 1)[0]).is_global
        except ValueError:
            public = False
        if not public:
            raise OutboundRefused(f"{host} resolves to a non-public address")


def client_hook(resolve: Resolver = default_resolve) -> Callable[[httpx.Request], None]:
    """An httpx `request` event hook: httpx calls it for the first request and for each redirect."""

    def check(request: httpx.Request) -> None:
        require_public_https(str(request.url), resolve)

    return check
