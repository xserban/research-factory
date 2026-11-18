"""Which source adapters exist, and how to build each one from settings.

A factory takes `Settings` and the project's `Clock`, so the adapter's HTTP client and its
contact address come from configuration and nowhere else. Tests substitute their own mapping.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from factory.clock import Clock
from factory.config import Settings
from factory.model.search import QueryKind
from factory.sources.arxiv import ArxivSource
from factory.sources.base import Source
from factory.sources.crossref import CrossrefSource
from factory.sources.http import default_http
from factory.sources.importlist import NAME as IMPORTLIST
from factory.sources.importlist import ImportlistReader, ImportlistSource
from factory.sources.openalex import OpenAlexSource
from factory.sources.pubmed import PubmedSource, ncbi_api_key
from factory.sources.reflist import NAME as REFLIST
from factory.sources.reflist import EntryReader, ReflistSource
from factory.sources.stored import NAME as STORED
from factory.sources.stored import StoredSource, WorkReader


@dataclass(frozen=True)
class SourceFactory:
    """How to build one adapter, and which query kinds it takes, known without building it.

    Validation reads `kinds` (the adapter class's own `Source.kinds`), so checking a query
    opens no HTTP client. Calling the factory builds the adapter.
    """

    kinds: frozenset[QueryKind]
    build: Callable[[Settings, Clock], Source]
    probe_kinds: frozenset[QueryKind] | None = None  # None: same as `kinds`
    window_filter: bool = False  # the adapter honours `filters["listed_since"]` (slice 4b)

    def __call__(self, settings: Settings, clock: Clock) -> Source:
        return self.build(settings, clock)


# What a query is sent to, for the record. Unknown sources fall back to their own name.
INTERFACES: dict[str, str] = {
    "openalex": "OpenAlex REST API (api.openalex.org/works)",
    "crossref": "Crossref REST API (api.crossref.org/works)",
    "arxiv": "arXiv API (export.arxiv.org/api/query)",
    "pubmed": "PubMed via NCBI E-utilities (eutils.ncbi.nlm.nih.gov)",
    REFLIST: "Stored reference entries of the included documents (offline)",
    STORED: "Stored records of works the project already holds (offline)",
    IMPORTLIST: "Stored records of an imported library export (offline)",
}


def reflist_factory(read: EntryReader) -> SourceFactory:
    """The offline `reflist` source over one project's stored entries.

    It is not in `default_sources`: its reader is bound to a project, so the snowball service
    builds it for the round it runs (`services.snowball.round_sources`).
    """
    return SourceFactory(
        ReflistSource.kinds, lambda _settings, clock: ReflistSource(read, clock=clock)
    )


def stored_factory(read: WorkReader) -> SourceFactory:
    """The offline `stored` source over one project's stored works (decision 135).

    Like `reflist` it is not in `default_sources`: its reader is bound to a project, so the
    snowball service builds it for the round it runs (`services.snowball.round_sources`).
    """
    return SourceFactory(
        StoredSource.kinds, lambda _settings, clock: StoredSource(read, clock=clock)
    )


def importlist_factory(read: ImportlistReader) -> SourceFactory:
    """The offline `importlist` source over one project's stored import records.

    Like `reflist` it is not in `default_sources`: its reader is bound to a project, so the
    admission service builds it for the import it runs (`services.import_admit`).
    """
    return SourceFactory(
        ImportlistSource.kinds, lambda _settings, clock: ImportlistSource(read, clock=clock)
    )


def openalex_api_key() -> str | None:
    """The OpenAlex API key from `FACTORY_OPENALEX_API_KEY`, else the first line of
    `~/.config/research-factory/openalex-api-key`, else None. Never stored in the repository
    or the event log."""
    key = os.environ.get("FACTORY_OPENALEX_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".config" / "research-factory" / "openalex-api-key"
    try:
        return path.read_text(encoding="utf-8").strip().splitlines()[0] or None
    except (OSError, IndexError):
        return None


def default_sources() -> dict[str, SourceFactory]:
    return {
        "openalex": SourceFactory(
            OpenAlexSource.kinds,
            lambda s, c: OpenAlexSource(
                default_http(s), clock=c, mailto=s.mailto, api_key=openalex_api_key()
            ),
            window_filter=OpenAlexSource.window_filter,
        ),
        "arxiv": SourceFactory(
            ArxivSource.kinds,
            lambda s, c: ArxivSource(default_http(s), clock=c, mailto=s.mailto),
            window_filter=ArxivSource.window_filter,
            # Its id-list intersection is keyed to the query's own `search_query`.
            probe_kinds=frozenset({QueryKind.KEYWORD}),
        ),
        "pubmed": SourceFactory(
            PubmedSource.kinds,
            lambda s, c: PubmedSource(
                default_http(s), clock=c, mailto=s.mailto, api_key=ncbi_api_key()
            ),
            window_filter=PubmedSource.window_filter,
            # An id-list probe has no meaning: the probe measures what a keyword query finds.
            probe_kinds=frozenset({QueryKind.KEYWORD}),
        ),
    }


def window_filter_sources() -> frozenset[str]:
    """The default sources whose adapter filters by listing date, so a watch may window them."""
    return frozenset(name for name, factory in default_sources().items() if factory.window_filter)


def _crossref_factory() -> SourceFactory:
    return SourceFactory(
        CrossrefSource.kinds,
        lambda s, c: CrossrefSource(default_http(s), clock=c, mailto=s.mailto),
    )


def status_sources() -> dict[str, SourceFactory]:
    """The adapters a status lookup may use: the default sources plus Crossref.

    Crossref takes no search purpose, so it is not among `default_sources`: a protocol cannot
    plan a search of it."""
    return {**default_sources(), "crossref": _crossref_factory()}


def lookup_sources() -> dict[str, SourceFactory]:
    """The adapters reference resolution may look works up in (IDEA-89): the default sources plus
    Crossref. Like `status_sources`, never used to validate a protocol."""
    return {**default_sources(), "crossref": _crossref_factory()}
