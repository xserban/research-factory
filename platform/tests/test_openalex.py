from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.clock import FixedClock, SystemClock
from factory.config import Settings
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod, Work, WorkType
from factory.sources.base import RawPage, SearchResult
from factory.sources.http import PoliteClient, default_http
from factory.sources.openalex import OpenAlexSource, reconstruct_abstract
from tests.helpers import SESSION, T0

RUN_ID = f"run_{SESSION}"
QUERY_ID = f"qry_{SESSION}"
FIXTURE = Path(__file__).parent / "fixtures" / "openalex_page.json"
SKIPPED_NOTE = "1 records skipped (untitled or duplicate within run)"

Handler = Callable[[httpx.Request], httpx.Response]

ITEM: dict[str, Any] = {
    "id": "https://openalex.org/W4298183756",
    "doi": "https://doi.org/10.1016/j.media.2023.12345",
    "display_name": "Self-Supervised Vessel Segmentation",
    "type": "conference-paper",
    "language": "en",
    "publication_date": "2023-06-14",
    "cited_by_count": 30,
    "is_retracted": False,
    "abstract_inverted_index": {"Vessel": [0], "segmentation": [1], "is": [2], "hard": [3]},
    "ids": {
        "pmid": "https://pubmed.ncbi.nlm.nih.gov/34655727",
        "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123",
    },
    "authorships": [
        {
            "author": {
                "display_name": "Ada Zhou",
                "orcid": "https://orcid.org/0000-0002-1825-0097",
            },
            "institutions": [{"display_name": "KAIST"}],
        },
        {"author": {"display_name": "Bo Liu"}, "institutions": []},
    ],
    "primary_location": {
        "source": {"display_name": "Medical Image Analysis", "host_organization_name": "Elsevier"},
        "landing_page_url": "https://example.org/paper",
    },
    "biblio": {"volume": "88", "issue": "2", "first_page": "10", "last_page": "22"},
    "topics": [{"display_name": "Medical Image Segmentation"}],
}
SECOND: dict[str, Any] = {**ITEM, "id": "https://openalex.org/W2", "doi": "https://doi.org/10.1/b"}


def page(items: list[dict[str, Any]], count: int, cursor: str | None) -> str:
    return json.dumps({"meta": {"count": count, "next_cursor": cursor}, "results": items})


def blob_for(ordinal: int) -> str:
    return f"sha256:{ordinal + 1:064x}"


def _archive(page_: RawPage) -> str:
    return blob_for(page_.ordinal)


def keyword(text: str = "q", **fields: Any) -> QuerySpec:
    return QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text=text, **fields)


def make_source(
    handler: Handler, *, mailto: str | None = None, page_size: int = 200
) -> OpenAlexSource:
    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None)
    return OpenAlexSource(http, clock=FixedClock(T0), mailto=mailto, page_size=page_size)


def serve(*bodies: str, status: int = 200) -> Handler:
    calls = iter(bodies)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=next(calls, bodies[-1]))

    return handler


def source_returning(*bodies: str, status: int = 200) -> OpenAlexSource:
    return make_source(serve(*bodies, status=status))


def capture(seen: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=page([], 0, None))

    return handler


def search(
    source: OpenAlexSource, spec: QuerySpec | None = None, *, resume_from: str | None = None
) -> SearchResult:
    return source.run(
        spec or keyword(),
        run_id=RUN_ID,
        query_id=QUERY_ID,
        archive=_archive,
        resume_from=resume_from,
    )


class TestAbstractReconstruction:
    def test_positions_are_restored_in_order(self) -> None:
        inverted = {"world": [1], "hello": [0], "hello again": [2]}
        assert reconstruct_abstract(inverted) == "hello world hello again"

    def test_repeated_words_appear_at_every_position(self) -> None:
        assert reconstruct_abstract({"a": [0, 2], "b": [1]}) == "a b a"

    @pytest.mark.parametrize("empty", [None, {}])
    def test_missing_index_yields_none(self, empty: dict[str, list[int]] | None) -> None:
        assert reconstruct_abstract(empty) is None


