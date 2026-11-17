"""PubMed adapter edge cases, offline: id normalisation, efetch XML shapes, paging, retry.

Reuses the payload builders of `test_pubmed`; every request goes through a mock transport.
"""

from __future__ import annotations

import httpx
import pytest

from factory.clock import FixedClock
from factory.model.search import RunStatus
from factory.model.work import Work
from factory.sources.http import PoliteClient
from factory.sources.pubmed import PubmedSource
from tests.helpers import T0
from tests.test_pubmed import (
    Handler,
    article,
    efetch,
    esearch,
    id_list,
    keyword,
    make_source,
    router,
    run,
)

# ---- id_list normalisation ------------------------------------------------------------------


def test_id_list_strips_leading_zeros_and_pmid_prefixes() -> None:
    handler, seen = router("unused", efetch(article("11", "One"), article("22", "Two")))
    result = run(make_source(handler), id_list("0011, pmid:22 PMID: 0022\n11"))
    assert result.query_sent == "11,22"
    assert seen[0].url.params["id"] == "11,22"
    assert result.reported_count == 2
    assert result.note is None


def test_id_list_with_a_non_pmid_token_is_rejected_before_any_request() -> None:
    handler, seen = router("unused", efetch())
    with pytest.raises(ValueError, match="digits only"):
        run(make_source(handler), id_list("11, PMC123"))
    assert seen == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("pmid:", "at least one PMID"),
        ("0", "positive integer"),
        ("000", "positive integer"),
        ("PMC", "digits only"),
        ("11, \u0661\u0662\u0663", "digits only"),  # Arabic-Indic digits are not ASCII
        ("11, 1\u00b2", "digits only"),  # superscript two passes str.isdigit
        ("11, -5", "digits only"),
        ("11, 1.5", "digits only"),
    ],
)
def test_id_list_invalid_tokens_are_rejected_before_any_request(text: str, message: str) -> None:
    handler, seen = router("unused", efetch())
    with pytest.raises(ValueError, match=message):
        run(make_source(handler), id_list(text))
    assert seen == []


def test_resuming_an_id_list_after_normalisation_fetches_the_tail_only() -> None:
    # Normalised ids are 11,22,33,44,55 (prefix, zeros and duplicates removed); resume at 2.
    handler, seen = router("unused", efetch(article("33"), article("44")))
    result = run(
        make_source(handler, batch_size=3),
        id_list("0011 pmid:22, PMID: 33 044\n55 11"),
        resume_from="2",
    )
    assert [r.url.params["id"] for r in seen] == ["33,44,55"]
    assert result.reported_count == 5
    assert result.status is RunStatus.COMPLETE
    # The ids before the offset are not asked for again, so only the tail can be missing.
    assert result.note == "1 requested id(s) not returned: 55; resumed at offset 2"
    assert result.resume_token is None


def test_resuming_an_id_list_ignores_ids_before_the_offset_in_the_missing_note() -> None:
    handler, seen = router("unused", efetch(article("44"), article("55")))
    result = run(make_source(handler, batch_size=5), id_list("11,22,33,44,55"), resume_from="3")
    assert seen[0].url.params["id"] == "44,55"
    assert "retstart" not in seen[0].url.params
    assert result.note == "resumed at offset 3"  # 11, 22, 33 were not returned but are not missing
    assert [w.identifiers.pmid for w in result.works] == ["44", "55"]


# ---- keyword terms with date slices are sent verbatim -------------------------------------------


def test_date_sliced_term_is_sent_unchanged() -> None:
    term = '(asthma[MeSH]) AND ("2020/01/01"[dp] : "2020/06/30"[dp])'
    handler, seen = router(esearch(1), efetch(article("1")))
    result = run(make_source(handler), keyword(term))
    assert seen[0].url.params["term"] == term
    assert result.status is RunStatus.COMPLETE


def test_two_date_slices_are_independent_runs() -> None:
    handler, seen = router(esearch(1), efetch(article("1")))
    source = make_source(handler)
    run(source, keyword("x AND 2020[dp]"))
    run(source, keyword("x AND 2021[dp]"))
    terms = [r.url.params["term"] for r in seen if r.url.path.endswith("esearch.fcgi")]
    assert terms == ["x AND 2020[dp]", "x AND 2021[dp]"]


# ---- pagination and the cap -------------------------------------------------------------------


