"""The contract every full-text route meets.

A route returns a `RouteResult` describing one attempt. The attempt's outcome and reason are the
only verdict it gives; whether the content becomes a document is decided by the service.
`metadata` is the raw response a route consulted to decide (for example arXiv's version lookup),
so it can be archived in `blobs/` alongside the content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Work


@dataclass(frozen=True)
class RouteResult:
    """One route's answer for one work.

    Invariants: `reason` is set exactly when the outcome is not retrieved; `content` and
    `media_type` are set exactly when the outcome is retrieved; `url` never carries a secret.
    """

    route: Route
    outcome: AttemptOutcome
    url: str | None = None
    http_status: int | None = None
    reason: str | None = None
    content: bytes | None = None
    media_type: str | None = None
    source_version: str | None = None
    licence: str | None = None
    metadata: bytes | None = None


def not_retrieved(
    route: Route,
    outcome: AttemptOutcome,
    reason: str,
    *,
    url: str | None = None,
    http_status: int | None = None,
    metadata: bytes | None = None,
) -> RouteResult:
    """A result for an attempt that yielded no content, named by its fixed reason string."""
    return RouteResult(
        route=route,
        outcome=outcome,
        url=url,
        http_status=http_status,
        reason=reason,
        metadata=metadata,
    )


class FullTextRoute(Protocol):
    """A source of full text. `version` pins the exact version to fetch, for restore."""

    route: Route

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult: ...
