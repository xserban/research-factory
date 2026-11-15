"""In-text citation links `[text](#b<k>)` from LaTeXML HTML (invented fixtures)."""

from factory.document.anchorise import anchorise
from factory.document.anchors import parse_manifest
from factory.document.latexml_html import CONVERTER_VERSION, LatexmlHtmlConverter
from factory.document.quotes import element_plain_text, quote_in_element


def _page(body: str) -> bytes:
    bib = (
        '<section class="ltx_bibliography"><h2 class="ltx_title">References</h2><ul>'
        '<li class="ltx_bibitem" id="bib.bib1"><span class="ltx_bibblock">Alpha A. One.</span></li>'
        '<li class="ltx_bibitem" id="bib.bib2"><span class="ltx_bibblock">Beta B. Two.</span></li>'
        "</ul></section>"
    )
    return f"<html><body><div class='ltx_page_content'>{body}{bib}</div></body></html>".encode()


def _md(body: str) -> str:
    return LatexmlHtmlConverter().to_markdown(_page(body), "text/html")[0]


def _cite(*targets: str) -> str:
    links = ", ".join(
        f'<a class="ltx_ref" href="#bib.{t}">{i + 1}</a>' for i, t in enumerate(targets)
    )
    return f'<cite class="ltx_cite">[{links}]</cite>'


def test_version() -> None:
    assert CONVERTER_VERSION == "1.3"


def test_cite_becomes_link_to_b_ordinal() -> None:
    md = _md(f'<p class="ltx_p">As shown in {_cite("bib2")} earlier.</p>')
    assert "[[1](#b2)]" in md
    one = '<span class="ltx_cite"><a class="ltx_ref" href="#bib.bib1">Alpha, 2020</a></span>'
    assert "[Alpha, 2020](#b1)" in _md(f'<p class="ltx_p">See {one}.</p>')


def test_cite_to_unknown_bibitem_is_plain_text() -> None:
    md = _md(f'<p class="ltx_p">See {_cite("bib9")} now.</p>')
    assert "(#b" not in md
    assert "See [1] now." in md


def test_two_cites_in_one_marker_each_linked() -> None:
    md = _md(f'<p class="ltx_p">See {_cite("bib1", "bib2")} now.</p>')
    assert "[[1](#b1), [2](#b2)]" in md


def test_link_text_is_escaped() -> None:
    html = '<span class="ltx_cite"><a class="ltx_ref" href="#bib.bib1">a]b\\c</a></span>'
    assert "[a\\]b\\\\c](#b1)" in _md(f'<p class="ltx_p">See {html}.</p>')


def test_links_do_not_change_verified_text() -> None:
    md = anchorise(_md(f'<p class="ltx_p">as shown in {_cite("bib1")} earlier</p>'))
    para = next(a for a in parse_manifest(md).anchors if "as shown" in a.text)
    assert element_plain_text(para.text) == "as shown in [1] earlier"
    assert quote_in_element(para.text, "as shown in [1] earlier")


def test_end_to_end_manifest_has_b_anchors() -> None:
    md = anchorise(_md(f'<p class="ltx_p">See {_cite("bib2")}.</p>'))
    manifest = parse_manifest(md)
    assert {"b1", "b2"} <= {a.id for a in manifest.anchors}
    assert "(#b2)" in md.split("References")[0]


def _md_bib(items: list[str], body: str, loose: str = "") -> str:
    lis = "".join(
        f'<li class="ltx_bibitem" id="bib.bib{i}">{x}</li>' for i, x in enumerate(items, 1)
    )
    page = (
        f"<html><body><div>{loose}<p class='ltx_p'>{body}</p>"
        f'<section class="ltx_bibliography"><h2 class="ltx_title">References</h2><ul>{lis}</ul>'
        "</section></div></body></html>"
    )
    return LatexmlHtmlConverter().to_markdown(page.encode(), "text/html")[0]


def _ordinal_for_third(middle: str) -> None:
    cite = '<cite class="ltx_cite"><a class="ltx_ref" href="#bib.bib3">g</a></cite>'
    md = _md_bib(["Alpha", middle, "Gamma"], cite)
    b2 = next(a for a in parse_manifest(anchorise(md)).anchors if a.id == "b2")
    assert b2.text == "Gamma"
    assert "[g](#b2)" in md


def test_script_only_bibitem_gets_no_ordinal() -> None:
    _ordinal_for_third("<script>x()</script>")


def test_image_only_bibitem_gets_no_ordinal() -> None:
    _ordinal_for_third('<img src="x.png"/>')


def test_empty_bibitem_before_linked_one() -> None:
    _ordinal_for_third("")


def test_loose_bibitem_outside_bibliography_not_counted() -> None:
    loose = '<ul><li class="ltx_bibitem" id="bib.loose">Loose</li></ul>'
    cite = '<cite class="ltx_cite"><a class="ltx_ref" href="#bib.loose">l</a></cite>'
    assert "(#b" not in _md_bib(["Alpha"], cite, loose)
