from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from factory.errors import FactoryError
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Provenance, Work
from factory.sources.base import PageSink, RawPage, SearchResult, Source, SourceError


def _works(prov: Provenance, n: int) -> list[Work]:
    return [Work.build(title=f"Paper {i}", provenance=[prov]) for i in range(n)]


# --- SearchResult: the shortfall rule (R-23 / slice-1 acceptance 14) ----------------------


def test_complete_run_with_unexplained_shortfall_is_invalid(prov: Provenance) -> None:
    with pytest.raises(ValueError):
        SearchResult(
            source="openalex",
            query_sent="q",
            reported_count=10,
            works=[],
            pages=1,
            status=RunStatus.COMPLETE,
        )


def test_explained_shortfall_is_allowed(prov: Provenance) -> None:
    result = SearchResult(
        source="openalex",
        query_sent="q",
        reported_count=10,
        works=_works(prov, 7),
        pages=1,
        status=RunStatus.COMPLETE,
        note="3 untitled records skipped",
    )
    assert result.has_shortfall is True
    assert result.retrieved_count == 7
    assert result.reported_count == 10


def test_complete_run_without_shortfall_needs_no_note(prov: Provenance) -> None:
    result = SearchResult(
        source="arxiv",
        query_sent="q",
        reported_count=2,
        works=_works(prov, 2),
        pages=1,
        status=RunStatus.COMPLETE,
    )
    assert result.has_shortfall is False


def test_unknown_reported_count_is_never_a_shortfall(prov: Provenance) -> None:
    result = SearchResult(
        source="arxiv",
        query_sent="q",
        reported_count=None,
        works=_works(prov, 3),
        pages=1,
        status=RunStatus.COMPLETE,
    )
    assert result.has_shortfall is False


@pytest.mark.parametrize("status", [RunStatus.PARTIAL, RunStatus.FAILED])
def test_partial_and_failed_runs_require_a_note(status: RunStatus, prov: Provenance) -> None:
    with pytest.raises(ValueError):
        SearchResult(
            source="openalex",
            query_sent="q",
            reported_count=None,
            works=_works(prov, 1),
            pages=1,
            status=status,
        )


@pytest.mark.parametrize("status", [RunStatus.PARTIAL, RunStatus.FAILED])
def test_partial_and_failed_runs_with_note_are_allowed(status: RunStatus, prov: Provenance) -> None:
    result = SearchResult(
        source="openalex",
        query_sent="q",
        reported_count=None,
        works=_works(prov, 1),
        pages=1,
        status=status,
        note="network error on page 3",
        resume_token="cursor-abc",
    )
    assert result.status is status
    assert result.resume_token == "cursor-abc"


@pytest.mark.parametrize("note", ["", "   "])
@pytest.mark.parametrize(
    ("status", "reported", "delivered"),
    [
        (RunStatus.COMPLETE, 10, 7),  # (a) complete with an unexplained shortfall
        (RunStatus.PARTIAL, None, 1),  # (b)
        (RunStatus.FAILED, None, 1),  # (c)
    ],
)
def test_blank_note_does_not_explain_a_shortfall(
    note: str, status: RunStatus, reported: int | None, delivered: int, prov: Provenance
) -> None:
    with pytest.raises(ValueError):
        SearchResult(
            source="openalex",
            query_sent="q",
            reported_count=reported,
            works=_works(prov, delivered),
            pages=1,
            status=status,
            note=note,
        )


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.INTERRUPTED])
def test_result_status_must_be_terminal_for_a_source_run(
    status: RunStatus, prov: Provenance
) -> None:
    with pytest.raises(ValueError):
        SearchResult(
            source="openalex",
            query_sent="q",
            reported_count=None,
            works=[],
            pages=0,
            status=status,
            note="x",
        )


def test_search_result_is_frozen(prov: Provenance) -> None:
    result = SearchResult(
        source="arxiv",
        query_sent="q",
        reported_count=0,
        works=[],
        pages=0,
        status=RunStatus.COMPLETE,
    )
    with pytest.raises(AttributeError):
        result.pages = 5  # type: ignore[misc]


def test_skipped_defaults_to_zero(prov: Provenance) -> None:
    result = SearchResult(
        source="arxiv",
        query_sent="q",
        reported_count=0,
        works=[],
        pages=0,
        status=RunStatus.COMPLETE,
    )
    assert result.skipped == 0
    assert result.note is None
    assert result.resume_token is None


# --- QuerySpec ----------------------------------------------------------------------------


def test_query_spec_validation() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="")
    with pytest.raises(ValidationError):
        QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="   ")
    with pytest.raises(ValidationError):
        QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="q", limit=0)


def test_query_spec_strips_text_and_defaults() -> None:
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="  linear attention \n")
    assert spec.text == "linear attention"
    assert spec.purpose is QueryPurpose.SEARCH
    assert spec.filters == {}
    assert spec.limit is None


