"""arXiv HTML route and version lookup, offline.

Responses are the synthetic fixtures under `fixtures/fulltext/`, served through a mock transport.
The route never records events and never raises for an HTTP or content problem.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Identifiers, Provenance, Work
from factory.sources.fulltext.arxiv import ArxivHtmlRoute, latest_arxiv_version
from factory.sources.fulltext.base import FullTextRoute, RouteResult
from factory.sources.http import PoliteClient
from tests.helpers import SESSION, T0

FIXTURES = Path(__file__).parent / "fixtures" / "fulltext"
META = (FIXTURES / "arxiv_meta.xml").read_bytes()
LTX = (FIXTURES / "ltx.html").read_bytes()
LTX_ERROR = (FIXTURES / "ltx_error.html").read_bytes()

Handler = Callable[[httpx.Request], httpx.Response]


def work_with_arxiv(arxiv: str | None) -> Work:
    return Work.build(
        title="A synthetic stand-in paper",
        identifiers=Identifiers(arxiv=arxiv),
        provenance=[
            Provenance(
                source="arxiv",
                run_id=f"run_{SESSION}",
                query_id=f"qry_{SESSION}",
                at=T0,
                raw_blob="sha256:" + "0" * 64,
            )
        ],
    )


def polite(handler: Handler) -> PoliteClient:
    transport = httpx.MockTransport(handler)
    return PoliteClient(httpx.Client(transport=transport), sleep=lambda _seconds: None)


def scripted(
    *, meta: httpx.Response | None = None, html: httpx.Response | None = None
) -> tuple[PoliteClient, list[httpx.Request]]:
    """A client whose lookup answers `meta` and whose HTML GET answers `html`, logging requests."""
    log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if request.url.host == "export.arxiv.org":
            return meta or httpx.Response(200, content=META)
        return html or httpx.Response(200, content=LTX)

    return polite(handler), log


@pytest.fixture
def http_with_fixtures() -> PoliteClient:
    client, _ = scripted()
    return client


def test_route_satisfies_the_protocol() -> None:
    route: FullTextRoute = ArxivHtmlRoute(polite(lambda _r: httpx.Response(200)))
    assert route.route is Route.ARXIV_HTML


def test_latest_version_is_read_from_the_api_entry() -> None:
    client, _ = scripted()
    version, body = latest_arxiv_version(client, "2301.01234")
    assert version == "2301.01234v3"
    assert body == META


def test_html_route_fetches_latest_version(http_with_fixtures: PoliteClient) -> None:
    r = ArxivHtmlRoute(http_with_fixtures).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert r.source_version == "2301.01234v3"
    assert r.url == "https://arxiv.org/html/2301.01234v3"
    assert r.http_status == 200
    assert r.media_type == "text/html"
    assert r.content == LTX
    assert r.licence is None
    assert r.metadata == META
    assert r.reason is None


def test_html_404_falls_through() -> None:
    client, _ = scripted(html=httpx.Response(404, content=b"not found"))
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "no-html-rendering"
    assert r.http_status == 404
    assert r.content is None


def test_html_without_ltx_document_is_not_available() -> None:
    client, _ = scripted(html=httpx.Response(200, content=LTX_ERROR))
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "no-html-rendering"
    assert r.http_status == 200
    assert r.content is None


def test_work_without_arxiv_id_is_not_available() -> None:
    client, log = scripted()
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv(None))
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "no-arxiv-id"
    assert r.url is None
    assert log == []


def test_pinned_version_skips_lookup() -> None:
    client, log = scripted(html=httpx.Response(200, content=LTX))
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"), version="2301.01234v2")
    assert [request.url.host for request in log] == ["arxiv.org"]
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert r.source_version == "2301.01234v2"
    assert r.url == "https://arxiv.org/html/2301.01234v2"
    assert r.metadata is None


def test_pinned_version_of_another_paper_is_unknown() -> None:
    client, log = scripted()
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"), version="2302.00001v1")
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "arxiv-version-unknown"
    assert log == []


def test_lookup_without_entry_is_version_unknown() -> None:
    empty = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    client, log = scripted(meta=httpx.Response(200, content=empty))
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "arxiv-version-unknown"
    assert [request.url.host for request in log] == ["export.arxiv.org"]


def test_lookup_server_error_is_failed_with_status() -> None:
    client, log = scripted(meta=httpx.Response(400, content=b"bad request"))
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.FAILED
    assert r.reason == "http-400"
    assert r.http_status == 400
    assert len(log) == 1


def test_html_server_error_is_failed_with_status() -> None:
    client, _ = scripted(html=httpx.Response(403, content=b"forbidden"))
    r = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.FAILED
    assert r.reason == "http-403"
    assert r.http_status == 403


def test_transport_error_is_failed_not_raised() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    r = ArxivHtmlRoute(polite(down)).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.FAILED
    assert r.reason == "transport"
    assert r.http_status is None


def test_result_urls_carry_no_mailto() -> None:
    client, _ = scripted()
    r: RouteResult = ArxivHtmlRoute(client).fetch(work_with_arxiv("2301.01234"))
    assert r.url is not None
    assert "mailto" not in r.url
