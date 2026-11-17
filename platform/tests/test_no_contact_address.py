"""The configured contact address is never sent to an outside host (researcher ruling 2026-11-17).

Every outbound path built from the registries is driven against a recording mock transport with a
distinctive `settings.mailto`; the address, its domain and the word "mailto" must appear in no
request URL, query string or header.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.model.search import QueryPurpose, QuerySpec
from factory.model.work import Identifiers, Provenance, Work
from factory.sources import http as http_module
from factory.sources.fulltext.registry import default_routes
from factory.sources.registry import status_sources
from tests.helpers import SESSION, T0

ADDRESS = "zq-distinct-contact@zq-distinct-domain.example"
FORBIDDEN = ("zq-distinct-contact", "zq-distinct-domain", "mailto", "email=", "tool=")
FIXTURES = Path(__file__).parent / "fixtures" / "fulltext"
OA_WORK = (FIXTURES / "openalex_work.json").read_bytes()
ARXIV_META = (FIXTURES / "arxiv_meta.xml").read_bytes()
LTX = (FIXTURES / "ltx.html").read_bytes()
ARTICLE = b"<article><body><p>x</p></body></article>"
LISTING = (
    b"<ListBucketResult><CommonPrefixes><Prefix>PMC123456.1/</Prefix></CommonPrefixes>"
    b"</ListBucketResult>"
)
PMC_META = b'{"is_pmc_openaccess": true, "license_code": "CC BY"}'
EPMC_HIT = (
    b'{"resultList": {"result": [{"pmcid": "PMC123456", "pmid": "123", '
    b'"doi": "10.1000/xyz", "isOpenAccess": "Y", "license": "cc by"}]}}'
)
PDF = b"%PDF-1.4\n% synthetic stand-in\n%%EOF\n"


def _work(*, pmcid: str | None = "PMC123456") -> Work:
    """A work carrying every identifier, so no full-text route stops before its requests."""
    return Work.build(
        title="A synthetic stand-in paper",
        identifiers=Identifiers(doi="10.1000/xyz", pmid="123", arxiv="2301.01234", pmcid=pmcid),
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


def _sink(page: Any) -> str:
    return f"sha256:{page.ordinal + 1:064x}"


def _drive(source: Any, spec: QuerySpec) -> None:
    """Run, count, sample and probe `spec`; failures are fine, only the requests matter."""
    with contextlib.suppress(Exception):
        source.run(spec, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_sink)
    for probe in ("count", "sample", "count_on_arxiv"):
        method = getattr(source, probe, None)
        if method is not None:
            args = (spec, 5) if probe == "sample" else (spec,)
            with contextlib.suppress(Exception):
                method(*args, archive=_sink)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        host, path = request.url.host, request.url.path
        if host == "api.openalex.org" and path.startswith("/works/doi:"):
            return httpx.Response(200, content=OA_WORK)  # best_oa_location -> example.org PDF
        if host == "export.arxiv.org":
            return httpx.Response(200, content=ARXIV_META)
        if host == "arxiv.org" and path.startswith("/html/"):
            return httpx.Response(200, content=LTX)
        if host == "pmc-oa-opendata.s3.amazonaws.com":
            if request.url.params.get("list-type"):
                return httpx.Response(200, content=LISTING)
            return httpx.Response(200, content=PMC_META if path.endswith(".json") else ARTICLE)
        if host == "pmc.ncbi.nlm.nih.gov":
            return httpx.Response(200, json={"records": [{"pmcid": "PMC123456"}]})
        if host == "www.ebi.ac.uk":
            return httpx.Response(200, content=ARTICLE if "fullTextXML" in path else EPMC_HIT)
        if host == "example.org":
            return httpx.Response(200, content=PDF, headers={"Content-Type": "application/pdf"})
        return httpx.Response(200, text="{}")

    real = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        kwargs.pop("event_hooks", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(http_module.httpx, "Client", client)
    monkeypatch.setattr(http_module.time, "sleep", lambda _s: None)
    return log


def test_no_outbound_path_carries_the_contact_address(
    seen: list[httpx.Request], tmp_path: Path
) -> None:
    settings = Settings(root=tmp_path, user="obd", mailto=ADDRESS)
    clock = FixedClock(T0)

    for name, factory in status_sources().items():
        source = factory(settings, clock)
        for kind in sorted(source.kinds, key=lambda k: k.value):
            purpose = QueryPurpose.STATUS if name == "crossref" else QueryPurpose.SEARCH
            texts = ["asthma", "doi:10.1000/xyz", "title.search:asthma", "10.1000/xyz", "123"]
            for text in texts:
                _drive(source, QuerySpec(source=name, kind=kind, text=text, purpose=purpose))

    # With a PMCID the PMC route goes straight to the bucket; without one it asks the ID converter.
    for work in (_work(), _work(pmcid=None)):
        for route in default_routes(settings).values():
            with contextlib.suppress(Exception):
                route.fetch(work)

    hosts = {r.url.host for r in seen}
    assert {
        "api.openalex.org",
        "eutils.ncbi.nlm.nih.gov",
        "api.crossref.org",
        "pmc.ncbi.nlm.nih.gov",
        "pmc-oa-opendata.s3.amazonaws.com",
        "www.ebi.ac.uk",
        "export.arxiv.org",
        "arxiv.org",
        "example.org",
    } <= hosts
    # Each full-text route reached its deepest request (the article, not just a lookup).
    paths = {(r.url.host, r.url.path) for r in seen}
    assert any(h == "pmc-oa-opendata.s3.amazonaws.com" and p.endswith(".xml") for h, p in paths)
    assert any(h == "www.ebi.ac.uk" and p.endswith("/fullTextXML") for h, p in paths)
    assert any(h == "arxiv.org" and p.startswith("/html/") for h, p in paths)
    assert any(h == "arxiv.org" and p.startswith("/e-print/") for h, p in paths)
    assert ("example.org", "/articles/001/paper.pdf") in paths
    for request in seen:
        blob = " ".join([str(request.url), *(f"{k}: {v}" for k, v in request.headers.items())])
        for needle in FORBIDDEN:
            assert needle not in blob.lower(), (needle, str(request.url))
        assert request.headers["User-Agent"] == http_module.GENERIC_CLIENT


def test_cli_clients_use_the_generic_identity(seen: list[httpx.Request], tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, user="obd", mailto=ADDRESS)
    client = http_module.default_http(settings)
    with contextlib.suppress(Exception):
        client.get("https://export.arxiv.org/api/query", {"search_query": "all:x"})
    assert seen
    assert all(r.headers["User-Agent"] == "research-factory" for r in seen)
    assert ADDRESS not in str(seen[0].headers)


def _assert_clean(requests: list[httpx.Request], *, user_agent: str | None) -> None:
    assert requests
    for request in requests:
        blob = " ".join([str(request.url), *(f"{k}: {v}" for k, v in request.headers.items())])
        for needle in FORBIDDEN:
            assert needle not in blob.lower(), (needle, str(request.url))
        if user_agent is not None:
            assert request.headers["User-Agent"] == user_agent


def test_generic_http_and_fetch_page_use_the_generic_identity(
    seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACTORY_MAILTO", ADDRESS)
    http_module.generic_http().get("https://www.ebi.ac.uk/europepmc/webservices/rest/search")
    http_module.fetch_page("https://example.org/page")
    assert len(seen) == 2
    _assert_clean(seen, user_agent=http_module.GENERIC_CLIENT)


def test_feed_cli_client_never_carries_the_address(
    seen: list[httpx.Request], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`factory feed run` builds its arXiv source from the settings; drive that source."""
    from typer.testing import CliRunner

    from factory.cli.main import app
    from factory.services import feed as feed_service

    def fake_run_all(*_a: Any, source: Any, **_kw: Any) -> Any:
        source._http.get("https://export.arxiv.org/api/query", {"search_query": "all:x"})
        raise SystemExit(0)

    monkeypatch.setattr(feed_service, "feed_run_all", fake_run_all)
    env = {"FACTORY_ROOT": str(tmp_path), "FACTORY_USER": "obd", "FACTORY_MAILTO": ADDRESS}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    CliRunner().invoke(app, ["feed", "run", "--all", "--dry-run"])
    _assert_clean(seen, user_agent=http_module.GENERIC_CLIENT)


