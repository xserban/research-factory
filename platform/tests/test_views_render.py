"""Renderers of the onion view (slice 7b, plan V-A, task 4)."""

from __future__ import annotations

import json

from factory.model.views import OnionNode, OnionView, Ring, ViewMeta, ViewNotice
from factory.views.render import onion_dot, onion_markdown

DEPTHS = ["verified", "extracted", "screened", "indexed"]


def _node(i: int, depth: str, title: str = "A title", **kw: object) -> OnionNode:
    return OnionNode.model_validate(
        {
            "work_id": f"rf:n{i}-{i:08x}",
            "title": title,
            "year": 2020 + i,
            "depth": depth,
            "scope": "corpus",
            **kw,
        }
    )


def _view(*, truncated: bool = False, notices: list[ViewNotice] | None = None) -> OnionView:
    nodes0 = [_node(i, d) for i, d in enumerate(DEPTHS)]
    nodes1 = [
        _node(10, "indexed", title='Quote " and | pipe \\ back', ideas=["ida_1"], regions=["reg_1"])
    ]
    rings = [
        Ring(
            distance=0,
            total=4,
            by_depth={"indexed": 1, "screened": 1, "extracted": 1, "verified": 1},
            nodes=nodes0,
            truncated=False,
        ),
        Ring(
            distance=1,
            total=900 if truncated else 1,
            by_depth={
                "indexed": 900 if truncated else 1,
                "screened": 0,
                "extracted": 0,
                "verified": 0,
            },
            nodes=nodes1,
            truncated=truncated,
        ),
    ]
    meta = ViewMeta(
        view="onion",
        version=1,
        project="demo",
        as_of="evt_9",
        filter={"max_ring": 1, "include_inferred": False},
        truncated=truncated,
        notices=notices or [],
    )
    return OnionView(meta=meta, rings=rings, edges_considered={"cites": 3})


def test_markdown_names_filter_as_of_and_totals() -> None:
    md = onion_markdown(_view())
    assert "as_of: evt_9" in md
    assert '"max_ring":1' in md
    assert "## Ring 0 (4 works)" in md and "## Ring 1 (1 works)" in md
    assert "| work | year | depth | ideas | regions |" in md
    assert "cites: 3" in md


def test_markdown_escapes_pipes_in_titles() -> None:
    md = onion_markdown(_view())
    assert 'Quote " and \\| pipe \\ back' in md
    assert all(row.count("|") - row.count("\\|") == 6 for row in md.splitlines() if "ida_1" in row)


def test_truncated_ring_prints_showing_of() -> None:
    md = onion_markdown(_view(truncated=True))
    assert "showing 1 of 900" in md


def test_notices_are_listed() -> None:
    md = onion_markdown(_view(notices=[ViewNotice(code="ring-clamped", text="Clamped to 3.")]))
    assert "ring-clamped" in md and "Clamped to 3." in md


def test_dot_structure() -> None:
    dot = onion_dot(_view())
    assert "layout=twopi" in dot and 'root="focus"' in dot
    assert '"focus" [style=invis' in dot
    for style in ("filled", "solid", "dashed", "dotted"):
        assert f"style={style}" in dot
    assert dot.startswith("// ") and "as_of=evt_9" in dot.splitlines()[0]
    assert '"focus" -- "rf:n0-00000000" [len=1]' in dot
    assert '"focus" -- "rf:n10-0000000a" [len=2]' in dot


def test_dot_escapes_titles() -> None:
    dot = onion_dot(_view())
    assert 'label="Quote \\" and | pipe \\\\ back"' in dot


def test_dot_states_truncation_in_the_comment() -> None:
    assert "truncated=true" in onion_dot(_view(truncated=True)).splitlines()[0]
    assert "truncated=false" in onion_dot(_view()).splitlines()[0]


def test_renderers_are_deterministic() -> None:
    view = _view()
    assert onion_markdown(view) == onion_markdown(view)
    assert onion_dot(view) == onion_dot(view)
    json.dumps(view.model_dump(mode="json"))
