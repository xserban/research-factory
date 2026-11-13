"""The layers page of the hub: which layer each work has and where it comes from.

Its data is a pure function of the explorer's works and the layers; the page escapes everything."""

from __future__ import annotations

from pathlib import Path

from factory.services import site
from factory.services.context import Project
from factory.services.site_layers import LAYER_ORDER, layers_view, render_layers
from factory.services.work_layers import WorkLayer


def _work(wid: str, title: str = "T") -> dict[str, object]:
    return {"id": wid, "slug": wid.replace("rf:", ""), "title": f"{title} {wid}", "year": "2026"}


def _wl(layer: str | None, source: str = "miner", miner: str | None = None) -> WorkLayer:
    return WorkLayer(layer=layer, source=source, scheme_version=1, miner_layer=miner)  # type: ignore[arg-type]


def test_works_are_grouped_by_layer_in_scheme_order_with_counts() -> None:
    works = [_work(f"rf:{c}") for c in "abcde"]
    layers = {
        "rf:a": _wl("applied"),
        "rf:b": _wl("core"),
        "rf:c": _wl("core"),
        "rf:d": _wl(None, "pending"),
    }
    view = layers_view(works, layers)
    assert [g["layer"] for g in view["groups"]] == ["core", "applied", "pending"]
    assert [g["n"] for g in view["groups"]] == [2, 1, 1]
    assert view["unlayered"] == 1  # rf:e has no layer row at all
    assert [w["id"] for w in view["groups"][0]["works"]] == ["rf:b", "rf:c"]


def test_a_move_that_overrides_the_miner_is_shown_with_what_the_miner_said() -> None:
    view = layers_view([_work("rf:a")], {"rf:a": _wl("core", "moved", miner="adjacent")})
    w = view["groups"][0]["works"][0]
    assert w["source"] == "moved" and w["miner_layer"] == "adjacent"


def test_an_unknown_layer_still_gets_a_group_after_the_known_ones() -> None:
    view = layers_view([_work("rf:a")], {"rf:a": _wl("odd")})
    assert [g["layer"] for g in view["groups"]] == ["odd"]
    assert LAYER_ORDER[0] == "core"


def test_the_page_escapes_titles_and_links_each_work_to_the_explorer() -> None:
    work = _work("rf:a")
    work["title"] = "<script>alert(1)</script>"
    html = render_layers(layers_view([work], {"rf:a": _wl("core")}))
    assert "<script>alert(1)</script>" not in html
    assert "explorer/index.html#open=a" in html


def test_the_page_says_so_when_no_work_has_a_layer() -> None:
    assert "No work has a layer" in render_layers(layers_view([_work("rf:a")], {}))


def test_the_product_builds_a_page_for_a_project_without_layers(
    project: Project, tmp_path: Path
) -> None:
    from factory.services.site_layers import build_layers

    out = tmp_path / "layers"
    out.mkdir()
    build_layers(project, out)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "Layers" in page and "not yet calibrated" in page
    assert any(p.id == "layers" for p in site.products())
