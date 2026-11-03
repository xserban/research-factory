"""Tests for the LaTeXML HTML converter on small synthetic fixtures in LaTeXML class names."""

import re
from pathlib import Path

from factory.document.anchors import AnchorKind
from factory.document.converter import convert
from factory.document.latexml_html import LatexmlHtmlConverter
from tests.document.kit import assert_converter_contract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "document"
ARTICLE = (FIXTURES / "latexml_article.html").read_bytes()
APPENDIX = (FIXTURES / "latexml_appendix.html").read_bytes()
ANCHOR_LINE = re.compile(r'<a id="[^"]+"></a>')


def _all_fixtures() -> list[tuple[bytes, str]]:
    paths = sorted(FIXTURES.glob("latexml_*.html"))
    assert paths, "no LaTeXML fixtures found"
    return [(path.read_bytes(), "text/html") for path in paths]


def _markdown(raw: bytes) -> str:
    markdown, _ = LatexmlHtmlConverter().to_markdown(raw, "text/html")
    return markdown


def test_contract() -> None:
    assert_converter_contract(LatexmlHtmlConverter(), _all_fixtures())


def test_convert_gives_valid_manifest_for_every_fixture() -> None:
    for raw, media_type in _all_fixtures():
        result = convert(LatexmlHtmlConverter(), raw, media_type)
        assert result.manifest.anchors, "manifest should not be empty"
        assert result.markdown_hash.startswith("sha256:")


def test_sections_keep_numbers() -> None:
    markdown = _markdown(ARTICLE)
    assert markdown.startswith("# Lorem ipsum dolor sit amet\n")
    assert "\n## 1 Introduction\n" in markdown
    assert "\n## 3 Method\n" in markdown
    assert "\n### 3.2 Setup\n" in markdown


def test_inline_and_display_math_use_alttext() -> None:
    markdown = _markdown(ARTICLE)
    assert "the ratio $x &lt; y$ holds" in markdown
    assert "$$E=mc^{2}$$" in markdown


def test_table_to_gfm_with_caption() -> None:
    markdown = _markdown(ARTICLE)
    expected = (
        "Table 1: Lorem table caption.\n"
        "\n"
        "| Item | Measure |  |\n"
        "| --- | --- | --- |\n"
        "|  | Low | High |\n"
        "| Lorem | 1 | 2 |\n"
        "| a \\| b | Spanning |  |\n"
    )
    assert expected in markdown


def test_colspan_rowspan_rectangular() -> None:
    markdown = _markdown(ARTICLE)
    rows = [line for line in markdown.splitlines() if line.startswith("|")]
    assert len(rows) == 5  # header, delimiter, three body rows
    for row in rows:
        cells = re.split(r"(?<!\\)\|", row.strip()[1:-1])
        assert len(cells) == 3, row
    spanning = rows[-1]
    assert spanning == "| a \\| b | Spanning |  |"


def test_ragged_table_is_padded_with_warning() -> None:
    _, warnings = LatexmlHtmlConverter().to_markdown(APPENDIX, "text/html")
    assert warnings == ("table 1: ragged rows padded",)
    assert "| d | e |  |" in _markdown(APPENDIX)


def test_bibliography_items_are_paragraphs() -> None:
    markdown = _markdown(ARTICLE)
    assert "## References" in markdown
    assert "1\\. Smith, A. Lorem ipsum. Journal." in markdown
    assert "[2] Jones, B. Dolor sit amet." in markdown
    for line in markdown.splitlines():
        assert not re.match(r"^\s*(\d+\.|[-+*]) ", line), line


def test_footnote_follows_its_section() -> None:
    markdown = _markdown(ARTICLE)
    assert "holds.[^1]" in markdown
    note = markdown.index("[^1] Dolor footnote text.")
    assert markdown.index("## 1 Introduction") < note < markdown.index("## 2 Related work")


def test_no_raw_html_in_output() -> None:
    assert "<" not in _markdown(ARTICLE)
    assert "<" not in _markdown(APPENDIX)
    for raw, media_type in _all_fixtures():
        markdown = convert(LatexmlHtmlConverter(), raw, media_type).markdown
        for line in markdown.splitlines():
            if "<" in line:
                assert ANCHOR_LINE.fullmatch(line), line


def test_appendix_letter_heading_anchors_to_s101() -> None:
    result = convert(LatexmlHtmlConverter(), APPENDIX, "text/html")
    assert "## A. Proofs" in result.markdown
    assert "### A.1 Lemma" in result.markdown
    anchor = result.manifest.get("s101")
    assert anchor is not None
    assert anchor.kind == AnchorKind.SECTION
    assert anchor.text == "## A. Proofs"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_no_text_is_lost_in_unrecognised_containers() -> None:
    markdown = _markdown(_fixture("latexml_blocks.html"))
    for marker in (
        "PREWORD",
        "DTWORD",
        "DDWORD",
        "LISTWORD",
        "BAREWORD",
        "SPANWORD",
        "TAILWORD",
        "ALGCAP",
        "ALGLINE",
        "LISTCAP",
        "LISTFLOAT",
    ):
        assert marker in markdown, marker
    assert "Algorithm 1: ALGCAP caption text" in markdown
    assert "Float 1: LISTCAP untagged listing" in markdown
    assert "```" not in markdown
    assert "EQNUM" not in markdown  # equation numbers carry no content and are dropped


def test_nested_float_caption_emitted_once() -> None:
    markdown = _markdown(_fixture("latexml_nested.html"))
    assert markdown.count("Lorem outer caption.") == 1
    assert markdown.count("Lorem sub alpha.") == 1
    assert markdown.count("Lorem sub beta.") == 1
    assert "Figure 2: Lorem outer caption." in markdown
    assert "Figure (a): Lorem sub alpha." in markdown


def test_dollar_in_alttext_is_escaped() -> None:
    markdown = _markdown(_fixture("latexml_blocks.html"))
    assert "$x\\$y$" in markdown
    assert "$$u\\$v$$" in markdown


def test_hostile_spans_are_clamped() -> None:
    _, warnings = LatexmlHtmlConverter().to_markdown(_fixture("latexml_span_cap.html"), "text/html")
    assert "table 1: span clamped" in warnings


def test_section_tag_with_markup_is_not_emitted() -> None:
    markdown = _markdown(_fixture("latexml_bad_tag.html"))
    assert "## Lorem title" in markdown
    assert "<" not in markdown
    assert "&lt;b" not in markdown
