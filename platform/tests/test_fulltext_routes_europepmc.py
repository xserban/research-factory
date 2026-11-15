"""Europe PMC JATS route, offline: a fake of the Europe PMC search and full-text endpoints."""

from __future__ import annotations

import httpx

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Identifiers, Provenance, Work
from factory.sources.fulltext.europepmc import EuropePmcJatsRoute
from factory.sources.http import PoliteClient
from tests.helpers import SESSION, T0

XML = b"<article><front/><body><p>text</p></body></article>"
XML_NO_BODY = b"<article><front/></article>"


def work(**ids: str) -> Work:
    return Work.build(
        title="A synthetic stand-in paper",
        identifiers=Identifiers(**ids),
        provenance=[
            Provenance(
                source="pubmed",
                run_id=f"run_{SESSION}",
                query_id=f"qry_{SESSION}",
                at=T0,
                raw_blob="sha256:" + "0" * 64,
            )
        ],
    )


def hit(**fields: object) -> dict[str, object]:
    row: dict[str, object] = {"pmcid": "PMC123", "isOpenAccess": "Y", "license": "cc by"}
    return {"hitCount": 1, "resultList": {"result": [row | fields]}}


def route(
    *,
    search: dict[str, object] | None = None,
    xml: bytes = XML,
    xml_status: int = 200,
    search_status: int = 200,
    fail: bool = False,
) -> tuple[EuropePmcJatsRoute, list[httpx.Request]]:
    log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if fail:
            raise httpx.ConnectError("down")
        if request.url.path.endswith("/search"):
            return httpx.Response(search_status, json=search if search is not None else hit())
        return httpx.Response(xml_status, content=xml)

    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )
    return EuropePmcJatsRoute(client), log


def test_success_carries_licence_version_and_metadata() -> None:
    r, log = route()
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.RETRIEVED
    assert result.route is Route.EUROPEPMC_JATS
    assert result.content == XML
    assert result.media_type == "application/jats+xml"
    assert result.url == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML"
    assert result.licence == "cc by"
    assert result.source_version == "EPMC:PMC123"
    assert result.metadata is not None and b"isOpenAccess" in result.metadata
    assert log[0].url.params["query"] == "PMCID:PMC123"


def test_no_contact_address_or_key_is_sent() -> None:
    r, log = route()
    r.fetch(work(pmcid="PMC123"))
    for request in log:
        assert "email" not in request.url.params and "api_key" not in request.url.params


def test_pmid_query_when_no_pmcid() -> None:
    r, log = route()
    result = r.fetch(work(pmid="9"))
    assert result.outcome is AttemptOutcome.RETRIEVED
    assert log[0].url.params["query"] == "EXT_ID:9 AND SRC:MED"


def test_doi_query_when_nothing_else() -> None:
    r, log = route()
    r.fetch(work(doi="10.1/x"))
    assert log[0].url.params["query"] == 'DOI:"10.1/x"'


def test_no_identifier() -> None:
    r, log = route()
    result = r.fetch(work(arxiv="2401.00001"))
    assert result.reason == "no-identifier"
    assert result.outcome is AttemptOutcome.NOT_AVAILABLE
    assert log == []


def test_not_in_europepmc_when_no_pmcid_in_reply() -> None:
    r, _ = route(search={"hitCount": 1, "resultList": {"result": [{"pmid": "9"}]}})
    result = r.fetch(work(pmid="9"))
    assert result.reason == "not-in-europepmc"
    assert result.metadata is not None


def test_empty_or_malformed_reply_is_not_in_europepmc() -> None:
    r, _ = route(search={"hitCount": 0, "resultList": {"result": []}})
    assert r.fetch(work(pmid="9")).reason == "not-in-europepmc"
    r2, _ = route(search={"resultList": "x"})
    assert r2.fetch(work(pmid="9")).reason == "not-in-europepmc"


def test_not_open_access_keeps_licence_and_fetches_no_xml() -> None:
    r, log = route(search=hit(isOpenAccess="N", license=None))
    result = r.fetch(work(pmcid="PMC123"))
    assert result.reason == "not-open-access"
    assert result.outcome is AttemptOutcome.NOT_AVAILABLE
    assert result.content is None
    assert len(log) == 1


def test_licence_recorded_when_refused() -> None:
    r, _ = route(search=hit(isOpenAccess="N", license="TDM"))
    assert r.fetch(work(pmcid="PMC123")).licence == "TDM"


def test_missing_licence_is_none() -> None:
    r, _ = route(search=hit(license="  "))
    assert r.fetch(work(pmcid="PMC123")).licence is None


def test_fulltext_404_is_not_available() -> None:
    r, _ = route(xml_status=404)
    result = r.fetch(work(pmcid="PMC123"))
    assert result.reason == "http-404"
    assert result.outcome is AttemptOutcome.NOT_AVAILABLE
    assert result.metadata is not None


def test_fulltext_500_fails() -> None:
    r, _ = route(xml_status=503)
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.FAILED
    assert result.reason == "http-503"


def test_search_error_fails() -> None:
    r, _ = route(search_status=400)
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.FAILED
    assert result.reason == "http-400"


def test_transport_failure() -> None:
    r, _ = route(fail=True)
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.FAILED
    assert result.reason == "transport"


def test_no_body() -> None:
    r, _ = route(xml=XML_NO_BODY)
    assert r.fetch(work(pmcid="PMC123")).reason == "no-body"


def test_unparseable_xml_is_no_body() -> None:
    r, _ = route(xml=b"not xml")
    assert r.fetch(work(pmcid="PMC123")).reason == "no-body"


def test_pinned_version_restores_the_same_article() -> None:
    r, log = route()
    result = r.fetch(work(pmid="9"), version="EPMC:PMC123")
    assert result.source_version == "EPMC:PMC123"
    assert log[0].url.params["query"] == "PMCID:PMC123"


def test_foreign_version_is_refused() -> None:
    r, log = route()
    result = r.fetch(work(pmcid="PMC123"), version="PMC123.1")
    assert result.reason == "no-version"
    assert log == []
