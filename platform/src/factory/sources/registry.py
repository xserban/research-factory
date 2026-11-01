"""Which source adapters exist, and how to build each one from settings.

A factory takes `Settings` and the project's `Clock`, so the adapter's HTTP client and its
contact address come from configuration and nowhere else. Tests substitute their own mapping.
"""

from collections.abc import Callable

from factory.clock import Clock
from factory.config import Settings
from factory.sources.arxiv import ArxivSource
from factory.sources.base import Source
from factory.sources.http import default_http
from factory.sources.openalex import OpenAlexSource

SourceFactory = Callable[[Settings, Clock], Source]

# What a query is sent to, for the record. Unknown sources fall back to their own name.
INTERFACES: dict[str, str] = {
    "openalex": "OpenAlex REST API (api.openalex.org/works)",
    "arxiv": "arXiv API (export.arxiv.org/api/query)",
}


def default_sources() -> dict[str, SourceFactory]:
    return {
        "openalex": lambda s, c: OpenAlexSource(default_http(s), clock=c, mailto=s.mailto),
        "arxiv": lambda s, c: ArxivSource(default_http(s), clock=c),
    }
