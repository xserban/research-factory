"""Crossref works lookups (IDEA-89): DOI lists and title queries parsed into works."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from factory.clock import FixedClock
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import WorkType
from factory.sources.base import RawPage, SearchResult
from factory.sources.crossref import CrossrefSource
from factory.sources.http import PoliteClient
from tests.helpers import SESSION, T0

RUN_ID = f"run_{SESSION}"
QUERY_ID = f"qry_{SESSION}"
Handler = Callable[[httpx.Request], httpx.Response]

ARTICLE: dict[str, Any] = {
    "DOI": "10.1000/Alpha",
    "type": "journal-article",
    "title": ["Self-Supervised  Vessel Segmentation"],
    "container-title": ["Medical Image Analysis"],
    "publisher": "Elsevier",
    "volume": "88",
    "issue": "2",
    "page": "10-22",
    "issued": {"date-parts": [[2023, 6, 14]]},
    "author": [
        {"given": "Ada", "family": "Zhou", "ORCID": "http://orcid.org/0000-0002-1825-0097"},
        {"name": "The Vessel Consortium"},
    ],
    "is-referenced-by-count": 30,
}
PREPRINT: dict[str, Any] = {
    "DOI": "10.1101/2024.01.01.000001",
    "type": "posted-content",
    "title": ["A preprint without an issued date"],
    "posted": {"date-parts": [[2024, 1, 2]]},
    "author": [{"given": "Bo", "family": "Liu"}],
}
NO_YEAR: dict[str, Any] = {
    "DOI": "10.1000/noyear",
    "type": "journal-article",
    "title": ["A record with no year at all"],
    "issued": {"date-parts": [[None]]},
}
UNTITLED: dict[str, Any] = {"DOI": "10.1000/untitled", "type": "journal-article"}


def _body(items: list[dict[str, Any]], total: int | None = None) -> str:
    message = {"total-results": len(items) if total is None else total, "items": items}
    return json.dumps({"status": "ok", "message-type": "work-list", "message": message})


def _archive(page: RawPage) -> str:
    return f"sha256:{page.ordinal + 1:064x}"


def _source(handler: Handler, *, mailto: str | None = "me@example.org") -> CrossrefSource:
    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None)
    return CrossrefSource(http, clock=FixedClock(T0), mailto=mailto)


def _serving(body: str, seen: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=body)

    return handler


def _spec(text: str, **fields: Any) -> QuerySpec:
    return QuerySpec(
        source="crossref",
        kind=QueryKind.FILTER,
        text=text,
        purpose=QueryPurpose.PROBE,
        **fields,
    )


def _run(source: CrossrefSource, spec: QuerySpec) -> SearchResult:
    return source.run(spec, run_id=RUN_ID, query_id=QUERY_ID, archive=_archive)


def test_journal_article_is_parsed() -> None:
    seen: list[httpx.Request] = []
    result = _run(_source(_serving(_body([ARTICLE]), seen)), _spec("doi:10.1000/alpha"))
    assert result.status is RunStatus.COMPLETE and result.note is None
    [work] = result.works
    assert work.title == "Self-Supervised Vessel Segmentation"
    assert work.type is WorkType.JOURNAL_ARTICLE
    assert work.identifiers.doi == "10.1000/alpha"
    assert [a.name for a in work.authors] == ["Ada Zhou", "The Vessel Consortium"]
    assert work.authors[0].orcid == "0000-0002-1825-0097"
    assert work.venue is not None
    assert work.venue.name == "Medical Image Analysis" and work.venue.pages == "10-22"
    assert work.dates.published == date(2023, 6, 14) and work.cited_by_count == 30
    assert work.provenance[0].source == "crossref"
    assert work.provenance[0].raw_blob == _archive(RawPage(0, "", "", T0))


def test_preprint_takes_its_posted_date() -> None:
    result = _run(_source(_serving(_body([PREPRINT]), [])), _spec("doi:10.1101/2024.01.01.000001"))
    [work] = result.works
    assert work.type is WorkType.PREPRINT and work.dates.published == date(2024, 1, 2)


def test_missing_year_stays_missing() -> None:
    result = _run(_source(_serving(_body([NO_YEAR]), [])), _spec("doi:10.1000/noyear"))
    [work] = result.works
    assert work.dates.year is None


def test_untitled_item_is_skipped_and_noted() -> None:
    result = _run(_source(_serving(_body([ARTICLE, UNTITLED]), [])), _spec("doi:a|b"))
    assert len(result.works) == 1 and result.skipped == 1
    assert result.note is not None and "skipped" in result.note


def test_doi_list_is_a_filter_with_rows_equal_to_the_dois_asked() -> None:
    seen: list[httpx.Request] = []
    _run(_source(_serving(_body([]), seen)), _spec("doi:10.1/a|10.1/b|10.1/c"))
    [request] = seen
    assert request.url.params["filter"] == "doi:10.1/a,doi:10.1/b,doi:10.1/c"
    assert request.url.params["rows"] == "3"
    assert request.url.params["mailto"] == "me@example.org"


def test_title_query_uses_bibliographic_search_with_the_limit_as_rows() -> None:
    seen: list[httpx.Request] = []
    _run(
        _source(_serving(_body([ARTICLE], total=4000), seen)),
        _spec("title.search:vessels", limit=7),
    )
    params = seen[0].url.params
    assert params["query.bibliographic"] == "vessels" and params["rows"] == "7"
    assert "filter" not in params


def test_title_query_with_more_matches_than_the_limit_is_partial() -> None:
    result = _run(
        _source(_serving(_body([ARTICLE], total=4000), [])), _spec("title.search:v", limit=1)
    )
    assert result.status is RunStatus.PARTIAL and len(result.works) == 1


def test_a_lookup_is_one_archived_page_without_the_contact_address() -> None:
    pages: list[RawPage] = []

    def archive(page: RawPage) -> str:
        pages.append(page)
        return _archive(page)

    source = _source(_serving(_body([ARTICLE]), []))
    source.run(_spec("doi:10.1/a"), run_id=RUN_ID, query_id=QUERY_ID, archive=archive)
    [page] = pages
    assert "me@example.org" not in page.url and page.ordinal == 0


def test_http_error_is_a_failed_explained_run() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = _run(_source(handler), _spec("doi:10.1/a"))
    assert result.status is RunStatus.FAILED and result.works == []
    assert result.note and "me@example.org" not in result.note


def test_429_is_retried_by_the_polite_client() -> None:
    answers = iter([httpx.Response(429, headers={"Retry-After": "0"}), None])

    def handler(_r: httpx.Request) -> httpx.Response:
        first = next(answers)
        return first if first is not None else httpx.Response(200, text=_body([ARTICLE]))

    result = _run(_source(handler), _spec("doi:10.1000/alpha"))
    assert result.status is RunStatus.COMPLETE and len(result.works) == 1


def test_unparseable_body_is_a_failed_run_with_the_page_archived() -> None:
    pages: list[RawPage] = []

    def archive(page: RawPage) -> str:
        pages.append(page)
        return _archive(page)

    source = _source(_serving("<html>nope</html>", []))
    result = source.run(_spec("doi:10.1/a"), run_id=RUN_ID, query_id=QUERY_ID, archive=archive)
    assert result.status is RunStatus.FAILED and len(pages) == 1


@pytest.mark.parametrize("text", ["updates:10.1/x", "doi:", "title.search:  "])
def test_unknown_lookup_text_is_refused(text: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ValueError):
        # QuerySpec strips the text; "doi:" alone names no DOI
        _run(_source(_serving(_body([]), seen)), _spec(text))
    assert seen == []
