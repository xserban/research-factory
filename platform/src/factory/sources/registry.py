"""Which source adapters exist, and how to build each one from settings.

A factory takes `Settings` and the project's `Clock`, so the adapter's HTTP client and its
contact address come from configuration and nowhere else. Tests substitute their own mapping.
"""

from collections.abc import Callable
from dataclasses import dataclass

from factory.clock import Clock
from factory.config import Settings
from factory.model.search import QueryKind
from factory.sources.arxiv import ArxivSource
from factory.sources.base import Source
from factory.sources.http import default_http
from factory.sources.openalex import OpenAlexSource


@dataclass(frozen=True)
class SourceFactory:
    """How to build one adapter, and which query kinds it takes, known without building it.

    Validation reads `kinds` (the adapter class's own `Source.kinds`), so checking a query
    opens no HTTP client. Calling the factory builds the adapter.
    """

    kinds: frozenset[QueryKind]
    build: Callable[[Settings, Clock], Source]

    def __call__(self, settings: Settings, clock: Clock) -> Source:
        return self.build(settings, clock)


# What a query is sent to, for the record. Unknown sources fall back to their own name.
INTERFACES: dict[str, str] = {
    "openalex": "OpenAlex REST API (api.openalex.org/works)",
    "arxiv": "arXiv API (export.arxiv.org/api/query)",
}


def default_sources() -> dict[str, SourceFactory]:
    return {
        "openalex": SourceFactory(
            OpenAlexSource.kinds,
            lambda s, c: OpenAlexSource(default_http(s), clock=c, mailto=s.mailto),
        ),
        "arxiv": SourceFactory(
            ArxivSource.kinds,
            lambda s, c: ArxivSource(default_http(s), clock=c, mailto=s.mailto),
        ),
    }
