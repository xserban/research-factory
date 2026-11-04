"""Link parsing at the inbox boundary (slice 4a ruling 5)."""

from __future__ import annotations

import pytest

from factory.inbox.links import MAX_LINK, IdentifierKind, LinkIdentifier, parse_link

ARXIV = IdentifierKind.ARXIV
DOI = IdentifierKind.DOI
OPENALEX = IdentifierKind.OPENALEX


@pytest.mark.parametrize(
    ("link", "kind", "value", "version"),
    [
        ("2103.14030", ARXIV, "2103.14030", None),
        ("arXiv:2103.14030v3", ARXIV, "2103.14030", "v3"),
        ("https://arxiv.org/abs/2103.14030v2", ARXIV, "2103.14030", "v2"),
        ("https://arxiv.org/pdf/2103.14030v1.pdf", ARXIV, "2103.14030", "v1"),
        ("https://arxiv.org/pdf/2103.14030", ARXIV, "2103.14030", None),
        ("arxiv.org/html/2103.14030", ARXIV, "2103.14030", None),
        ("https://export.arxiv.org/abs/2103.14030?context=cs#x", ARXIV, "2103.14030", None),
        ("https://arxiv.org/abs/hep-th/9901001v2", ARXIV, "hep-th/9901001", "v2"),
        ("10.1109/ICCV48922.2021.00986", DOI, "10.1109/iccv48922.2021.00986", None),
        ("doi:10.1109/ICCV48922.2021.00986", DOI, "10.1109/iccv48922.2021.00986", None),
        (
            "https://doi.org/10.1109/ICCV48922.2021.00986",
            DOI,
            "10.1109/iccv48922.2021.00986",
            None,
        ),
        ("https://dx.doi.org/10.1145/3292500.3330701", DOI, "10.1145/3292500.3330701", None),
        ("https://openaccess.thecvf.com/x/10.1109/ICCV.2021.1", DOI, "10.1109/iccv.2021.1", None),
        (
            "https://dl.acm.org/doi/10.1145/3292500.3330701?x=1",
            DOI,
            "10.1145/3292500.3330701",
            None,
        ),
        ("https://doi.org/10.48550/arXiv.2103.14030", ARXIV, "2103.14030", None),
        ("10.48550/arXiv.2103.14030", ARXIV, "2103.14030", None),
        ("https://openalex.org/W3138516171", OPENALEX, "W3138516171", None),
        ("https://api.openalex.org/works/w3138516171", OPENALEX, "W3138516171", None),
        ("W3138516171", OPENALEX, "W3138516171", None),
    ],
)
def test_parse_supported(link: str, kind: IdentifierKind, value: str, version: str | None) -> None:
    assert parse_link(link) == LinkIdentifier(kind=kind, value=value, version=version)


@pytest.mark.parametrize(
    "link",
    [
        "https://example.org/paper",
        "",
        "  ",
        "not a link",
        "x" * (MAX_LINK + 1),
        "https://arxiv.org/abs/" + "1" * 600,
        "https://openalex.org/A123",
        "2103.140",
        "10.12/abc",
        "https://arxiv.org/list/cs.LG/recent",
    ],
)
def test_parse_unsupported(link: str) -> None:
    assert parse_link(link) is None


def test_parse_is_whitespace_tolerant() -> None:
    expected = LinkIdentifier(kind=ARXIV, value="2103.14030", version="v2")
    assert parse_link("  https://arxiv.org/abs/2103.14030v2 \n") == expected
    assert parse_link("\t2103.14030v2") == expected


def test_max_link_is_500() -> None:
    assert MAX_LINK == 500
    assert parse_link("https://doi.org/10.1000/" + "a" * (MAX_LINK - 24)) is not None
