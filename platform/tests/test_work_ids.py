import re

import pytest

from factory.model.work_ids import (
    WORK_ID_RE,
    normalize_arxiv,
    normalize_doi,
    normalize_title,
    work_id,
)


class TestNormalization:
    def test_title_strips_accents_punctuation_and_case(self) -> None:
        assert normalize_title("Déjà-Vu: A  Study!") == "deja vu a study"

    @pytest.mark.parametrize(
        "raw",
        ["10.1234/ABC", "https://doi.org/10.1234/abc", "doi:10.1234/Abc", " 10.1234/abc "],
    )
    def test_doi_forms_converge(self, raw: str) -> None:
        assert normalize_doi(raw) == "10.1234/abc"

    @pytest.mark.parametrize(
        "raw",
        ["2301.01234", "2301.01234v3", "http://arxiv.org/abs/2301.01234v1", "arXiv:2301.01234"],
    )
    def test_arxiv_versions_are_the_same_work(self, raw: str) -> None:
        assert normalize_arxiv(raw) == "2301.01234"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("hep-th/9901001v2", "hep-th/9901001"),
            ("http://arxiv.org/abs/hep-th/9901001v1", "hep-th/9901001"),
            ("https://arxiv.org/abs/2301.01234v3", "2301.01234"),
            ("https://arxiv.org/pdf/2301.01234v3.pdf", "2301.01234"),
            ("arXiv:2301.01234", "2301.01234"),
        ],
    )
    def test_only_known_wrappers_are_stripped(self, raw: str, expected: str) -> None:
        """An old-style archive prefix is part of the id, not a URL path to discard."""
        assert normalize_arxiv(raw) == expected


class TestWorkId:
    def test_is_deterministic(self) -> None:
        first = work_id(
            title="Self-Supervised Coronary Segmentation", authors=["Ada Zhou"], year=2023
        )
        again = work_id(
            title="Self-Supervised Coronary Segmentation", authors=["Ada Zhou"], year=2023
        )
        assert first == again

    def test_doi_is_identity_regardless_of_surrounding_metadata(self) -> None:
        """A corrected title or author list must not re-identify the work."""
        a = work_id(title="A Study", authors=["Ada Zhou"], year=2023, doi="10.1234/abc")
        b = work_id(title="A Study (corrected)", authors=["A. Zhou"], year=2023, doi="10.1234/ABC")
        assert a.rsplit("-", 1)[1] == b.rsplit("-", 1)[1]

    def test_arxiv_version_bump_does_not_change_identity(self) -> None:
        a = work_id(title="A Study", authors=["Ada Zhou"], year=2023, arxiv="2301.01234")
        b = work_id(title="A Study", authors=["Ada Zhou"], year=2023, arxiv="2301.01234v4")
        assert a == b

    def test_old_style_ids_in_different_archives_are_different_works(self) -> None:
        a = work_id(title="A Study", authors=["Ada Zhou"], year=1999, arxiv="hep-th/9901001")
        b = work_id(title="A Study", authors=["Ada Zhou"], year=1999, arxiv="cond-mat/9901001")
        assert a != b

    def test_distinct_works_get_distinct_ids(self) -> None:
        a = work_id(title="A Study of Cats", authors=["Ada Zhou"], year=2023)
        b = work_id(title="A Study of Dogs", authors=["Ada Zhou"], year=2023)
        assert a != b

    def test_slug_is_readable_and_skips_stopwords(self) -> None:
        got = work_id(title="A Survey of the Coronary Arteries", authors=["Ada Zhou"], year=2023)
        assert got.startswith("rf:zhou2023-survey-coronary-arteries-")

    def test_missing_authors_and_year_still_produce_an_id(self) -> None:
        assert work_id(title="Untitled Work", authors=[], year=None).startswith("rf:anon-")

    def test_datacite_doi_and_bare_arxiv_id_share_an_id(self) -> None:
        a = work_id(
            title="Linear Attention",
            authors=["Ada Zhou"],
            year=2023,
            doi="10.48550/arXiv.2301.01234",
        )
        b = work_id(
            title="Linear attention!",
            authors=["A. Zhou"],
            year=2023,
            arxiv="2301.01234v2",
        )
        assert a == b

    def test_bridged_ids_differ_only_in_the_readable_part_when_metadata_differs(self) -> None:
        a = work_id(
            title="Linear Attention",
            authors=["Ada Zhou"],
            year=2023,
            doi="10.48550/arXiv.2301.01234",
        )
        b = work_id(
            title="Linear attention!",
            authors=["A. Zhou"],
            year=2024,
            arxiv="2301.01234v2",
        )
        assert a != b
        assert a[-8:] == b[-8:]

    def test_cjk_and_accented_titles_produce_stable_ids(self) -> None:
        for title, author in [
            ("视觉线性注意力", "王伟"),
            ("Étude de l\u2019attention", "Zoë Müller"),
            ("", ""),
        ]:
            authors = [author] if author else []
            wid = work_id(title=title, authors=authors, year=None)
            assert re.fullmatch(WORK_ID_RE, wid)
            assert wid == work_id(title=title, authors=authors, year=None)