class TestParsing:
    def test_fields_are_carried_across(self) -> None:
        work = search(source_returning(page([ITEM], 1, None))).works[0]
        assert work.title == "Self-Supervised Vessel Segmentation"
        assert work.abstract == "Vessel segmentation is hard"
        assert work.type is WorkType.CONFERENCE_PAPER
        assert work.cited_by_count == 30
        assert work.subjects == ["Medical Image Segmentation"]
        assert work.venue is not None
        assert (work.venue.name, work.venue.publisher) == ("Medical Image Analysis", "Elsevier")
        assert work.venue.pages == "10-22"

    def test_identifier_urls_are_stripped_to_bare_ids(self) -> None:
        work = search(source_returning(page([ITEM], 1, None))).works[0]
        assert work.identifiers.openalex == "W4298183756"
        assert work.identifiers.doi == "10.1016/j.media.2023.12345"
        assert work.identifiers.pmid == "34655727"
        assert work.identifiers.pmcid == "PMC123"

    def test_author_orcid_and_affiliation(self) -> None:
        authors = search(source_returning(page([ITEM], 1, None))).works[0].authors
        assert authors[0].orcid == "0000-0002-1825-0097"
        assert authors[0].affiliation == "KAIST"
        assert authors[1].orcid is None

    def test_unmapped_type_becomes_other_rather_than_a_guess(self) -> None:
        item = {**ITEM, "type": "libguides"}
        work = search(source_returning(page([item], 1, None))).works[0]
        assert work.type is WorkType.OTHER

    def test_conference_abstract_is_not_promoted_to_a_paper(self) -> None:
        item = {**ITEM, "type": "conference-abstract"}
        work = search(source_returning(page([item], 1, None))).works[0]
        assert work.type is WorkType.OTHER

    def test_untitled_records_are_skipped(self) -> None:
        item = {k: v for k, v in ITEM.items() if k != "display_name"}
        result = search(source_returning(page([item], 1, None)))
        assert result.works == []
        assert result.skipped == 1
        assert result.status is RunStatus.COMPLETE
        assert result.note == SKIPPED_NOTE

    def test_provenance_is_attached(self) -> None:
        work = search(source_returning(page([ITEM], 1, None))).works[0]
        provenance = work.provenance[0]
        assert provenance.source == "openalex"
        assert provenance.run_id == RUN_ID
        assert provenance.query_id == QUERY_ID
        assert provenance.at == T0
        assert provenance.raw_blob == blob_for(0)
        assert provenance.raw_ref == "W4298183756"
        assert provenance.method is ProvenanceMethod.DATABASE

    def test_unparseable_json_is_a_failed_run_not_an_empty_success(self) -> None:
        archived: list[RawPage] = []

        def archive(page_: RawPage) -> str:
            archived.append(page_)
            return blob_for(page_.ordinal)

        result = make_source(serve("not json")).run(
            keyword(), run_id=RUN_ID, query_id=QUERY_ID, archive=archive
        )
        assert result.status is RunStatus.FAILED
        assert result.works == [] and result.resume_token == "*"
        assert result.note is not None and result.note.startswith("SourceError: ")
        assert len(archived) == 1, "the unparseable page is archived before it fails"

    def test_non_object_payload_is_a_failed_run(self) -> None:
        result = search(source_returning("[1, 2, 3]"))
        assert result.status is RunStatus.FAILED
        assert result.note is not None and result.note.startswith("SourceError: ")
        assert result.resume_token == "*"

    def test_parse_failure_mid_run_keeps_earlier_records(self) -> None:
        archived: list[RawPage] = []

        def archive(page_: RawPage) -> str:
            archived.append(page_)
            return blob_for(page_.ordinal)

        result = make_source(serve(page([ITEM], 2, "c2"), "not json")).run(
            keyword(), run_id=RUN_ID, query_id=QUERY_ID, archive=archive
        )
        assert result.status is RunStatus.PARTIAL
        assert result.retrieved_count == 1
        assert result.resume_token == "c2"
        assert result.note is not None and result.note.startswith("SourceError: ")
        assert len(archived) == 2
        assert result.works[0].provenance[0].raw_blob == blob_for(0)

    def test_fixture_preprint_has_a_datacite_doi_and_preprint_type(self) -> None:
        works = search(source_returning(FIXTURE.read_text(encoding="utf-8"))).works
        preprint = next(w for w in works if w.type is WorkType.PREPRINT)
        assert preprint.identifiers.doi == "10.48550/arxiv.2401.00001"
        assert preprint.abstract is None


