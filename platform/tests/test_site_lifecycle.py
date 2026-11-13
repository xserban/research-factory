"""The lifecycle page of the hub (plan 2026-11-13-ai-scientist-lifecycle): its data is a pure
function of the explorer's works and the layers, the page is built from the index, and every
stage and paper is reachable by a link or a click."""

from __future__ import annotations

import json
import re
from pathlib import Path

from factory.services import site
from factory.services.context import Project
from factory.services.site_lifecycle import (
    STAGES,
    lifecycle_data,
    render_own_sequences,
)


def _work(wid: str, *rows: tuple[str, str, str]) -> dict[str, object]:
    return {
        "id": wid,
        "slug": wid.replace("rf:", ""),
        "title": f"Title {wid}",
        "year": "2026",
        "stages": [{"stage": s, "mode": m, "quote": q, "anchor": "s1.p1"} for s, m, q in rows],
    }


def test_lifecycle_data_keeps_only_works_with_stage_rows_in_id_order() -> None:
    works = [
        _work("rf:b", ("ideation-hypothesis", "automated", "q1")),
        _work("rf:c"),
        _work(
            "rf:a", ("data-analysis", "human-assisted", "q2"), ("data-analysis", "automated", "q3")
        ),
    ]
    data = lifecycle_data(works, {"rf:a": "core", "rf:b": None})
    assert [w["slug"] for w in data["works"]] == ["a", "b"]
    assert data["works"][0]["layer"] == "core"
    assert data["works"][1]["layer"] == "pending"
    assert len(data["works"][0]["stages"]["data-analysis"]) == 2
    assert [s["id"] for s in data["stages"]] == [s for s, _ in STAGES]


def test_layers_are_counted_in_the_scheme_order_with_pending_last() -> None:
    works = [_work(f"rf:{i}", ("other", "automated", "q")) for i in "abcd"]
    data = lifecycle_data(works, {"rf:a": "applied", "rf:b": "core", "rf:c": "core"})
    assert data["layers"] == [
        {"id": "core", "n": 2},
        {"id": "applied", "n": 1},
        {"id": "pending", "n": 1},
    ]


def test_lifecycle_data_is_deterministic() -> None:
    works = [_work("rf:b", ("other", "automated", "q")), _work("rf:a", ("other", "automated", "q"))]
    assert lifecycle_data(works, {}) == lifecycle_data(list(reversed(works)), {})


def test_own_sequences_render_order_actor_links_and_loops() -> None:
    seqs = [
        {
            "id": "rf:a",
            "title": "A <paper>",
            "year": "2026",
            "stages": [
                {
                    "order": "1",
                    "name": "idea generation",
                    "actor": "automated",
                    "how": "by tree search",
                    "next": "2",
                    "loops": "",
                    "anchor": "s1.p1",
                },
                {
                    "order": "2",
                    "name": "review",
                    "actor": "human-assisted",
                    "how": "",
                    "next": "",
                    "loops": "1",
                    "anchor": "s1.p2",
                },
            ],
        }
    ]
    html = render_own_sequences(seqs)
    assert "../explorer/index.html#open=a" in html
    assert "A &lt;paper&gt;" in html and "A <paper>" not in html
    assert "→ 2" in html and "↺ 1" in html
    assert "automated" in html and "human-assisted" in html
    assert "calibration sample only" in html


def test_own_sequences_say_so_when_the_miner_has_no_rows() -> None:
    assert "m-lifecycle" in render_own_sequences([])


def test_the_product_is_registered_with_the_layer_event_as_an_input() -> None:
    product = next(p for p in site.products() if p.id == "lifecycle")
    assert product.entry == "index.html"
    assert "work.layer_set" in product.inputs and "extraction.%" in product.inputs


def test_the_page_builds_on_an_empty_project_with_its_script_and_links(
    project: Project, tmp_path: Path
) -> None:
    product = next(p for p in site.products() if p.id == "lifecycle")
    product.build(project, tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "id=lc-svg" in page and "Click a stage or an arc" in page
    assert "../explorer/index.html" in page and "../miners/index.html" in page
    m = re.search(r"<script type='application/json' id='lc-data'>(.*?)</script>", page, re.S)
    assert m is not None
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert data["works"] == [] and len(data["stages"]) == len(STAGES)
    assert "#layer=all&mode=any&stage=literature-review" in page


def test_a_title_cannot_break_out_of_the_embedded_data() -> None:
    works = [_work("rf:a", ("other", "automated", "q"))]
    works[0]["title"] = "</script><script>alert(1)</script>"
    data = lifecycle_data(works, {})
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    assert "</script>" not in payload
