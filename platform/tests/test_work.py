from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from factory.model.work import Author, Dates, Identifiers, Provenance, Work, WorkType
from factory.model.work_ids import work_id
from tests.helpers import SESSION


def test_work_without_provenance_cannot_exist() -> None:  # slice-1 acceptance 2
    with pytest.raises(ValidationError):
        Work.build(title="T", provenance=[])


def test_build_derives_the_id_from_content(prov: Provenance) -> None:
    w = Work.build(
        title="Linear Attention",
        authors=[Author(name="Ada Zhou")],
        identifiers=Identifiers(doi="https://doi.org/10.1/X"),
        provenance=[prov],
    )
    assert w.id == work_id(title="Linear Attention", authors=["Ada Zhou"], year=None, doi="10.1/x")
    assert w.identifiers.doi == "10.1/x"


def test_identifiers_normalise_arxiv_versions() -> None:
    assert Identifiers(arxiv="arXiv:2301.01234v3").arxiv == "2301.01234"


def test_identifiers_are_normalised_on_a_frozen_model() -> None:
    ids = Identifiers(doi="doi:10.1/ABC")
    assert ids.doi == "10.1/abc"
    with pytest.raises(ValidationError):
        ids.doi = "other"  # type: ignore[misc]


def test_any_strong_prefers_doi_then_arxiv_then_pmid_then_openalex() -> None:
    assert Identifiers(doi="10.1/a", arxiv="2301.01234", pmid="1").any_strong() == "10.1/a"
    assert Identifiers(arxiv="2301.01234", pmid="1").any_strong() == "2301.01234"
    assert Identifiers(pmid="1", openalex="W1").any_strong() == "1"
    assert Identifiers(openalex="W1").any_strong() == "W1"
    assert Identifiers(url="https://example.org").any_strong() is None


def test_dates_year_comes_from_published() -> None:
    assert Dates().year is None
    assert Dates(published=date(2023, 5, 1)).year == 2023


@pytest.mark.parametrize(
    "field, value",
    [
        ("run_id", "run_NOT-A-ULID"),
        ("run_id", f"qry_{SESSION}"),
        ("query_id", f"run_{SESSION}"),
        ("query_id", "qry_short"),
        ("raw_blob", "sha256:" + "A" * 64),
        ("raw_blob", "sha256:" + "a" * 63),
        ("raw_blob", "md5:" + "a" * 32),
    ],
)
def test_provenance_requires_platform_ids_and_blob(field: str, value: str) -> None:
    good: dict[str, object] = {
        "source": "openalex",
        "run_id": f"run_{SESSION}",
        "query_id": f"qry_{SESSION}",
        "at": "2026-10-31T12:00:00Z",
        "raw_blob": "sha256:" + "a" * 64,
    }
    good[field] = value
    with pytest.raises(ValidationError):
        Provenance.model_validate(good)


def test_provenance_rejects_naive_datetimes(prov: Provenance) -> None:
    data = prov.model_dump()
    data["at"] = "2026-10-31T12:00:00"
    with pytest.raises(ValidationError):
        Provenance.model_validate(data)


def test_provenance_method_defaults_to_database(prov: Provenance) -> None:
    assert prov.method == "database"


def test_sources_are_distinct_in_first_seen_order(prov: Provenance) -> None:
    w = Work.build(
        title="T",
        provenance=[
            prov.model_copy(update={"source": "openalex"}),
            prov.model_copy(update={"source": "arxiv"}),
            prov.model_copy(update={"source": "openalex"}),
        ],
    )
    assert w.sources == ["openalex", "arxiv"]


def test_round_trips_through_json(prov: Provenance) -> None:
    w = Work.build(
        title="Linear Attention",
        authors=[Author(name="Ada Zhou", orcid="0000-0002-1825-0097")],
        identifiers=Identifiers(doi="10.1/abc", arxiv="arXiv:2301.01234v2"),
        dates=Dates(published=None),
        subjects=["ml"],
        provenance=[prov],
    )
    assert Work.model_validate_json(w.model_dump_json()) == w


def test_work_models_strip_whitespace_and_forbid_extra(prov: Provenance) -> None:
    w = Work.build(title="  Padded Title  ", provenance=[prov])
    assert w.title == "Padded Title"
    with pytest.raises(ValidationError):
        Work.model_validate({**w.model_dump(), "unexpected": 1})


def test_work_is_frozen(prov: Provenance) -> None:
    w = Work.build(title="T", provenance=[prov])
    with pytest.raises(ValidationError):
        w.title = "changed"  # type: ignore[misc]


def test_peer_review_default() -> None:
    assert WorkType.JOURNAL_ARTICLE.is_peer_reviewed_by_default is True
    assert WorkType.PREPRINT.is_peer_reviewed_by_default is False
