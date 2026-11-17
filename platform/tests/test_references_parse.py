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
    assert (PARSER, PARSER_VERSION) == ("refparse", "2")


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


def _timed(fn):  # type: ignore[no-untyped-def]
    import time

    t0 = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - t0


def test_long_sentence_entry_is_linear_time() -> None:
    text = "Word. " * 8000
    f, elapsed = _timed(lambda: parse_entry_fields(text))
    assert elapsed < 0.5 and f.year is None
    bib, elapsed = _timed(lambda: parse_bibliography(manifest([text], ["x"])))
    assert elapsed < 0.5 and bib.entries[0].truncated


@pytest.mark.parametrize(
    ("text", "author"),
    [
        ("Łukasiewicz, J. (1920). On three-valued logic. Ruch Filozoficzny.", "Łukasiewicz"),
        ("Émile, A. (2001). Title here. Venue.", "Émile"),
        ("Šimon, P. (1999). Title here. Venue.", "Šimon"),
        ("Ł. Kowalski. Title here. Venue, 2003.", "Kowalski"),
        ("Šimon P, Novak J. Title here. Venue. 2004;1:2.", "Šimon"),
    ],
)
def test_unicode_uppercase_surnames_and_initials(text: str, author: str) -> None:
    assert parse_entry_fields(text).first_author == author


def test_stray_digit_label_is_still_a_label() -> None:
    bib = parse_bibliography(manifest(["2018. Foo bar.", "Baz. Qux.", "Quux. Corge."], []))
    assert [e.label for e in bib.entries] == ["2018", None, None]


def test_last_year_wins() -> None:
    assert parse_entry_fields("Smith, J. (1999). Title. Journal, 2005.").year == 2005


def test_truncation_boundary_is_exactly_1000() -> None:
    exact = "A. " + "x" * (MAX_ENTRY_CHARS - 3)
    over = exact + "y"
    bib = parse_bibliography(manifest([exact, over], []))
    assert [(len(e.text), e.truncated) for e in bib.entries] == [(1000, False), (1000, True)]


def test_all_matching_sections_are_tried() -> None:
    m = manifest(["[1] A. T. 2001."], ["x"], b_anchors=False)
    # an earlier empty "References" heading must not hide a later one with paragraphs
    first = Anchor("s0", AnchorKind.SECTION, None, "## References")
    full = Manifest((first, *m.anchors))
    bib = parse_bibliography(full)
    assert [e.anchor for e in bib.entries] == ["s2.p1"]


def test_heading_without_entries_flag() -> None:
    bib = parse_bibliography(manifest([], ["x"], b_anchors=False))
    assert bib.flags == ("bibliography-without-entries",) and not bib.entries


def test_heading_with_trailing_colon_is_a_bibliography() -> None:
    bib = parse_bibliography(manifest(ENTRIES, ["x"], b_anchors=False, heading="References:"))
    assert bib.entry_anchors == "paragraph" and len(bib.entries) == 3


def test_real_anchorise_output() -> None:
    from factory.document.anchorise import anchorise
    from factory.document.anchors import parse_manifest

    md = (
        "# Paper\n\n## 1 Intro\n\nSee [1].\n\n## References\n\n"
        "One, A. (2001). First. Venue.\n\nTwo, B. (2002). Second. Venue.\n"
    )
    bib = parse_bibliography(parse_manifest(anchorise(md)))
    assert bib.entry_anchors == "b" and [e.anchor for e in bib.entries] == ["b1", "b2"]
    assert bib.entries[1].fields.first_author == "Two"


def test_b_entries_selected_by_kind_not_id_shape() -> None:
    m = Manifest(
        (
            Anchor("b1", AnchorKind.PARAGRAPH, None, "body paragraph with an odd id"),
            Anchor("s2", AnchorKind.SECTION, None, "## References"),
            Anchor("b2", AnchorKind.BIBLIOGRAPHY_ENTRY, "s2", "Real, A. (2001). T. V."),
        )
    )
    assert [e.anchor for e in parse_bibliography(m).entries] == ["b2"]
