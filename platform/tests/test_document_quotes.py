import pytest

from factory.document.quotes import (
    element_blocks,
    element_plain_text,
    normalise_quote,
    quote_in_element,
)

LIGATURE_FI = "\N{LATIN SMALL LIGATURE FI}"
NBSP = "\N{NO-BREAK SPACE}"
SOFT_HYPHEN = "\N{SOFT HYPHEN}"
ZWSP = "\N{ZERO WIDTH SPACE}"
ZWNJ = "\N{ZERO WIDTH NON-JOINER}"
ZWJ = "\N{ZERO WIDTH JOINER}"
WORD_JOINER = "\N{WORD JOINER}"
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"


def test_plain_text_strips_markup() -> None:
    markdown = "**bold** and \\_x\\_ [link](u) `c`"
    assert element_plain_text(markdown) == "bold and _x_ link c"


def test_plain_text_joins_block_texts_with_a_space() -> None:
    assert element_plain_text("# Title\n\nPara one.") == "Title Para one."


def test_plain_text_keeps_image_alt_text() -> None:
    assert element_plain_text("![a figure](f.png)") == "a figure"


def test_plain_text_maps_line_breaks_to_spaces() -> None:
    assert element_plain_text("alpha\nbeta  \ngamma") == "alpha beta gamma"


def test_plain_text_of_an_already_plain_cell_is_unchanged() -> None:
    cell = "x|y, cost 5 * 3 = 15"
    assert element_plain_text(cell) == cell


def test_normalise_folds_ligatures_nbsp_soft_hyphen_and_zero_width() -> None:
    raw = f"{LIGATURE_FI}ne{NBSP}d{SOFT_HYPHEN}{ZWSP}{ZWNJ} {WORD_JOINER}x{BOM}\ny "
    assert normalise_quote(raw) == "fine d x y"


def test_normalise_preserves_case() -> None:
    assert normalise_quote("  Alpha   BETA ") == "Alpha BETA"


def test_quote_matches_across_ligature_nbsp_softhyphen_linebreak() -> None:
    element = f"The {LIGATURE_FI}ne{NBSP}sof{SOFT_HYPHEN}t\nwork."
    assert quote_in_element(element, "fine soft work")


def test_quote_rejects_changed_word() -> None:
    assert not quote_in_element("The fine soft work.", "fine hard work")


def test_quote_rejects_empty_after_normalisation() -> None:
    assert not quote_in_element("Some text.", f"{SOFT_HYPHEN} {ZWSP} {NBSP}")


def test_quote_is_case_sensitive() -> None:
    assert not quote_in_element("Alpha beta", "alpha")
    assert quote_in_element("Alpha beta", "Alpha beta")


def test_quote_must_be_contiguous() -> None:
    assert not quote_in_element("alpha beta gamma", "alpha gamma")


@pytest.mark.parametrize("quote", ["cell", "x|y"])
def test_quote_in_plain_cell_text(quote: str) -> None:
    assert quote_in_element("x|y cell", quote)


TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"


@pytest.mark.parametrize("quote", ["a", "2", "1", "b"])
def test_quote_matches_a_single_table_cell(quote: str) -> None:
    assert quote_in_element(TABLE, quote)


@pytest.mark.parametrize("quote", ["b 1", "a b", "a b 1 2"])
def test_quote_never_spans_table_cells(quote: str) -> None:
    assert not quote_in_element(TABLE, quote)


def test_quote_never_spans_two_paragraphs() -> None:
    assert not quote_in_element("First paragraph.\n\nSecond paragraph.", "paragraph Second")
    assert quote_in_element("First paragraph.\n\nSecond paragraph.", "Second paragraph.")


def test_soft_break_within_one_paragraph_still_matches() -> None:
    assert quote_in_element("alpha beta\ngamma delta", "beta gamma")


def test_element_blocks_lists_each_block_separately() -> None:
    assert element_blocks("# Title\n\nPara one.") == ["Title", "Para one."]
    assert element_blocks(TABLE) == ["a", "b", "1", "2"]


def test_quote_with_markdown_escapes_as_served_is_found() -> None:
    markdown = "The team\\_size was 5 and a\\*b, see \\[1\\]."
    assert quote_in_element(markdown, "The team\\_size was 5 and a\\*b, see \\[1\\].")
    assert quote_in_element(markdown, "team_size was 5 and a*b, see [1].")  # unescaped form too


def test_escape_tolerance_does_not_loosen_the_match() -> None:
    markdown = "The team\\_size was 5."
    assert not quote_in_element(markdown, "The team size was 5.")  # a different character
    assert not quote_in_element(markdown, "The team\\ size was 5.")  # backslash before a space
    assert not quote_in_element(markdown, "THE TEAM_SIZE")  # still case-sensitive
    assert quote_in_element("a \\q b", "a \\q b")  # a backslash before a letter is literal


def test_literal_backslash_inside_code_is_dropped_too_accepted_behaviour() -> None:
    # The block text is flattened, so code and math tokens get the same rule as text: a quote
    # "a_b" verifies against the code span `a\_b`. Accepted (a small false accept, never a reject).
    assert quote_in_element("Use `a\\_b` here.", "a_b")
    assert quote_in_element("Use `a\\_b` here.", "a\\_b")
    assert quote_in_element("Use $a\\_b$ here.", "a_b")


def test_trailing_backslash_in_the_quote_is_kept() -> None:
    assert not quote_in_element("The team size was 5.", "The team size was 5.\\")
    assert quote_in_element("a b\\\\", "a b\\\\")


def test_backslash_before_space_letter_or_digit_stays() -> None:
    assert not quote_in_element("a q b", "a \\q b")
    assert not quote_in_element("a 1 b", "a \\1 b")
    assert not quote_in_element("a  b", "a \\ b")
    assert quote_in_element("a \\1 b", "a \\1 b")
