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


# --- the animated layer rings -------------------------------------------------------------------


def test_layer_history_is_ordered_by_time_then_event_and_names_the_researcher() -> None:
    from factory.services.work_layers import layer_history

    rows = [
        ("2026-11-06T10:00:00Z", "e2", "rf:b", "core"),
        ("2026-11-05T09:00:00Z", "e9", "rf:a", "applied"),
        ("2026-11-06T10:00:00Z", "e1", "rf:a", "core"),
    ]
    assert layer_history(rows) == [
        ("2026-11-05T09:00:00Z", "rf:a", "applied", "researcher"),
        ("2026-11-06T10:00:00Z", "rf:a", "core", "researcher"),
        ("2026-11-06T10:00:00Z", "rf:b", "core", "researcher"),
    ]
    assert layer_history([]) == []


def test_replay_steps_group_by_day_keep_the_last_move_of_a_work_per_day_and_cap() -> None:
    from factory.services.site_layers import replay_steps

    history = [
        ("2026-11-05T09:00:00Z", "rf:a", "applied", "researcher"),
        ("2026-11-05T11:00:00Z", "rf:a", "core", "researcher"),
        ("2026-11-06T10:00:00Z", "rf:b", "core", "researcher"),
        ("2026-11-06T10:00:00Z", "rf:zz", "core", "researcher"),  # not a known work: skipped
    ]
    index = {"rf:a": 0, "rf:b": 1}
    steps = replay_steps(history, index, list(LAYER_ORDER))
    assert steps == [{"d": "2026-11-05", "mv": [[0, 0]]}, {"d": "2026-11-06", "mv": [[1, 0]]}]
    # over the cap, the earliest days merge into one step (last move of each work wins)
    assert replay_steps(history, index, list(LAYER_ORDER), cap=1) == [
        {"d": "2026-11-06", "mv": [[0, 0], [1, 0]]}
    ]
    assert replay_steps([], index, list(LAYER_ORDER)) == []


def test_payload_places_each_work_by_layer_with_unlayered_in_the_halo() -> None:
    from factory.services.site_layers import layers_payload

    works = [_work("rf:a"), _work("rf:b"), _work("rf:c")]
    layers = {"rf:a": _wl("core"), "rf:b": _wl("applied", "moved", miner="adjacent")}
    history = [("2026-11-05T09:00:00Z", "rf:b", "applied", "researcher")]
    p = layers_payload(works, layers, history)
    assert p["layers"] == list(LAYER_ORDER)
    by = {w["id"]: w for w in p["works"]}
    assert by["rf:a"]["l"] == 0 and by["rf:b"]["l"] == 2 and by["rf:c"]["l"] == -1
    assert by["rf:b"]["m"] == 3  # the miner placed it in 'adjacent' before the move
    assert p["steps"] == [{"d": "2026-11-05", "mv": [[1, 2]]}]
    assert p["counts"][0] == 1 and p["unlayered"] == 1


def test_the_animation_block_embeds_escaped_json_and_uses_only_theme_variables() -> None:
    import re

    from factory.services.site_layers import CSS, SCRIPT, render_animation

    work = _work("rf:a")
    work["title"] = "</script><b>x"
    block = render_animation([work], {"rf:a": _wl("core")}, [])
    assert "id=ly-anim" in block and "application/json" in block and "Replay" in block
    assert "</script><b>x" not in block and "<\\/script>" in block
    for src in (CSS, SCRIPT):
        stripped = re.sub(r"var\(--[a-z]+,\s*#[0-9a-fA-F]{3,8}\)", "", src)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", stripped)
        assert not re.search(r"rgba?\(|hsla?\(", stripped)
    assert "prefers-reduced-motion" in SCRIPT and "visibilitychange" in SCRIPT
    assert "data-theme" in SCRIPT and "storage" in SCRIPT


def test_the_animation_block_has_empty_states() -> None:
    from factory.services.site_layers import render_animation

    block = render_animation([], {}, [])
    assert "id=ly-anim" in block and "No works" in block
    block = render_animation([_work("rf:a")], {}, [])  # works, no layers, no events
    assert "id=ly-anim" in block and "unlayered" in block


def test_the_built_page_puts_the_animation_above_the_list(project: Project, tmp_path: Path) -> None:
    from factory.services.site_layers import build_layers

    out = tmp_path / "layers"
    out.mkdir()
    build_layers(project, out)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert page.index("id=ly-anim") < page.index("No work has a layer")
