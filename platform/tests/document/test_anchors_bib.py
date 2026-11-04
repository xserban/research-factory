"""Bibliography entry anchors `b<n>`: grammar, manifest and anchoriser."""

import pytest

from factory.document.anchorise import BIBLIOGRAPHY_HEADINGS, anchorise, normalise_heading
from factory.document.anchors import AnchorKind, Manifest, ManifestError, parse_manifest

BIB = (
    '<a id="s9"></a>\n## 9 References\n\n<a id="b1"></a>\nSmith J. A title. 2020.\n\n'
    '<a id="b2"></a>\nLee K. Another. 2021.\n'
)


def test_b_anchor_parses() -> None:
    m = parse_manifest(BIB)
    assert [a.id for a in m.anchors if a.kind is AnchorKind.BIBLIOGRAPHY_ENTRY] == ["b1", "b2"]
    b1 = m.get("b1")
    assert b1 is not None and b1.parent == "s9" and b1.text == "Smith J. A title. 2020."


def test_b_anchor_must_precede_paragraph() -> None:
    with pytest.raises(ManifestError):
        parse_manifest('<a id="b1"></a>\n## Heading\n')


def test_b_anchor_must_be_sequential() -> None:
    gap = BIB.replace('"b2"', '"b3"')
    with pytest.raises(ManifestError):
        parse_manifest(gap)


def test_b_manifest_json_round_trip() -> None:
    m = parse_manifest(BIB)
    assert Manifest.from_json(m.to_json()) == m


def test_old_manifest_still_parses() -> None:
    old = (
        '<a id="s9"></a>\n## 9 References\n\n<a id="s9.p1"></a>\nSmith.\n\n'
        '<a id="s9.p2"></a>\nLee.\n'
    )
    assert parse_manifest(old).get("s9.p2") is not None


def test_anchoriser_numbers_bibliography_entries() -> None:
    out = anchorise(
        "# T\n\n## 1 Intro\n\nText.\n\n## References\n\nSmith J. A. 2020.\n\n"
        "Lee K. B. 2021.\n\n## A. Proofs\n\nProof.\n"
    )
    assert '<a id="b1"></a>\nSmith' in out and '<a id="b2"></a>\nLee' in out
    assert '<a id="s101.p1"></a>' in out
    assert anchorise(out) == out
    parse_manifest(out)


@pytest.mark.parametrize(
    "title", ["References", "5 Bibliography", "Literature Cited", "Works cited", "Reference list"]
)
def test_heading_variants(title: str) -> None:
    out = anchorise(f"# T\n\n## 1 Intro\n\nText.\n\n## {title}\n\nSmith.\n")
    assert '<a id="b1"></a>\nSmith.' in out
    assert anchorise(out) == out
    assert parse_manifest(out).get("b1") is not None


def test_non_bibliography_section_keeps_paragraph_anchors() -> None:
    out = anchorise("# T\n\n## 1 Intro\n\nText.\n\n## 2 Related Work\n\nPrior.\n")
    assert '<a id="s2.p1"></a>\nPrior.' in out and '<a id="b1"></a>' not in out


def test_references_as_only_top_heading_is_title_and_keeps_paragraph_anchors() -> None:
    out = anchorise("# References\n\nSmith J. A. 2020.\n\n## 1 Intro\n\nText.\n")
    assert '<a id="s0"></a>\n# References' in out
    assert '<a id="s0.p1"></a>\nSmith' in out and '<a id="b1"></a>' not in out


def test_subsection_paragraphs_are_not_entries() -> None:
    out = anchorise("# T\n\n## 1 References\n\nA.\n\n### 1.1 Notes\n\nB.\n\n## 2 Next\n\nC.\n")
    assert '<a id="b1"></a>\nA.' in out
    assert '<a id="s1.1.p1"></a>\nB.' in out and '<a id="s2.p1"></a>\nC.' in out


def test_numbering_is_document_wide() -> None:
    out = anchorise("# T\n\n## 1 References\n\nA.\n\n## 2 Bibliography\n\nB.\n")
    assert '<a id="b1"></a>\nA.' in out and '<a id="b2"></a>\nB.' in out


def test_headings_constant() -> None:
    expected = {"references", "bibliography", "literature cited", "works cited", "reference list"}
    assert set(BIBLIOGRAPHY_HEADINGS) == expected


def test_trailing_colon_heading_gets_b_anchors() -> None:
    out = anchorise("# Paper\n\n## 1 Intro\n\nText.\n\n## References:\n\nSmith J. A. 2020.\n")
    assert '<a id="b1"></a>' in out
    assert normalise_heading("References:") == "references"
    assert normalise_heading("A.1 Bibliography :") == "bibliography"
