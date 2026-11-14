"""PubMed is a registered default source: kinds, interface line, probe kinds, window filter."""

from factory.model.search import QueryKind
from factory.sources.registry import INTERFACES, default_sources, window_filter_sources


def test_default_sources_has_pubmed() -> None:
    factory = default_sources()["pubmed"]
    assert factory.kinds == {QueryKind.KEYWORD, QueryKind.ID_LIST}
    assert factory.probe_kinds == {QueryKind.KEYWORD}
    assert "pubmed" not in window_filter_sources()


def test_interface_line_names_eutils() -> None:
    assert "E-utilities" in INTERFACES["pubmed"]
