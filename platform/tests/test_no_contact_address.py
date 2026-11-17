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
FORBIDDEN = ("zq-distinct-contact", "zq-distinct-domain", "mailto", "email=")


def _work() -> Work:
    return Work.build(
        title="A synthetic stand-in paper",
        identifiers=Identifiers(doi="10.1000/xyz", pmid="123", arxiv="2101.00001"),
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

    for route in default_routes(settings).values():
        with contextlib.suppress(Exception):
            route.fetch(_work())

    hosts = {r.url.host for r in seen}
    assert {"api.openalex.org", "eutils.ncbi.nlm.nih.gov", "api.crossref.org"} <= hosts
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