class TestCursorPaging:
    def test_follows_the_cursor_until_it_is_exhausted(self) -> None:
        result = search(source_returning(page([ITEM], 2, "cursor2"), page([SECOND], 2, None)))
        assert result.retrieved_count == 2
        assert result.status is RunStatus.COMPLETE
        assert result.pages == 2

    def test_reported_count_comes_from_meta(self) -> None:
        result = search(source_returning(page([ITEM], 4321, None)))
        assert result.reported_count == 4321
        assert result.has_shortfall

    def test_limit_truncates_and_is_recorded_as_partial(self) -> None:
        result = search(source_returning(page([ITEM, SECOND], 2, "c2")), keyword(limit=1))
        assert (result.status, result.retrieved_count) == (RunStatus.PARTIAL, 1)
        assert result.note == "truncated by caller-supplied limit"

    def test_limit_equal_to_everything_available_is_complete(self) -> None:
        result = search(source_returning(page([ITEM], 1, None)), keyword(limit=1))
        assert result.status is RunStatus.COMPLETE
        assert result.note is None

    def test_empty_result_set(self) -> None:
        result = search(source_returning(page([], 0, None)))
        assert result.works == []
        assert result.status is RunStatus.COMPLETE

    def test_duplicate_within_run_is_skipped_and_counted(self) -> None:
        result = search(source_returning(page([ITEM], 2, "c2"), page([ITEM], 2, None)))
        assert result.retrieved_count == 1
        assert result.skipped == 1
        assert result.status is RunStatus.COMPLETE
        assert result.note == SKIPPED_NOTE

    def test_untitled_record_makes_an_explained_shortfall(self) -> None:
        result = search(source_returning(FIXTURE.read_text(encoding="utf-8")))
        assert result.reported_count == 3
        assert result.retrieved_count == 2
        assert result.status is RunStatus.COMPLETE
        assert result.note == SKIPPED_NOTE

    def test_resume_continues_from_the_given_cursor(self) -> None:
        cursors: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cursors.append(request.url.params["cursor"])
            return httpx.Response(200, text=page([SECOND], 1, None))

        result = search(make_source(handler), resume_from="c2")
        assert cursors == ["c2"]
        assert [w.identifiers.openalex for w in result.works] == ["W2"]


