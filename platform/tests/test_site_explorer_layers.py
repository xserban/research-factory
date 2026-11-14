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
