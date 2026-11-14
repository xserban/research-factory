"""The paper side panel: shared CSS/JS, its insertion, the explorer's panel mode, and the product
pages that open it (citations first)."""

from __future__ import annotations

import re

from factory.services import site
from factory.services.citations import Candidate, CitationReport, WorkCitations
from factory.services.site_citations import render_citations
from factory.services.site_explorer_page import PAGE as EXPLORER_PAGE
from factory.services.site_panel import PANEL_CSS, PANEL_JS, with_panel

_FULL = "<!doctype html><html><head><title>t</title></head><body><p>x</p></body></html>"


def test_with_panel_inserts_css_and_js_once() -> None:
    doc = with_panel(_FULL)
    assert PANEL_CSS in doc and PANEL_JS in doc
    assert doc.index(PANEL_CSS) < doc.index("</head>")
    assert doc.index(PANEL_JS) < doc.index("</body>")
    again = with_panel(doc)
    assert again == doc
    assert again.count(PANEL_JS) == 1


def test_with_panel_on_a_fragment_appends() -> None:
    doc = with_panel("<p>x</p>")
    assert doc.count(PANEL_JS) == 1 and doc.startswith("<p>x</p>")


def test_panel_colours_only_through_variables() -> None:
    stripped = re.sub(
        r"var\(--[a-z-]+,\s*(?:var\(--[a-z-]+,\s*)?#[0-9a-fA-F]{3,8}\)+", "", PANEL_CSS
    )
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", stripped)
    assert "role" in PANEL_JS and "Paper detail" in PANEL_JS and "Escape" in PANEL_JS
    assert "explorer/index.html" in PANEL_JS and "panel=1" in PANEL_JS
    assert "min-width:420px" in PANEL_CSS and "46%" in PANEL_CSS


def test_the_explorer_page_has_panel_mode_and_no_panel_script() -> None:
    assert PANEL_JS not in EXPLORER_PAGE and PANEL_CSS not in EXPLORER_PAGE
    assert "hashchange" in EXPLORER_PAGE and "panel" in EXPLORER_PAGE
    assert "Open in the explorer" in EXPLORER_PAGE


def test_page_includes_the_panel() -> None:
    doc = site.page("T", "<p>b</p>")
    assert PANEL_JS in doc and PANEL_CSS in doc


def _report() -> CitationReport:
    w = WorkCitations("rf:in", "In <corpus> & title", 2024, 3, 0, ("rf:a",), 1.0, 9)
    cand = Candidate("k", "Outside <work>", 2023, 2, ("10.1/ab<c",), ())
    arx = Candidate("k2", "Arxiv work", 2023, 1, (), ("2401.00001",))
    bare = Candidate("k3", "Bare work", 2023, 1, (), ())
    return CitationReport(
        works=[w],
        works_total=1,
        extractions=1,
        entries=3,
        resolved_links=1,
        candidates=[cand, arx, bare],
        as_of_year=2026,
    )


def test_citations_titles_in_the_corpus_open_the_panel() -> None:
    html = render_citations(_report(), {"rf:in": "in"})
    assert html.count("href='../explorer/index.html#open=in'") == 2  # most cited and per year
    assert "In &lt;corpus&gt; &amp; title" in html and "<corpus>" not in html


def test_a_title_not_in_the_corpus_stays_plain_text() -> None:
    html = render_citations(_report(), {})
    assert "explorer/index.html#open" not in html
    assert "In &lt;corpus&gt; &amp; title" in html


def test_candidates_link_to_doi_or_arxiv_and_escape() -> None:
    html = render_citations(_report(), {})
    assert "href='https://doi.org/10.1/ab%3Cc'" in html
    assert "href='https://arxiv.org/abs/2401.00001'" in html
    assert "Bare work" in html and "<work>" not in html
    assert "Outside &lt;work&gt;" in html


def test_queue_titles_open_the_panel_or_link_to_arxiv() -> None:
    from factory.services.site_queue import _title_link
    from factory.services.work_queue import QueueItem

    def item(work_id: str | None) -> QueueItem:
        return QueueItem(
            entry_id="2401.00001",
            title="A <b> title",
            inbox_item_id="i",
            sent_at="t",
            work_id=work_id,
            stage="added",
            stopped=False,
            detail="",
        )

    inside = _title_link(item("rf:w"), {"rf:w": "w"})
    assert "href='../explorer/index.html#open=w'" in inside and "A &lt;b&gt; title" in inside
    outside = _title_link(item(None), {})
    assert "href='https://arxiv.org/abs/2401.00001'" in outside and "<b>" not in outside


def test_layers_dot_click_uses_the_panel_and_titles_are_panel_links() -> None:
    from pathlib import Path

    from factory.services import site_layers

    assert "window.factoryPanel={open:" in PANEL_JS
    src = Path(site_layers.__file__).read_text(encoding="utf-8")
    assert "window.factoryPanel" in src and "ev.ctrlKey" in src and "location.href=D.open" in src
    assert "explorer/index.html#open=" in src
    assert PANEL_JS in site.page("Layers", "<p>x</p>")
