"""The explorer filters works by layer in the static page: payload fields and page code."""

from __future__ import annotations

from factory.services.site_corpus import UNLAYERED, layer_fields
from factory.services.site_explorer_page import PAGE
from factory.services.work_layers import WorkLayer


def _wl(layer: str | None, source: str, miner: str | None = None) -> WorkLayer:
    return WorkLayer(layer=layer, source=source, scheme_version=1, miner_layer=miner)  # type: ignore[arg-type]


def test_a_work_without_a_row_is_unlayered() -> None:
    assert layer_fields(None) == {"layer": UNLAYERED, "layer_source": "", "layer_miner": ""}
    assert UNLAYERED == "unlayered"


def test_a_pending_work_is_unlayered_never_pending() -> None:
    assert layer_fields(_wl(None, "pending"))["layer"] == "unlayered"


def test_a_moved_work_carries_its_source_and_the_miner_layer() -> None:
    f = layer_fields(_wl("core", "moved", "adjacent"))
    assert f == {"layer": "core", "layer_source": "moved", "layer_miner": "adjacent"}


def test_a_miner_layer_has_miner_source() -> None:
    assert layer_fields(_wl("applied", "miner", "applied"))["layer_source"] == "miner"


def test_the_page_has_a_layer_facet_ordered_and_a_badge_without_server_calls() -> None:
    assert "key:'layer',label:'Layer'" in PAGE
    assert "DATA.layer_order" in PAGE
    assert "d.key==='layer'?lcmp" in PAGE
    assert "layerBadge(w)" in PAGE
    # the existing hash form f=key:value reaches the layer dimension through DIMS
    assert "H.getAll('f')" in PAGE


def test_cited_in_corpus_tooltip_states_the_extracted_denominator() -> None:
    assert "Counts only works whose reference lists were extracted ('+DATA.refs_done+' of '" in PAGE


def test_the_layer_filter_comes_first_and_mining_acts_are_folded_away() -> None:
    assert "DIMS.filter(d=>d.key==='layer').concat(" in PAGE
    assert '<details class="minebox">' in PAGE
    assert "Mine this layer" in PAGE  # still reachable, only out of the filter list


def test_the_explorer_sorts_by_date_by_default_with_four_choices() -> None:
    assert 'id="sortby"' in PAGE
    for value in ("new", "old", "cited", "title"):
        assert f'<option value="{value}">' in PAGE
    assert (
        "sortBy=['new','old','cited','title'].includes(H.get('sort'))?H.get('sort'):'new'" in PAGE
    )
    assert "l.sort(wcmp)" in PAGE
    assert "by[m].sort(wcmp)" in PAGE


def test_the_comparator_orders_dates_and_puts_undated_last() -> None:
    import json
    import re
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    m = re.search(r"function wcmp\(a,b\)\{.*?\n return sortBy==='old'.*?\}", PAGE, re.S)
    assert m
    works = [
        {"title": "b", "published": "2025-01-02", "cited_in_corpus": 1},
        {"title": "a", "published": "", "cited_in_corpus": 9},
        {"title": "c", "published": "2025-03-01", "cited_in_corpus": 5},
    ]
    out = {}
    for mode in ("new", "old", "cited", "title"):
        js = (
            f"let sortBy='{mode}';{m.group(0)}"
            f"console.log(JSON.stringify({json.dumps(works)}.sort(wcmp).map(w=>w.title)))"
        )
        out[mode] = json.loads(
            subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout
        )
    assert out["new"] == ["c", "b", "a"]
    assert out["old"] == ["b", "c", "a"]
    assert out["cited"] == ["a", "c", "b"]
    assert out["title"] == ["a", "b", "c"]
