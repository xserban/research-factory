"""Tests for the anchoriser: numbering, captions, equations, pages and idempotence."""

import string

import pytest

from factory.document.anchorise import _APPENDIX_LETTER, _APPENDIX_SUB, anchorise
from factory.document.anchors import AnchorKind, parse_manifest

TITLE_DOC = "# Paper Title\n\nAbstract text.\n\n## 1 Intro\n\nBody.\n"
PAGE_DOC = "# 1 Intro\n\nPage one.\n\f\nPage two.\n"
CAPTION_DOC = "Table 1: Results.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter.\n"
MATH_DOC = "# 1\n\n$$\nx = 1\n$$\n\nAfter.\n\n$$y^2$$\n"
LIST_DOC = "# 1 Intro\n\n- one\n- two\n\n> quoted\n\n```\ncode\n```\n\nPara after.\n"

SAMPLES = [
    "# 1 Intro\n\nText here.\n\n## 1.2 Detail\n\nMore.\n",
    "# 1 Intro\n\n## Background\n\n## Scope\n\n## 1.2 Odd\n\n# 2 A\n\n# Notes\n\n# 2 B\n",
    TITLE_DOC,
    "# 1 Main\n\n# A. Proofs\n\n## A.1 Lemma\n\nText.\n\n# B) Data\n\nMore.\n",
    "# 1\n\nOne.\n\nTwo.\n\n## 1.1\n\nThree.\n\n# 2\n\nFour.\n",
    "Preamble one.\n\nPreamble two.\n\n# 1 Intro\n\nBody.\n",
    CAPTION_DOC,
    "# 1 Intro\n\nFigure 3: A plot.\n\nFig. 7 another.\n\nFigure 3: duplicate.\n\nText.\n",
    MATH_DOC,
    PAGE_DOC,
    '<a id="s9"></a>\n# 1 Intro\n\n<a id="p7"></a>\n\n<a id="s1.p5"></a>\nText.\n',
    LIST_DOC,
    "| a | b |\n|---|---|\n| 1 |\n\nAfter ragged.\n",
    "Intro\n=====\n\nText.\n",
    "$$\na\n\nb\n$$\n\n$$\nx\n=\n$$\n",
    "# 1\n\n| a |\n|---|\n| 1 |\n\nTable 2 caption above.\n\n| b |\n|---|\n| 2 |\n",
    "# A\n\n```\n$$\n```\n\n$$x$$ inline $$y$$\n",
    "# 1\n\n<!-- c -->\n\n```python\n$$\n```\n\n$$\nq\n\n```\n",
    "===\nfoo\n",
    '- a\n  <a id="s1"></a>\n- b\n',
    "text\n\f\n```\n\f\n```\n",
    "$$\n# 2 Heading\nz$$\n",
    "$$a$$ and $$b$$\n",
    "Table 1 first\n\nTable 2\n\n| a |\n|---|\n| 1 |\n\nTable 3 after\n",
    '> q\n> <a id="s1"></a>\n# 1\n',
    "",
]


def _ids(md: str) -> list[str]:
    return [a.id for a in parse_manifest(anchorise(md)).anchors]


def test_numbered_headings_give_section_paths() -> None:
    md = "# 1 Intro\n\n## 1.2 Detail\n\n### 1.2.1 Deep\n\n## 2 Method\n"
    assert _ids(md) == ["s1", "s1.2", "s1.2.1", "s2"]
    m = parse_manifest(anchorise(md))
    deep = m.get("s1.2.1")
    assert deep is not None and deep.parent == "s1.2"
    detail = m.get("s1.2")
    assert detail is not None and detail.parent == "s1"
    top = m.get("s2")
    assert top is not None and top.parent is None


def test_unnumbered_and_duplicate_headings() -> None:
    md = "# 1 Intro\n\n## Background\n\n## Scope\n\n## 1.2 Odd\n\n# 2 A\n\n# Notes\n\n# 2 B\n"
    # Background and Scope take the next ordinals under s1; the later 1.2 collides and gets .2;
    # Notes takes the next top-level ordinal (3); the later 2 collides and gets .2.
    assert _ids(md) == ["s1", "s1.1", "s1.2", "s1.2.2", "s2", "s3", "s2.2"]


def test_title_heading_is_s0() -> None:
    assert _ids(TITLE_DOC) == ["s0", "s0.p1", "s1", "s1.p1"]
    assert '<a id="s0"></a>\n# Paper Title' in anchorise(TITLE_DOC)


def test_appendix_letters() -> None:
    md = "# 1 Main\n\n# A. Proofs\n\n## A.1 Lemma\n\nText.\n\n# B: Data\n\nMore.\n"
    assert _ids(md) == ["s1", "s101", "s101.1", "s101.1.p1", "s102", "s102.p1"]
    lemma = parse_manifest(anchorise(md)).get("s101.1")
    assert lemma is not None and lemma.parent == "s101"


