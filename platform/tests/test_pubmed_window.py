"""PubMed watch window (IDEA-76): `listed_since` as an `[edat]` clause, validated at register."""

from __future__ import annotations

from datetime import date

import pytest

from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.services.context import Project
from factory.services.search import query_issues
from factory.sources.pubmed import PubmedSource, entry_date_term
from factory.sources.registry import default_sources, window_filter_sources
from tests.test_pubmed import article, efetch, esearch, keyword, make_source, router, run


def test_pubmed_declares_a_window_filter() -> None:
    assert PubmedSource.window_filter is True
    assert "pubmed" in window_filter_sources()


def test_entry_date_term_is_open_ended_on_the_entry_date() -> None:
    assert (
        entry_date_term("asthma[MeSH]", date(2026, 1, 5))
        == '(asthma[MeSH]) AND ("2026/01/05"[edat] : "3000"[edat])'
    )


def test_listed_since_is_sent_and_recorded_as_the_query_sent() -> None:
    handler, seen = router(esearch(1), efetch(article("1")))
    result = run(make_source(handler), keyword(filters={"listed_since": "2026-01-05"}))
    expected = '(asthma[MeSH]) AND ("2026/01/05"[edat] : "3000"[edat])'
    assert seen[0].url.params["term"] == expected
    assert result.query_sent == expected
    assert result.status is RunStatus.COMPLETE


def test_no_filter_leaves_the_term_verbatim() -> None:
    handler, seen = router(esearch(1), efetch(article("1")))
    result = run(make_source(handler), keyword())
    assert seen[0].url.params["term"] == "asthma[MeSH]"
    assert result.query_sent == "asthma[MeSH]"


def test_probe_count_uses_the_windowed_term() -> None:
    handler, seen = router('{"esearchresult": {"count": "3"}}', efetch())
    count = make_source(handler).count(
        keyword(filters={"listed_since": "2026-01-05"}), archive=lambda _p: "sha256:x"
    )
    assert count == 3
    assert "[edat]" in seen[0].url.params["term"]


def _issues(project: Project, spec: QuerySpec) -> list[str]:
    return [i.reason for i in query_issues(project, spec, default_sources())]


def test_registering_accepts_listed_since_on_a_keyword_query(project: Project) -> None:
    assert _issues(project, keyword(filters={"listed_since": "2026-01-05"})) == []


@pytest.mark.parametrize(
    "filters",
    [{"listed_since": "05/01/2026"}, {"mindate": "2020"}, {"listed_since": "2026-01-05", "x": "y"}],
)
def test_registering_refuses_other_pubmed_filters(
    project: Project, filters: dict[str, str]
) -> None:
    assert _issues(project, keyword(filters=filters))


def test_registering_refuses_listed_since_on_an_id_list(project: Project) -> None:
    spec = QuerySpec(
        source="pubmed",
        kind=QueryKind.ID_LIST,
        text="1,2",
        filters={"listed_since": "2026-01-05"},
    )
    assert _issues(project, spec)
