"""PubMed adapter tests, offline.

Responses are small hand-made esearch JSON and efetch XML payloads served through a mock
transport; no test touches the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.clock import FixedClock
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod, WorkType
from factory.sources.base import (
    BUDGET_STOP_NOTE,
    BudgetedSink,
    RawPage,
    SearchResult,
    SourceError,
)
from factory.sources.http import HOST_INTERVALS, PoliteClient
from factory.sources.pubmed import PubmedSource, ncbi_api_key
from tests.helpers import SESSION, T0

RUN_ID = f"run_{SESSION}"
QUERY_ID = f"qry_{SESSION}"

Handler = Callable[[httpx.Request], httpx.Response]


def article(
    pmid: str,
    title: str | None = "A trial of <i>things</i>",
    *,
    extra: str = "",
    ids: str = "",
) -> str:
    title_xml = f"<ArticleTitle>{title}</ArticleTitle>" if title else ""
    return f"""
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">{pmid}</PMID>
    <Article>
      <Journal>
        <JournalIssue>
          <Volume>12</Volume><Issue>3</Issue>
          <PubDate><Year>2020</Year><Month>Mar</Month><Day>15</Day></PubDate>
        </JournalIssue>
        <Title>Journal of Tests</Title>
      </Journal>
      {title_xml}
      <Pagination><MedlinePgn>100-9</MedlinePgn></Pagination>
      <Abstract>
        <AbstractText Label="BACKGROUND">Why.</AbstractText>
        <AbstractText Label="METHODS">How.</AbstractText>
      </Abstract>
      <AuthorList>
        <Author>
          <LastName>Doe</LastName><ForeName>Jane</ForeName>
          <Identifier Source="ORCID">https://orcid.org/0000-0002-1825-0097</Identifier>
          <AffiliationInfo><Affiliation>Dept of Tests</Affiliation></AffiliationInfo>
        </Author>
        <Author><CollectiveName>The Test Group</CollectiveName></Author>
      </AuthorList>
      <Language>eng</Language>
      <PublicationTypeList>
        <PublicationType>Journal Article</PublicationType>{extra}
      </PublicationTypeList>
    </Article>
    <MeshHeadingList>
      <MeshHeading><DescriptorName>Humans</DescriptorName></MeshHeading>
    </MeshHeadingList>
    <KeywordList><Keyword>testing</Keyword></KeywordList>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">{pmid}</ArticleId>
      <ArticleId IdType="doi">10.1000/Test.{pmid}</ArticleId>
      <ArticleId IdType="pmc">PMC{pmid}</ArticleId>{ids}
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>"""


def efetch(*articles: str) -> str:
    return f'<?xml version="1.0"?><PubmedArticleSet>{"".join(articles)}</PubmedArticleSet>'


def esearch(count: int, webenv: str = "WEBENV_1", key: str = "1") -> str:
    return json.dumps(
        {"esearchresult": {"count": str(count), "webenv": webenv, "querykey": key, "idlist": []}}
    )


def blob_for(ordinal: int) -> str:
    return f"sha256:{ordinal + 1:064x}"


def _archive(page: RawPage) -> str:
    return blob_for(page.ordinal)


def keyword(text: str = "asthma[MeSH]", **fields: Any) -> QuerySpec:
    return QuerySpec(source="pubmed", kind=QueryKind.KEYWORD, text=text, **fields)


def id_list(text: str, **fields: Any) -> QuerySpec:
    return QuerySpec(source="pubmed", kind=QueryKind.ID_LIST, text=text, **fields)


def make_source(
    handler: Handler,
    *,
    mailto: str | None = None,
    api_key: str | None = None,
    batch_size: int = 200,
) -> PubmedSource:
    http = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None, retries=0
    )
    return PubmedSource(
        http, clock=FixedClock(T0), mailto=mailto, api_key=api_key, batch_size=batch_size
    )


def router(search_body: str, *fetch_bodies: str) -> tuple[Handler, list[httpx.Request]]:
    """esearch answers `search_body`; each efetch answers the next body (the last repeats)."""
    seen: list[httpx.Request] = []
    fetches = iter(fetch_bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, text=search_body)
        return httpx.Response(200, text=next(fetches, fetch_bodies[-1]))

    return handler, seen


def run(
    source: PubmedSource,
    spec: QuerySpec,
    *,
    resume_from: str | None = None,
    archive: Callable[[RawPage], str] = _archive,
) -> SearchResult:
    return source.run(
        spec, run_id=RUN_ID, query_id=QUERY_ID, archive=archive, resume_from=resume_from
    )


def test_interval_is_registered() -> None:
    assert HOST_INTERVALS["eutils.ncbi.nlm.nih.gov"] == 0.34


def test_class_attributes() -> None:
    assert PubmedSource.name == "pubmed"
    assert PubmedSource.kinds == {QueryKind.KEYWORD, QueryKind.ID_LIST}
    assert PubmedSource.window_filter is False


def test_keyword_two_phase_request_shape() -> None:
    handler, seen = router(esearch(2), efetch(article("1"), article("2")))
    result = run(make_source(handler), keyword())

    assert result.status is RunStatus.COMPLETE
    assert result.reported_count == 2
    assert result.retrieved_count == 2
    assert result.pages == 2
    assert result.note is None
    first, second = (r.url.params for r in seen)
    assert first["db"] == "pubmed"
    assert first["term"] == "asthma[MeSH]"
    assert first["usehistory"] == "y"
    assert first["retmode"] == "json"
    assert first["retmax"] == "0"
    assert second["WebEnv"] == "WEBENV_1"
    assert second["query_key"] == "1"
    assert second["retstart"] == "0"
    assert second["retmax"] == "200"
    assert second["retmode"] == "xml"
    assert "api_key" not in first
    assert "email" not in first
    assert "tool" not in first


def test_work_is_mapped_from_the_record() -> None:
    handler, _ = router(
        esearch(1), efetch(article("42", extra="<PublicationType>Review</PublicationType>"))
    )
    result = run(make_source(handler), keyword())
    (work,) = result.works

    assert work.title == "A trial of things"
    assert work.type is WorkType.JOURNAL_ARTICLE
    assert work.abstract == "BACKGROUND: Why.\n\nMETHODS: How."
    assert work.language == "eng"
    assert work.identifiers.pmid == "42"
    assert work.identifiers.doi is not None
    assert work.identifiers.doi.lower() == "10.1000/test.42"
    assert work.identifiers.pmcid == "PMC42"
    assert [a.name for a in work.authors] == ["Jane Doe", "The Test Group"]
    assert work.authors[0].orcid == "0000-0002-1825-0097"
    assert work.authors[0].affiliation == "Dept of Tests"
    assert work.venue is not None
    assert (work.venue.name, work.venue.volume, work.venue.issue, work.venue.pages) == (
        "Journal of Tests",
        "12",
        "3",
        "100-9",
    )
    assert work.dates.published is not None
    assert work.dates.published.isoformat() == "2020-03-15"
    assert work.dates.retrieved == T0
    assert work.subjects == ["Humans", "testing"]
    assert work.retracted is False
    (prov,) = work.provenance
    assert prov.source == "pubmed"
    assert prov.run_id == RUN_ID
    assert prov.query_id == QUERY_ID
    assert prov.raw_blob == blob_for(1)
    assert prov.raw_ref == "42"
    assert prov.method is ProvenanceMethod.DATABASE


def test_retraction_type_and_preprint_type() -> None:
    handler, _ = router(
        esearch(2),
        efetch(
            article("1", extra="<PublicationType>Retracted Publication</PublicationType>"),
            article("2", "Other", extra="<PublicationType>Preprint</PublicationType>"),
        ),
    )
    first, second = run(make_source(handler), keyword()).works
    assert first.retracted is True
    assert second.type is WorkType.PREPRINT


def test_medline_date_fallback() -> None:
    xml = article("1").replace(
        "<PubDate><Year>2020</Year><Month>Mar</Month><Day>15</Day></PubDate>",
        "<PubDate><MedlineDate>2019 Dec-2020 Jan</MedlineDate></PubDate>",
    )
    handler, _ = router(esearch(1), efetch(xml))
    (work,) = run(make_source(handler), keyword()).works
    assert work.dates.published is not None
    assert work.dates.published.year == 2019


def test_purpose_maps_to_method() -> None:
    handler, _ = router(esearch(1), efetch(article("1")))
    result = run(make_source(handler), keyword(purpose=QueryPurpose.SEED))
    assert result.works[0].provenance[0].method is ProvenanceMethod.SEED_ADMISSION


def test_untitled_and_duplicate_records_are_skipped_and_noted() -> None:
    handler, _ = router(
        esearch(3),
        efetch(article("1"), article("2", None), article("1")),
    )
    result = run(make_source(handler), keyword())
    # The third record repeats the first, so it is the same work id.
    assert result.retrieved_count == 1
    assert result.skipped == 2
    assert result.status is RunStatus.COMPLETE
    assert result.note == "2 records skipped (untitled or duplicate within run)"


def test_batches_page_through_the_history() -> None:
    handler, seen = router(
        esearch(3),
        efetch(article("1", "One"), article("2", "Two")),
        efetch(article("3", "Three")),
    )
    result = run(make_source(handler, batch_size=2), keyword())
    assert result.retrieved_count == 3
    assert result.pages == 3
    offsets = [r.url.params["retstart"] for r in seen[1:]]
    assert offsets == ["0", "2"]


def test_each_response_is_archived_before_it_is_parsed() -> None:
    handler, _ = router(esearch(1), "<broken")
    archived: list[RawPage] = []

    def archive(page: RawPage) -> str:
        archived.append(page)
        return blob_for(page.ordinal)

    with pytest.raises(SourceError, match="unparseable XML"):
        run(make_source(handler), keyword(), archive=archive)
    assert [p.ordinal for p in archived] == [0, 1]
    assert archived[1].body == "<broken"
    assert archived[1].fetched_at == T0


def test_unparseable_esearch_json_raises_after_archiving() -> None:
    handler, _ = router("not json")
    archived: list[RawPage] = []

    def archive(page: RawPage) -> str:
        archived.append(page)
        return blob_for(page.ordinal)

    with pytest.raises(SourceError, match="unparseable JSON"):
        run(make_source(handler), keyword(), archive=archive)
    assert len(archived) == 1


def test_cap_gives_partial_with_the_cap_note() -> None:
    handler, seen = router(esearch(25000), efetch(article("1")))
    result = run(make_source(handler, batch_size=5000), keyword())
    assert result.status is RunStatus.PARTIAL
    assert result.reported_count == 25000
    assert result.note == "esearch-cap: 25000 reported, 9999 retrievable; split the query by date"
    assert result.resume_token is None
    # 9999 records come in two batches of 5000: offsets 0 and 5000.
    assert [r.url.params["retstart"] for r in seen[1:]] == ["0", "5000"]


def test_zero_matches_is_complete_with_no_fetch() -> None:
    handler, seen = router(esearch(0, webenv="", key=""))
    result = run(make_source(handler), keyword())
    assert result.status is RunStatus.COMPLETE
    assert result.reported_count == 0
    assert len(seen) == 1


def test_resume_continues_from_the_offset_and_says_so() -> None:
    handler, seen = router(esearch(5), efetch(article("3", "Three")))
    result = run(make_source(handler, batch_size=2), keyword(), resume_from="4")
    assert [r.url.params["retstart"] for r in seen[1:]] == ["4"]
    assert result.status is RunStatus.COMPLETE
    assert result.note is not None
    assert "resumed at offset 4 after a new esearch; the result set may have changed" in result.note


def test_esearch_http_error_fails_with_token_zero() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = run(make_source(handler), keyword())
    assert result.status is RunStatus.FAILED
    assert result.resume_token == "0"
    assert result.note is not None
    assert result.note.startswith("esearch:")


def test_efetch_http_error_is_partial_with_the_offset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, text=esearch(4))
        if request.url.params["retstart"] == "0":
            return httpx.Response(200, text=efetch(article("1", "One"), article("2", "Two")))
        return httpx.Response(503, text="down")

    result = run(make_source(handler, batch_size=2), keyword())
    assert result.status is RunStatus.PARTIAL
    assert result.retrieved_count == 2
    assert result.resume_token == "2"
    assert result.note is not None
    assert result.note.startswith("efetch:")


def test_budget_stops_before_each_request_with_a_resume_token() -> None:
    handler, seen = router(esearch(4), efetch(article("1", "One"), article("2", "Two")))
    allowed = iter([False, False, True])  # esearch, first efetch, then spent

    sink = BudgetedSink(sink=_archive, spent=lambda: next(allowed, True))
    result = run(make_source(handler, batch_size=2), keyword(), archive=sink)
    assert len(seen) == 2
    assert result.status is RunStatus.PARTIAL
    assert result.note == BUDGET_STOP_NOTE
    assert result.resume_token == "2"
    assert result.retrieved_count == 2


def test_budget_spent_before_esearch_resumes_at_the_offset() -> None:
    handler, seen = router(esearch(4))
    sink = BudgetedSink(sink=_archive, spent=lambda: True)
    result = run(make_source(handler), keyword(), archive=sink, resume_from="200")
    assert seen == []
    assert result.resume_token == "200"
    assert result.note is not None
    assert BUDGET_STOP_NOTE in result.note


def test_progress_is_reported_after_each_batch() -> None:
    handler, _ = router(
        esearch(3), efetch(article("1", "One"), article("2", "Two")), efetch(article("3", "Three"))
    )
    calls: list[tuple[int, int | None, int]] = []
    sink = BudgetedSink(
        sink=_archive, spent=lambda: False, progress=lambda a, b, c: calls.append((a, b, c))
    )
    run(make_source(handler, batch_size=2), keyword(), archive=sink)
    assert calls == [(2, 3, 2), (3, 3, 3)]


def test_limit_gives_partial_with_the_truncated_note() -> None:
    handler, _ = router(
        esearch(3), efetch(article("1", "One"), article("2", "Two"), article("3", "Three"))
    )
    result = run(make_source(handler), keyword(limit=2))
    assert result.status is RunStatus.PARTIAL
    assert result.retrieved_count == 2
    assert result.note == "truncated by caller-supplied limit"


def test_id_list_fetches_directly_without_esearch() -> None:
    handler, seen = router("unused", efetch(article("11", "One"), article("22", "Two")))
    result = run(make_source(handler), id_list("11, 22\n11 22"))
    assert result.status is RunStatus.COMPLETE
    assert result.reported_count == 2
    assert result.query_sent == "11,22"
    assert len(seen) == 1
    assert seen[0].url.path.endswith("efetch.fcgi")
    assert seen[0].url.params["id"] == "11,22"
    assert "WebEnv" not in seen[0].url.params


def test_id_list_names_the_ids_that_did_not_come_back() -> None:
    handler, _ = router("unused", efetch(article("11", "One")))
    result = run(make_source(handler), id_list("11,99"))
    assert result.status is RunStatus.COMPLETE
    assert result.note == "1 requested id(s) not returned: 99"


def test_id_list_batches_and_resumes_by_index() -> None:
    handler, seen = router("unused", efetch(article("3", "Three")))
    result = run(make_source(handler, batch_size=2), id_list("1,2,3"), resume_from="2")
    assert [r.url.params["id"] for r in seen] == ["3"]
    assert result.retrieved_count == 1


def test_unsupported_kind_and_empty_id_list_are_rejected() -> None:
    handler, _ = router("unused", efetch())
    source = make_source(handler)
    with pytest.raises(ValueError, match="does not take"):
        run(source, QuerySpec(source="pubmed", kind=QueryKind.FILTER, text="x"))
    with pytest.raises(ValueError, match="at least one PMID"):
        run(source, id_list(" , "))


def test_key_and_address_are_sent_but_never_archived_or_noted() -> None:
    key, mail = "SECRETKEY123", "me@example.org"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, text=esearch(2))
        return httpx.Response(503, text="down")

    archived: list[RawPage] = []

    def archive(page: RawPage) -> str:
        archived.append(page)
        return blob_for(page.ordinal)

    result = run(make_source(handler, mailto=mail, api_key=key), keyword(), archive=archive)
    sent = seen[0].url.params
    assert sent["api_key"] == key
    assert sent["email"] == mail
    assert sent["tool"] == "research-factory"
    assert result.note is not None
    assert key not in result.note
    assert mail not in result.note
    for page in archived:
        assert key not in page.url
        assert mail not in page.url
        assert "api_key" not in page.url
        assert "email=" not in page.url


def test_ncbi_api_key_from_environment_then_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FACTORY_NCBI_API_KEY", raising=False)
    assert ncbi_api_key() is None

    config = tmp_path / ".config" / "research-factory"
    config.mkdir(parents=True)
    (config / "ncbi-api-key").write_text("filekey\nsecond line\n", encoding="utf-8")
    assert ncbi_api_key() == "filekey"

    monkeypatch.setenv("FACTORY_NCBI_API_KEY", " envkey ")
    assert ncbi_api_key() == "envkey"