def test_appendix_forms_per_ruling_f() -> None:
    # Letter then "." ":" or ")" then whitespace, letter.digits, or the letter alone.
    assert _ids("# 1 Main\n\n# A\n") == ["s1", "s101"]
    assert _ids("# 1 Main\n\n# A.1.2 Setup\n") == ["s1", "s101.1.2"]
    assert _ids("# 1 Main\n\n# C) Notes\n") == ["s1", "s103"]


def test_roman_numeral_headings_are_unnumbered() -> None:
    # Roman numerals are not recognised (Ruling G): I, V and X are not appendix letters, so these
    # headings take ordinals under s1 rather than s101.
    md = (
        "# 1 Main\n\n## I. INTRODUCTION\n\nText.\n\n"
        "## II. METHODS\n\nMore.\n\n## V. RESULTS\n\nEnd.\n\n## X. RESULTS\n\nLast.\n"
    )
    assert _ids(md) == [
        "s1",
        "s1.1",
        "s1.1.p1",
        "s1.2",
        "s1.2.p1",
        "s1.3",
        "s1.3.p1",
        "s1.4",
        "s1.4.p1",
    ]
    assert "s101" not in anchorise(md)


def test_appendix_letter_classes_exclude_exactly_i_v_x() -> None:
    # Ruling G: the appendix letter classes match every capital except the roman numerals I, V, X.
    for letter in string.ascii_uppercase:
        expected = letter not in "IVX"
        assert (_APPENDIX_LETTER.match(f"{letter}.") is not None) is expected, letter
        assert (_APPENDIX_SUB.match(f"{letter}.1") is not None) is expected, letter


def test_appendix_letter_at_level_two_is_s101() -> None:
    md = "# 1 Main\n\n## A. Proofs\n\nText.\n"
    assert _ids(md) == ["s1", "s101", "s101.p1"]


def test_bare_capital_word_is_not_an_appendix() -> None:
    # "A Note on X" is an unnumbered heading: it takes the next ordinal under s1, never s101.
    md = "# 1 Intro\n\n## A Note on X\n\nText.\n"
    assert _ids(md) == ["s1", "s1.1", "s1.1.p1"]
    assert "s101" not in anchorise(md)


def test_sole_appendix_looking_title_is_s0() -> None:
    # "A Survey of Methods" is a title (the only minimum-depth heading, unnumbered), not appendix A.
    md = "# A Survey of Methods\n\nAbstract.\n\n## 1 Intro\n\nBody.\n"
    assert _ids(md) == ["s0", "s0.p1", "s1", "s1.p1"]
    assert "s101" not in anchorise(md)


def test_paragraphs_numbered_per_section() -> None:
    md = "# 1\n\nOne.\n\nTwo.\n\n## 1.1\n\nThree.\n\n# 2\n\nFour.\n"
    assert _ids(md) == ["s1", "s1.p1", "s1.p2", "s1.1", "s1.1.p1", "s2", "s2.p1"]


def test_preamble_paragraphs_under_s0() -> None:
    m = parse_manifest(anchorise(SAMPLES[5]))
    first = m.get("s0.p1")
    assert first is not None and first.parent == "s0"
    assert m.get("s0.p2") is not None
    assert m.get("s1.p1") is not None


def test_table_caption_attached() -> None:
    assert anchorise(CAPTION_DOC) == (
        '<a id="t1"></a>\n| a | b |\n|---|---|\n| 1 | 2 |\n\n'
        'Table 1: Results.\n\n<a id="s0.p1"></a>\nAfter.\n'
    )
    assert _ids(CAPTION_DOC) == [
        "t1",
        "t1.r1.c1",
        "t1.r1.c2",
        "t1.r2.c1",
        "t1.r2.c2",
        "s0.p1",
    ]


def test_figure_caption_anchor_uses_text_number() -> None:
    md = SAMPLES[7]
    assert _ids(md) == ["s1", "f3.cap", "f7.cap", "f4.cap", "s1.p1"]
    m = parse_manifest(anchorise(md))
    caption = m.get("f7.cap")
    assert caption is not None and caption.kind is AnchorKind.FIGURE_CAPTION
    assert caption.text == "Fig. 7 another."


def test_display_math_equation_anchor() -> None:
    out = anchorise(MATH_DOC)
    assert '<a id="e1"></a>\n$$\nx = 1\n$$' in out
    m = parse_manifest(out)
    equation = m.get("e1")
    assert equation is not None and equation.kind is AnchorKind.EQUATION
    assert equation.text == "$$\nx = 1\n$$"
    assert m.get("e2") is not None
    assert m.get("s1.p1") is not None  # equations do not consume paragraph numbers


