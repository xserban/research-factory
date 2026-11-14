"""PMC JATS route, offline: a fake of the ID converter and the open bucket."""

from __future__ import annotations

import json

import httpx

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Identifiers, Provenance, Work
from factory.sources.fulltext.pmc import PmcJatsRoute
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


def listing(*versions: int, num: str = "123") -> bytes:
    prefixes = "".join(
        f"<CommonPrefixes><Prefix>PMC{num}.{v}/</Prefix></CommonPrefixes>" for v in versions
    )
    return f"<ListBucketResult>{prefixes}</ListBucketResult>".encode()


def info(**fields: object) -> bytes:
    base: dict[str, object] = {"is_pmc_openaccess": True, "license_code": "CC BY"}
    return json.dumps(base | fields).encode()


def route(
    *,
    versions: tuple[int, ...] = (1,),
    meta: bytes | None = None,
    xml: bytes = XML,
    converter: dict[str, object] | None = None,
    fail: bool = False,
    mailto: str | None = None,
) -> tuple[PmcJatsRoute, list[httpx.Request]]:
    log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if fail:
            raise httpx.ConnectError("down")
        if request.url.host == "pmc.ncbi.nlm.nih.gov":
            return httpx.Response(200, json=converter or {"status": "ok", "records": []})
        if request.url.params.get("list-type"):
            return httpx.Response(200, content=listing(*versions))
        if request.url.path.endswith(".json"):
            return httpx.Response(200, content=meta if meta is not None else info())
        return httpx.Response(200, content=xml)

    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )
    return PmcJatsRoute(client, mailto), log


def test_pmcid_present_skips_the_converter() -> None:
    r, log = route()
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.RETRIEVED
    assert all(q.url.host != "pmc.ncbi.nlm.nih.gov" for q in log)


def test_success_carries_licence_version_and_metadata() -> None:
    r, _ = route()
    result = r.fetch(work(pmcid="PMC123"))
    assert result.route is Route.PMC_JATS
    assert result.content == XML
    assert result.media_type == "application/jats+xml"
    assert result.url == "https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/PMC123.1.xml"
    assert result.licence == "CC BY"
    assert result.source_version == "PMC123.1"
    assert result.metadata == info()


def test_pmcid_converted_from_pmid() -> None:
    r, log = route(converter={"status": "ok", "records": [{"pmid": "9", "pmcid": "PMC123"}]})
    result = r.fetch(work(pmid="9"))
    assert result.outcome is AttemptOutcome.RETRIEVED
    assert log[0].url.params["idtype"] == "pmid"
    assert "email" not in log[0].url.params


def test_converter_sends_tool_and_email_when_configured() -> None:
    r, log = route(converter={"records": [{"pmcid": "PMC123"}]}, mailto="a@example.org")
    r.fetch(work(doi="10.1/x"))
    assert log[0].url.params["idtype"] == "doi"
    assert log[0].url.params["email"] == "a@example.org"
    assert log[0].url.params["tool"]


def test_no_pmcid_anywhere() -> None:
    r, _ = route(converter={"status": "ok", "records": [{"pmid": "9"}]})
    result = r.fetch(work(pmid="9"))
    assert result.outcome is AttemptOutcome.NOT_AVAILABLE
    assert result.reason == "no-pmcid"


def test_work_without_identifiers_is_no_pmcid() -> None:
    r, log = route()
    assert r.fetch(work(url="https://x.example/a")).reason == "no-pmcid"
    assert log == []


def test_highest_version_is_taken() -> None:
    r, _ = route(versions=(1, 3, 2, 10))
    assert r.fetch(work(pmcid="PMC123")).source_version == "PMC123.10"


def test_empty_listing_is_no_version() -> None:
    r, _ = route(versions=())
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.NOT_AVAILABLE
    assert result.reason == "no-version"


def test_explicit_version_skips_listing_and_converter() -> None:
    r, log = route(versions=(1, 5))
    result = r.fetch(work(pmid="9"), version="PMC123.2")
    assert result.source_version == "PMC123.2"
    assert all(q.url.host == "pmc-oa-opendata.s3.amazonaws.com" for q in log)
    assert not any(q.url.params.get("list-type") for q in log)


def test_not_open_access_and_not_tdm() -> None:
    r, _ = route(meta=info(is_pmc_openaccess=False, license_code="CC BY"))
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.NOT_AVAILABLE
    assert result.reason == "not-open-access"
    assert result.content is None
    assert result.licence == "CC BY"


def test_tdm_manuscript_is_fetched() -> None:
    r, _ = route(meta=info(is_pmc_openaccess=False, is_manuscript=True, license_code="TDM"))
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.RETRIEVED
    assert result.licence == "TDM"


def test_retracted_is_fetched() -> None:
    r, _ = route(meta=info(is_retracted=True))
    assert r.fetch(work(pmcid="PMC123")).outcome is AttemptOutcome.RETRIEVED


def test_xml_without_body() -> None:
    r, _ = route(xml=XML_NO_BODY)
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.NOT_AVAILABLE
    assert result.reason == "no-body"
    assert result.metadata == info()


def test_transport_failure() -> None:
    r, _ = route(fail=True)
    result = r.fetch(work(pmcid="PMC123"))
    assert result.outcome is AttemptOutcome.FAILED
    assert result.reason == "transport"
