"""Markdown metacharacters in LaTeXML text render literally (invented fixtures)."""

import pytest

from factory.document.latexml_html import CONVERTER_VERSION, LatexmlHtmlConverter
from factory.document.quotes import element_plain_text, quote_in_element


def _md(body: str) -> str:
    page = f"<html><body><div class='ltx_page_content'>{body}</div></body></html>".encode()
    return LatexmlHtmlConverter().to_markdown(page, "text/html")[0]


@pytest.mark.parametrize(
    "raw",
    [
        "a*b*c",
        "snake_case_name",
        "use `fast` mode",
        "x ~~y~~ z",
        "2*3 = 6 and 3*4 = 12",
        "*lead* x",
    ],
)
def test_text_with_markdown_metacharacters_renders_literally(raw: str) -> None:
    assert element_plain_text(_md(f'<p class="ltx_p">{raw}</p>')) == raw


def test_math_alttext_is_unchanged_by_the_new_escapes() -> None:
    md = _md('<p class="ltx_p">see <math alttext="a_1 * b_2"></math> ok</p>')
    assert "$a_1 * b_2$" in md


def test_converter_version_is_1_3() -> None:
    assert CONVERTER_VERSION == "1.3"


def test_quote_with_asterisk_verifies_against_converted_paragraph() -> None:
    md = _md('<p class="ltx_p">a*b*c and snake_case_name</p>')
    assert quote_in_element(md, "a*b*c")
    assert quote_in_element(md, "snake_case_name")
