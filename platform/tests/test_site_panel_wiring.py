"""Product pages that show paper titles link them to the explorer and are wrapped by the panel."""

from __future__ import annotations

from factory.services import site
from factory.services.site_bibliography import _JS as BIBLIOGRAPHY_JS
from factory.services.site_lifecycle import render_own_sequences
from factory.services.site_panel import PANEL_JS
from factory.services.site_queue import _title_link
from factory.services.site_steps import _work
from factory.services.site_synthesis import markdown_to_html
from factory.services.work_queue import QueueItem

_OPEN = "../explorer/index.html#open="


def _item(work_id: str | None) -> QueueItem:
    return QueueItem(
        entry_id="2401.00001",
        title="A <b>paper</b>",
        inbox_item_id="i1",
        sent_at="t",
        work_id=work_id,
        stage="added",
        stopped=False,
        detail="",
    )


def test_page_carries_the_panel() -> None:
    doc = site.page("Any", f"<a href='{_OPEN}s-1'>t</a>")
    assert PANEL_JS in doc and _OPEN + "s-1" in doc


def test_queue_title_links_to_explorer_escaped() -> None:
    out = _title_link(_item("w1"), {"w1": "a b-2024"})
    assert _OPEN + "a%20b-2024" in out and "A &lt;b&gt;paper&lt;/b&gt;" in out


def test_steps_work_title_links() -> None:
    w = {"slug": "s-1", "title": "T <x>", "year": 2024, "steps": []}
    out = _work(w)
    assert _OPEN + "s-1" in out and "T &lt;x&gt;" in out


def test_lifecycle_sequence_title_links() -> None:
    seq = [{"id": "rf:w1", "title": "Life", "year": 2024, "stages": []}]
    assert _OPEN in render_own_sequences(seq)


def test_synthesis_citation_links() -> None:
    assert _OPEN + "s-1" in markdown_to_html("see [[works/s-1]]", {"s-1": "Title"})


def test_bibliography_script_links_slug_encoded() -> None:
    assert "#open='+encodeURIComponent(r.slug)" in BIBLIOGRAPHY_JS
