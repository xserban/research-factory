from __future__ import annotations

from datetime import UTC, date, datetime

from factory.model.work import Author, Dates, Identifiers, Provenance, Work, WorkType
from factory.services.dedup_cascade import dedup
from tests.helpers import SESSION

AT = datetime(2026, 9, 11, tzinfo=UTC)


def w(
    title: str,
    *,
    source: str = "openalex",
    authors: list[str] | None = None,
    year: int | None = 2023,
    type_: WorkType = WorkType.JOURNAL_ARTICLE,
    abstract: str | None = None,
    **ids: str,
) -> Work:
    return Work.build(
        title=title,
        type=type_,
        abstract=abstract,
        authors=[Author(name=n) for n in (authors or ["Ada Zhou"])],
        identifiers=Identifiers(**ids),
        dates=Dates(published=date(year, 6, 1) if year else None),
        provenance=[
            Provenance(
                source=source,
                run_id=f"run_{SESSION}",
                query_id=f"qry_{SESSION}",
                at=AT,
                raw_blob="sha256:" + "a" * 64,
            )
        ],
    )


class TestExactIdentifiers:
    def test_same_doi_from_two_sources_becomes_one_work(self) -> None:
        result = dedup(
            [
                w("A Study", source="openalex", doi="10.1234/abc"),
                w("A Study", source="pubmed", doi="10.1234/ABC", pmid="123"),
            ]
        )
        assert len(result.works) == 1
        assert result.removed == 1
        assert result.works[0].sources == ["openalex", "pubmed"]

    def test_merge_unions_identifiers(self) -> None:
        result = dedup(
            [
                w("A Study", source="openalex", doi="10.1234/abc", openalex="W1"),
                w("A Study", source="pubmed", doi="10.1234/abc", pmid="123", pmcid="PMC9"),
            ]
        )
        ids = result.works[0].identifiers
        assert (ids.doi, ids.openalex, ids.pmid, ids.pmcid) == ("10.1234/abc", "W1", "123", "PMC9")

    def test_distinct_dois_are_not_merged(self) -> None:
        result = dedup([w("A Study", doi="10.1234/abc"), w("B Study", doi="10.1234/xyz")])
        assert len(result.works) == 2
        assert result.removed == 0


class TestArxivDoiBridge:
    def test_bare_arxiv_id_and_datacite_doi_are_the_same_preprint(self) -> None:
        """The arXiv adapter returns `2209.14566`; OpenAlex returns `10.48550/arxiv.2209.14566`."""
        result = dedup(
            [
                w(
                    "Diffusion Vessel Segmentation",
                    source="arxiv",
                    type_=WorkType.PREPRINT,
                    arxiv="2209.14566v1",
                ),
                w(
                    "Diffusion Vessel Segmentation",
                    source="openalex",
                    type_=WorkType.PREPRINT,
                    doi="https://doi.org/10.48550/arXiv.2209.14566",
                ),
            ]
        )
        assert len(result.works) == 1
        assert sorted(result.works[0].sources) == ["arxiv", "openalex"]


class TestPreprintAndPublished:
    def test_published_version_becomes_primary_and_supersedes_the_preprint(self) -> None:
        preprint = w("Shared Title", source="arxiv", type_=WorkType.PREPRINT, arxiv="2301.01234")
        published = w(
            "Shared Title",
            source="openalex",
            type_=WorkType.JOURNAL_ARTICLE,
            doi="10.1016/j.media.2023.1",
            arxiv="2301.01234",
        )
        result = dedup([preprint, published])
        assert len(result.works) == 1
        survivor = result.works[0]
        assert survivor.type is WorkType.JOURNAL_ARTICLE
        assert preprint.id in survivor.supersedes


