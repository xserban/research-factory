"""Query purpose to provenance method, per adapter (slice 4a ruling 6). Offline."""

from __future__ import annotations

import json

import httpx

from factory.clock import FixedClock
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.work import ProvenanceMethod
from factory.sources.arxiv import ArxivSource
from factory.sources.base import RawPage
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from tests.helpers import SESSION, T0

RUN_ID = f"run_{SESSION}"
QUERY_ID = f"qry_{SESSION}"

ARXIV_ONE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2103.14030v2</id>
    <title>A supplied preprint</title>
  </entry>
</feed>
"""

OPENALEX_ONE = json.dumps(
    {
        "meta": {"count": 1, "next_cursor": None},
        "results": [
            {
                "id": "https://openalex.org/W3138516171",
                "doi": "https://doi.org/10.1109/iccv48922.2021.00986",
                "display_name": "A supplied paper",
                "type": "article",
                "publication_date": "2021-10-01",
                "authorships": [{"author": {"display_name": "Ada Zhou"}, "institutions": []}],
            }
        ],
    }
)


def _http(body: str) -> PoliteClient:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, text=body))
    return PoliteClient(httpx.Client(transport=transport), sleep=lambda _s: None)


def _archive(page_: RawPage) -> str:
    return f"sha256:{page_.ordinal + 1:064x}"


def test_arxiv_supplied_purpose_marks_supplied() -> None:
    source = ArxivSource(_http(ARXIV_ONE), clock=FixedClock(T0))
    spec = QuerySpec(
        source="arxiv", kind=QueryKind.ID_LIST, text="2103.14030", purpose=QueryPurpose.SUPPLIED
    )
    works = source.run(spec, run_id=RUN_ID, query_id=QUERY_ID, archive=_archive).works
    assert [p.method for w in works for p in w.provenance] == [ProvenanceMethod.SUPPLIED]


def test_openalex_supplied_purpose_marks_supplied() -> None:
    source = OpenAlexSource(_http(OPENALEX_ONE), clock=FixedClock(T0))
    spec = QuerySpec(
        source="openalex",
        kind=QueryKind.FILTER,
        text="doi:10.1109/iccv48922.2021.00986",
        purpose=QueryPurpose.SUPPLIED,
    )
    works = source.run(spec, run_id=RUN_ID, query_id=QUERY_ID, archive=_archive).works
    assert [p.method for w in works for p in w.provenance] == [ProvenanceMethod.SUPPLIED]


def test_supplied_values() -> None:
    assert ProvenanceMethod.SUPPLIED.value == "supplied"
    assert QueryPurpose.SUPPLIED.value == "supplied"
