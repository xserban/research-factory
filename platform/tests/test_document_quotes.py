import pytest

from factory.document.quotes import element_plain_text, normalise_quote, quote_in_element

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