def test_one_past_the_cap_is_partial_with_esearch_cap_note() -> None:
    handler, seen = router(esearch(10000), efetch(article("1")))
    result = run(make_source(handler, batch_size=5000), keyword())
    assert result.status is RunStatus.PARTIAL
    assert result.note is not None and result.note.startswith("esearch-cap: 10000 reported")
    last = seen[-1].url.params
    assert int(last["retstart"]) + int(last["retmax"]) == 9999


def _serving(count: int) -> tuple[Handler, list[httpx.Request]]:
    """esearch reports `count`; efetch returns one article per requested record."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, text=esearch(count))
        first = int(request.url.params["retstart"])
        size = int(request.url.params["retmax"])
        body = "".join(
            _bare(str(n + 1), f"<ArticleTitle>Title {n + 1}</ArticleTitle>")
            for n in range(first, first + size)
        )
        return httpx.Response(200, text=efetch(body))

    return handler, seen


def test_capped_run_keeps_the_reported_count_and_retrieves_the_cap() -> None:
    handler, seen = _serving(10000)
    result = run(make_source(handler, batch_size=5000), keyword())
    assert result.status is RunStatus.PARTIAL
    assert result.reported_count == 10000
    assert len(result.works) == 9999
    assert result.skipped == 0
    assert result.pages == 3  # esearch plus two efetch pages
    assert [int(r.url.params["retmax"]) for r in seen[1:]] == [5000, 4999]
    assert result.note == "esearch-cap: 10000 reported, 9999 retrievable; split the query by date"


def test_capped_run_has_no_resume_token_because_the_rest_is_unreachable() -> None:
    # The cap is a limit of the source, not of this run: offsets past 9,999 are refused by
    # E-utilities, so a token would invite a resume that can never finish. None is intended.
    handler, _ = _serving(10000)
    result = run(make_source(handler, batch_size=5000), keyword())
    assert result.status is RunStatus.PARTIAL
    assert result.resume_token is None


def test_cap_with_a_limit_below_it_is_truncated_and_keeps_the_cap_note() -> None:
    handler, seen = _serving(10000)
    result = run(make_source(handler, batch_size=200), keyword(limit=150))
    assert result.status is RunStatus.PARTIAL
    assert len(result.works) == 150
    assert result.reported_count == 10000
    assert result.note is not None
    assert "truncated by caller-supplied limit" in result.note
    assert "esearch-cap: 10000 reported" in result.note
    assert len(seen) == 2  # one esearch, one efetch


def test_cap_with_a_limit_above_the_cap_is_still_capped() -> None:
    handler, _ = _serving(10000)
    result = run(make_source(handler, batch_size=5000), keyword(limit=20000))
    assert len(result.works) == 9999
    assert result.note is not None
    assert result.note.startswith("esearch-cap: 10000 reported")
    assert "truncated" not in result.note


def test_cap_with_a_resume_offset_fetches_up_to_the_cap_and_notes_both() -> None:
    handler, seen = _serving(10000)
    result = run(make_source(handler, batch_size=500), keyword(), resume_from="9000")
    assert [(r.url.params["retstart"], r.url.params["retmax"]) for r in seen[1:]] == [
        ("9000", "500"),
        ("9500", "499"),
    ]
    assert len(result.works) == 999
    assert result.reported_count == 10000
    assert result.status is RunStatus.PARTIAL
    assert result.resume_token is None
    assert result.note is not None
    assert result.note.startswith("esearch-cap: 10000 reported")
    assert "resumed at offset 9000" in result.note


def test_exactly_the_cap_retrieves_every_record() -> None:
    handler, _ = _serving(9999)
    result = run(make_source(handler, batch_size=5000), keyword())
    assert result.status is RunStatus.COMPLETE
    assert result.reported_count == 9999
    assert len(result.works) == 9999
    assert result.note is None


def test_last_page_asks_only_for_the_remainder() -> None:
    handler, seen = router(esearch(5), efetch(article("1")))
    run(make_source(handler, batch_size=2), keyword())
    fetches = [(r.url.params["retstart"], r.url.params["retmax"]) for r in seen[1:]]
    assert fetches == [("0", "2"), ("2", "2"), ("4", "1")]


# ---- efetch XML shapes ----------------------------------------------------------------


def _bare(pmid: str, body: str) -> str:
    return (
        f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>{body}</Article>"
        "</MedlineCitation></PubmedArticle>"
    )


def _one(xml: str) -> Work:
    handler, _ = router(esearch(1), efetch(xml))
    result = run(make_source(handler), keyword())
    assert len(result.works) == 1
    return result.works[0]


def test_missing_abstract_and_ids_and_authors() -> None:
    work = _one(_bare("7", "<ArticleTitle>Bare</ArticleTitle>"))
    assert work.abstract is None
    assert work.identifiers.pmid == "7"
    assert work.identifiers.doi is None
    assert work.authors == []
    assert work.dates.published is None


def test_unlabelled_abstract_is_plain_and_structured_keeps_labels() -> None:
    plain = _one(
        _bare(
            "8",
            "<ArticleTitle>T</ArticleTitle><Abstract><AbstractText>Just text.</AbstractText>"
            "</Abstract>",
        )
    )
    assert plain.abstract == "Just text."


def test_structured_abstract_keeps_labels_in_order() -> None:
    work = _one(article("9"))
    assert work.abstract == "BACKGROUND: Why.\n\nMETHODS: How."


def test_collective_author_only_and_nameless_author_dropped() -> None:
    xml = _bare(
        "10",
        "<ArticleTitle>T</ArticleTitle><AuthorList>"
        "<Author><CollectiveName>The Group</CollectiveName></Author>"
        "<Author><Initials>X</Initials></Author>"
        "<Author><LastName>Solo</LastName></Author>"
        "</AuthorList>",
    )
    work = _one(xml)
    assert [a.name for a in work.authors] == ["The Group", "Solo"]


def test_medline_date_range_uses_its_first_year() -> None:
    xml = _bare(
        "11",
        "<ArticleTitle>T</ArticleTitle><Journal><JournalIssue><PubDate>"
        "<MedlineDate>1998 Dec-1999 Jan</MedlineDate></PubDate></JournalIssue></Journal>",
    )
    work = _one(xml)
    assert work.dates.published is not None
    assert work.dates.published.year == 1998


def test_numeric_month_and_out_of_range_day_are_clamped() -> None:
    xml = _bare(
        "12",
        "<ArticleTitle>T</ArticleTitle><Journal><JournalIssue><PubDate>"
        "<Year>2021</Year><Month>02</Month><Day>31</Day></PubDate></JournalIssue></Journal>",
    )
    work = _one(xml)
    assert work.dates.published is not None
    assert (work.dates.published.month, work.dates.published.day) == (2, 28)


def test_nonsense_year_gives_no_date() -> None:
    xml = _bare(
        "13",
        "<ArticleTitle>T</ArticleTitle><Journal><JournalIssue><PubDate><Year>n/a</Year>"
        "</PubDate></JournalIssue></Journal>",
    )
    assert _one(xml).dates.published is None


def test_book_article_without_a_pubmedarticle_is_not_a_record() -> None:
    body = (
        '<?xml version="1.0"?><PubmedArticleSet><PubmedBookArticle><BookDocument/>'
        "</PubmedBookArticle></PubmedArticleSet>"
    )
    handler, _ = router(esearch(1), body)
    result = run(make_source(handler), keyword())
    assert result.works == []


# ---- PMC id on the record ----------------------------------------------------------------------


def test_pmcid_is_kept_as_given_and_absent_when_not_listed() -> None:
    with_pmc = _one(article("20"))
    assert with_pmc.identifiers.pmcid == "PMC20"
    without = _one(_bare("21", "<ArticleTitle>T</ArticleTitle>"))
    assert without.identifiers.pmcid is None


# ---- rate limiting and retry -------------------------------------------------------------------


def test_retry_after_429_is_honoured_then_the_run_completes() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "3"})
            return httpx.Response(200, text=esearch(1))
        return httpx.Response(200, text=efetch(article("1")))

    http = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append, retries=2
    )
    source = PubmedSource(http, clock=FixedClock(T0))
    result = run(source, keyword())
    assert result.status is RunStatus.COMPLETE
    assert calls["n"] == 2
    assert 3.0 in sleeps


def test_persistent_5xx_on_esearch_fails_with_token_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    http = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None, retries=1
    )
    result = run(PubmedSource(http, clock=FixedClock(T0)), keyword())
    assert result.status is RunStatus.FAILED
    assert result.resume_token == "0"


def test_a_non_numeric_resume_token_is_refused_before_any_request() -> None:
    handler, seen = router(esearch(1), efetch(article("1")))
    with pytest.raises(ValueError, match="non-negative offset"):
        run(make_source(handler), keyword(), resume_from="abc")
    with pytest.raises(ValueError, match="non-negative offset"):
        run(make_source(handler), keyword(), resume_from="-3")
    assert seen == []
