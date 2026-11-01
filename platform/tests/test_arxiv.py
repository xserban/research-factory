"""arXiv adapter tests, offline.

Ported from the old project. Responses are the recorded Atom payload in
`fixtures/arxiv_page.xml`, served through a mock transport, so a test suite that needs the
network is a suite that gets skipped. One live lookup is marked `network`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.clock import FixedClock, SystemClock
from factory.config import Settings
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod, WorkType
from factory.sources.arxiv import ArxivSource
from factory.sources.base import RawPage, SearchResult
from factory.sources.http import PoliteClient, default_http
from tests.helpers import SESSION, T0

RUN_ID = f"run_{SESSION}"
QUERY_ID = f"qry_{SESSION}"
FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_page.xml"
ATOM = FIXTURE.read_text(encoding="utf-8")
SKIPPED_NOTE = "1 records skipped (untitled or duplicate within run)"
TRUNCATED_NOTE = "truncated by caller-supplied limit"

EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>0</opensearch:totalResults>
</feed>
"""

# One matching entry, as arXiv answers an id_list intersected with a search_query.
MATCH_ONE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2301.02033v3</id>
    <title>Physics-informed self-supervised reconstruction</title>
  </entry>
</feed>
"""

# A single titled entry for 2301.00001, as arXiv answers an id_list that names it.
ONE_ENTRY_2301_00001 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>A paper that exists</title>
  </entry>
</feed>
"""

# Two entries, one of which has no title and so cannot be screened.
UNTITLED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2301.02033v3</id>
    <title>Physics-informed</title>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2209.14566v1</id>
  </entry>