class TestFailure:
    def test_http_error_is_reported_not_swallowed(self) -> None:
        result = search(source_returning(page([], 0, None), status=500))
        assert result.status is RunStatus.FAILED
        assert result.note is not None
        assert result.note.startswith("HTTPStatusError: ")
        assert result.resume_token == "*"

    def test_mid_run_failure_keeps_archived_works_and_a_resume_token(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params["cursor"] == "*":
                return httpx.Response(200, text=page([ITEM], 2, "c2"))
            return httpx.Response(500, text="boom")

        archived: list[RawPage] = []

        def archive(page_: RawPage) -> str:
            archived.append(page_)
            return blob_for(page_.ordinal)

        result = make_source(handler).run(
            keyword(), run_id=RUN_ID, query_id=QUERY_ID, archive=archive
        )
        assert result.status is RunStatus.PARTIAL
        assert result.retrieved_count == 1
        assert result.resume_token == "c2"
        assert result.pages == 1
        assert [p.ordinal for p in archived] == [0]
        assert result.works[0].provenance[0].raw_blob == blob_for(0)
        assert result.note is not None
        assert result.note.startswith("HTTPStatusError: ")


class TestPoliteness:
    def test_mailto_is_sent_when_configured(self) -> None:
        seen: list[httpx.Request] = []
        make_source(capture(seen), mailto="someone@example.org").run(
            keyword(), run_id=RUN_ID, query_id=QUERY_ID, archive=_archive
        )
        assert seen[0].url.params["mailto"] == "someone@example.org"

    def test_no_mailto_is_sent_when_unconfigured(self) -> None:
        seen: list[httpx.Request] = []
        search(make_source(capture(seen)))
        assert "mailto" not in seen[0].url.params

    def test_never_sends_sort_or_relevance_search(self) -> None:
        seen: list[httpx.Request] = []
        search(make_source(capture(seen), page_size=50))
        params = seen[0].url.params
        assert "sort" not in params
        assert "search" not in params
        assert params["per-page"] == "50"
        assert params["cursor"] == "*"


class TestQueryMapping:
    def test_keyword_is_wrapped_in_title_and_abstract_search(self) -> None:
        seen: list[httpx.Request] = []
        result = search(make_source(capture(seen)), keyword("linear attention"))
        assert seen[0].url.params["filter"] == "title_and_abstract.search:linear attention"
        assert result.query_sent == "title_and_abstract.search:linear attention"

    def test_filter_kind_is_sent_verbatim_with_extra_filters(self) -> None:
        seen: list[httpx.Request] = []
        spec = QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text="doi:10.1/a|10.1/b",
            filters={"publication_year": ">2019"},
        )
        result = search(make_source(capture(seen)), spec)
        assert seen[0].url.params["filter"] == "doi:10.1/a|10.1/b,publication_year:>2019"
        assert result.query_sent == "doi:10.1/a|10.1/b,publication_year:>2019"

    def test_id_list_kind_is_refused(self) -> None:
        spec = QuerySpec(source="openalex", kind=QueryKind.ID_LIST, text="W1|W2")
        with pytest.raises(ValueError):
            search(source_returning(page([], 0, None)), spec)

    def test_chase_purpose_marks_provenance_method(self) -> None:
        spec = QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text="cites:W1",
            purpose=QueryPurpose.CHASE,
        )
        work = search(source_returning(page([ITEM], 1, None)), spec).works[0]
        assert work.provenance[0].method is ProvenanceMethod.CITATION_CHASE

    def test_seed_purpose_marks_seed_admission(self) -> None:
        spec = QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text="openalex:W1",
            purpose=QueryPurpose.SEED,
        )
        work = search(source_returning(page([ITEM], 1, None)), spec).works[0]
        assert work.provenance[0].method is ProvenanceMethod.SEED_ADMISSION


class TestArchiveOrder:
    def test_each_page_is_archived_before_its_records_are_parsed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = source_returning(page([ITEM], 2, "c2"), page([SECOND], 2, None))
        events: list[tuple[str, object]] = []
        original = source.to_work

        def spy_to_work(item: dict[str, Any], **kwargs: Any) -> Work | None:
            events.append(("parse", item["id"]))
            return original(item, **kwargs)

        def archive(page_: RawPage) -> str:
            events.append(("archive", page_.ordinal))
            return blob_for(page_.ordinal)

        monkeypatch.setattr(source, "to_work", spy_to_work)
        result = source.run(keyword(), run_id=RUN_ID, query_id=QUERY_ID, archive=archive)

        assert events == [
            ("archive", 0),
            ("parse", ITEM["id"]),
            ("archive", 1),
            ("parse", SECOND["id"]),
        ]
        assert [w.provenance[0].raw_blob for w in result.works] == [blob_for(0), blob_for(1)]


@pytest.mark.network
def test_live_small_query() -> None:
    http = default_http(Settings.load())
    try:
        source = OpenAlexSource(http, clock=SystemClock())
        spec = QuerySpec(
            source="openalex", kind=QueryKind.KEYWORD, text="linear attention", limit=5
        )
        result = search(source, spec)
    finally:
        http._http.close()  # PoliteClient has no close(); release the socket pool
    assert result.status is RunStatus.PARTIAL
    assert result.retrieved_count == 5
    assert result.reported_count is not None
    assert result.reported_count > 5