def test_math_with_blank_line_or_rule_line_is_not_an_equation() -> None:
    blank = anchorise("$$\na\n\nb\n$$\n")
    assert "e1" not in _ids("$$\na\n\nb\n$$\n")
    assert "$$\na\n\n" in blank
    rule = anchorise("$$\nx\n=\n$$\n")
    assert "e1" not in _ids("$$\nx\n=\n$$\n")
    assert "$$\nx\n=\n$$" in rule


def test_form_feed_page_anchor() -> None:
    assert _ids(PAGE_DOC) == ["s1", "s1.p1", "p1", "s1.p2"]
    page = parse_manifest(anchorise(PAGE_DOC)).get("p1")
    assert page is not None and page.kind is AnchorKind.PAGE
    assert '<a id="p1"></a>' in anchorise(PAGE_DOC)


def test_existing_anchors_replaced() -> None:
    md = '<a id="s9"></a>\n# 1 Intro\n\n<a id="p7"></a>\n\n<a id="s1.p5"></a>\nText.\n'
    out = anchorise(md)
    assert _ids(md) == ["s1", "p1", "s1.p1"]
    assert 's9"' not in out and "p7" not in out and "s1.p5" not in out


def test_list_items_anchored_blockquote_and_code_left_alone() -> None:
    out = anchorise(LIST_DOC)
    assert _ids(LIST_DOC) == ["s1", "s1.p1", "s1.p2", "s1.p3"]
    assert '<a id="s1.p1"></a>\none\n' in out and '<a id="s1.p2"></a>\ntwo\n' in out
    assert "> quoted" in out
    assert "```\ncode\n```" in out
    assert parse_manifest(out).get("s1.p3") is not None


def test_ragged_table_left_unanchored() -> None:
    md = "| a | b |\n|---|---|\n| 1 |\n\nAfter ragged.\n"
    assert _ids(md) == ["s0.p1"]


def test_setext_heading_becomes_atx() -> None:
    assert anchorise("Intro\n=====\n\nText.\n") == (
        '<a id="s1"></a>\n# Intro\n\n<a id="s1.p1"></a>\nText.\n'
    )


def test_caption_runs_move_once() -> None:
    # The table claims the caption run on both sides; the captions follow it in document order.
    md = "Table 1 first\n\nTable 2\n\n| a |\n|---|\n| 1 |\n\nTable 3 after\n"
    once = anchorise(md)
    assert once == (
        '<a id="t1"></a>\n| a |\n|---|\n| 1 |\n\nTable 1 first\n\nTable 2\n\nTable 3 after\n'
    )
    assert anchorise(once) == once


def test_form_feed_inside_code_fence_is_not_a_page_break() -> None:
    md = "# 1\n\n```\na\n\f\nb\n```\n\nAfter.\n"
    out = anchorise(md)
    assert "\x00" not in out
    assert _ids(md) == ["s1", "s1.p1"]
    assert anchorise(out) == out


def test_idempotent() -> None:
    for sample in SAMPLES:
        once = anchorise(sample)
        assert anchorise(once) == once, sample


def test_parse_manifest_never_raises_over_samples() -> None:
    for sample in SAMPLES:
        parse_manifest(anchorise(sample))


def test_version_1_leaves_lists_unanchored() -> None:
    out = anchorise(LIST_DOC, version=1)
    assert "- one\n- two" in out
    assert [a.id for a in parse_manifest(out).anchors] == ["s1", "s1.p1"]
    assert anchorise(out, version=1) == out


def test_unknown_version_refused() -> None:
    with pytest.raises(ValueError):
        anchorise("x\n", version=3)


def test_nested_items_belong_to_the_parent_and_ordered_items_keep_numbers() -> None:
    md = "# 1 A\n\n- parent\n  - child\n\n3. third\n4. fourth\n"
    m = parse_manifest(anchorise(md))
    assert [(a.id, a.text) for a in m.anchors[1:]] == [
        ("s1.p1", "parent child"),
        ("s1.p2", "[3] third"),
        ("s1.p3", "[4] fourth"),
    ]


def test_list_with_code_stays_unanchored() -> None:
    md = "# 1 A\n\n- a\n\n  ```\n  x\n  ```\n- b\n"
    assert _ids(md) == ["s1"]


def test_bibliography_list_items_become_entries() -> None:
    md = (
        "# 1 A\n\nText.\n\n# References\n\n"
        "1. Smith, J. A paper title (2020).\n2. Jones, K. Other (2021).\n"
    )
    m = parse_manifest(anchorise(md))
    entries = [a for a in m.anchors if a.kind is AnchorKind.BIBLIOGRAPHY_ENTRY]
    assert [(a.id, a.text) for a in entries] == [
        ("b1", "[1] Smith, J. A paper title (2020)."),
        ("b2", "[2] Jones, K. Other (2021)."),
    ]