def test_query_spec_accepts_a_positive_limit() -> None:
    spec = QuerySpec(source="arxiv", kind=QueryKind.FILTER, text="cat:cs.LG", limit=50)
    assert spec.limit == 50


def test_query_spec_is_frozen() -> None:
    spec = QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text="2301.01234")
    with pytest.raises(ValidationError):
        spec.text = "other"  # type: ignore[misc]


# --- Enum values --------------------------------------------------------------------------


def test_enum_values_are_lowercase_strings() -> None:
    assert QueryKind.KEYWORD.value == "keyword"
    assert QueryKind.FILTER.value == "filter"
    assert QueryKind.ID_LIST.value == "id_list"
    assert {p.value for p in QueryPurpose} == {
        "probe",
        "search",
        "chase",
        "seed",
        "supplied",
        "import",
        "status",
        "grey",  # reported grey searches (489e70d)
    }
    assert {s.value for s in RunStatus} == {
        "running",
        "complete",
        "partial",
        "failed",
        "interrupted",
    }


# --- RawPage, errors, Source protocol -----------------------------------------------------


def test_raw_page_fields_and_frozen() -> None:
    at = datetime(2026, 11, 1, tzinfo=UTC)
    page = RawPage(ordinal=1, body="{}", url="https://api.openalex.org/works", fetched_at=at)
    assert page.ordinal == 1
    assert page.fetched_at == at
    with pytest.raises(AttributeError):
        page.body = "x"  # type: ignore[misc]


def test_source_error_is_a_factory_error() -> None:
    assert issubclass(SourceError, FactoryError)


class _FakeSource:
    name = "fake"
    kinds = frozenset({QueryKind.KEYWORD})

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        archive(RawPage(ordinal=1, body="", url="u", fetched_at=datetime.now(UTC)))
        return SearchResult(
            source=self.name,
            query_sent=spec.text,
            reported_count=0,
            works=[],
            pages=1,
            status=RunStatus.COMPLETE,
        )


def test_a_conforming_adapter_satisfies_the_source_protocol() -> None:
    source: Source = _FakeSource()
    assert isinstance(source, Source)


# --- probe_key: the identity a probe matches a work by -----------------------------------


def test_probe_key_bridges_datacite_doi_to_arxiv(prov: Provenance) -> None:
    from factory.model.work import Identifiers
    from factory.sources.base import probe_key

    bridged = Work.build(
        title="Bridged",
        provenance=[prov],
        identifiers=Identifiers(doi="https://doi.org/10.48550/arXiv.2301.02033v2"),
    )
    direct = Work.build(
        title="Direct",
        provenance=[prov],
        identifiers=Identifiers(arxiv="http://arxiv.org/abs/2301.02033v3"),
    )
    nothing = Work.build(
        title="Nothing", provenance=[prov], identifiers=Identifiers(doi="10.1016/j.x.2023.1")
    )

    assert probe_key("arxiv", bridged) == "2301.02033"
    assert probe_key("arxiv", direct) == "2301.02033"
    assert probe_key("arxiv", nothing) is None
    assert probe_key("pubmed", direct) is None


def test_probe_key_for_pubmed_is_the_pmid(prov: Provenance) -> None:
    from factory.model.work import Identifiers
    from factory.sources.base import probe_key

    with_pmid = Work.build(title="P", provenance=[prov], identifiers=Identifiers(pmid="123"))
    without = Work.build(title="Q", provenance=[prov], identifiers=Identifiers(doi="10.1/x"))

    assert probe_key("pubmed", with_pmid) == "123"
    assert probe_key("pubmed", without) is None


def test_probe_key_for_openalex_is_the_work_id(prov: Provenance) -> None:
    from factory.model.work import Identifiers
    from factory.sources.base import probe_key

    work = Work.build(
        title="Works", provenance=[prov], identifiers=Identifiers(openalex="W4298183756")
    )
    assert probe_key("openalex", work) == "W4298183756"
    assert probe_key("openalex", Work.build(title="None", provenance=[prov])) is None


def test_probe_key_for_openalex_falls_back_to_a_doi_key(prov: Provenance) -> None:
    from factory.model.work import Identifiers
    from factory.sources.base import probe_key

    def work(**ids: str) -> Work:
        return Work.build(title="T", provenance=[prov], identifiers=Identifiers(**ids))

    assert probe_key("openalex", work(openalex="W9", doi="10.1/x")) == "W9"
    assert probe_key("openalex", work(doi="https://doi.org/10.1/X")) == "doi:10.1/x"
    assert probe_key("openalex", work(arxiv="2610.04074v2")) == "doi:10.48550/arxiv.2610.04074"
    assert probe_key("openalex", work(doi="10.1/a,b")) is None
