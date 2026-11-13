# ruff: noqa: E501
"""The layers product: which layer each work has and where that layer comes from.

A layer is the project's triage of a work (core, benchmark, applied, adjacent, background,
off-topic), set by the layer miner or moved by the researcher (`work_layers.layers_of`). This page
only reads that fold and the explorer's works; it judges nothing.

Invariants:
- Pure data: `layers_view` is a function of the works and the layers, in work-id order within a
  layer and scheme order across layers (an unknown layer follows the known ones, `pending` is last).
- A work with no layer row is not listed; it is counted as `unlayered`, never as pending.
- Every title and id written into the page is escaped.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from factory.services.context import Project
from factory.services.site_widgets import REPORT_CSS, esc, section
from factory.services.work_layers import WorkLayer

LAYER_ORDER: tuple[str, ...] = (
    "core",
    "benchmark",
    "applied",
    "adjacent",
    "background",
    "off-topic",
)
PENDING = "pending"

CSS = (
    ".ly-bar{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 14px}"
    ".ly-bar a{border:1px solid var(--mut);background:var(--card);color:var(--fg);padding:4px 12px;"
    "text-decoration:none;font-size:13px}.ly-bar a:hover{border-color:var(--ac)}.ly-bar b{color:var(--ac)}"
    ".badge{font-size:10px;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--mut);"
    "padding:0 6px;margin-left:6px;color:var(--dim)}.badge.moved{color:var(--amber);border-color:var(--amber)}"
)


def _rank(layer: str) -> tuple[int, str]:
    if layer == PENDING:
        return (2, layer)
    return (0, f"{LAYER_ORDER.index(layer):02d}") if layer in LAYER_ORDER else (1, layer)


def layers_view(
    works: Sequence[Mapping[str, Any]], layers: Mapping[str, WorkLayer]
) -> dict[str, Any]:
    """Groups of works by layer (`groups`: layer, n, works) and the number of works with no layer
    row (`unlayered`)."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unlayered = 0
    for w in sorted(works, key=lambda x: str(x["id"])):
        wl = layers.get(str(w["id"]))
        if wl is None:
            unlayered += 1
            continue
        by[wl.layer if wl.layer is not None else PENDING].append(
            {
                "id": w["id"],
                "slug": w.get("slug", ""),
                "title": w.get("title", ""),
                "year": w.get("year", ""),
                "source": wl.source,
                "miner_layer": wl.miner_layer,
            }
        )
    groups = [
        {"layer": k, "n": len(v), "works": v}
        for k, v in sorted(by.items(), key=lambda kv: _rank(kv[0]))
    ]
    return {"groups": groups, "unlayered": unlayered}


def render_layers(view: Mapping[str, Any]) -> str:
    """The page body for a `layers_view`."""
    groups = view["groups"]
    if not groups:
        return "<p class=dim>No work has a layer yet. The layer miner <code>m-layer</code> sets one per work.</p>"
    bar = "".join(
        f"<a href='#layer-{esc(g['layer'])}'>{esc(g['layer'])} <b>{g['n']}</b></a>" for g in groups
    )
    out = f"<div class=ly-bar>{bar}</div>"
    for g in groups:
        rows = ""
        for w in g["works"]:
            note = ""
            if w["source"] == "moved":
                said = f" (miner said {esc(w['miner_layer'])})" if w["miner_layer"] else ""
                note = f"<span class='badge moved'>moved by the researcher{said}</span>"
            rows += (
                f"<tr><td><a href='../explorer/index.html#open={esc(w['slug'])}'>{esc(str(w['title'])[:110])}</a>"
                f"{note}</td><td>{esc(w['year'])}</td></tr>"
            )
        out += f"<div id='layer-{esc(g['layer'])}'></div>" + section(
            f"{g['layer']} ({g['n']})",
            f"<table><tr><th>work</th><th>year</th></tr>{rows}</table>",
        )
    if view["unlayered"]:
        out += (
            f"<p class=dim>{view['unlayered']} further works in the corpus have no layer row "
            "(they are outside the layer pass's population).</p>"
        )
    return out


def build_layers(project: Project, out: Path) -> None:
    from factory.services.site import page
    from factory.services.site_corpus import corpus_payload
    from factory.services.work_layers import layers_of

    works: list[dict[str, Any]] = corpus_payload(project)["works"]
    try:
        layers = layers_of(project)
    except Exception:  # layers are an aid: a project without them still gets the page
        layers = {}
    slug = esc(project.paths.slug)
    body = "<h1>Layers</h1>"
    body += (
        "<div class=note>The layer of each work: the project's triage into core, benchmark, applied, adjacent, "
        "background and off-topic. It comes from the layer miner <code>m-layer</code>, or from a researcher's move "
        "(shown on the row, with what the miner said). The layer pass is <b>not yet calibrated</b>: treat the "
        "layers as a first triage, not a finding.</div>"
    )
    body += render_layers(layers_view(works, layers))
    body += section(
        "What you can do",
        "<ul class=links>"
        "<li><a href='../lifecycle/index.html'>Lifecycle</a>: filter the stage flow by layer.</li>"
        "<li><a href='../miners/m-layer.html'>The layer miner</a>: its rows, quotes and agreement.</li>"
        "<li><a href='../explorer/index.html'>Explorer</a>: every paper with its rows.</li></ul>"
        f"<p class=dim>Commands: <code>factory --project {slug} mine status</code>.</p>",
    )
    (out / "index.html").write_text(page("Layers", body, REPORT_CSS + CSS), encoding="utf-8")
