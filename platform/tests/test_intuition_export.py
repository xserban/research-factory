"""Labelled JSON and DOT export of the layer (slice 3c, plan G3-C, task 2)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.intuition.export import (
    LAYER_NOTICE,
    layer_dot,
    layer_json,
    with_layer_dot,
    with_layer_json,
)
from factory.lineage.graph import GraphFilter
from factory.model.intuition import ConceptInput, UseBasisInput
from factory.model.screening import Channel
from factory.services.concepts import decide_concept_source, define_concept, propose_concept_link
from factory.services.context import Project
from factory.services.interpretations import layer_graph
from factory.services.lineage import graph_export, iter_graph_export
from tests.helpers import open_session
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world
from tests.intuition_separation import populate_layer, twin_projects

WIDE = GraphFilter(include_inferred=True, include_stale=True)


def _layer_lines(dot: str) -> list[str]:
    lines = dot.splitlines()
    start = next(i for i, line in enumerate(lines) if "subgraph cluster_interpretation" in line)
    body = [line for line in lines[start + 1 :] if "->" in line or "shape=note" in line]
    return body


def test_default_export_byte_identical(tmp_path: Path, project: Project, iw: IWorld) -> None:
    plain, layered = twin_projects(tmp_path, project, iw)
    for fmt in ("json", "dot"):
        for flt in (GraphFilter(), WIDE):
            assert graph_export(layered, fmt, flt=flt) == graph_export(plain, fmt, flt=flt)  # type: ignore[arg-type]
            assert graph_export(layered, fmt, flt=flt, layer="evidence") == graph_export(  # type: ignore[arg-type]
                plain, fmt, flt=flt
            )


def test_json_with_layer_has_notice_and_labels(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    text = graph_export(project, "json", layer="all")
    d = json.loads(text)
    assert list(d) == ["evidence", "interpretation", "notice"]
    assert d["notice"] == LAYER_NOTICE
    assert d["evidence"] == json.loads(graph_export(project, "json"))
    layer = d["interpretation"]
    assert layer["nodes"] and layer["edges"]
    for item in layer["nodes"] + layer["edges"]:
        assert item["class"] == "interpretation" and "review_state" in item
        assert item["label"].endswith(item["review_state"])
    assert "wrong" not in {i["review_state"] for i in layer["nodes"] + layer["edges"]}
    assert layer["hidden"]["interpretations"] == {"wrong": 1, "superseded": 1}
    assert text.endswith("}\n") and text.count("\n") == 1
    # the evidence nodes and edges carry no layer id
    assert not any("int_" in n["id"] or "cpt_" in n["id"] for n in d["evidence"]["nodes"])


def test_dot_with_layer_dashed_cluster_and_header(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    dot = graph_export(project, "dot", layer="all")
    assert dot.splitlines()[0] == f"// {LAYER_NOTICE}"
    assert "subgraph cluster_interpretation" in dot and "interpretation (not evidence)" in dot
    body = _layer_lines(dot)
    assert body and all("style=dashed" in line for line in body)
    assert all(
        line.rstrip().endswith(('unreviewed"];', 'reviewed"];', 'inferred"];', 'stated"];'))
        and "interpretation · " in line
        for line in body
    )
    assert dot.endswith("}\n") and dot.count("digraph") == 1
    evidence_part = graph_export(project, "dot")
    assert evidence_part[: -len("}\n")] in dot


def test_export_deterministic_across_rebuilds(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    first = [graph_export(project, f, layer="all", flt=WIDE) for f in ("json", "dot")]  # type: ignore[arg-type]
    project.index.rebuild()
    again = [graph_export(project, f, layer="all", flt=WIDE) for f in ("json", "dot")]  # type: ignore[arg-type]
    assert first == again


@pytest.mark.parametrize("fmt", ["json", "dot"])
def test_streamed_layer_export_equals_whole(project: Project, iw: IWorld, fmt: str) -> None:
    populate_layer(project, iw)
    for flt in (GraphFilter(), WIDE):
        whole = graph_export(project, fmt, layer="all", flt=flt)  # type: ignore[arg-type]
        assert "".join(iter_graph_export(project, fmt, layer="all", flt=flt)) == whole  # type: ignore[arg-type]
        queried = graph_export(
            project,
            fmt,  # type: ignore[arg-type]
            query="descendants",
            node=iw.source,
            layer="all",
            flt=flt,
        )
        assert queried.count("interpretation") > 0
        streamed = iter_graph_export(
            project,
            fmt,  # type: ignore[arg-type]
            query="descendants",
            node=iw.source,
            layer="all",
            flt=flt,
        )
        assert "".join(streamed) == queried


def test_pure_renderers_match_the_service(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    layer = layer_graph(project)
    assert with_layer_json(json.loads(graph_export(project, "json")), layer) == graph_export(
        project, "json", layer="all"
    )
    assert with_layer_dot(graph_export(project, "dot"), layer) == graph_export(
        project, "dot", layer="all"
    )
    assert json.loads(with_layer_json({}, layer))["interpretation"] == layer_json(layer)
    assert layer_dot(layer)[0].startswith("  subgraph cluster_interpretation")


def test_labels_escaped(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    cid = define_concept(
        project,
        iw.writer,
        ConceptInput.model_validate(
            {"name": 'the "kernel" \\ trick', "source": {"kind": "textbook", "citation": "B, 1"}}
        ),
    )
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    dot = graph_export(project, "dot", layer="all")
    assert 'label="the \\"kernel\\" \\\\ trick · interpretation · unreviewed"' in dot
    assert json.loads(graph_export(project, "json", layer="all"))  # still valid JSON


def test_invalid_layer_refused_before_any_chunk(project: Project, iw: IWorld) -> None:
    with pytest.raises(FactoryValidationError) as err:
        iter_graph_export(project, "json", layer="x")  # type: ignore[arg-type]
    assert err.value.issues[0].field == "layer"
    with pytest.raises(FactoryValidationError):
        graph_export(project, "dot", layer="x")  # type: ignore[arg-type]


def test_the_mcp_cap_still_counts_evidence_edges_only(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    with pytest.raises(FactoryValidationError):
        graph_export(project, "json", layer="all", max_edges=0)


@pytest.mark.anyio
async def test_mcp_export_layer_parameter(
    settings: Settings, project: Project, clock: FixedClock, iw: IWorld
) -> None:
    populate_layer(project, iw)
    async with open_session(settings, clock) as client:
        plain = await client.call("graph_export", project="demo")
        withl = await client.call("graph_export", project="demo", layer="all")
        bad = await client.call("graph_export", project="demo", layer="x")
    assert plain["ok"] is True and "interpretation" not in str(plain["data"])
    assert withl["ok"] is True and LAYER_NOTICE in str(withl["data"])
    assert bad["ok"] is False and bad["errors"][0]["field"] == "layer"
