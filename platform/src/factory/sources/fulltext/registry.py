"""The full-text routes the factory tries automatically, built from settings.

`default_routes` builds one polite client shared by every route (so one throttle clock per host)
and one version lookup shared by the two arXiv routes. Each call returns fresh routes with a
fresh lookup, so no version answer outlives the call that asked for it. `RESEARCHER` is not
included: it is supplied by the researcher, never fetched.
"""

from __future__ import annotations

from factory.config import Settings
from factory.model.fulltext import Route
from factory.sources.fulltext.arxiv import (
    ArxivHtmlRoute,
    ArxivSourceRoute,
    arxiv_version_lookup,
)
from factory.sources.fulltext.base import FullTextRoute
from factory.sources.fulltext.oa_pdf import OaPdfRoute
from factory.sources.fulltext.pmc import PmcJatsRoute
from factory.sources.http import default_http


def default_routes(settings: Settings) -> dict[Route, FullTextRoute]:
    """The automatic routes, keyed by route, in the order they are tried."""
    http = default_http(settings)
    lookup = arxiv_version_lookup(http)
    return {
        Route.ARXIV_HTML: ArxivHtmlRoute(http, lookup=lookup),
        Route.ARXIV_SOURCE: ArxivSourceRoute(http, lookup=lookup),
        Route.PMC_JATS: PmcJatsRoute(http),
        Route.OA_PDF: OaPdfRoute(http, settings.mailto),
    }