def test_site_cli_feed_runner_never_carries_the_address(
    seen: list[httpx.Request], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`factory site` builds the hub's feed runner from the settings; drive its arXiv source."""
    from types import SimpleNamespace

    from factory.cli import site as site_cli
    from factory.services import feed as feed_service

    def fake_run_all(*_a: Any, source: Any, **_kw: Any) -> Any:
        source._http.get("https://export.arxiv.org/api/query", {"search_query": "all:x"})
        return None

    monkeypatch.setattr(feed_service, "feed_run_all", fake_run_all)
    state = SimpleNamespace(
        settings=Settings(root=tmp_path, user="obd", mailto=ADDRESS),
        clock=FixedClock(T0),
        session=SESSION,
    )
    runner = site_cli._feed_runner(state)
    runner._run(False)
    _assert_clean(seen, user_agent=http_module.GENERIC_CLIENT)


def test_library_push_client_never_carries_the_address(
    seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The push client sets no User-Agent of its own (httpx default) and has no access to the
    settings' address; its requests must not contain it."""
    from factory.services import library_push

    monkeypatch.setenv("FACTORY_MAILTO", ADDRESS)
    client = library_push.push_client()
    client.head("https://hub.example.org/library/sha256/" + "0" * 64)
    _assert_clean(seen, user_agent=None)
    assert ADDRESS not in seen[0].headers["User-Agent"]
