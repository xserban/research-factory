import json
from pathlib import Path

import pytest

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.references.parse import (
    MAX_ENTRY_CHARS,
    PARSER,
    PARSER_VERSION,
    parse_bibliography,
    parse_entry_fields,
)
from tests.references_helpers import manifest

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "references" / "entries.json").read_text("utf-8")
)
ENTRIES = [
    "[1] A. One. First thing. 2001.",
    "[2] B. Two. Second thing. 2002.",
    "[3] C. Three. Third.",
]


def test_parser_identity() -> None:
    assert (PARSER, PARSER_VERSION) == ("refparse", "1")


def test_entries_from_b_anchors() -> None:
    bib = parse_bibliography(manifest(ENTRIES, ["x"]))
    assert [e.anchor for e in bib.entries] == ["b1", "b2", "b3"]
    assert [e.ordinal for e in bib.entries] == [1, 2, 3]
    assert [e.label for e in bib.entries] == ["1", "2", "3"]
    assert bib.entry_anchors == "b" and bib.flags == ()


def test_paragraph_fallback_flags() -> None:
    bib = parse_bibliography(manifest(ENTRIES, ["x"], b_anchors=False, heading="3 Bibliography"))
    assert "entry-anchors-paragraph" in bib.flags
    assert bib.entry_anchors == "paragraph"
    assert [e.anchor for e in bib.entries] == ["s2.p1", "s2.p2", "s2.p3"]


def test_no_bibliography_is_recorded() -> None:
    m = manifest([], ["x"], heading="Appendix")
    bib = parse_bibliography(m)
    assert bib.flags == ("no-bibliography",) and not bib.entries
    empty = parse_bibliography(Manifest(()))
    assert empty.flags == ("no-bibliography",)


def test_heading_with_no_paragraphs_is_no_bibliography() -> None:
    assert parse_bibliography(manifest([], ["x"], b_anchors=False)).flags == ("no-bibliography",)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["text"][:25])
def test_fields_on_hand_checked_entries(case: dict[str, object]) -> None:
    f = parse_entry_fields(str(case["text"]))
    assert (f.doi, f.arxiv, f.url, f.year) == (
        case["doi"],
        case["arxiv"],
        case["url"],
        case["year"],
    )
    assert (f.first_author, f.title, f.venue) == (
        case["first_author"],
        case["title"],
        case["venue"],
    )


def test_fields_doi_arxiv_year() -> None:
    f = parse_entry_fields(
        "[12] K. He et al. Deep residual learning. CVPR 2016. doi:10.1109/CVPR.2016.90."
    )
    assert (f.doi, f.year) == ("10.1109/cvpr.2016.90", 2016)
    g = parse_entry_fields(
        "A. Dosovitskiy. An image is worth 16x16 words. arXiv:2010.11929v2, 2020."
    )
    assert g.arxiv == "2010.11929"


def test_doi_keeps_balanced_parenthesis_and_drops_trailing_one() -> None:
    assert parse_entry_fields("X. Y. Z. doi:10.1000/abc(1)2.").doi == "10.1000/abc(1)2"
    assert parse_entry_fields("(see doi:10.1000/abc12)").doi == "10.1000/abc12"


def test_unparseable_text_yields_none() -> None:
    f = parse_entry_fields("???")
    assert (f.doi, f.arxiv, f.url, f.year, f.first_author, f.title, f.venue) == (None,) * 7


def test_truncation_flag_at_1000_chars() -> None:
    long = "[1] A. Author. " + "x" * 1100
    short = "[2] B. Author. Short."
    bib = parse_bibliography(manifest([long, short], ["x"]))
    first, second = bib.entries
    assert first.truncated and len(first.text) == MAX_ENTRY_CHARS
    assert not second.truncated


def test_whitespace_in_entry_text_is_collapsed() -> None:
    bib = parse_bibliography(manifest(["[1] A.  One.\n  Title here.  2001."], ["x"]))
    assert bib.entries[0].text == "[1] A. One. Title here. 2001."


def test_deterministic() -> None:
    m = manifest(ENTRIES, ["x"])
    assert parse_bibliography(m) == parse_bibliography(m)


def test_label_forms() -> None:
    bib = parse_bibliography(
        manifest(["(4) A. B. T. 2000.", "5. C. D. T. 2001.", "No label. 2002."], [])
    )
    assert [e.label for e in bib.entries] == ["4", "5", None]


def test_section_anchor_kind_only() -> None:
    m = Manifest((Anchor("s1", AnchorKind.PARAGRAPH, None, "References"),))
    assert parse_bibliography(m).flags == ("no-bibliography",)