class TestTitleSimilarity:
    def test_near_identical_titles_by_the_same_author_merge(self) -> None:
        result = dedup(
            [
                w("Self-Supervised Coronary Segmentation"),
                w("Self-supervised coronary segmentation."),
            ]
        )
        assert len(result.works) == 1

    def test_same_title_by_different_authors_does_not_merge(self) -> None:
        """A false merge is unrecoverable, so title alone is never enough."""
        result = dedup(
            [
                w("Deep Learning for Segmentation", authors=["Ada Zhou"]),
                w("Deep Learning for Segmentation", authors=["Bo Patel"]),
            ]
        )
        assert len(result.works) == 2

    def test_distant_years_do_not_merge(self) -> None:
        result = dedup(
            [
                w("Self-Supervised Coronary Segmentation", year=2019),
                w("Self-Supervised Coronary Segmentation", year=2025),
            ]
        )
        assert len(result.works) == 2

    def test_different_titles_do_not_merge(self) -> None:
        result = dedup([w("A Study of Cats"), w("A Study of Dogs")])
        assert len(result.works) == 2


class TestBlockedPairs:
    def test_blocked_pair_is_never_merged(self) -> None:
        a = w("Linear Attention for Vision", doi="10.1/a")
        b = w("Linear attention for vision", arxiv="2301.00001")
        assert len(dedup([a, b]).works) == 1
        assert len(dedup([a, b], blocked=frozenset({frozenset({a.id, b.id})})).works) == 2

    def test_blocked_pair_also_blocks_transitive_joins(self) -> None:
        """a and c share a DOI, c and b share an arXiv id; blocking a-b must keep a and b apart."""
        a = w("Linear Attention for Vision", doi="10.1/a")
        c = w("Linear attention for vision", doi="10.1/a", arxiv="2301.00001")
        b = w("Linear attention for vision", arxiv="2301.00001")
        assert len(dedup([a, c, b]).works) == 1

        result = dedup([a, c, b], blocked=frozenset({frozenset({a.id, b.id})}))
        assert len(result.works) == 2
        for survivor in result.works:
            assert not {a.id, b.id} <= {survivor.id, *survivor.absorbed}


class TestMergeContent:
    def test_all_provenance_is_retained(self) -> None:
        """PRISMA counts come from provenance; a merge that drops one corrupts them."""
        result = dedup(
            [
                w("A Study", source="arxiv", doi="10.1234/abc"),
                w("A Study", source="openalex", doi="10.1234/abc"),
                w("A Study", source="pubmed", doi="10.1234/abc"),
            ]
        )
        assert sorted(result.works[0].sources) == ["arxiv", "openalex", "pubmed"]
        assert len(result.works[0].provenance) == 3

    def test_abstract_is_recovered_from_whichever_record_has_one(self) -> None:
        result = dedup(
            [
                w("A Study", source="arxiv", doi="10.1234/abc"),
                w("A Study", source="openalex", doi="10.1234/abc", abstract="The abstract."),
            ]
        )
        assert result.works[0].abstract == "The abstract."

    def test_retraction_propagates_through_a_merge(self) -> None:
        flagged = w("A Study", source="openalex", doi="10.1234/abc")
        result = dedup(
            [
                w("A Study", source="arxiv", doi="10.1234/abc"),
                flagged.model_copy(update={"retracted": True}),
            ]
        )
        assert result.works[0].retracted

    def test_merge_is_reversible_from_the_map(self) -> None:
        a = w("A Study", source="arxiv", doi="10.1234/abc")
        b = w("A Study", source="openalex", doi="10.1234/abc")
        result = dedup([a, b])
        merge = result.merges[0]
        # Same DOI means the two records already share an identity, so nothing is "absorbed" —
        # but two records went in and one work came out, which is what PRISMA reports.
        assert merge.primary == a.id == b.id
        assert merge.records == 2
        assert result.removed == 1


class TestStability:
    def test_output_is_order_independent(self) -> None:
        works = [
            w("A Study", source="arxiv", doi="10.1234/abc"),
            w("A Study", source="openalex", doi="10.1234/abc"),
            w("Another Study", doi="10.1234/xyz"),
        ]
        forward = dedup(works)
        backward = dedup(list(reversed(works)))
        assert [x.id for x in forward.works] == [x.id for x in backward.works]

    def test_empty_corpus(self) -> None:
        assert dedup([]).works == []