</feed>
"""

Handler = Callable[[httpx.Request], httpx.Response]


def blob_for(ordinal: int) -> str:
    return f"sha256:{ordinal + 1:064x}"


def _archive(page_: RawPage) -> str:
    return blob_for(page_.ordinal)


def keyword(text: str = "all:test", **fields: Any) -> QuerySpec:
    return QuerySpec(source="arxiv", kind=QueryKind.KEYWORD, text=text, **fields)


def make_source(handler: Handler, *, page_size: int = 100) -> ArxivSource:
    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None)
    return ArxivSource(http, clock=FixedClock(T0), page_size=page_size)


def serve(*bodies: str, status: int = 200) -> Handler:
    """A handler that answers one canned body per request, repeating the last one after that."""
    calls = iter(bodies)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=next(calls, bodies[-1]))

    return handler


def source_returning(*bodies: str, status: int = 200, page_size: int = 100) -> ArxivSource:
    return make_source(serve(*bodies, status=status), page_size=page_size)


def capture(seen: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=EMPTY)

    return handler


def search(
    source: ArxivSource,
    spec: QuerySpec | None = None,
    *,
    resume_from: str | None = None,
    archive: Callable[[RawPage], str] = _archive,
) -> SearchResult:
    return source.run(
        spec or keyword(),
        run_id=RUN_ID,
        query_id=QUERY_ID,
        archive=archive,
        resume_from=resume_from,
    )


class TestParsing:
    def test_entries_become_works(self) -> None:
        result = search(source_returning(ATOM, EMPTY))
        assert [w.title for w in result.works] == [
            "Physics-informed self-supervised reconstruction",
            "Diffusion Adversarial Representation Learning",
        ]

    def test_reported_count_comes_from_opensearch(self) -> None:
        assert search(source_returning(ATOM, EMPTY)).reported_count == 2

    def test_arxiv_id_is_normalized_but_url_keeps_the_version(self) -> None:
        work = search(source_returning(ATOM, EMPTY)).works[0]
        assert work.identifiers.arxiv == "2301.02033"
        assert work.identifiers.url == "http://arxiv.org/abs/2301.02033v3"

    def test_metadata_is_carried_across(self) -> None:
        work = search(source_returning(ATOM, EMPTY)).works[0]
        assert work.type is WorkType.PREPRINT
        assert work.identifiers.doi == "10.1007/978-3-030-88552-6_9"
        assert [a.name for a in work.authors] == ["Ana Gonzalez", "Bo Liu"]
        assert work.subjects == ["eess.IV", "cs.LG"]
        assert work.venue is not None and work.venue.name == "MICCAI 2023"
        assert work.dates.published is not None and work.dates.published.year == 2023

    def test_every_work_carries_provenance(self) -> None:
        result = search(source_returning(ATOM, EMPTY))
        for work in result.works:
            assert [p.source for p in work.provenance] == ["arxiv"]
            assert work.provenance[0].run_id == RUN_ID
            assert work.provenance[0].query_id == QUERY_ID
            assert work.provenance[0].at == T0
            assert work.provenance[0].raw_blob == blob_for(0)
            assert work.provenance[0].method is ProvenanceMethod.DATABASE
        assert result.works[0].provenance[0].raw_ref == "http://arxiv.org/abs/2301.02033v3"

    def test_malformed_xml_is_a_failed_run_never_an_empty_success(self) -> None:
        archived: list[int] = []

        def archive(page_: RawPage) -> str:
            archived.append(page_.ordinal)
            return blob_for(page_.ordinal)

        result = search(source_returning("<not-xml", EMPTY), archive=archive)
        assert result.status is RunStatus.FAILED
        assert result.works == [] and result.resume_token == "0"
        assert result.note is not None and result.note.startswith("SourceError: ")
        assert archived == [0], "the page must be archived before it fails to parse"

    def test_parse_failure_mid_run_keeps_earlier_records(self) -> None:
        archived: list[int] = []

        def archive(page_: RawPage) -> str:
            archived.append(page_.ordinal)
            return blob_for(page_.ordinal)

        # page_size 1: the one-entry first page is full, so paging continues to offset 1.
        source = source_returning(MATCH_ONE, "<not-xml", page_size=1)
        result = search(source, archive=archive)
        assert result.status is RunStatus.PARTIAL
        assert result.retrieved_count == 1
        assert result.resume_token == "1"
        assert result.note is not None and result.note.startswith("SourceError: ")
        assert archived == [0, 1]
        assert result.works[0].provenance[0].raw_blob == blob_for(0)

    def test_untitled_entry_is_an_explained_shortfall(self) -> None:
        result = search(source_returning(UNTITLED))
        assert (result.retrieved_count, result.skipped) == (1, 1)
        assert result.status is RunStatus.COMPLETE
        assert result.note == SKIPPED_NOTE

    def test_query_sent_is_the_exact_search_query(self) -> None:
        assert search(source_returning(ATOM, EMPTY)).query_sent == "all:test"


class TestExhaustiveness:
    def test_a_short_page_ends_paging(self) -> None:
        """Two entries against a page size of 100 means the result set is exhausted."""
        result = search(source_returning(ATOM))
        assert result.status is RunStatus.COMPLETE
        assert result.retrieved_count == 2
        assert result.pages == 1

    def test_caller_limit_is_recorded_as_partial(self) -> None:
        """A capped search and a complete one must never look the same afterwards."""
        result = search(source_returning(ATOM), keyword(limit=1))
        assert result.status is RunStatus.PARTIAL
        assert result.retrieved_count == 1
        assert result.note == TRUNCATED_NOTE

    def test_raw_pages_are_archived_verbatim(self) -> None:
        pages: list[RawPage] = []

        def archive(page_: RawPage) -> str:
            pages.append(page_)
            return blob_for(page_.ordinal)

        search(source_returning(ATOM), archive=archive)
        assert [p.body for p in pages] == [ATOM]

    def test_duplicate_entries_across_pages_are_not_double_counted(self) -> None:
        result = search(source_returning(ATOM, ATOM, EMPTY, page_size=2))
        assert result.retrieved_count == 2
        assert result.skipped == 2
        assert result.status is RunStatus.COMPLETE

    def test_sorts_by_submission_date_never_relevance(self) -> None:
        """Relevance is not reproducible across runs, so paging would skip or repeat records."""
        seen: list[httpx.Request] = []
        source = make_source(capture(seen))
        search(source)  # ascending by default
        search(source, keyword(limit=5))  # descending when capped, to get the newest
        assert [r.url.params["sortBy"] for r in seen] == ["submittedDate", "submittedDate"]
        assert [r.url.params["sortOrder"] for r in seen] == ["ascending", "descending"]
        assert all("relevance" not in str(r.url) for r in seen)

    def test_filter_kind_is_refused(self) -> None:
        spec = QuerySpec(source="arxiv", kind=QueryKind.FILTER, text="cites:W1")
        with pytest.raises(ValueError):
            search(source_returning(EMPTY), spec)

    def test_id_list_kind_fetches_in_batches(self) -> None:
        ids = [f"2301.{n:05d}" for n in range(150)]
        seen: list[httpx.Request] = []
        source = make_source(capture(seen), page_size=100)
        source.run(
            QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text=",".join(ids)),
            run_id=RUN_ID,
            query_id=QUERY_ID,
            archive=_archive,
        )
        batches = [r.url.params["id_list"].split(",") for r in seen]
        assert [len(b) for b in batches] == [100, 50]
        assert all("search_query" not in r.url.params for r in seen)

    def test_id_list_text_is_split_stripped_and_empties_ignored(self) -> None:
        seen: list[httpx.Request] = []
        spec = QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text=" 2301.02033 , ,2209.14566, ")
        result = search(make_source(capture(seen)), spec)
        assert seen[0].url.params["id_list"] == "2301.02033,2209.14566"
        assert result.query_sent == "2301.02033,2209.14566"

    def test_id_list_with_no_ids_is_refused(self) -> None:
        spec = QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text=" , ")
        with pytest.raises(ValueError):
            search(source_returning(EMPTY), spec)

    def test_id_list_missing_id_is_an_explained_shortfall(self) -> None:
        """A seed that arXiv does not return must be visible, not silently absent."""
        spec = QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text="2301.00001,2301.99999")
        result = search(source_returning(ONE_ENTRY_2301_00001), spec)
        assert result.status is RunStatus.COMPLETE
        assert (result.reported_count, result.retrieved_count) == (2, 1)
        assert result.note is not None and "2301.99999" in result.note

    def test_id_list_duplicate_requests_count_once(self) -> None:
        spec = QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text="2301.00001, 2301.00001v2")
        result = search(source_returning(ONE_ENTRY_2301_00001), spec)
        assert result.reported_count == 1
        assert result.query_sent == "2301.00001"

    def test_old_style_ids_are_sent_with_their_archive(self) -> None:
        seen: list[httpx.Request] = []
        spec = QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text="hep-th/9901001")
        search(make_source(capture(seen)), spec)
        assert seen[0].url.params["id_list"] == "hep-th/9901001"

    def test_distinct_old_style_ids_are_not_collapsed(self) -> None:
        spec = QuerySpec(
            source="arxiv", kind=QueryKind.ID_LIST, text="hep-th/9901001,cond-mat/9901001"
        )
        result = search(source_returning(EMPTY), spec)
        assert result.reported_count == 2

    def test_version_pin_is_sent_as_requested(self) -> None:
        seen: list[httpx.Request] = []
        returned = ONE_ENTRY_2301_00001.replace("2301.00001v1", "2301.00001v2")

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, text=returned)

        spec = QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text="2301.00001v2")
        result = search(make_source(handler), spec)
        assert seen[0].url.params["id_list"] == "2301.00001v2"
        assert (result.reported_count, result.retrieved_count) == (1, 1)
        assert result.status is RunStatus.COMPLETE
        assert result.note is None

    def test_matching_intersects_ids_with_query(self) -> None:
        seen: list[httpx.Request] = []
        archived: list[RawPage] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, text=MATCH_ONE)

        def archive(page_: RawPage) -> str:
            archived.append(page_)
            return blob_for(page_.ordinal)

        found = make_source(handler).matching(
            ["2301.02033", "2209.14566"],
            "all:test",
            run_id=RUN_ID,
            query_id=QUERY_ID,
            archive=archive,
        )
        assert found == {"2301.02033"}
        assert seen[0].url.params["search_query"] == "all:test"
        assert seen[0].url.params["id_list"] == "2301.02033,2209.14566"
        assert [p.body for p in archived] == [MATCH_ONE]


class TestFailure:
    def test_http_error_yields_failed_status_not_an_empty_success(self) -> None:
        result = search(source_returning(EMPTY, status=503))
        assert result.status is RunStatus.FAILED
        assert result.note is not None
        assert result.note.startswith("HTTPStatusError: ")
        assert result.resume_token == "0"

    def test_shortfall_is_visible(self) -> None:
        result = search(source_returning(ATOM), keyword(limit=1))
        assert result.has_shortfall


class TestDurability:
    def test_pages_are_archived_as_they_arrive(self) -> None:
        """Archiving must not wait for the run to finish: a 58-page search can die at page 26."""
        seen: list[int] = []

        def archive(page_: RawPage) -> str:
            seen.append(page_.ordinal)
            return blob_for(page_.ordinal)

        search(source_returning(ATOM, ATOM, EMPTY, page_size=2), archive=archive)
        assert seen == [0, 1, 2]

    def test_each_page_is_archived_before_its_records_are_parsed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = source_returning(ATOM, EMPTY, page_size=2)
        events: list[tuple[str, Any]] = []
        original = source._to_work

        def spy_to_work(entry: Any, **kwargs: Any) -> Any:
            events.append(("parse", kwargs["raw_blob"]))
            return original(entry, **kwargs)

        def archive(page_: RawPage) -> str:
            events.append(("archive", page_.ordinal))
            return blob_for(page_.ordinal)

        monkeypatch.setattr(source, "_to_work", spy_to_work)
        search(source, archive=archive)
        assert events == [
            ("archive", 0),
            ("parse", blob_for(0)),
            ("parse", blob_for(0)),
            ("archive", 1),
        ]

    def test_a_page_reaches_the_sink_even_when_a_later_page_fails(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] > 1:
                return httpx.Response(429, text="slow down")
            return httpx.Response(200, text=ATOM)

        archived: list[int] = []

        def archive(page_: RawPage) -> str:
            archived.append(page_.ordinal)
            return blob_for(page_.ordinal)

        result = make_source(handler, page_size=2).run(
            keyword(), run_id=RUN_ID, query_id=QUERY_ID, archive=archive
        )
        assert archived == [0], "the successful page must survive the later failure"
        assert result.status is RunStatus.PARTIAL
        assert result.retrieved_count == 2

    def test_failure_records_a_resume_token(self) -> None:
        result = search(source_returning(EMPTY, status=503))
        assert result.status is RunStatus.FAILED
        assert result.resume_token == "0"

    def test_resume_starts_from_the_given_offset(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.params.get("start", ""))
            return httpx.Response(200, text=EMPTY)

        search(make_source(handler), resume_from="2600")
        assert seen[0] == "2600", "a resumed run must not re-fetch what it already has"

    def test_page_ordinals_continue_across_a_resume(self) -> None:
        """Ordinals key the archive filenames; restarting them would overwrite earlier pages."""
        archived: list[int] = []

        def archive(page_: RawPage) -> str:
            archived.append(page_.ordinal)
            return blob_for(page_.ordinal)

        search(source_returning(ATOM, EMPTY), resume_from="2600", archive=archive)
        assert archived and min(archived) >= 26


@pytest.mark.network
def test_live_id_lookup() -> None:
    http = default_http(Settings.load())
    try:
        source = ArxivSource(http, clock=SystemClock())
        result = source.run(
            QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text="1706.03762"),
            run_id=RUN_ID,
            query_id=QUERY_ID,
            archive=_archive,
        )
    finally:
        http._http.close()  # PoliteClient has no close(); release the socket pool
    assert result.retrieved_count == 1
    assert "Attention" in result.works[0].title
