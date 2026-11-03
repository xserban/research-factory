"""Open-access PDF route and the route registry, offline.

Responses are the synthetic fixtures under `fixtures/fulltext/`, served through a mock transport.
The route never records events and never raises for an HTTP or content problem.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from factory.config import Settings
from factory.model.fulltext import ROUTE_ORDER, AttemptOutcome, Route
from factory.model.work import Identifiers, Provenance, Work
from factory.sources.fulltext import registry
from factory.sources.fulltext.base import FullTextRoute, RouteResult
from factory.sources.fulltext.oa_pdf import OaPdfRoute
from factory.sources.fulltext.registry import default_routes
from factory.sources.http import PoliteClient
from tests.helpers import SESSION, T0

FIXTURES = Path(__file__).parent / "fixtures" / "fulltext"
OA_WORK = (FIXTURES / "openalex_work.json").read_bytes()
ARXIV_META = (FIXTURES / "arxiv_meta.xml").read_bytes()
LTX = (FIXTURES / "ltx.html").read_bytes()
PDF = b"%PDF-1.4\n% synthetic stand-in\n%%EOF\n"
DOI = "10.1000/synthetic.2024.001"
PDF_URL = "https://example.org/articles/001/paper.pdf"
MAILTO = "ops@example.org"

Handler = Callable[[httpx.Request], httpx.Response]


def work_with(doi: str | None = None, arxiv: str | None = None) -> Work:
    return Work.build(
        title="A synthetic stand-in paper",
        identifiers=Identifiers(doi=doi, arxiv=arxiv),
        provenance=[
            Provenance(
                source="openalex",
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


def openalex(body: bytes | None = None) -> Callable[[httpx.Request], httpx.Response]:
    """A lookup answer for the synthetic work, by default the fixture."""

    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body or OA_WORK)

    return answer


def scripted(
    *,
    lookup: httpx.Response | None = None,
    pdf: httpx.Response | None = None,
) -> tuple[PoliteClient, list[httpx.Request]]:
    """A client whose OpenAlex lookup answers `lookup` and whose PDF GET answers `pdf`."""
    log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if request.url.host == "api.openalex.org":
            return lookup or httpx.Response(200, content=OA_WORK)
        return pdf or httpx.Response(200, content=PDF, headers={"Content-Type": "application/pdf"})

    return polite(handler), log


def pdf_requests(log: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in log if request.url.host != "api.openalex.org"]


def test_route_satisfies_the_protocol() -> None:
    route: FullTextRoute = OaPdfRoute(polite(lambda _r: httpx.Response(200)), MAILTO)
    assert route.route is Route.OA_PDF


def test_oa_pdf_retrieved_with_licence_and_version() -> None:
    client, log = scripted()
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert r.route is Route.OA_PDF
    assert r.url == PDF_URL
    assert r.http_status == 200
    assert r.content == PDF
    assert r.media_type == "application/pdf"
    assert r.source_version == f"{DOI}#publishedVersion"
    assert r.licence == "cc-by"
    assert r.reason is None
    assert r.metadata is not None
    assert json.loads(r.metadata)["best_oa_location"]["pdf_url"] == PDF_URL
    assert [request.url.host for request in log] == ["api.openalex.org", "example.org"]
    assert log[0].url.path == f"/works/doi:{DOI}"


def test_oa_landing_page_is_not_a_pdf() -> None:
    client, _ = scripted(pdf=httpx.Response(200, content=b"<html>landing page</html>"))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "not-a-pdf"
    assert r.http_status == 200
    assert r.content is None
    assert r.media_type is None


def test_no_best_oa_location() -> None:
    body = json.dumps({"id": "https://openalex.org/W1", "best_oa_location": None}).encode()
    client, log = scripted(lookup=httpx.Response(200, content=body))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "no-oa-pdf"
    assert r.url is None
    assert pdf_requests(log) == []


def test_best_oa_location_without_pdf_url() -> None:
    body = json.dumps({"best_oa_location": {"landing_page_url": "https://example.org/a"}})
    client, log = scripted(lookup=httpx.Response(200, content=body.encode()))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.reason == "no-oa-pdf"
    assert pdf_requests(log) == []


def test_arxiv_only_work_uses_datacite_doi() -> None:
    client, log = scripted()
    r = OaPdfRoute(client, MAILTO).fetch(work_with(arxiv="arXiv:2301.01234v2"))
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert log[0].url.path == "/works/doi:10.48550/arxiv.2301.01234"
    assert r.source_version == "10.48550/arxiv.2301.01234#publishedVersion"


def test_work_without_identifiers_is_not_available() -> None:
    client, log = scripted()
    r = OaPdfRoute(client, MAILTO).fetch(work_with())
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "no-identifier"
    assert log == []


def test_work_not_in_openalex_is_not_available() -> None:
    client, _ = scripted(lookup=httpx.Response(404, content=b'{"error": "Not found"}'))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "not-in-openalex"
    assert r.http_status == 404


def test_lookup_server_error_is_failed_with_status() -> None:
    client, _ = scripted(lookup=httpx.Response(403, content=b"forbidden"))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.FAILED
    assert r.reason == "http-403"
    assert r.http_status == 403


def test_lookup_transport_error_is_failed_not_raised() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    r = OaPdfRoute(polite(down), MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.FAILED
    assert r.reason == "transport"


def test_pdf_server_error_is_failed_with_status() -> None:
    client, _ = scripted(pdf=httpx.Response(404, content=b"gone"))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.FAILED
    assert r.reason == "http-404"
    assert r.url == PDF_URL
    assert r.http_status == 404


def test_pdf_transport_error_is_failed_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, content=OA_WORK)
        raise httpx.ReadError("reset", request=request)

    r = OaPdfRoute(polite(handler), MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.FAILED
    assert r.reason == "transport"
    assert r.url == PDF_URL


def test_null_licence_is_not_reported() -> None:
    body = json.loads(OA_WORK)
    body["best_oa_location"]["license"] = None
    client, _ = scripted(lookup=httpx.Response(200, content=json.dumps(body).encode()))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert r.licence is None


def test_blank_version_falls_back_to_unknown() -> None:
    body = json.loads(OA_WORK)
    body["best_oa_location"]["version"] = None
    client, _ = scripted(lookup=httpx.Response(200, content=json.dumps(body).encode()))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.source_version == f"{DOI}#unknown"


def test_pinned_version_must_match_the_lookup() -> None:
    client, log = scripted()
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI), version=f"{DOI}#preprint")
    assert r.outcome is AttemptOutcome.NOT_AVAILABLE
    assert r.reason == "oa-version-unknown"
    assert pdf_requests(log) == []


def test_pinned_version_that_matches_is_retrieved() -> None:
    client, _ = scripted()
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI), version=f"{DOI}#publishedVersion")
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert r.source_version == f"{DOI}#publishedVersion"


def test_mailto_is_sent_to_openalex_only() -> None:
    client, log = scripted()
    OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert log[0].url.params.get("mailto") == MAILTO
    assert all("mailto" not in str(request.url) for request in pdf_requests(log))


def test_mailto_never_in_url_or_metadata() -> None:
    body = json.loads(OA_WORK)
    body["note"] = f"queried as {MAILTO} and ops%40example.org"
    body["echo"] = f"https://api.openalex.org/works?mailto={MAILTO}&x=1"
    client, _ = scripted(lookup=httpx.Response(200, content=json.dumps(body).encode()))
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.metadata is not None
    secrets = (MAILTO, "ops%40example.org")
    for field in (r.url, r.reason, r.source_version, r.licence, r.media_type):
        assert all(secret not in (field or "") for secret in secrets)
    assert all(secret.encode() not in r.metadata for secret in secrets)
    assert b"<mailto>" in r.metadata


def test_mailto_never_in_failure_metadata() -> None:
    client, _ = scripted(
        lookup=httpx.Response(404, content=f"no work for {MAILTO}".encode()),
    )
    r = OaPdfRoute(client, MAILTO).fetch(work_with(doi=DOI))
    assert r.metadata is not None
    assert MAILTO.encode() not in r.metadata


def test_no_mailto_sends_no_parameter() -> None:
    client, log = scripted()
    r = OaPdfRoute(client, None).fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert "mailto" not in str(log[0].url)


# Registry ----------------------------------------------------------------------------------


def _arxiv_handler(log: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, content=ARXIV_META)
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, content=OA_WORK)
        return httpx.Response(200, content=LTX)

    return handler


def _lookups(log: list[httpx.Request]) -> int:
    return sum(1 for request in log if request.url.host == "export.arxiv.org")


def test_default_routes_cover_the_automatic_routes_in_order(tmp_path: Path) -> None:
    routes = default_routes(Settings(root=tmp_path, user="obd", mailto=MAILTO))
    assert tuple(routes) == ROUTE_ORDER
    assert all(route.route is key for key, route in routes.items())
    assert Route.RESEARCHER not in routes


def test_default_routes_share_one_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    built: list[Settings] = []

    def counting(settings: Settings) -> PoliteClient:
        built.append(settings)
        return polite(_arxiv_handler([]))

    monkeypatch.setattr(registry, "default_http", counting)
    settings = Settings(root=tmp_path, user="obd", mailto=MAILTO)
    default_routes(settings)
    assert built == [settings]


def test_each_default_routes_call_has_its_own_lookup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log: list[httpx.Request] = []
    monkeypatch.setattr(registry, "default_http", lambda _s: polite(_arxiv_handler(log)))
    settings = Settings(root=tmp_path, user="obd", mailto=MAILTO)
    work = work_with(doi=DOI, arxiv="2301.01234")

    first: dict[Route, FullTextRoute] = default_routes(settings)
    first[Route.ARXIV_HTML].fetch(work)
    first[Route.ARXIV_SOURCE].fetch(work)
    assert _lookups(log) == 1

    second: dict[Route, FullTextRoute] = default_routes(settings)
    second[Route.ARXIV_HTML].fetch(work)
    assert _lookups(log) == 2


def test_registry_oa_route_carries_the_settings_mailto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log: list[httpx.Request] = []
    handler = _arxiv_handler(log)

    def serve_pdf(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.org":
            log.append(request)
            return httpx.Response(200, content=PDF)
        return handler(request)

    monkeypatch.setattr(registry, "default_http", lambda _s: polite(serve_pdf))
    routes = default_routes(Settings(root=tmp_path, user="obd", mailto=MAILTO))
    r: RouteResult = routes[Route.OA_PDF].fetch(work_with(doi=DOI))
    assert r.outcome is AttemptOutcome.RETRIEVED
    openalex_requests = [q for q in log if q.url.host == "api.openalex.org"]
    assert openalex_requests[0].url.params.get("mailto") == MAILTO
