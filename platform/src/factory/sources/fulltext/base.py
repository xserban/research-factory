"""The contract every full-text route meets.

A route returns a `RouteResult` describing one attempt. The attempt's outcome and reason are the
only verdict it gives; whether the content becomes a document is decided by the service.
`metadata` is the raw response a route consulted to decide (for example arXiv's version lookup),
so it can be archived in `blobs/` alongside the content.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv


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


def transport_failure(
    route: Route, *, url: str | None = None, metadata: bytes | None = None
) -> RouteResult:
    """The failed attempt for a request that raised before any response (any `httpx.RequestError`).

    This covers transport errors and redirect errors such as `httpx.TooManyRedirects`, which are
    not transport errors but must not escape a route.
    """
    return not_retrieved(route, AttemptOutcome.FAILED, "transport", url=url, metadata=metadata)


class FullTextRoute(Protocol):
    """A source of full text. `version` pins the exact version to fetch, for restore."""

    route: Route

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult: ...


@dataclass(frozen=True)
class VersionAnswer:
    """The arXiv export API's answer for one bare id: the latest versioned id, if one was named.

    `status` and `body` are the raw response, kept so a route can archive what it consulted.
    """

    versioned: str | None
    status: int
    body: bytes


class ArxivVersionLookup:
    """A per-call cache of arXiv version lookups, keyed by bare arXiv id.

    A `fetch_fulltext` call creates one lookup and passes it to every arXiv route, so the API is
    asked once per paper per call. A lookup that raised is not cached; an answer, whatever its
    status, is. Create a new lookup per call: a long-lived one would serve stale versions.
    """

    def __init__(self, resolve: Callable[[str], VersionAnswer]) -> None:
        self._resolve = resolve
        self._answers: dict[str, VersionAnswer] = {}

    def get(self, arxiv_id: str) -> VersionAnswer:
        base = normalize_arxiv(arxiv_id)
        answer = self._answers.get(base)
        if answer is None:
            answer = self._resolve(base)
            self._answers[base] = answer
        return answer
