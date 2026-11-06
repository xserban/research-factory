"""May this root be served over HTTP? (slice 5 ruling 7; `factory serve --http`.)

Invariants:
- Serving needs a lab registry, a host id, a root `server_check` passes, and a loopback bind: TLS
  ends at the reverse proxy, so a public bind needs the explicit `insecure_direct`.
- Each failed condition is one issue; an empty list means the server may start.
"""

import ipaddress

from factory.config import Settings
from factory.errors import ValidationIssue
from factory.services.lab import lab_exists
from factory.services.server_check import server_check


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def serve_http_issues(
    settings: Settings, host: str, *, insecure_direct: bool
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not lab_exists(settings):
        issues.append(ValidationIssue("lab", "no lab registry here; run `factory server init`"))
    if settings.host_id is None:
        issues.append(ValidationIssue("host_id", "this machine has no host id"))
    issues.extend(server_check(settings))
    if not is_loopback(host) and not insecure_direct:
        issues.append(
            ValidationIssue(
                "host", "bind to loopback behind a TLS proxy, or pass --insecure-direct"
            )
        )
    return issues
