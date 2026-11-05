"""Stub full-text retrieval routes for tests."""

from collections.abc import Callable

from factory.model.fulltext import (
    AttemptOutcome,
    Route,
)
from factory.model.work import Work
from factory.sources.fulltext.base import RouteResult, not_retrieved

Answer = Callable[[Work], RouteResult]


class StubRoute:
    """A route whose answer for each work comes from `answer`. `calls` lists the works asked."""

    def __init__(self, route: Route, answer: Answer) -> None:
        self.route = route
        self._answer = answer
        self.calls: list[str] = []

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        self.calls.append(work.id)
        return self._answer(work)


def always(result: RouteResult) -> Answer:
    return lambda _work: result


def retrieved(
    route: Route,
    content: bytes,
    *,
    version: str | None = "v2",
    licence: str | None = None,
    url: str | None = None,
    media_type: str | None = "text/html",
    metadata: bytes | None = None,
) -> RouteResult:
    return RouteResult(
        route=route,
        outcome=AttemptOutcome.RETRIEVED,
        url=url or f"https://arxiv.org/html/2101.00001{version or ''}",
        http_status=200,
        content=content,
        media_type=media_type,
        source_version=version,
        licence=licence,
        metadata=metadata,
    )


def missing(route: Route, reason: str) -> RouteResult:
    return not_retrieved(route, AttemptOutcome.NOT_AVAILABLE, reason)


def routes_for(**answering: Answer) -> dict[Route, StubRoute]:
    """One stub per automatic route, keyed by route, with the answers given by route value."""
    return {
        route: StubRoute(route, answering.get(route.name.lower(), always(missing(route, "none"))))
        for route in (Route.ARXIV_HTML, Route.ARXIV_SOURCE, Route.OA_PDF)
    }
