"""Status parsers: Crossref update metadata, OpenAlex flags and locations, arXiv versions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from factory.clock import FixedClock
from factory.model.notices import NoticeKind
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Identifiers
from factory.sources.arxiv import ArxivSource
from factory.sources.base import RawPage, SearchResult, StatusRecord
from factory.sources.crossref import CrossrefSource
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from factory.sources.registry import default_sources, status_sources
from tests.helpers import SESSION, T0

FIXTURES = Path(__file__).parent / "fixtures" / "living"
RUN_ID = f"run_{SESSION}"
QUERY_ID = f"qry_{SESSION}"
Handler = Callable[[httpx.Request], httpx.Response]


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _http(handler: Handler) -> PoliteClient:
    return PoliteClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None)


def _serve(*bodies: str) -> Handler:
    calls = iter(bodies)
    return lambda _r: httpx.Response(200, text=next(calls, bodies[-1]))


def _archive(page: RawPage) -> str:
    return f"sha256:{page.ordinal + 1:064x}"


def _status(text: str, source: str, kind: QueryKind) -> QuerySpec:
    return QuerySpec(source=source, kind=kind, text=text, purpose=QueryPurpose.STATUS)


def _crossref(*bodies: str, seen: list[httpx.Request] | None = None) -> CrossrefSource:
    inner = _serve(*bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return inner(request)

    return CrossrefSource(_http(handler), clock=FixedClock(T0), mailto="me@example.org")


def _run(source: CrossrefSource | OpenAlexSource | ArxivSource, spec: QuerySpec) -> SearchResult:
    return source.run(spec, run_id=RUN_ID, query_id=QUERY_ID, archive=_archive)


def test_crossref_retraction_parsed() -> None:
    source = _crossref(_fixture("crossref_updates_retraction.json"))
    result = _run(source, _status("updates:10.1000/alpha", "crossref", QueryKind.FILTER))
    assert result.status is RunStatus.COMPLETE and result.works == []
    assert result.status_records == (
        StatusRecord(
            target=Identifiers(doi="10.1000/alpha"),
            kind="notice",
            notice_kind=NoticeKind.RETRACTION,
            notice_doi="10.1000/alpha.retraction",
            notice_date=date(2023, 5, 17),
        ),
    )


def test_crossref_correction_parsed() -> None:
    source = _crossref(_fixture("crossref_updates_mixed.json"))
    result = _run(source, _status("updates:10.1000/beta", "crossref", QueryKind.FILTER))
    by_kind = {r.notice_kind: r for r in result.status_records}
    correction = by_kind[NoticeKind.CORRECTION]
    assert correction.notice_doi == "10.1000/beta.correction"
    assert correction.notice_date == date(2024, 1, 8)
    assert correction.target == Identifiers(doi="10.1000/beta")
    # No `updated`: the notice's own issue date, a bare month taken as its first day.
    assert by_kind[NoticeKind.EXPRESSION_OF_CONCERN].notice_date == date(2024, 3, 1)
    assert by_kind[NoticeKind.WITHDRAWAL].notice_date == date(2024, 5, 19)


def test_crossref_unknown_update_type_ignored_and_counted() -> None:
    source = _crossref(_fixture("crossref_updates_mixed.json"))
    result = _run(source, _status("updates:10.1000/beta", "crossref", QueryKind.FILTER))
    assert len(result.status_records) == 3
    assert result.note is not None and "2 update(s) of other types ignored" in result.note
    assert "addendum" in result.note and "new_version" in result.note


def test_crossref_sends_filter_polite_and_archives_before_parse() -> None:
    seen: list[httpx.Request] = []
    archived: list[RawPage] = []

    def archive(page: RawPage) -> str:
        archived.append(page)
        return _archive(page)

    source = _crossref(_fixture("crossref_updates_retraction.json"), seen=seen)
    source.run(
        _status("updates:10.1000/alpha", "crossref", QueryKind.FILTER),
        run_id=RUN_ID,
        query_id=QUERY_ID,
        archive=archive,
    )
    params = dict(seen[0].url.params)
    assert params["filter"] == "updates:10.1000/alpha" and params["mailto"] == "me@example.org"
    assert len(archived) == 1 and "me@example.org" not in archived[0].url


def test_crossref_follows_cursor_to_the_end() -> None:
    page_one = _fixture("crossref_updates_retraction.json")
    empty = _fixture("crossref_updates_empty.json")
    seen: list[httpx.Request] = []
    source = _crossref(page_one, empty, seen=seen)
    # total-results is 1 and one item came back: no second request is needed.
    result = _run(source, _status("updates:10.1000/alpha", "crossref", QueryKind.FILTER))
    assert len(seen) == 1 and len(result.status_records) == 1


def test_crossref_takes_no_search_queries() -> None:
    source = _crossref(_fixture("crossref_updates_empty.json"))
    with pytest.raises(ValueError):
        _run(source, QuerySpec(source="crossref", kind=QueryKind.FILTER, text="updates:10.1/x"))
    assert "crossref" in status_sources() and "crossref" in default_sources()


def test_crossref_bad_json_is_a_failed_explained_run() -> None:
    source = _crossref("<html>nope</html>")
    result = _run(source, _status("updates:10.1000/alpha", "crossref", QueryKind.FILTER))
    assert result.status is RunStatus.FAILED and result.note


def _openalex(body: str, seen: list[httpx.Request] | None = None) -> OpenAlexSource:
    inner = _serve(body)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return inner(request)

    return OpenAlexSource(_http(handler), clock=FixedClock(T0))


def test_openalex_is_retracted_parsed() -> None:
    seen: list[httpx.Request] = []
    source = _openalex(_fixture("openalex_status_retracted.json"), seen)
    result = _run(source, _status("doi:10.1000/alpha|10.1000/beta", "openalex", QueryKind.FILTER))
    assert result.works == [] and result.status is RunStatus.COMPLETE
    assert dict(seen[0].url.params)["filter"] == "doi:10.1000/alpha|10.1000/beta"
    [notice] = [r for r in result.status_records if r.kind == "notice"]
    assert notice.notice_kind is NoticeKind.RETRACTION
    assert notice.notice_doi is None and notice.notice_date is None
    assert notice.target.openalex == "W9001" and notice.target.doi == "10.1000/alpha"


def test_openalex_published_location_parsed() -> None:
    source = _openalex(_fixture("openalex_status_retracted.json"))
    result = _run(source, _status("openalex:W9001|W9002", "openalex", QueryKind.FILTER))
    [linked] = [r for r in result.status_records if r.kind == "version"]
    assert linked.target.openalex == "W9002"
    assert linked.target.arxiv == "2301.00001"  # bridged from the DataCite DOI
    assert linked.linked == Identifiers(doi="10.1000/beta-journal")
    assert linked.venue == "Journal of Synthetic Results"
    # The alpha work's published location is its own DOI: no link.
    assert all(r.target.openalex != "W9001" for r in result.status_records if r.kind == "version")


def _arxiv(body: str, seen: list[httpx.Request] | None = None) -> ArxivSource:
    inner = _serve(body)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return inner(request)

    return ArxivSource(_http(handler), clock=FixedClock(T0))


def test_arxiv_latest_version_and_doi_parsed() -> None:
    seen: list[httpx.Request] = []
    source = _arxiv(_fixture("arxiv_status_v3.xml"), seen)
    result = _run(source, _status("2301.00001,2302.00002", "arxiv", QueryKind.ID_LIST))
    assert result.works == [] and result.status is RunStatus.COMPLETE
    assert dict(seen[0].url.params)["id_list"] == "2301.00001,2302.00002"
    first, second = result.status_records
    assert (
        first.target == Identifiers(arxiv="2301.00001") and first.source_version == "2301.00001v3"
    )
    assert first.linked == Identifiers(doi="10.1000/beta-journal")
    assert first.venue == "J. Synthetic Results 4 (2023)"
    assert second.source_version == "2302.00002v1" and second.linked is None