RUN = (
    "# 1 A\n\n# References\n\n1. Guan, Y. et al. Drug repurposing (2025). "
    "2. Penades, J. R. et al. AI mirrors Cell 188(23), 6654-6665 (2025). "
    "3. Third, A. Something long enough (2020).\n"
)


def test_inline_numbered_run_is_split() -> None:
    out = anchorise(RUN)
    texts = [a.text for a in parse_manifest(out).anchors if a.id.startswith("b")]
    assert [t[:4] for t in texts] == ["[1] ", "[2] ", "[3] "]
    assert texts[1].startswith("[2] Penades")
    assert anchorise(out) == out


def test_run_with_gap_or_short_part_is_not_split() -> None:
    gap = RUN.replace("2. Penades", "5. Penades")
    assert [a.id for a in parse_manifest(anchorise(gap)).anchors if a.id.startswith("b")] == ["b1"]
    short = "# R\n\n# References\n\n1. Guan, Y. et al. Drug repurposing (2025). 2. Tiny.\n"
    assert [a.id for a in parse_manifest(anchorise(short)).anchors if a.id.startswith("b")] == [
        "b1"
    ]


def _bib(md: str) -> list[str]:
    return [a.text for a in parse_manifest(anchorise(md)).anchors if a.id.startswith("b")]


KNUTH = "1. Knuth, D. The Art of Computer Programming, Vol. 2. Addison-Wesley, Reading, 1981."


def test_abbreviation_before_a_number_is_not_a_split() -> None:
    only = f"# R\n\n# References\n\n{KNUTH}\n"
    assert _bib(only) == [f"[1] {KNUTH[3:]}"]
    paragraph = f"# R\n\n# References\n\n[1] {KNUTH[3:]}\n"
    assert _bib(paragraph) == [f"[1] {KNUTH[3:]}"]
    for word in ("Vols.", "Part", "Ed.", "No.", "pp.", "Ser", "X."):
        md = f"# R\n\n# References\n\n[1] Some long enough title, {word} 2. Another long entry.\n"
        assert len(_bib(md)) == 1, word


def test_a_list_item_followed_by_another_item_is_not_split() -> None:
    md = (
        "# R\n\n# References\n\n1. Guan, Y. et al. Drug repurposing (2025). "
        "2. Penades, J. et al. AI Cell (2025).\n2. Smith, A. A second real entry (2020).\n"
    )
    assert [t[:4] for t in _bib(md)] == ["[1] ", "[2] "]
    assert _bib(md)[1].startswith("[2] Smith")


def test_a_kept_list_item_stays_kept_when_re_anchored() -> None:
    """Fixed point: once the list items are paragraphs, a second pass must not split the first
    one (the next entry still holds label 2)."""
    md = (
        "# R\n\n# References\n\n1. Guan, Y. et al. Drug repurposing (2025). "
        "2. Penades, J. et al. AI Cell (2025).\n2. Smith, A. A second real entry (2020).\n"
    )
    once = anchorise(md)
    assert anchorise(once) == once


def test_a_label_already_used_is_not_repeated() -> None:
    md = (
        "# R\n\n# References\n\n[2] Smith, A. A second real entry (2020).\n\n"
        "[1] Guan, Y. et al. Drug repurposing (2025). 2. Penades, J. et al. AI Cell (2025).\n"
    )
    labels = [t[:3] for t in _bib(md)]
    assert labels == ["[2]", "[1]"]


def test_three_item_run_in_the_only_item_is_split() -> None:
    md = (
        "# R\n\n# References\n\n1. Guan, Y. et al. AI-Assisted Drug Re-Purposing for Human "
        "Liver Fibrosis. Adv Sci (Weinh) e08751 (2025). 2. Penad\u00e9s, J. R. et al. AI mirrors "
        "experimental science. Cell 188(23), 6654\u20136665 (2025). 3. Smith, A. Another paper "
        "title here. Nature 1, 2 (2024).\n"
    )
    assert [t[:4] for t in _bib(md)] == ["[1] ", "[2] ", "[3] "]


def test_split_continues_the_count() -> None:
    md = (
        "# R\n\n# References\n\n[4] Guan, Y. et al. Drug repurposing (2025). "
        "5. Penades, J. et al. AI Cell (2025).\n"
    )
    texts = [a.text for a in parse_manifest(anchorise(md)).anchors if a.id.startswith("b")]
    assert [t[:3] for t in texts] == ["[4]", "[5]"]


@pytest.mark.parametrize("sample", [*SAMPLES, RUN])
def test_stripping_and_reanchoring_reproduces_each_version(sample: str) -> None:
    """A stored blob is a fixed point of the rules it was made under (re-anchor soundness)."""
    for version in (1, 2):
        stored = anchorise(sample, version=version)
        assert anchorise(stored, version=version) == stored
