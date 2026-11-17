"""Import admission names a PubMed-only work by PMID (IDEA-76)."""

from __future__ import annotations

from datetime import date

from factory.model.work import Dates, Identifiers, Provenance, Work
from factory.services.import_admit import _ORDER, _PREFIX, _SEPARATOR, _SOURCE_KIND, _route
from tests.helpers import SESSION, T0

RUN_ID = f"run_{SESSION}"
QUERY_ID = f"qry_{SESSION}"


def _work(**ids: str) -> Work:
    return Work.build(
        title="A trial",
        authors=[],
        identifiers=Identifiers(**ids),
        dates=Dates(published=date(2020, 1, 1)),
        provenance=[
            Provenance(
                source="pubmed",
                run_id=RUN_ID,
                query_id=QUERY_ID,
                at=T0,
                raw_blob="sha256:" + "a" * 64,
            )
        ],
    )


def test_a_pmid_work_routes_to_a_pubmed_id_list() -> None:
    assert _route(_work(pmid="123")) == ("pmid", "123")
    assert _SOURCE_KIND["pmid"][0] == "pubmed"
    assert _PREFIX["pmid"] == "" and _SEPARATOR["pmid"] == ","
    assert "pmid" in _ORDER


def test_precedence_is_openalex_then_pmid_then_arxiv_then_doi() -> None:
    assert _route(_work(openalex="W1", pmid="2", arxiv="2001.00001", doi="10.1/x")) == (
        "openalex",
        "W1",
    )
    assert _route(_work(pmid="2", arxiv="2001.00001", doi="10.1/x")) == ("pmid", "2")
    assert _route(_work(arxiv="2001.00001", doi="10.1/x")) == ("arxiv", "2001.00001")
    assert _route(_work(doi="10.1/x")) == ("doi", "10.1/x")


def test_a_pmid_is_skipped_when_pubmed_is_not_a_registered_source() -> None:
    """An admission that went by DOI or arXiv before PMID routing is not refused for an unknown
    source: the next identifier names the work."""
    without = {"openalex", "arxiv"}
    assert _route(_work(pmid="2", doi="10.1/x"), without) == ("doi", "10.1/x")
    assert _route(_work(pmid="2", arxiv="2001.00001"), without) == ("arxiv", "2001.00001")
    assert _route(_work(pmid="2"), without) is None  # the caller falls back to the import list
    assert _route(_work(pmid="2", doi="10.1/x"), {"pubmed"}) == ("pmid", "2")
